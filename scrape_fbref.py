#!/usr/bin/env python3
"""
xG, xAG en kaarten per speler van FBref -> fbref.csv  --  stap 5.

Waarom dit erbij komt: pouletips levert geen assists en geen kaarten, en de
doelpuntenschatting in cvhj_model.py draait nu op RUWE doelpunten uit een klein
aantal recente wedstrijden -- ruizig, vooral vroeg in het seizoen. FBref's
standaardstatistiekentabel heeft alle drie in EEN pagina: xG/xAG (verwachte
doelpunten/assists -- minder ruis dan de ruwe telling omdat schotkwaliteit
meetelt, niet alleen of de bal binnenging) en gele/rode kaarten.

LET OP -- dit is een ander soort risico dan de pouletips-scrapers:
FBref draait achter Cloudflare en blokkeert scripted requests soms al bij de
eerste poging (in de bouwomgeving van dit project gaf een enkele test-fetch
al een 403, zonder dat er iets geprobeerd was). Of dit vanuit GitHub Actions
werkt is dus NIET bevestigd. Draai dit script eerst handmatig (of via de
workflow_dispatch-knop) voordat je erop vertrouwt.

De tabel zelf staat, zoals bij alle sport-reference-achtige sites, verstopt
in een HTML-commentaar (de reden dat FBref dat doet is onbekend, maar het is
al jaren zo en breekt een naive `find(id=...)`-zoekopdracht). Dit script haalt
het commentaar eruit voordat het parset. Kolommen worden gelezen via het
`data-stat`-attribuut van elke cel -- dat attribuut is FBref's eigen stabiele
naam voor een statistiek, onafhankelijk van de zichtbare kop of kolomvolgorde,
en is daarmee net zo robuust als de kolomnaam-detectie in scrape_prijzen.py.
Als FBref een `data-stat`-naam ooit wijzigt, faalt dit script met een
duidelijke melding welke kolom niet is gevonden -- geen stille misser.

EEN enkele request voor de hele competitie (in tegenstelling tot de
programma-horizon-scraper, die per ronde een pagina per wedstrijd nodig
heeft) -- FBref's eigen richtlijn is maximaal ~10 requests per minuut, en
hier is er precies één nodig.

Gebruik:
    python scrape_fbref.py                    # -> fbref.csv
    python scrape_fbref.py --uit data/

Uitvoer: fbref.csv met
    speler, club, positie, wedstrijden, minuten_90s,
    goals_per90, xg_per90, assists_per90, xag_per90,
    gele_kaarten, rode_kaarten

`club` is al genormaliseerd naar de schrijfwijze uit cvhj_model.py (via
CLUB_ALIAS_FBREF); zie het join-mechanisme in dat bestand voor hoe dit met
speler_id/naam wordt gekoppeld -- FBref heeft geen slug die met pouletips'
speler_id overeenkomt, dus de koppeling gaat op genormaliseerde naam + club.

Afhankelijkheden: pip install requests beautifulsoup4
"""
import argparse
import csv
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Comment

BASE = "https://fbref.com"
STATS_URL = BASE + "/en/comps/23/stats/Eredivisie-Stats"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
TABEL_ID = "stats_standard"
MIN_SPELERS = 200   # ruime ondergrens: minder dan dit betekent iets is misgegaan

TRANS = str.maketrans({
    "ø": "o", "Ø": "O", "æ": "ae", "Æ": "Ae", "å": "a", "Å": "A",
    "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th", "ł": "l", "Ł": "L",
    "đ": "d", "Đ": "D", "ß": "ss", "ı": "i",
})

# FBref schrijft clubnamen soms voluit ("AZ Alkmaar", "PSV Eindhoven",
# "NEC Nijmegen") waar cvhj_model.py de kortere pouletips-schrijfwijze
# gebruikt. NIET LIVE GEVERIFIEERD (zie moduledocstring) -- controleer de
# eerste keer handmatig of elke club hieronder daadwerkelijk matcht met een
# regel uit clubs.csv, en vul aan waar dat niet zo is.
CLUB_ALIAS_FBREF = {
    "AZ Alkmaar": "AZ",
    "PSV Eindhoven": "PSV",
    "NEC Nijmegen": "NEC",
    "Heerenveen": "sc Heerenveen",
    "SC Heerenveen": "sc Heerenveen",
    "Cambuur": "SC Cambuur",
    "SC Cambuur Leeuwarden": "SC Cambuur",
    "Sparta R'dam": "Sparta Rotterdam",
    "Den Haag": "ADO Den Haag",
    "FC Den Haag": "ADO Den Haag",
    "Fortuna Sittard": "Fortuna Sittard",
    "Go Ahead Eagles": "Go Ahead Eagles",
}

POSITIE_FBREF_EN = {
    "GK": "Goalkeeper", "DF": "Defender", "MF": "Midfielder", "FW": "Forward",
}


def norm_club(c):
    c = (c or "").strip()
    return CLUB_ALIAS_FBREF.get(c, c)


def norm(s):
    s = (s or "").strip().translate(TRANS)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()


def haal_tabel(url, tabel_id, pogingen=3, pauze=3.0):
    """Haalt de pagina op en geeft de BeautifulSoup van de gegeven tabel terug.

    FBref verstopt de spelerstabel (in tegenstelling tot de teamtabel erboven)
    in een HTML-commentaar. `find(id=...)` ziet die dus niet -- eerst alle
    commentaarblokken doorzoeken op eentje die de tabel bevat.
    """
    laatste = None
    for poging in range(pogingen):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                break
            laatste = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            laatste = str(e)
        time.sleep(pauze * (poging + 1))
    else:
        raise RuntimeError(
            f"kon {url} niet ophalen ({laatste}). Als dit een 403 of 429 is: FBref "
            f"blokkeert het request (Cloudflare of rate limit) -- geen kolomprobleem, "
            f"een netwerk-/toegangsprobleem. Zie de moduledocstring.")

    soup = BeautifulSoup(r.text, "html.parser")
    direct = soup.find("table", id=tabel_id)
    if direct:
        return direct

    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        if tabel_id in c:
            binnen = BeautifulSoup(c, "html.parser")
            tabel = binnen.find("table", id=tabel_id)
            if tabel:
                return tabel

    raise RuntimeError(
        f"tabel #{tabel_id} niet gevonden op {url} (ook niet in de HTML-commentaren). "
        f"FBref heeft mogelijk de pagina-structuur gewijzigd -- controleer de live pagina.")


def cel(rij, data_stat):
    c = rij.find(["td", "th"], {"data-stat": data_stat})
    return c.get_text(strip=True) if c else None


def getal(tekst, standaard=0.0):
    if not tekst:
        return standaard
    tekst = tekst.replace(",", "")
    try:
        return float(tekst)
    except ValueError:
        return standaard


def parse_spelers(tabel):
    rijen = tabel.find("tbody").find_all("tr")
    uit = []
    for rij in rijen:
        if rij.get("class") and "thead" in rij.get("class"):
            continue  # tussenkopjes die FBref elke ~25 rijen herhaalt
        naam = cel(rij, "player")
        if not naam:
            continue
        club = norm_club(cel(rij, "team"))
        pos_kort = (cel(rij, "position") or "").split(",")[0].strip()
        positie = POSITIE_FBREF_EN.get(pos_kort, pos_kort)
        negentigers = getal(cel(rij, "minutes_90s"))
        if negentigers <= 0:
            continue  # nog niet gespeeld dit seizoen -- niets te schatten
        uit.append({
            "speler": naam,
            "speler_key": f"{norm(naam)}|{norm(club)}",
            "club": club,
            "positie": positie,
            "wedstrijden": getal(cel(rij, "games")),
            "minuten_90s": negentigers,
            "goals_per90": getal(cel(rij, "goals_per90")),
            "xg_per90": getal(cel(rij, "xg_per90")),
            "assists_per90": getal(cel(rij, "assists_per90")),
            "xag_per90": getal(cel(rij, "xg_assist_per90")),
            "gele_kaarten": getal(cel(rij, "cards_yellow")),
            "rode_kaarten": getal(cel(rij, "cards_red")),
        })
    return uit


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--uit", default=".", help="doelmap voor fbref.csv")
    p.add_argument("--url", default=STATS_URL, help="override voor testen")
    args = p.parse_args()

    print(f"FBref ophalen: {args.url}")
    tabel = haal_tabel(args.url, TABEL_ID)
    spelers = parse_spelers(tabel)

    if len(spelers) < MIN_SPELERS:
        sys.exit(f"FOUT: slechts {len(spelers)} spelers gevonden (verwacht >= {MIN_SPELERS}). "
                 f"Waarschijnlijk is de tabelstructuur veranderd of is de pagina niet volledig "
                 f"geladen -- er wordt niets geschreven, om geen halve data te laten doorstromen.")

    velden = ["speler", "club", "positie", "wedstrijden", "minuten_90s",
              "goals_per90", "xg_per90", "assists_per90", "xag_per90",
              "gele_kaarten", "rode_kaarten"]
    uit = Path(args.uit)
    uit.mkdir(parents=True, exist_ok=True)
    pad = uit / "fbref.csv"
    with pad.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=velden)
        w.writeheader()
        for s in spelers:
            w.writerow({k: s[k] for k in velden})

    onbekende_club = sorted({s["club"] for s in spelers if s["club"] not in CLUB_ALIAS_FBREF.values()
                             and s["club"] not in CLUB_ALIAS_FBREF})
    print(f"{len(spelers)} spelers -> {pad}")
    print(f"  clubs gezien: {len(sorted({s['club'] for s in spelers}))}")
    if onbekende_club:
        print(f"  LET OP: {len(onbekende_club)} clubnaam/namen niet in CLUB_ALIAS_FBREF en niet "
              f"gelijk aan de standaardschrijfwijze -- controleer of deze matchen met clubs.csv:")
        for c in onbekende_club:
            print(f"    {c!r}")


if __name__ == "__main__":
    main()
