#!/usr/bin/env python3
"""
Eredivisie-data per speelronde ophalen en wegschrijven naar CSV.

Bron: pouletips.nl wedstrijdpagina's — officiele basiselftallen, bank, wissels
met minuut, doelpuntenmakers en afwezigen met reden.

Gebruik:
    python scrape_eredivisie.py --ronde 1
    python scrape_eredivisie.py --alles-tot 34

Afhankelijkheden:  pip install requests beautifulsoup4
"""
import argparse, csv, re, sys, time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://pouletips.nl"
ROUND_URL = BASE + "/eredivisie/speelronde/{ronde}/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cvhj-model/1.0)"}
OUT = Path(__file__).parent

SPELER_COLS = ["ronde", "datum", "speler", "speler_id", "club", "tegenstander",
               "thuis_uit", "status", "basis", "minuten", "goals", "clean_sheet",
               "ploegpunten", "afwezig_reden", "opgehaald"]
CLUB_COLS = ["ronde", "datum", "club", "tegenstander", "thuis_uit", "voor",
             "tegen", "resultaat", "ploegpunten", "clean_sheet", "formatie",
             "opgehaald"]
VANDAAG = time.strftime("%Y-%m-%d")


def get(url, pauze=1.5):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    time.sleep(pauze)
    return BeautifulSoup(r.text, "html.parser")


def match_urls(ronde):
    soup = get(ROUND_URL.format(ronde=ronde))
    urls = {a["href"] for a in soup.select('a[href*="/eredivisie/wedstrijd/"]')}
    return sorted(u if u.startswith("http") else BASE + u for u in urls)


def slug_naar_naam(slug):
    return " ".join(w.capitalize() for w in slug.split("-"))


def club_secties(lines, clubs):
    """Knip de pagina in blokken per club. Een clubkop is een regel met alleen
    de clubnaam, direct gevolgd door een formatie zoals 4-2-3-1."""
    koppen = [(i, l.strip()) for i, l in enumerate(lines[:-1])
              if l.strip() in clubs and re.fullmatch(r"\d+(-\d+)+", lines[i + 1].strip())]
    secties = {}
    for k, (i, club) in enumerate(koppen):
        eind = koppen[k + 1][0] if k + 1 < len(koppen) else len(lines)
        secties[club] = lines[i:eind]
    return secties


def parse_wissels(sectie):
    """[(minuut, in, uit)] binnen EEN clubblok. Per regel, dus geen namen die
    het volgende minuutgetal opslurpen."""
    out = []
    for raw in sectie:
        l = raw.strip().lstrip("-*• ").strip()
        m = re.match(r"(\d{1,3})\s*'\s*[↑↓]?\s*(.+?)\s+voor\s+(.+?)\s*$", l)
        if m:
            out.append((int(m.group(1)), m.group(2).strip(), m.group(3).strip()))
    return out


def parse_bank(sectie_html):
    """Bankspelers via de link-slug, want de zichtbare tekst is alleen de
    achternaam."""
    namen = []
    for m in re.finditer(r"/eredivisie/speler/([^/\"')\s]+)/", sectie_html):
        slug = m.group(1)
        if slug not in [s for s, _ in namen]:
            namen.append((slug, slug_naar_naam(slug)))
    return namen


def parse_match(url, ronde):
    soup = get(url)
    plat = re.sub(r"[ \t]+", " ", soup.get_text("\n", strip=True))
    lines = plat.split("\n")

    kop = soup.find("h1").get_text(" ", strip=True)
    m = re.search(r"(.+?)\s*-\s*(.+?)\s+uitslag:\s*(\d+)-(\d+)", kop)
    if not m:
        print("    ! geen uitslag gevonden"); return [], []
    thuis, uitc = m.group(1).strip(), m.group(2).strip()
    gh, ga = int(m.group(3)), int(m.group(4))
    dm = re.search(r"Speelronde\s+\d+\s*·\s*(.+)", plat)
    datum = dm.group(1).strip() if dm else ""

    # doelpunten: tel per speler-slug hoe vaak hij bij een minuut staat
    goals = {}
    for a in soup.select('a[href*="/eredivisie/speler/"]'):
        omg = a.parent.get_text(" ", strip=True) if a.parent else ""
        sm = re.search(r"/speler/([^/]+)/", a.get("href", ""))
        if sm and re.search(r"\d{1,3}\s*'", omg):
            goals[sm.group(1)] = goals.get(sm.group(1), 0) + 1

    secties = club_secties(lines, {thuis, uitc})
    club_rows, speler_rows = [], []

    for club, tegen, gf, gc in ((thuis, uitc, gh, ga), (uitc, thuis, ga, gh)):
        res = "W" if gf > gc else ("G" if gf == gc else "V")
        ppt = 3 if res == "W" else (1 if res == "G" else 0)
        tu = "thuis" if club == thuis else "uit"
        sectie = secties.get(club, [])
        formatie = sectie[1].strip() if len(sectie) > 1 else ""

        club_rows.append({
            "ronde": ronde, "datum": datum, "club": club, "tegenstander": tegen,
            "thuis_uit": tu, "voor": gf, "tegen": gc, "resultaat": res,
            "ploegpunten": ppt, "clean_sheet": int(gc == 0), "formatie": formatie,
            "opgehaald": VANDAAG})

        # basiself uit de FAQ; lookahead stopt op de volgende zin, dus namen met
        # een punt ("Jeremiah St. Juste", "Ronald Koeman Jr.") blijven heel
        pat = (rf"De offici[eë]le opstelling van {re.escape(club)}\s*\([\d\-]+\):\s*"
               rf"(.+?)(?=De offici[eë]le opstelling van|Wie was de scheidsrechter|\Z)")
        fm = re.search(pat, plat, re.S)
        basis = []
        if fm:
            blok = fm.group(1).replace("\n", " ").strip()
            blok = re.sub(r"\.\s*$", "", blok)
            basis = [n.strip() for n in blok.split(",") if n.strip()]

        wissels = parse_wissels(sectie)
        eruit = {w[2]: w[0] for w in wissels}
        erin = {w[1]: w[0] for w in wissels}

        sectie_html = "\n".join(sectie)
        bank = [(s, n) for s, n in parse_bank(sectie_html) if n not in basis]

        naar_slug = {n: s for s, n in bank}

        def sid(naam):
            return naar_slug.get(naam, naam.lower().replace(" ", "-").replace(".", ""))

        for naam in basis:
            s = sid(naam)
            speler_rows.append({
                "ronde": ronde, "datum": datum, "speler": naam, "speler_id": s,
                "club": club, "tegenstander": tegen, "thuis_uit": tu,
                "status": "basis", "basis": 1, "minuten": eruit.get(naam, 90),
                "goals": goals.get(s, 0), "clean_sheet": int(gc == 0),
                "ploegpunten": ppt, "afwezig_reden": "", "opgehaald": VANDAAG})

        for slug, naam in bank:
            mi = erin.get(naam)
            speler_rows.append({
                "ronde": ronde, "datum": datum, "speler": naam, "speler_id": slug,
                "club": club, "tegenstander": tegen, "thuis_uit": tu,
                "status": "invaller" if mi else "bank", "basis": 0,
                "minuten": (90 - mi) if mi else 0,
                "goals": goals.get(slug, 0) if mi else 0,
                "clean_sheet": int(gc == 0) if mi else "",
                "ploegpunten": ppt if mi else 0,
                "afwezig_reden": "", "opgehaald": VANDAAG})

        for raw in sectie:
            if raw.strip().startswith("Afwezig:"):
                for stuk in raw.split("Afwezig:", 1)[1].split(","):
                    am = re.match(r"\s*(.+?)\s*\((.+?)\)", stuk)
                    if am:
                        nm = am.group(1).strip()
                        speler_rows.append({
                            "ronde": ronde, "datum": datum, "speler": nm,
                            "speler_id": nm.lower().replace(" ", "-").replace(".", ""),
                            "club": club, "tegenstander": tegen, "thuis_uit": tu,
                            "status": "afwezig", "basis": 0, "minuten": 0, "goals": 0,
                            "clean_sheet": "", "ploegpunten": 0,
                            "afwezig_reden": am.group(2).strip(), "opgehaald": VANDAAG})

        print(f"    {club}: {len(basis)} basis, {len(bank)} bank, {len(wissels)} wissels")
    return club_rows, speler_rows


def schrijf(pad, cols, nieuw, sleutel):
    rijen, index = [], {}
    if pad.exists():
        with open(pad, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                k = tuple(str(r.get(c, "")) for c in sleutel)
                index[k] = len(rijen); rijen.append(r)
    bij = 0
    for r in nieuw:                        # nieuwe data overschrijft oude
        k = tuple(str(r.get(c, "")) for c in sleutel)
        if k in index:
            rijen[index[k]] = r
        else:
            index[k] = len(rijen); rijen.append(r); bij += 1
    with open(pad, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(rijen)
    print(f"  {pad.name}: {bij} nieuw, {len(rijen)} totaal")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ronde", type=int, action="append", default=[])
    p.add_argument("--alles-tot", type=int)
    a = p.parse_args()
    rondes = a.ronde or (list(range(1, a.alles_tot + 1)) if a.alles_tot else [])
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
                print(f"    ! mislukt: {e}")
        if cr or sr:
            schrijf(OUT / "clubs.csv", CLUB_COLS, cr, ["ronde", "club"])
            schrijf(OUT / "spelers.csv", SPELER_COLS, sr, ["ronde", "speler_id", "club"])


if __name__ == "__main__":
    main()
