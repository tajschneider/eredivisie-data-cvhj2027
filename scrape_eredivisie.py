#!/usr/bin/env python3
"""
Eredivisie-data per speelronde ophalen en wegschrijven naar CSV.

Bron: pouletips.nl wedstrijdpagina's — officiele basiselftallen, bank,
wissels met minuut, doelpuntenmakers en afwezigen met reden.

Gebruik:
    python scrape_eredivisie.py --ronde 1
    python scrape_eredivisie.py --alles-tot 34
    python scrape_eredivisie.py --debug https://pouletips.nl/eredivisie/wedstrijd/psv-fortuna-sittard/

Die laatste drukt af wat er daadwerkelijk in de HTML staat. Gebruik hem zodra
een club "0 bank" of "0 wissels" oplevert; dan hoeft er niet geraden te worden.

Afhankelijkheden:  pip install requests beautifulsoup4
"""
import argparse
import csv
import html as htmllib
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://pouletips.nl"
ROUND_URL = BASE + "/eredivisie/speelronde/{ronde}/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cvhj-model/1.0)"}
OUT = Path(__file__).parent
VANDAAG = time.strftime("%Y-%m-%d")

SPELER_COLS = ["ronde", "datum", "speler", "speler_id", "club", "tegenstander",
               "thuis_uit", "status", "basis", "minuten", "goals", "clean_sheet",
               "ploegpunten", "afwezig_reden", "opgehaald"]
CLUB_COLS = ["ronde", "datum", "club", "tegenstander", "thuis_uit", "voor",
             "tegen", "resultaat", "ploegpunten", "clean_sheet", "formatie",
             "kans_winst", "kans_gelijk", "kans_verlies", "verwacht_voor",
             "verwacht_tegen", "opgehaald"]

WISSEL_RE = re.compile(r"(\d{1,3})\s*[’']\s*[↑↓\u2191\u2193]?\s*(.+?)\s+voor\s+(.+?)\s*$")
SPELER_HREF = re.compile(r"/eredivisie/speler/([^/\"'>\s]+)/")  # ook accenten in de slug


# ---------------------------------------------------------------- hulpjes
TRANS = str.maketrans({
    "\u00f8": "o", "\u00d8": "O", "\u00e6": "ae", "\u00c6": "Ae",
    "\u00e5": "a", "\u00c5": "A", "\u00f0": "d", "\u00d0": "D",
    "\u00fe": "th", "\u00de": "Th", "\u0142": "l", "\u0141": "L",
    "\u0111": "d", "\u0110": "D", "\u00df": "ss", "\u0131": "i",
})


def norm(s):
    """'S\u00f8ren Tengstedt' -> 'soren-tengstedt' (zelfde vorm als de link-slug).

    Let op: ASCII-normalisatie alleen is niet genoeg. \u00f8 en \u00e5 hebben geen
    ontbinding in NFKD en zouden zonder deze tabel wegvallen.
    """
    s = (s or "").translate(TRANS)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def slug_naar_naam(slug):
    kleine = {"van", "de", "der", "den", "het", "ter", "te", "op", "in", "'t"}
    delen = slug.split("-")
    return " ".join(w if w in kleine and i else w.capitalize() for i, w in enumerate(delen))


def get(url, pauze=1.2, pogingen=4):
    """Haal een pagina op, met geduld. Bij een 429 of 5xx wachten we steeds
    langer; anders knijpt de bron ons af halverwege een grote run."""
    wacht = 5
    for poging in range(1, pogingen + 1):
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code in (429, 500, 502, 503, 504) and poging < pogingen:
            print(f"      ({r.status_code}, {wacht}s wachten)")
            time.sleep(wacht)
            wacht *= 2
            continue
        r.raise_for_status()
        time.sleep(pauze)
        return BeautifulSoup(r.text, "html.parser")
    raise RuntimeError(f"niet op te halen: {url}")


def match_urls(ronde):
    soup = get(ROUND_URL.format(ronde=ronde))
    urls = {a["href"] for a in soup.select('a[href*="/eredivisie/wedstrijd/"]')}
    return sorted(u if u.startswith("http") else BASE + u for u in urls)


# ------------------------------------------------------------ pagina delen
def club_blokken(ruwe_html, clubs):
    """Knip de ruwe HTML in een blok per club.

    Twee valkuilen. De clubnaam staat twee keer als kop op de pagina: bij de
    opstelling en bij "Spelers om op te letten". En een blok moet eindigen bij
    de EERSTVOLGENDE kop van welk niveau dan ook — niet pas bij de volgende
    clubkop, want dan slokt de uitploeg de rest van de pagina op.
    """
    koppen = []
    for m in re.finditer(r"<h([1-6])[^>]*>(.*?)</h\1>", ruwe_html, re.S | re.I):
        naam = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        koppen.append((m.start(), naam))

    kandidaten = {}
    for k, (pos, naam) in enumerate(koppen):
        if naam not in clubs:
            continue
        eind = koppen[k + 1][0] if k + 1 < len(koppen) else len(ruwe_html)
        kandidaten.setdefault(naam, []).append(ruwe_html[pos:eind])

    blokken = {}
    for naam, opties in kandidaten.items():
        met_bank = [b for b in opties if "Bank" in b or "voor" in b]
        blokken[naam] = (met_bank or opties)[0]
    return blokken


def parse_wissels(blok):
    """[(minuut, speler_in, speler_uit)] uit de lijstitems van EEN clubblok."""
    uit = []
    sub = BeautifulSoup(blok, "html.parser")
    kandidaten = sub.find_all(["li", "p", "div", "span"])
    gezien = set()
    for el in kandidaten:
        t = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if len(t) > 120 or t in gezien:
            continue
        m = WISSEL_RE.match(t)
        if m:
            gezien.add(t)
            uit.append((int(m.group(1)), m.group(2).strip(), m.group(3).strip()))
    # ontdubbel op (minuut, in)
    zien, res = set(), []
    for mi, i_, u_ in uit:
        if (mi, norm(i_)) in zien:
            continue
        zien.add((mi, norm(i_)))
        res.append((mi, i_, u_))
    return res


def parse_selectie(blok):
    """[(slug, naam)] van alle spelerslinks in het clubblok, in paginavolgorde."""
    namen, gezien = [], set()
    for m in SPELER_HREF.finditer(blok):
        slug = norm(m.group(1))
        if slug not in gezien:
            gezien.add(slug)
            namen.append((slug, slug_naar_naam(slug)))
    return namen


def parse_basis(plat, club):
    """Basiself uit de FAQ-zin. De lookahead stopt op de volgende zin, dus
    namen met een punt ('Jeremiah St. Juste') blijven heel."""
    pat = (r"De offici[e\u00eb]le opstelling van " + re.escape(club) +
           r"\s*\(([\d\-]+)\)\s*:\s*(.+?)"
           r"(?=De offici[e\u00eb]le opstelling van|Wie was de scheidsrechter|\Z)")
    m = re.search(pat, plat, re.S)
    if not m:
        return "", []
    blok = re.sub(r"\s+", " ", m.group(2)).strip()
    blok = re.sub(r"\.\s*$", "", blok)
    return m.group(1), [n.strip() for n in blok.split(",") if n.strip()]


def parse_odds(soup, plat, thuis, uitc):
    """Winstkansen en meest waarschijnlijke uitslag.

    Opmaak op de pagina: "Kansen vooraf 64% 19% 17% Ajax wint Gelijkspel
    sc Heerenveen wint" — de percentages staan dus VOOR hun label, in de
    vaste volgorde thuis, gelijkspel, uit.
    """
    kans = {"thuis": "", "gelijk": "", "uit": ""}
    m = re.search(r"Kansen vooraf\s*(\d{1,3})\s*%\s*(\d{1,3})\s*%\s*(\d{1,3})\s*%",
                  plat, re.S)
    if not m:
        m = re.search(r"(\d{1,3})\s*%\s*(\d{1,3})\s*%\s*(\d{1,3})\s*%", plat, re.S)
    if m:
        kans = {"thuis": m.group(1), "gelijk": m.group(2), "uit": m.group(3)}

    vw_t = vw_u = ""
    ms = re.search(r"Meest waarschijnlijke uitslagen(.{0,400})", plat, re.S)
    if ms:
        sc = re.search(r"(\d)\s*-\s*(\d)\s*\n?\s*\d+[.,]\d+\s*%", ms.group(1), re.S)
        if sc:
            vw_t, vw_u = sc.group(1), sc.group(2)
    return kans, vw_t, vw_u


def parse_afwezig(blok):
    """[(naam, reden)] uit 'Afwezig: X (blessure), Y (schorsing)'."""
    tekst = BeautifulSoup(blok, "html.parser").get_text(" ", strip=True)
    m = re.search(r"Afwezig\s*:\s*(.+?)(?:$|\|)", tekst)
    if not m:
        return []
    uit = []
    for stuk in m.group(1).split(","):
        am = re.match(r"\s*(.+?)\s*\((.+?)\)", stuk)
        if am:
            uit.append((am.group(1).strip(), am.group(2).strip()))
    return uit


# ------------------------------------------------------------ een wedstrijd
def parse_match(url, ronde):
    soup = get(url)
    ruw = str(soup)
    plat = re.sub(r"[ \t]+", " ", soup.get_text("\n", strip=True))

    h1 = soup.find("h1")
    m = re.search(r"(.+?)\s*-\s*(.+?)\s+uitslag:\s*(\d+)\s*-\s*(\d+)",
                  h1.get_text(" ", strip=True) if h1 else "")
    if not m:
        print("    ! nog geen uitslag")
        return [], []
    thuis, uitc = m.group(1).strip(), m.group(2).strip()
    gh, ga = int(m.group(3)), int(m.group(4))
    dm = re.search(r"Speelronde\s+\d+\s*·\s*(.+)", plat)
    datum = dm.group(1).strip() if dm else ""

    # doelpunten: alleen links BUITEN de clubblokken. Binnen een clubblok
    # staan opstelling, bank en wissels, en die bevatten allemaal
    # minuutaanduidingen die anders als treffer worden geteld. Filteren op een
    # pijltje werkt niet: in de wissellijst is dat een teken, op de bankregel
    # een icoon.
    koppen = [(m.start(), htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip())
              for m in re.finditer(r"<h([1-6])[^>]*>(.*?)</h\1>", ruw, re.S | re.I)]
    knip = []
    for k, (pos, naam) in enumerate(koppen):
        if naam in (thuis, uitc):
            knip.append((pos, koppen[k + 1][0] if k + 1 < len(koppen) else len(ruw)))
    rest = ruw
    for a, b in sorted(knip, reverse=True):
        rest = rest[:a] + rest[b:]

    goals = {}
    for a in BeautifulSoup(rest, "html.parser").select('a[href*="/eredivisie/speler/"]'):
        ouder = a.find_parent(["li", "p", "div"])
        omg = ouder.get_text(" ", strip=True) if ouder else ""
        sm = SPELER_HREF.search(a.get("href", ""))
        if sm and len(omg) < 160 and re.search(r"\d{1,3}\s*[’']", omg):
            slug = norm(sm.group(1))
            goals[slug] = goals.get(slug, 0) + 1

    kans, vw_thuis, vw_uit = parse_odds(soup, plat, thuis, uitc)
    blokken = club_blokken(ruw, {thuis, uitc})
    club_rows, speler_rows = [], []

    for club, tegen, gf, gc in ((thuis, uitc, gh, ga), (uitc, thuis, ga, gh)):
        blok = blokken.get(club, "")
        res = "W" if gf > gc else ("G" if gf == gc else "V")
        ppt = 3 if res == "W" else (1 if res == "G" else 0)
        tu = "thuis" if club == thuis else "uit"
        cs = int(gc == 0)

        formatie, basis = parse_basis(plat, club)
        wissels = parse_wissels(blok)
        eruit = {norm(w[2]): w[0] for w in wissels}
        erin = {norm(w[1]): w[0] for w in wissels}

        basis_norm = {norm(n) for n in basis}
        selectie = parse_selectie(blok)
        bank = [(s, n) for s, n in selectie if s not in basis_norm]

        club_rows.append({
            "ronde": ronde, "datum": datum, "club": club, "tegenstander": tegen,
            "thuis_uit": tu, "voor": gf, "tegen": gc, "resultaat": res,
            "ploegpunten": ppt, "clean_sheet": cs, "formatie": formatie,
            "kans_winst": kans["thuis"] if tu == "thuis" else kans["uit"],
            "kans_gelijk": kans["gelijk"],
            "kans_verlies": kans["uit"] if tu == "thuis" else kans["thuis"],
            "verwacht_voor": vw_thuis if tu == "thuis" else vw_uit,
            "verwacht_tegen": vw_uit if tu == "thuis" else vw_thuis,
            "opgehaald": VANDAAG})

        for naam in basis:
            s = norm(naam)
            speler_rows.append({
                "ronde": ronde, "datum": datum, "speler": naam, "speler_id": s,
                "club": club, "tegenstander": tegen, "thuis_uit": tu,
                "status": "basis", "basis": 1, "minuten": eruit.get(s, 90),
                "goals": goals.get(s, 0), "clean_sheet": cs, "ploegpunten": ppt,
                "afwezig_reden": "", "opgehaald": VANDAAG})

        for slug, naam in bank:
            mi = erin.get(slug)
            speler_rows.append({
                "ronde": ronde, "datum": datum, "speler": naam, "speler_id": slug,
                "club": club, "tegenstander": tegen, "thuis_uit": tu,
                "status": "invaller" if mi else "bank", "basis": 0,
                "minuten": (90 - mi) if mi else 0,
                "goals": goals.get(slug, 0) if mi else 0,
                "clean_sheet": cs if mi else "", "ploegpunten": ppt if mi else 0,
                "afwezig_reden": "", "opgehaald": VANDAAG})

        for naam, reden in parse_afwezig(blok):
            speler_rows.append({
                "ronde": ronde, "datum": datum, "speler": naam,
                "speler_id": norm(naam), "club": club, "tegenstander": tegen,
                "thuis_uit": tu, "status": "afwezig", "basis": 0, "minuten": 0,
                "goals": 0, "clean_sheet": "", "ploegpunten": 0,
                "afwezig_reden": reden, "opgehaald": VANDAAG})

        vlag = "" if (basis and bank) else "   <-- CONTROLEER (draai --debug)"
        print(f"    {club}: {len(basis)} basis, {len(bank)} bank, "
              f"{len(wissels)} wissels{vlag}")
    return club_rows, speler_rows


# ------------------------------------------------------------------ debug
def debug(url):
    soup = get(url)
    ruw = str(soup)
    print(f"=== {url}\n")
    print("KOPPEN (h1-h4):")
    for h in soup.find_all(["h1", "h2", "h3", "h4"]):
        print(f"  <{h.name}> {h.get_text(' ', strip=True)[:90]}")
    links = SPELER_HREF.findall(ruw)
    print(f"\nSPELERSLINKS: {len(links)} totaal, {len(set(links))} uniek")
    print("  eerste 8:", list(dict.fromkeys(links))[:8])
    print("\nELEMENTEN DIE OP EEN WISSEL LIJKEN:")
    n = 0
    for el in soup.find_all(["li", "p", "div", "span"]):
        t = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if len(t) < 120 and re.search(r"\d{1,3}\s*[’'].{0,60}\bvoor\b", t):
            print(f"  <{el.name}> {t}")
            n += 1
            if n >= 12:
                break
    if not n:
        print("  GEEN gevonden — plak hieronder wat er rond 'Wissels' staat:")
        i = ruw.find("Wissels")
        print(ruw[max(0, i - 200): i + 1500] if i > 0 else "  'Wissels' niet gevonden")
    print("\nELEMENTEN MET EEN PERCENTAGE:")
    n = 0
    for el in soup.find_all(["td", "div", "span", "li", "p", "strong"]):
        t = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if "%" in t and len(t) < 90:
            print(f"  <{el.name}> {t}")
            n += 1
            if n >= 15:
                break
    if not n:
        print("  GEEN percentages gevonden op deze pagina")

    print("\nBLOK 'Bank' (eerste 900 tekens ruwe HTML):")
    i = ruw.find("Bank")
    print(ruw[i:i + 900] if i > 0 else "  'Bank' niet gevonden")


# ------------------------------------------------------------- wegschrijven
def schrijf(pad, cols, nieuw, sleutel):
    rijen, index = [], {}
    if pad.exists():
        with open(pad, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if set(r) != set(cols):          # oud kolomformaat -> opnieuw beginnen
                    rijen, index = [], {}
                    break
                k = tuple(str(r.get(c, "")) for c in sleutel)
                index[k] = len(rijen)
                rijen.append(r)
    bij = 0
    for r in nieuw:
        k = tuple(str(r.get(c, "")) for c in sleutel)
        if k in index:
            rijen[index[k]] = r
        else:
            index[k] = len(rijen)
            rijen.append(r)
            bij += 1
    with open(pad, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rijen)
    print(f"  {pad.name}: {bij} nieuw, {len(rijen)} totaal")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ronde", type=int, action="append", default=[])
    p.add_argument("--alles-tot", type=int)
    p.add_argument("--debug", metavar="URL")
    a = p.parse_args()

    if a.debug:
        debug(a.debug)
        return

    rondes = a.ronde or (list(range(1, a.alles_tot + 1)) if a.alles_tot else [])
    if not rondes:
        sys.exit("Geef --ronde N, --alles-tot N of --debug URL")

    leeg = 0
    for ronde in rondes:
        print(f"Speelronde {ronde}")
        try:
            urls = match_urls(ronde)
        except Exception as e:
            print(f"  ! ronde overgeslagen: {e}")
            continue
        cr, sr = [], []
        for url in urls:
            print(f"  {url.rstrip('/').rsplit('/', 1)[-1]}")
            try:
                c, s = parse_match(url, ronde)
                cr += c
                sr += s
            except Exception as e:
                print(f"    ! mislukt: {type(e).__name__}: {e}")
        if cr or sr:
            leeg = 0
            schrijf(OUT / "clubs.csv", CLUB_COLS, cr, ["ronde", "club"])
            schrijf(OUT / "spelers.csv", SPELER_COLS, sr,
                    ["ronde", "speler_id", "club", "status"])
        else:
            leeg += 1
            print("  (nog niet gespeeld)")
            if leeg >= 2:
                print("Twee lege rondes achter elkaar — klaar.")
                break


if __name__ == "__main__":
    main()
