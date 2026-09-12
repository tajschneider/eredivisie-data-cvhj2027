#!/usr/bin/env python3
"""
Assists, kaarten, doelpunten en reddingen van pouletips -> xg.csv  --  stap 5, versie 3.

WAAROM DIT DE VORIGE TWEE POGINGEN VERVANGT
-------------------------------------------
Stap 5 moest het model aan assists en kaarten helpen: die ontbreken volledig in
de pouletips-data die het al gebruikt, en het model valt daarvoor nu terug op
een positieprior -- dus op een gemiddelde, niet op deze speler.

Daar is eerst FBref voor gebouwd (Opta-licentie weg in januari 2026, plus een
403 vanaf GitHub Actions) en daarna Sofascore (data compleet, maar ook een 403
vanaf GitHub Actions). Beide keren was de aanname dat zulke data alleen bij een
gespecialiseerde statistiekensite te halen viel.

Dat klopte niet. Pouletips heeft 31 ranglijsten, waaronder assists, gele en
rode kaarten, doelpunten en reddingen -- op dezelfde site die dit project al
scrapet en die aantoonbaar WEL bereikbaar is vanaf GitHub Actions, want
scrape_prijzen.py draait daar gewoon. Vier extra verzoeken, geen sleutels,
geen blokkades.

WAT ER PRECIES IN xg.csv KOMT -- lees dit, de kolomnamen liegen een beetje
--------------------------------------------------------------------------
Het bestandsformaat is ongewijzigd gebleven zodat cvhj_model.py niets hoeft te
weten van de bronwissel. Maar twee kolomnamen dekken de lading nu anders:

  assists_per90   ECHT. Assists uit de ranglijst, gedeeld door de gespeelde
                  minuten uit spelers.csv.

  xag_per90       GEEN expected assists -- die bestaan hier niet. Gevuld met
                  dezelfde waarde als assists_per90. cvhj_model.py middelt die
                  twee om ruis te dempen; door ze gelijk te zetten wordt dat
                  middelen een no-op in plaats van een vertekening. Er wordt
                  dus niets verzonnen, alleen niets toegevoegd.

  xg_per90        GEEN expected goals. Gevuld met het SEIZOENSdoelpuntentempo
                  uit de doelpunten-ranglijst. In bouw_pool() is dat de term
                  die het lokale venster van zes ronden stabiliseert; een
                  seizoenstempo doet dat werk prima, alleen via volume in
                  plaats van via schotkwaliteit. Zwakker dan echte xG, veel
                  sterker dan de huidige situatie (niets).

  gele_kaarten    ECHT, seizoenstotalen uit de ranglijsten.
  rode_kaarten

DE TOP-40-BEPERKING, EN WAAROM DIE MEEVALT
------------------------------------------
Elke ranglijst toont de top 40, niet alle 511 spelers. Een speler die er niet
in staat krijgt hier een 0. Dat is geen gat maar grotendeels de waarheid: bij
assists hebben 93 spelers er uberhaupt een, en wie buiten de top 40 valt zit op
nul of een. De fout is dus hooguit een assist, in de richting van te laag.

Belangrijker: een 0 is hier ECHTE INFORMATIE. Een speler met 500 minuten en
geen assists heeft daadwerkelijk een laag assisttempo, en dat hoort het model
te weten. Nu krijgt hij de positieprior, alsof er niets bekend is. Ook voor de
spelers die niet in een ranglijst staan is dit dus een verbetering.

Gebruik:
    python scrape_statistieken.py                 # -> xg.csv
    python scrape_statistieken.py --uit data/
    python scrape_statistieken.py --dump ruw/     # ruwe HTML bewaren

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
from bs4 import BeautifulSoup

BASE = "https://pouletips.nl"
STAT = BASE + "/eredivisie/statistieken/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cvhj-model/1.0)"}

# (sleutel, pad, koptekst waarop de waardekolom te herkennen is)
CATEGORIEEN = [
    ("assists", "assists/", "assist"),
    ("doelpunten", "doelpunten/", "doelpunt"),
    ("gele_kaarten", "gele-kaarten/", "geel"),
    ("rode_kaarten", "rode-kaarten/", "rood"),
    ("reddingen", "reddingen/", "redding"),
]

MIN_GEVULD = 20   # onder dit aantal spelers met een waarde is er iets stuk

TRANS = str.maketrans({
    "ø": "o", "Ø": "O", "æ": "ae", "Æ": "Ae", "å": "a", "Å": "A",
    "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th", "ł": "l", "Ł": "L",
    "đ": "d", "Đ": "D", "ß": "ss", "ı": "i",
})


def norm(s):
    s = (s or "").strip().translate(TRANS)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.split()).lower()


def get(url, pauze=1.2, pogingen=4):
    laatste = None
    for poging in range(pogingen):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                time.sleep(pauze)
                return r.text
            laatste = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            laatste = str(e)
        time.sleep(pauze * (poging + 1))
    raise RuntimeError(f"niet op te halen: {url} ({laatste})")


def getal(tekst):
    t = re.sub(r"[^\d,.\-]", "", (tekst or "").replace("\xa0", " "))
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def splits_speler(cel):
    """'Irakli Yegoian, Excelsior' -> ('Irakli Yegoian', 'Excelsior').

    Zonder komma valt de club niet te bepalen; dan alleen de naam, en de
    aanroeper matcht op naam zonder club.
    """
    tekst = re.sub(r"\s+", " ", (cel or "")).strip()
    if "," in tekst:
        naam, _, club = tekst.rpartition(",")
        return naam.strip(), club.strip()
    return tekst, ""


def parse_ranglijst(html, koptekst):
    """[(naam, club, waarde)] uit een ranglijsttabel.

    De waardekolom wordt op koptekst gezocht. Lukt dat niet, dan de eerste
    kolom NA de spelerkolom die een getal bevat -- die volgorde is stabiel
    (#, Speler, waarde) ook als de site er een per-90-kolom bij zet.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tabel in soup.find_all("table"):
        koppen = [re.sub(r"\s+", " ", th.get_text(" ", strip=True)).lower()
                  for th in tabel.find_all("th")]
        if not any(k.startswith("speler") for k in koppen):
            continue
        i_speler = next(i for i, k in enumerate(koppen) if k.startswith("speler"))
        i_waarde = next((i for i, k in enumerate(koppen)
                         if i != i_speler and koptekst in k), None)

        uit = []
        for tr in tabel.find_all("tr"):
            cellen = tr.find_all("td")
            if len(cellen) <= i_speler:
                continue
            naam, club = splits_speler(cellen[i_speler].get_text(" ", strip=True))
            if not naam:
                continue
            waarde = None
            if i_waarde is not None and len(cellen) > i_waarde:
                waarde = getal(cellen[i_waarde].get_text(" ", strip=True))
            if waarde is None:                      # terugval: eerste getal erna
                for c in cellen[i_speler + 1:]:
                    waarde = getal(c.get_text(" ", strip=True))
                    if waarde is not None:
                        break
            if waarde is not None:
                uit.append((naam, club, waarde))
        if uit:
            return uit
    return []


def lees_minuten(pad_spelers):
    """{sleutel: {'minuten', 'duels', 'speler', 'club'}} uit spelers.csv.

    Dit is de betrouwbare bron voor speelminuten: hij dekt ALLE spelers, terwijl
    de ranglijst 'speelminuten' ook maar een top 40 is.
    """
    per = {}
    with open(pad_spelers, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("afwezig_reden"):
                continue
            sid = r.get("speler_id") or norm(r["speler"])
            d = per.setdefault(sid, {"minuten": 0, "duels": 0,
                                     "speler": r["speler"], "club": r["club"]})
            d["minuten"] += int(r["minuten"] or 0)
            d["duels"] += 1
            d["club"] = r["club"]        # laatst bekende club
    return per


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--uit", default=".", help="doelmap voor xg.csv")
    p.add_argument("--spelers", default="spelers.csv")
    p.add_argument("--min-minuten", type=int, default=90,
                   help="spelers met minder minuten komen niet in xg.csv")
    p.add_argument("--dump", default=None, help="map om de ruwe HTML in te bewaren")
    a = p.parse_args()

    if not Path(a.spelers).exists():
        sys.exit(f"{a.spelers} niet gevonden -- die is nodig voor de speelminuten.")

    per_speler = lees_minuten(a.spelers)
    print(f"{len(per_speler)} spelers met speeltijd uit {a.spelers}")

    # naam+club -> sleutel, om de ranglijsten aan spelers.csv te koppelen
    op_naam_club = {}
    op_naam = {}
    for sid, d in per_speler.items():
        op_naam_club[f"{norm(d['speler'])}|{norm(d['club'])}"] = sid
        op_naam.setdefault(norm(d["speler"]), []).append(sid)

    waarden = {sid: {} for sid in per_speler}
    for sleutel, pad, koptekst in CATEGORIEEN:
        url = STAT + pad
        html = get(url)
        if a.dump:
            Path(a.dump).mkdir(parents=True, exist_ok=True)
            (Path(a.dump) / f"{sleutel}.html").write_text(html, encoding="utf-8")
        rijen = parse_ranglijst(html, koptekst)

        gekoppeld, niet = 0, []
        for naam, club, waarde in rijen:
            sid = op_naam_club.get(f"{norm(naam)}|{norm(club)}")
            if sid is None:
                kandidaten = op_naam.get(norm(naam), [])
                sid = kandidaten[0] if len(kandidaten) == 1 else None
            if sid is None:
                niet.append(f"{naam} ({club})")
                continue
            waarden[sid][sleutel] = waarde
            gekoppeld += 1

        print(f"  {sleutel:14s} {len(rijen):3d} in de ranglijst, {gekoppeld:3d} gekoppeld"
              + (f", {len(niet)} niet: {', '.join(niet[:3])}" if niet else ""))
        if len(rijen) < MIN_GEVULD:
            sys.exit(f"FOUT: {url} leverde maar {len(rijen)} regels op. De opmaak is "
                     f"waarschijnlijk gewijzigd -- xg.csv NIET geschreven. Draai met "
                     f"--dump om de HTML te bekijken.")

    rijen_uit = []
    for sid, d in per_speler.items():
        if d["minuten"] < a.min_minuten:
            continue
        n90 = d["minuten"] / 90.0
        w = waarden[sid]
        assists90 = w.get("assists", 0.0) / n90
        doelpunten90 = w.get("doelpunten", 0.0) / n90
        rijen_uit.append({
            "speler": d["speler"],
            "club": d["club"],
            "positie": "",
            "wedstrijden": d["duels"],
            "minuten_90s": round(n90, 4),
            "goals_per90": round(doelpunten90, 4),
            # GEEN expected goals: seizoenstempo. Zie de moduledocstring.
            "xg_per90": round(doelpunten90, 4),
            "assists_per90": round(assists90, 4),
            # GEEN expected assists: gelijk aan assists, zodat het middelen in
            # cvhj_model.py neutraal is in plaats van vertekenend.
            "xag_per90": round(assists90, 4),
            "gele_kaarten": w.get("gele_kaarten", 0.0),
            "rode_kaarten": w.get("rode_kaarten", 0.0),
        })

    velden = ["speler", "club", "positie", "wedstrijden", "minuten_90s",
              "goals_per90", "xg_per90", "assists_per90", "xag_per90",
              "gele_kaarten", "rode_kaarten"]
    uit = Path(a.uit)
    uit.mkdir(parents=True, exist_ok=True)
    pad = uit / "xg.csv"
    with pad.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=velden)
        w.writeheader()
        w.writerows(rijen_uit)

    met_assist = sum(1 for r in rijen_uit if r["assists_per90"] > 0)
    met_kaart = sum(1 for r in rijen_uit if r["gele_kaarten"] or r["rode_kaarten"])
    print(f"\n{len(rijen_uit)} spelers -> {pad}")
    print(f"  met assists: {met_assist}")
    print(f"  met kaarten: {met_kaart}")
    print(f"  LET OP: xg_per90 is het seizoensdoelpuntentempo en xag_per90 is gelijk")
    print(f"  aan assists_per90 -- er zit GEEN expected-goals-model achter. Zie de")
    print(f"  moduledocstring voor waarom dat hier verdedigbaar is.")


if __name__ == "__main__":
    main()
