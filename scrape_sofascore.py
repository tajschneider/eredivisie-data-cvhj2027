#!/usr/bin/env python3
"""
xG, xAG, assists en kaarten per speler van Sofascore -> xg.csv  --  stap 5, versie 2.

WAAROM DIT scrape_fbref.py VERVANGT
-----------------------------------
FBref is als bron weggevallen. Twee onafhankelijke redenen, beide bevestigd:

1. Sports Reference (het moederbedrijf van FBref) is op 23 januari 2026 zijn
   Opta-licentie kwijtgeraakt na een geschil over de overeenkomst. De
   xG/xAG-data die dit model gebruikte staat er niet meer; alleen "basic,
   non-advanced" statistiek blijft. Dat is aangekondigd als permanent.
2. Los daarvan blokkeert FBref scripted requests (HTTP 403) vanaf
   datacenter-IP's -- precies wat een GitHub Actions-runner is. Dat gaf de
   fbref-workflow in de praktijk ook: 403, drie pogingen, gestopt.

Sofascore lost beide op: de data is er wel, en het endpoint antwoordde in een
test vanaf een datacenter-IP gewoon met 200.

WAT WEL EN WAT NIET GEVERIFIEERD IS -- lees dit voor je erop vertrouwt
---------------------------------------------------------------------
WEL geverifieerd (met echte, live respons van api.sofascore.com):
  - Het toernooi-id voor de Eredivisie is 37 en het seizoen 26/27 heeft
    id 96143; /seasons levert die lijst met nieuwste seizoen vooraan.
  - Het /statistics-endpoint levert PER SPELER precies de velden die dit
    model nodig heeft: goals, assists, expectedGoals, expectedAssists,
    yellowCards, redCards, minutesPlayed, appearances. Voorbeeldregel uit
    de echte respons: Gjivai Zechiel (Feyenoord) -- 4 goals, 3 assists,
    xG 1.83, xAG 1.71, 1 gele kaart, 440 minuten, 5 wedstrijden.
  - Paginering met limit/offset werkt; offset=100 gaf andere spelers dan
    offset=0.
  - Alle 18 Eredivisie-clubnamen zoals Sofascore ze schrijft (zie
    CLUB_ALIAS_SOFASCORE hieronder -- die map is dus GEEN gok).
  - robots.txt van sofascore.com noemt /api/ niet; het is dus niet
    door robots.txt verboden. (Dat is niet hetzelfde als expliciete
    toestemming in de gebruiksvoorwaarden -- zie de README.)

NIET geverifieerd:
  - Dit SCRIPT als geheel is nooit live gedraaid. De bouwomgeving kon
    api.sofascore.com niet bereiken via een eigen HTTP-verzoek (de proxy
    daar staat dat niet toe); alle bovenstaande controles liepen via een
    los ophaalmechanisme. De parsing hieronder is dus getest tegen een
    synthetische respons met exact de echte veldnamen (zie
    test_sofascore.py), niet tegen de live API.
  - DRAAI DIT DUS EEN KEER HANDMATIG en kijk of het aantal spelers en de
    clubnamen kloppen, voordat je de wekelijkse keten erop laat leunen.
    Het script faalt hard (schrijft niets) bij te weinig spelers, dus een
    halve vulling van xg.csv kan niet ongemerkt doorstromen.

VERHOUDING TOT HET MODEL
------------------------
De uitvoer heeft exact hetzelfde formaat als het oude fbref.csv, zodat
cvhj_model.py's lees_fbref()/bouw_pool() ongewijzigd blijven werken. Ontbreekt
xg.csv, dan valt het model net als voorheen terug op het gedrag van vóór
stap 5 (doelpunten uit pouletips, geen assists/kaarten) -- geen crash.

EEN VERSCHIL MET FBREF, IN ONS VOORDEEL: Sofascore geeft exacte gespeelde
minuten, waar FBref afgeronde "90s" gaf. De per-90-omrekening hieronder is
daardoor iets nauwkeuriger dan voorheen.

Gebruik:
    python scrape_sofascore.py                  # -> xg.csv
    python scrape_sofascore.py --uit data/
    python scrape_sofascore.py --seizoen 77012  # ander seizoen forceren
    python scrape_sofascore.py --dump ruw.json  # ruwe respons wegschrijven

Uitvoer: xg.csv met
    speler, club, positie, wedstrijden, minuten_90s,
    goals_per90, xg_per90, assists_per90, xag_per90,
    gele_kaarten, rode_kaarten

Afhankelijkheden: pip install requests
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import requests

BASE = "https://api.sofascore.com/api/v1"
TOERNOOI_EREDIVISIE = 37          # geverifieerd: /unique-tournament/37 = Eredivisie
MIN_SPELERS = 200                 # ruime ondergrens; minder betekent iets is misgegaan
PAGINA = 100                      # limit per verzoek; ~4-5 verzoeken voor de hele competitie

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# De velden die het model nodig heeft, in Sofascore's eigen naamgeving. Het
# endpoint geeft alleen wat je hier opvraagt -- dus dit is tegelijk de
# documentatie van wat we ophalen en waarom.
VELDEN_API = [
    "goals",            # -> goals_per90
    "assists",          # -> assists_per90
    "expectedGoals",    # -> xg_per90
    "expectedAssists",  # -> xag_per90  (Sofascore's tegenhanger van FBref's xAG)
    "yellowCards",
    "redCards",
    "minutesPlayed",    # exacte minuten; FBref gaf afgeronde 90s
    "appearances",
]

# Sofascore schrijft zes clubnamen anders dan pouletips/clubs.csv. Deze map is
# opgebouwd uit de ECHTE respons (alle 18 clubs uit seizoen 26/27 zijn nagelopen),
# niet uit aannames. De twaalf andere clubs schrijft Sofascore identiek en
# hoeven hier dus niet in te staan.
CLUB_ALIAS_SOFASCORE = {
    "AZ Alkmaar": "AZ",
    "PSV Eindhoven": "PSV",
    "AFC Ajax": "Ajax",
    "NEC Nijmegen": "NEC",
    "SC Heerenveen": "sc Heerenveen",
    "SC Telstar": "Telstar",
    "Willem II Tilburg": "Willem II",
}


def norm_club(naam):
    naam = (naam or "").strip()
    return CLUB_ALIAS_SOFASCORE.get(naam, naam)


def haal_json(url, params=None, pogingen=3, pauze=3.0):
    """GET met herhaalpogingen. Faalt luid; geeft nooit half werk terug."""
    laatste = None
    for poging in range(pogingen):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.json()
            laatste = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            laatste = str(e)
        except ValueError as e:          # geen geldige JSON
            laatste = f"ongeldige JSON: {e}"
        if poging < pogingen - 1:
            time.sleep(pauze * (poging + 1))
    raise RuntimeError(
        f"kon {url} niet ophalen ({laatste}). Bij 403/429 blokkeert Sofascore het "
        f"verzoek (rate limit of botdetectie) -- dat is een toegangsprobleem, geen "
        f"veldprobleem. Bij 404: het seizoen-id klopt niet meer, draai met --seizoen.")


def huidig_seizoen(toernooi):
    """Het nieuwste seizoen-id voor dit toernooi.

    /seasons geeft de seizoenen met het nieuwste vooraan (geverifieerd: de
    eerste regel was 'Eredivisie 26/27', id 96143). We nemen die, maar printen
    de naam zodat in de log zichtbaar is welk seizoen is gebruikt -- in de
    voorbereiding op een nieuw seizoen kan het nieuwste seizoen nog leeg zijn,
    en dan wil je dat kunnen zien in plaats van raden.
    """
    d = haal_json(f"{BASE}/unique-tournament/{toernooi}/seasons")
    seizoenen = d.get("seasons") or []
    if not seizoenen:
        raise RuntimeError(f"geen seizoenen gevonden voor toernooi {toernooi}")
    return seizoenen[0]["id"], seizoenen[0].get("name", "?")


def haal_spelers(toernooi, seizoen, pagina=PAGINA, dump=None):
    """Alle spelersstatistieken van het seizoen, gepagineerd opgehaald."""
    url = f"{BASE}/unique-tournament/{toernooi}/season/{seizoen}/statistics"
    alles, offset, ruw = [], 0, []
    while True:
        d = haal_json(url, params={
            "limit": pagina,
            "offset": offset,
            "order": "-minutesPlayed",
            "accumulation": "total",
            "fields": ",".join(VELDEN_API),
        })
        resultaten = d.get("results") or []
        ruw.append(d)
        alles.extend(resultaten)
        # Stoppen op een korte pagina in plaats van op d["pages"]: dat werkt
        # ook als Sofascore die metadata ooit anders noemt of weglaat.
        if len(resultaten) < pagina:
            break
        offset += pagina
        if offset > 5000:               # noodrem tegen een oneindige lus
            raise RuntimeError("meer dan 5000 spelers opgehaald -- dat klopt niet; gestopt")
        time.sleep(0.5)                 # vriendelijk blijven: ~2 verzoeken per seconde
    if dump:
        Path(dump).write_text(json.dumps(ruw, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  ruwe respons -> {dump}")
    return alles


def naar_rijen(resultaten):
    """Sofascore-resultaten -> rijen in het fbref.csv-formaat dat het model leest.

    Per-90 wordt hier berekend uit exacte minuten. Een speler zonder minuten
    valt af: daar is niets uit te schatten, en 0 minuten zou een deling door
    nul geven (net als de `negentigers <= 0`-check in het oude scrape_fbref.py).
    """
    rijen = []
    for r in resultaten:
        speler = (r.get("player") or {}).get("name")
        club = norm_club((r.get("team") or {}).get("name"))
        minuten = float(r.get("minutesPlayed") or 0)
        if not speler or not club or minuten <= 0:
            continue
        n90 = minuten / 90.0

        def per90(sleutel):
            return round(float(r.get(sleutel) or 0) / n90, 4)

        rijen.append({
            "speler": speler,
            "club": club,
            # Sofascore levert de positie niet mee in dit endpoint. Het model
            # gebruikt deze kolom niet (de positie komt uit prijzen.csv); de
            # kolom blijft bestaan zodat het bestandsformaat identiek blijft.
            "positie": "",
            "wedstrijden": int(r.get("appearances") or 0),
            "minuten_90s": round(n90, 4),
            "goals_per90": per90("goals"),
            "xg_per90": per90("expectedGoals"),
            "assists_per90": per90("assists"),
            "xag_per90": per90("expectedAssists"),
            "gele_kaarten": float(r.get("yellowCards") or 0),
            "rode_kaarten": float(r.get("redCards") or 0),
        })
    return rijen


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--uit", default=".", help="doelmap voor xg.csv")
    p.add_argument("--toernooi", type=int, default=TOERNOOI_EREDIVISIE,
                   help="Sofascore unique-tournament id (37 = Eredivisie)")
    p.add_argument("--seizoen", type=int, default=None,
                   help="seizoen-id; standaard automatisch het nieuwste")
    p.add_argument("--min-spelers", type=int, default=MIN_SPELERS,
                   help="ondergrens; daaronder wordt er niets geschreven")
    p.add_argument("--dump", default=None, help="ruwe JSON-respons wegschrijven (voor debuggen)")
    a = p.parse_args()

    if a.seizoen:
        seizoen, naam = a.seizoen, "(handmatig opgegeven)"
    else:
        seizoen, naam = huidig_seizoen(a.toernooi)
    print(f"Sofascore ophalen: toernooi {a.toernooi}, seizoen {seizoen} {naam}")

    resultaten = haal_spelers(a.toernooi, seizoen, dump=a.dump)
    rijen = naar_rijen(resultaten)

    if len(rijen) < a.min_spelers:
        sys.exit(
            f"FOUT: slechts {len(rijen)} spelers met speeltijd gevonden (verwacht >= "
            f"{a.min_spelers}). Er wordt NIETS geschreven, zodat een half gevuld xg.csv "
            f"niet ongemerkt in het model terechtkomt. Mogelijke oorzaken: het seizoen is "
            f"nog niet begonnen (probeer --seizoen met het vorige seizoen), of het "
            f"endpoint geeft andere velden terug (draai met --dump en bekijk de respons).")

    velden = ["speler", "club", "positie", "wedstrijden", "minuten_90s",
              "goals_per90", "xg_per90", "assists_per90", "xag_per90",
              "gele_kaarten", "rode_kaarten"]
    uit = Path(a.uit)
    uit.mkdir(parents=True, exist_ok=True)
    pad = uit / "xg.csv"
    with pad.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=velden)
        w.writeheader()
        for r in rijen:
            w.writerow(r)

    clubs = sorted({r["club"] for r in rijen})
    print(f"{len(rijen)} spelers -> {pad}")
    print(f"  clubs: {len(clubs)}")
    if len(clubs) != 18:
        print(f"  LET OP: {len(clubs)} clubs gevonden, verwacht 18 voor de Eredivisie.")
    # Clubnamen die noch in de aliasmap staan, noch al de doelspelling zijn,
    # kunnen niet matchen met clubs.csv -- dan valt die hele club stil in het
    # model zonder dat er iets crasht. Dus expliciet melden.
    bekend = set(CLUB_ALIAS_SOFASCORE.values())
    onbekend = [c for c in clubs if c not in bekend and c not in CLUB_ALIAS_SOFASCORE]
    if onbekend:
        print(f"  Controleer of deze clubnamen exact zo in clubs.csv staan "
              f"(anders aanvullen in CLUB_ALIAS_SOFASCORE):")
        for c in onbekend:
            print(f"    {c!r}")


if __name__ == "__main__":
    main()
