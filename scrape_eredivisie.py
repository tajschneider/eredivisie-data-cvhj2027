#!/usr/bin/env python3
"""
Eredivisie-data per speelronde ophalen en wegschrijven naar CSV.

Bron: pouletips.nl wedstrijdpagina's. Die bevatten per duel de officiele
basiselftallen, de bank, alle wissels MET minuut, de doelpuntenmakers en de
afwezigen met reden. Dat is precies wat het CVHJ-model nodig heeft.

Gebruik:
    python scrape_eredivisie.py --ronde 1
    python scrape_eredivisie.py --ronde 1 --ronde 2 --ronde 3
    python scrape_eredivisie.py --alles-tot 4

Output (append, dedupliceert op ronde+speler):
    spelers.csv   ronde, speler, club, basis, minuten, goals, geel, rood, ...
    clubs.csv     ronde, club, tegenstander, thuis_uit, voor, tegen, ...

Afhankelijkheden:  pip install requests beautifulsoup4
"""
import argparse, csv, os, re, sys, time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://pouletips.nl"
ROUND_URL = BASE + "/eredivisie/speelronde/{ronde}/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cvhj-model/1.0)"}
OUT = Path(__file__).parent

SPELER_COLS = ["ronde", "datum", "speler", "club", "tegenstander", "thuis_uit",
               "basis", "minuten", "goals", "geel", "rood", "clean_sheet",
               "ploegpunten", "afwezig_reden", "opgehaald"]
CLUB_COLS = ["ronde", "datum", "club", "tegenstander", "thuis_uit", "voor",
             "tegen", "resultaat", "ploegpunten", "clean_sheet", "formatie",
             "kans_winst", "verwachte_goals", "opgehaald"]


def get(url, pauze=1.5):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    time.sleep(pauze)                      # wees beleefd tegen de bron
    return BeautifulSoup(r.text, "html.parser")


def match_urls(ronde):
    """Alle wedstrijd-URL's van een speelronde."""
    soup = get(ROUND_URL.format(ronde=ronde))
    urls = {a["href"] for a in soup.select('a[href*="/eredivisie/wedstrijd/"]')}
    return sorted(u if u.startswith("http") else BASE + u for u in urls)


def _minuut(txt):
    m = re.search(r"(\d{1,3})'", txt or "")
    return int(m.group(1)) if m else None


def parse_match(url, ronde):
    soup = get(url)
    tekst = soup.get_text("\n", strip=True)

    # --- uitslag en clubs ---
    kop = soup.find("h1").get_text(" ", strip=True)
    m = re.search(r"(.+?)\s*-\s*(.+?)\s+uitslag:\s*(\d+)-(\d+)", kop)
    if not m:
        print(f"  ! geen uitslag gevonden op {url}")
        return [], []
    thuis, uit, gh, ga = m.group(1).strip(), m.group(2).strip(), int(m.group(3)), int(m.group(4))
    dm = re.search(r"Speelronde\s+\d+\s*·\s*([^\n]+)", tekst)
    datum = dm.group(1).strip() if dm else ""

    # --- doelpuntenmakers: naam + minuut ---
    goals = {}
    for a in soup.select('a[href*="/eredivisie/speler/"]'):
        naam = a.get_text(" ", strip=True)
        omgeving = a.parent.get_text(" ", strip=True) if a.parent else ""
        mi = _minuut(omgeving)
        if mi and naam and len(naam.split()) >= 2:
            goals[naam] = goals.get(naam, 0) + 1

    club_rows, speler_rows = [], []
    for club, tegen, gf, gc in ((thuis, uit, gh, ga), (uit, thuis, ga, gh)):
        res = "W" if gf > gc else ("G" if gf == gc else "V")
        club_rows.append({
            "ronde": ronde, "datum": datum, "club": club, "tegenstander": tegen,
            "thuis_uit": "thuis" if club == thuis else "uit", "voor": gf, "tegen": gc,
            "resultaat": res, "ploegpunten": 3 if res == "W" else (1 if res == "G" else 0),
            "clean_sheet": int(gc == 0), "formatie": "", "kans_winst": "",
            "verwachte_goals": "", "opgehaald": time.strftime("%Y-%m-%d"),
        })

    # --- opstellingen uit de FAQ-samenvatting (stabielste plek op de pagina) ---
    for club, tegen, gf, gc in ((thuis, uit, gh, ga), (uit, thuis, ga, gh)):
        pat = rf"De offici[eë]le opstelling van {re.escape(club)}\s*\(([\d\-]+)\):\s*([^.]+)\."
        mm = re.search(pat, tekst)
        basisnamen = [n.strip() for n in mm.group(2).split(",")] if mm else []
        formatie = mm.group(1) if mm else ""
        for r in club_rows:
            if r["club"] == club:
                r["formatie"] = formatie

        # wissels: "62' ↑ X voor Y"  -> Y eruit op 62, X erin op 62
        eruit, erin = {}, {}
        vlak = re.sub(r"\s+", " ", tekst)
        for w in re.finditer(
                r"(\d{1,3})\s*'\s*[↑↓\-–]*\s*([A-ZÀ-Ý][\w'’.\-]*(?:\s+[\w'’.\-]+){0,3}?)"
                r"\s+voor\s+([A-ZÀ-Ý][\w'’.\-]*(?:\s+[\w'’.\-]+){0,3})", vlak):
            mi, inn, out = int(w.group(1)), w.group(2).strip(), w.group(3).strip()
            eruit[out] = mi
            erin[inn] = mi
        print(f"    {club}: {len(erin)} wissels gevonden")

        for naam in basisnamen:
            speler_rows.append({
                "ronde": ronde, "datum": datum, "speler": naam, "club": club,
                "tegenstander": tegen, "thuis_uit": "thuis" if club == thuis else "uit",
                "basis": 1, "minuten": eruit.get(naam, 90),
                "goals": goals.get(naam, 0), "geel": "", "rood": "",
                "clean_sheet": int(gc == 0),
                "ploegpunten": 3 if gf > gc else (1 if gf == gc else 0),
                "afwezig_reden": "", "opgehaald": time.strftime("%Y-%m-%d"),
            })
        for naam, mi in erin.items():
            if naam in basisnamen:
                continue
            speler_rows.append({
                "ronde": ronde, "datum": datum, "speler": naam, "club": club,
                "tegenstander": tegen, "thuis_uit": "thuis" if club == thuis else "uit",
                "basis": 0, "minuten": max(0, 90 - mi), "goals": goals.get(naam, 0),
                "geel": "", "rood": "", "clean_sheet": int(gc == 0),
                "ploegpunten": 3 if gf > gc else (1 if gf == gc else 0),
                "afwezig_reden": "", "opgehaald": time.strftime("%Y-%m-%d"),
            })

    # --- afwezigen met reden ---
    for line in tekst.split("\n"):
        if line.startswith("Afwezig:"):
            for stuk in line.replace("Afwezig:", "").split(","):
                am = re.match(r"\s*(.+?)\s*\((.+?)\)", stuk)
                if am:
                    speler_rows.append({
                        "ronde": ronde, "datum": datum, "speler": am.group(1).strip(),
                        "club": "", "tegenstander": "", "thuis_uit": "", "basis": 0,
                        "minuten": 0, "goals": 0, "geel": "", "rood": "",
                        "clean_sheet": "", "ploegpunten": 0,
                        "afwezig_reden": am.group(2).strip(),
                        "opgehaald": time.strftime("%Y-%m-%d"),
                    })
    return club_rows, speler_rows


def schrijf(pad, cols, nieuw, sleutel):
    bestaand, gezien = [], set()
    if pad.exists():
        with open(pad, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                bestaand.append(r)
                gezien.add(tuple(str(r.get(k, "")) for k in sleutel))
    toegevoegd = 0
    for r in nieuw:                                  # nieuwe data wint bij dubbel
        k = tuple(str(r.get(c, "")) for c in sleutel)
        if k in gezien:
            continue
        bestaand.append(r); gezien.add(k); toegevoegd += 1
    with open(pad, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(bestaand)
    print(f"  {pad.name}: +{toegevoegd} regels (totaal {len(bestaand)})")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ronde", type=int, action="append", default=[])
    p.add_argument("--alles-tot", type=int)
    a = p.parse_args()
    rondes = a.ronde or []
    if a.alles_tot:
        rondes = list(range(1, a.alles_tot + 1))
    if not rondes:
        sys.exit("Geef --ronde N of --alles-tot N")

    for ronde in rondes:
        print(f"Speelronde {ronde}")
        cr, sr = [], []
        for url in match_urls(ronde):
            print(f"  {url.rsplit('/', 2)[-2]}")
            try:
                c, s = parse_match(url, ronde)
                cr += c; sr += s
            except Exception as e:
                print(f"  ! mislukt: {e}")
        schrijf(OUT / "clubs.csv", CLUB_COLS, cr, ["ronde", "club"])
        schrijf(OUT / "spelers.csv", SPELER_COLS, sr, ["ronde", "speler"])


if __name__ == "__main__":
    main()
