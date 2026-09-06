#!/usr/bin/env python3
"""
Programma van de eerstvolgende speelronde ophalen -> programma.csv

Vult het gat dat scrape_eredivisie.py laat: die schrijft alleen GESPEELDE
wedstrijden weg (parse_match stopt bij "nog geen uitslag"). Voor de
transferbeslissing heeft het model juist de KOMENDE ronde nodig, inclusief
de winstkansen vooraf.

Doet drie dingen:
  1. bepaalt welke ronde de eerstvolgende nog niet (volledig) gespeelde is
  2. haalt per wedstrijd datum en 'Kansen vooraf' op
  3. spoort uitgestelde duels op -- wedstrijden uit een eerdere ronde die
     nog geen uitslag hebben (de INHAAL-lijst van het model)

Gebruik:
    python scrape_programma.py                      # volgende ronde, automatisch
    python scrape_programma.py --ronde 6
    python scrape_programma.py --clubs ../data/clubs.csv --uit data/
    python scrape_programma.py --snippet            # PROGRAMMA/INHAAL als Python
    python scrape_programma.py --horizon 4           # + programma van de 3 ronden erna

Uitvoer: programma.csv met
    ronde, datum, thuis, uit, kans_thuis, kans_gelijk, kans_uit,
    verwacht_thuis, verwacht_uit, soort

soort:  regulier      wedstrijd van de komende ronde (of, met --horizon, van een
                      van de ronden erna -- te onderscheiden via de kolom 'ronde')
        inhaal        uitgesteld duel dat VOOR de volgende deadline wordt
                      gespeeld -- telt mee, want je zet er nu je elftal voor
        inhaal_later  uitgesteld duel daarna -- staat er wel in, telt niet mee

--horizon haalt ronde+1 t/m ronde+N-1 ERBIJ, zonder de inhaalzoektocht (die is
alleen zinvol relatief aan de eerstvolgende deadline). Verre ronden hebben
meestal nog geen kansen vooraf -- multi_periode.py heeft die toch niet nodig,
zie de toelichting daar: alleen de indeling (wie tegen wie) telt voor een
ronde die nog niet dichtbij is.

Afhankelijkheden: pip install requests beautifulsoup4
"""
import argparse
import collections
import csv
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://pouletips.nl"
ROUND_URL = BASE + "/eredivisie/speelronde/{ronde}/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cvhj-model/1.0)"}
LAATSTE_RONDE = 34
WEDSTRIJDEN_PER_RONDE = 9   # 18 clubs

MAANDEN = {"januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5,
           "juni": 6, "juli": 7, "augustus": 8, "september": 9,
           "oktober": 10, "november": 11, "december": 12}

TRANS = str.maketrans({
    "ø": "o", "Ø": "O", "æ": "ae", "Æ": "Ae", "å": "a", "Å": "A",
    "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th", "ł": "l", "Ł": "L",
    "đ": "d", "Đ": "D", "ß": "ss", "ı": "i",
})


def norm(s):
    s = s.strip().translate(TRANS)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()


def get(url, pauze=1.2, pogingen=4):
    laatste = None
    for poging in range(pogingen):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                time.sleep(pauze)
                return BeautifulSoup(r.text, "html.parser")
            laatste = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            laatste = str(e)
        time.sleep(pauze * (poging + 1))
    raise RuntimeError(f"niet op te halen: {url} ({laatste})")


def lees_clubs(pad):
    """Exacte clubnamen uit clubs.csv -> {slug: naam}.

    Slug-naar-naam raden gaat mis bij 'sc Heerenveen' en 'Go Ahead Eagles'.
    De scraperdata bevat de namen al goed, dus die is de bron van waarheid.
    Levert meteen ook de al gespeelde (ronde, thuis, uit)-combinaties op.
    """
    if not Path(pad).exists():
        sys.exit(f"FOUT: {pad} niet gevonden. Wijs met --clubs naar clubs.csv "
                 f"uit de data-repo; zonder exacte clubnamen sluit de join niet aan.")
    namen, gespeeld, max_ronde = {}, set(), 0
    with open(pad, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            namen[norm(r["club"])] = r["club"]
            ronde = int(r["ronde"])
            max_ronde = max(max_ronde, ronde)
            if r["thuis_uit"] == "thuis" and r.get("resultaat"):
                gespeeld.add((ronde, r["club"], r["tegenstander"]))
    return namen, gespeeld, max_ronde


def match_urls(ronde):
    soup = get(ROUND_URL.format(ronde=ronde))
    urls = {a["href"] for a in soup.select('a[href*="/eredivisie/wedstrijd/"]')}
    return sorted(u if u.startswith("http") else BASE + u for u in urls)


def clubs_uit_url(url, namen):
    """'/eredivisie/wedstrijd/psv-fortuna-sittard/' -> ('PSV', 'Fortuna Sittard').

    De slug is thuis-uit aan elkaar geplakt zonder scheidingsteken, dus wordt
    er gezocht naar de splitsing waarbij BEIDE helften een bekende club zijn.
    """
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    delen = slug.split("-")
    for k in range(1, len(delen)):
        links, rechts = "-".join(delen[:k]), "-".join(delen[k:])
        if links in namen and rechts in namen:
            return namen[links], namen[rechts]
    return None, None


def parse_datum(plat):
    m = re.search(r"Speelronde\s+\d+\s*·\s*(.+)", plat)
    return m.group(1).strip() if m else ""


def datum_naar_dt(datum):
    """'zaterdag 8 augustus 2026, 21:00' -> datetime, of None."""
    m = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})(?:,\s*(\d{1,2}):(\d{2}))?",
                  datum.lower())
    if not m or m.group(2) not in MAANDEN:
        return None
    return datetime(int(m.group(3)), MAANDEN[m.group(2)], int(m.group(1)),
                    int(m.group(4) or 0), int(m.group(5) or 0))


def parse_odds(plat):
    """'Kansen vooraf 64% 19% 17%' -> (thuis, gelijk, uit), volgorde is vast."""
    m = re.search(r"Kansen vooraf\s*(\d{1,3})\s*%\s*(\d{1,3})\s*%\s*(\d{1,3})\s*%",
                  plat, re.S)
    if not m:
        m = re.search(r"(\d{1,3})\s*%\s*(\d{1,3})\s*%\s*(\d{1,3})\s*%", plat, re.S)
    return (m.group(1), m.group(2), m.group(3)) if m else ("", "", "")


def parse_verwacht(plat):
    ms = re.search(r"Meest waarschijnlijke uitslagen(.{0,400})", plat, re.S)
    if not ms:
        return "", ""
    sc = re.search(r"(\d)\s*-\s*(\d)\s*\n?\s*\d+[.,]\d+\s*%", ms.group(1), re.S)
    return (sc.group(1), sc.group(2)) if sc else ("", "")


def parse_wedstrijd(url, ronde, namen):
    """Eén wedstrijdpagina -> rij, of None als hij al gespeeld is."""
    soup = get(url)
    plat = re.sub(r"[ \t]+", " ", soup.get_text("\n", strip=True))
    h1 = soup.find("h1")
    kop = h1.get_text(" ", strip=True) if h1 else ""

    if re.search(r"uitslag:\s*\d+\s*-\s*\d+", kop):
        return None  # al gespeeld; staat al in clubs.csv

    thuis, uit = clubs_uit_url(url, namen)
    if not thuis:  # terugval op de kop
        m = re.match(r"(.+?)\s+-\s+(.+?)$", re.sub(r"\s+", " ", kop).strip())
        if m:
            thuis, uit = m.group(1).strip(), m.group(2).strip()
    if not thuis:
        print(f"    ! clubs niet herkend: {url}")
        return None

    kt, kg, ku = parse_odds(plat)
    vt, vu = parse_verwacht(plat)
    datum = parse_datum(plat)
    vlag = "" if kt else "   <-- geen kansen vooraf"
    print(f"    {thuis} - {uit}  ({datum}) {kt}/{kg}/{ku}{vlag}")
    return {"ronde": ronde, "datum": datum, "thuis": thuis, "uit": uit,
            "kans_thuis": kt, "kans_gelijk": kg, "kans_uit": ku,
            "verwacht_thuis": vt, "verwacht_uit": vu, "soort": "regulier"}


def volgende_ronde(namen, max_ronde, nu=None):
    """Eerste ronde waarvan de DEADLINE nog niet verstreken is.

    Niet "eerste ronde met een onspeelde wedstrijd": op een zondagmiddag loopt
    de huidige ronde nog, maar de deadline lag vrijdag bij de aftrap van de
    eerste wedstrijd. Adviseren over die ronde is zinloos -- je kunt niets meer
    wijzigen. Bepalend is dus of de eerste wedstrijd nog moet beginnen.
    """
    nu = nu or datetime.now()
    for ronde in range(max(1, max_ronde), LAATSTE_RONDE + 1):
        data = []
        for url in match_urls(ronde):
            soup = get(url)
            plat = re.sub(r"[ \t]+", " ", soup.get_text("\n", strip=True))
            h1 = soup.find("h1")
            kop = h1.get_text(" ", strip=True) if h1 else ""
            if re.search(r"uitslag:\s*\d+\s*-\s*\d+", kop):
                continue
            dt = datum_naar_dt(parse_datum(plat))
            if dt:
                data.append(dt)
        if not data:
            continue                      # ronde volledig gespeeld
        if min(data) > nu:
            return ronde                  # deadline nog niet verstreken
        print(f"  ronde {ronde} is al begonnen (deadline verstreken), doorschuiven")
    sys.exit("FOUT: geen ronde met een openstaande deadline gevonden.")


def zoek_inhaal(namen, gespeeld, tot_ronde):
    """Uitgestelde duels: een eerdere ronde die geen negen uitslagen heeft.

    NIET op "datum al verstreken" testen. Zodra een uitgesteld duel een nieuwe
    speeldatum krijgt, ligt die in de TOEKOMST -- juist het geval dat we willen
    vinden. Het signaal is dat de ronde onvolledig is, niet dat de datum voorbij
    is.

    Werkt vanuit clubs.csv: alleen rondes met minder dan negen wedstrijden
    worden opgehaald, en daarbinnen alleen de ontbrekende duels. Dat scheelt
    ~300 paginabezoeken per draai aan het eind van het seizoen.
    """
    per_ronde = collections.Counter(r for r, _, _ in gespeeld)
    rijen = []
    for ronde in range(1, tot_ronde):
        if per_ronde.get(ronde, 0) >= WEDSTRIJDEN_PER_RONDE:
            continue
        print(f"    ronde {ronde}: {per_ronde.get(ronde, 0)}/{WEDSTRIJDEN_PER_RONDE} "
              f"uitslagen, ontbrekende duels ophalen")
        for url in match_urls(ronde):
            thuis, uit = clubs_uit_url(url, namen)
            if not thuis or (ronde, thuis, uit) in gespeeld:
                continue
            soup = get(url)
            plat = re.sub(r"[ \t]+", " ", soup.get_text("\n", strip=True))
            h1 = soup.find("h1")
            kop = h1.get_text(" ", strip=True) if h1 else ""
            if re.search(r"uitslag:\s*\d+\s*-\s*\d+", kop):
                continue  # inmiddels gespeeld, scraper moet nog bijwerken
            kt, kg, ku = parse_odds(plat)
            vt, vu = parse_verwacht(plat)
            datum = parse_datum(plat)
            print(f"      inhaal: {thuis} - {uit}  ({datum or 'datum onbekend'})")
            rijen.append({"ronde": ronde, "datum": datum,
                          "thuis": thuis, "uit": uit, "kans_thuis": kt,
                          "kans_gelijk": kg, "kans_uit": ku,
                          "verwacht_thuis": vt, "verwacht_uit": vu,
                          "soort": "inhaal"})
    return rijen


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ronde", type=int, help="expliciete ronde (anders automatisch)")
    p.add_argument("--clubs", default="clubs.csv", help="pad naar clubs.csv")
    p.add_argument("--uit", default=".", help="doelmap voor programma.csv")
    p.add_argument("--geen-inhaal", action="store_true", help="sla inhaaldetectie over")
    p.add_argument("--venster-dagen", type=float, default=7.0,
                   help="dagen tot de volgende deadline (standaard 7)")
    p.add_argument("--snippet", action="store_true",
                   help="druk PROGRAMMA/INHAAL af als Python-blokken")
    p.add_argument("--horizon", type=int, default=1,
                   help="aantal ronden vooruit (standaard 1 = alleen de eerstvolgende); "
                        "voor multi_periode.py minstens de resterende ronden in de periode")
    args = p.parse_args()

    namen, gespeeld, max_ronde = lees_clubs(args.clubs)
    print(f"{len(namen)} clubs bekend, data t/m ronde {max_ronde}")

    ronde = args.ronde or volgende_ronde(namen, max_ronde)
    print(f"\nprogramma ronde {ronde}:")

    rijen = []
    for url in match_urls(ronde):
        rij = parse_wedstrijd(url, ronde, namen)
        if rij:
            rijen.append(rij)

    if not rijen:
        sys.exit(f"FOUT: geen openstaande wedstrijden in ronde {ronde}. "
                 f"Is de ronde al gespeeld? Probeer --ronde {ronde + 1}.")

    inhaal = []
    if not args.geen_inhaal:
        print("\ninhaalduels:")
        inhaal = zoek_inhaal(namen, gespeeld, ronde)
        if not inhaal:
            print("    geen")
        rijen.extend(inhaal)

    # Telt een inhaalduel mee voor DEZE beslissing?
    #
    # Bepalend is niet wanneer de rest van de ronde speelt, maar welk elftal er
    # staat op het moment van het inhaalduel. Het team dat je vastzet bij de
    # deadline van deze ronde blijft staan tot de deadline van de volgende.
    # Alles wat in dat venster wordt gespeeld, speel je met dit elftal.
    #
    # Voorbeeld: ronde 6 begint vrijdag 11 september, een uitgesteld duel uit
    # ronde 3 wordt gespeeld op dinsdag 15 september. Dat valt na de laatste
    # wedstrijd van ronde 6, maar ruim voor de deadline van ronde 7 -- dus het
    # telt wel degelijk mee, en je moet die spelers nu al bezitten.
    #
    # De deadline van de volgende ronde staat nog nergens; de Eredivisie speelt
    # wekelijks, dus wordt zeven dagen aangehouden. Bij een interlandperiode of
    # een bekerweek klopt dat niet -- vandaar --venster-dagen.
    speeldata = [d for d in (datum_naar_dt(r["datum"]) for r in rijen
                             if r["soort"] == "regulier") if d]
    deadline = min(speeldata) if speeldata else None
    volgende = deadline + timedelta(days=args.venster_dagen) if deadline else None
    for r in inhaal:
        dt = datum_naar_dt(r["datum"])
        if not deadline or not dt:
            continue          # datum onbekend: laten staan, mens beslist
        if not (deadline <= dt < volgende):
            r["soort"] = "inhaal_later"

    verder = []
    if args.horizon > 1:
        print(f"\nprogramma horizon (ronde {ronde + 1} t/m {ronde + args.horizon - 1}):")
        for latere_ronde in range(ronde + 1, ronde + args.horizon):
            print(f"  ronde {latere_ronde}:")
            gevonden = 0
            for url in match_urls(latere_ronde):
                rij = parse_wedstrijd(url, latere_ronde, namen)
                if rij:
                    verder.append(rij)
                    gevonden += 1
            if gevonden == 0:
                print(f"    geen wedstrijden gevonden voor ronde {latere_ronde} -- "
                      f"programma stopt hier (seizoen op, of pagina bestaat nog niet)")
                break
        rijen.extend(verder)

    uit = Path(args.uit)
    uit.mkdir(parents=True, exist_ok=True)
    pad = uit / "programma.csv"
    velden = ["ronde", "datum", "thuis", "uit", "kans_thuis", "kans_gelijk",
              "kans_uit", "verwacht_thuis", "verwacht_uit", "soort"]
    with pad.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=velden)
        w.writeheader()
        w.writerows(rijen)

    regulier = [r for r in rijen if r["soort"] == "regulier"]
    meegeteld = [r for r in rijen if r["soort"] == "inhaal"]
    later = [r for r in rijen if r["soort"] == "inhaal_later"]
    zonder = [r for r in regulier if not r["kans_thuis"]]
    print(f"\n{len(regulier)} wedstrijden + {len(meegeteld)} inhaal -> {pad}")
    if verder:
        rondes_gehaald = sorted({r["ronde"] for r in verder})
        print(f"  waarvan {len(verder)} uit de horizon (ronde {rondes_gehaald[0]} t/m {rondes_gehaald[-1]})")
    if zonder:
        print(f"  LET OP: {len(zonder)} wedstrijd(en) zonder kansen vooraf; "
              f"het model valt daar sowieso op terug voor de puntenschatting -- "
              f"die gebruikt alleen wie tegen wie speelt, geen marktkansen per duel.")
    if later:
        print(f"  {len(later)} inhaalduel(s) worden NA deze ronde gespeeld en "
              f"tellen dus niet mee voor deze beslissing:")
        for r in later:
            print(f"    {r['thuis']} - {r['uit']} ({r['datum']}) -> soort=inhaal_later")

    if args.snippet:
        print("\n# --- plak in cvhj_model.py ---")
        print("PROGRAMMA = [")
        for r in regulier:
            print(f'    ("{r["thuis"]}", "{r["uit"]}"),')
        print("]")
        print("INHAAL = [")
        for r in rijen:
            if r["soort"] == "inhaal":
                print(f'    ("{r["thuis"]}", "{r["uit"]}"),')
        print("]")


if __name__ == "__main__":
    main()
