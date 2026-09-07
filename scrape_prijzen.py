#!/usr/bin/env python3
"""
Waarde en positie van alle koopbare CVHJ-spelers ophalen -> prijzen.csv

Bron: https://pouletips.nl/eredivisie/poule/coach-van-het-jaar/spelers/
Die pagina lijst alle spelers die je in Coach van het Jaar kunt kopen, met
club, positie, waarde in miljoenen en een link naar /eredivisie/speler/<slug>/.
Die slug is identiek aan de kolom `speler_id` in spelers.csv, dus de join met
de scraperdata is exact -- geen naamsmatching op accenten.

Gebruik:
    python scrape_prijzen.py                    # schrijft prijzen.csv
    python scrape_prijzen.py --uit data/        # andere doelmap
    python scrape_prijzen.py --dump ruw.html    # bewaar HTML om te debuggen

Uitvoer (kolomvolgorde zoals cvhj_model.py verwacht):
    team, speler, positie, prijs, speler_id

`positie` is Engels (Goalkeeper/Defender/Midfielder/Forward), zoals het model eist.

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
PRIJZEN_URL = BASE + "/eredivisie/poule/coach-van-het-jaar/spelers/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cvhj-model/1.0)"}
SPELER_HREF = re.compile(r"/eredivisie/speler/([^/\"'>\s]+)/")

# De pagina belooft ~512 spelers. Ligt de opbrengst daar ver onder, dan is er
# iets stuk (paginering, gewijzigde opmaak) en moet het script hard falen in
# plaats van een half bestand achter te laten waar het model op doorrekent.
MIN_SPELERS = 400

POSITIE_NL_EN = {
    "keeper": "Goalkeeper",
    "doelman": "Goalkeeper",
    "kee": "Goalkeeper",
    "verdediger": "Defender",
    "ver": "Defender",
    "middenvelder": "Midfielder",
    "mid": "Midfielder",
    "aanvaller": "Forward",
    "aan": "Forward",
}

# Clubnamen moeten letterlijk gelijk zijn aan die in clubs.csv/spelers.csv,
# anders valt de join stil. Alleen bekende afwijkingen staan hier; onbekende
# namen worden gemeld door --check, niet stilzwijgend aangepast.
CLUB_ALIAS = {
    "N.E.C.": "NEC",
    "N.E.C": "NEC",
    "NEC Nijmegen": "NEC",
    "SC Heerenveen": "sc Heerenveen",
    "Heerenveen": "sc Heerenveen",
    "SC Cambuur": "SC Cambuur",
    "Cambuur": "SC Cambuur",
    "Sparta": "Sparta Rotterdam",
    "Go Ahead": "Go Ahead Eagles",
}

TRANS = str.maketrans({
    "ø": "o", "Ø": "O", "æ": "ae", "Æ": "Ae",
    "å": "a", "Å": "A", "ð": "d", "Ð": "D",
    "þ": "th", "Þ": "Th", "ł": "l", "Ł": "L",
    "đ": "d", "Đ": "D", "ß": "ss", "ı": "i",
})


def norm_slug(s):
    """'Søren Tengstedt' -> 'soren-tengstedt', zelfde vorm als de link-slug."""
    s = s.strip().translate(TRANS)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s


def get(url, pauze=1.2, pogingen=4):
    """Ophalen met retry; dezelfde beleefde pauze als de bestaande scraper."""
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


# De naamcel bevat naast de naam ook status: "Sekou Sylla bank",
# "Calvin Stengs basis nieuw", "Jordan Bos ! geblesseerd tot en met 1 januari".
# Dat is waardevolle informatie, maar het hoort niet IN de naam -- zo sluit de
# join met spelers.csv niet meer aan. Naam en status worden dus gescheiden.
#
# re.IGNORECASE: op 6 september 2026 bleek "Gjivai Zechiël basis" niet als
# marktdata-naam te matchen met de "Gjivai Zechiël" uit selectie.csv (zie
# cvhj_model.vind_bijna_match, dat als vangnet zulke gevallen alsnog repareert).
# Een hoofdlettervariant van het statuswoord ("Basis" i.p.v. "basis") was een
# van de reproduceerbare manieren om dat te veroorzaken: \b(?:basis|...)\b is
# hoofdlettergevoelig, dus "Basis" liep er ongestript doorheen. Niet met
# zekerheid vastgesteld dat dit precies de live oorzaak was (de site-HTML zelf
# is niet ingezien) -- maar het is een reeel, reproduceerbaar gat, dus dicht.
STATUS_RE = re.compile(r"\s*(?:!\s*(?P<bless>[^!]*)$|\b(?P<rol>basis|bank|nieuw)\b)",
                        re.IGNORECASE)


def splits_status(cel):
    """'Jordan Bos ! geblesseerd tot en met 1 januari'
        -> ('Jordan Bos', {'rol': '', 'nieuw': 0, 'blessure': 'tot en met 1 januari'})"""
    naam, rol, is_nieuw, blessure = cel, "", 0, ""
    for _ in range(4):
        m = STATUS_RE.search(naam)
        if not m:
            break
        if m.group("bless") is not None:
            tekst = m.group("bless").strip().rstrip(",")
            tekst = re.sub(r"^geblesseerd\s*,?\s*", "", tekst, flags=re.IGNORECASE).strip()
            blessure = tekst or "onbekend"
        elif m.group("rol").lower() == "nieuw":
            is_nieuw = 1
        else:
            rol = m.group("rol").lower()
        naam = (naam[:m.start()] + naam[m.end():]).strip()
    # Opruimen wat de status-strip kan achterlaten: lege haakjes/vierkante
    # haken ("Naam ()" na het strippen van "(basis)"), en dubbele spaties of
    # losse komma's/streepjes die overblijven tussen de weggehaalde stukken.
    naam = re.sub(r"\(\s*\)|\[\s*\]", "", naam)
    naam = re.sub(r"\s+", " ", naam).strip(" ,-")
    return naam, {"rol": rol, "nieuw": is_nieuw, "blessure": blessure}


def parse_prijs(tekst):
    """'4,0 mln' / '1,75M' / '€ 3.75 mln' -> 4.0 / 1.75 / 3.75"""
    t = tekst.replace(" ", " ").strip()
    m = re.search(r"(\d+(?:[.,]\d+)?)", t)
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def parse_positie(tekst):
    sleutel = re.sub(r"[^a-z]", "", tekst.strip().lower())
    return POSITIE_NL_EN.get(sleutel)


def kies_tabel(soup):
    """De spelerstabel is die met kopteksten Speler/Club/Positie/Waarde.

    Bewust niet op class of id gezocht: die veranderen bij elke redesign,
    kopteksten niet. Levert (tabel, {kolomnaam: index}).
    """
    for tabel in soup.find_all("table"):
        koppen = [re.sub(r"\s+", " ", th.get_text(" ", strip=True)).lower()
                  for th in tabel.find_all("th")]
        if not koppen:
            continue
        idx = {}
        for i, k in enumerate(koppen):
            if k.startswith("speler"):
                idx.setdefault("speler", i)
            elif k.startswith("club") or k.startswith("team"):
                idx.setdefault("club", i)
            elif k.startswith("positie"):
                idx.setdefault("positie", i)
            elif k.startswith("waarde") or k.startswith("prijs"):
                idx.setdefault("prijs", i)
        if {"speler", "club", "positie", "prijs"} <= set(idx):
            return tabel, idx
    return None, None


def parse_rijen(html):
    soup = BeautifulSoup(html, "html.parser")
    tabel, idx = kies_tabel(soup)
    if tabel is None:
        raise RuntimeError(
            "geen tabel met kolommen Speler/Club/Positie/Waarde gevonden -- "
            "opmaak van de bronpagina is waarschijnlijk gewijzigd; "
            "draai opnieuw met --dump ruw.html en bekijk de bron")

    rijen, overgeslagen = [], []
    for tr in tabel.find_all("tr"):
        cellen = tr.find_all("td")
        if len(cellen) <= max(idx.values()):
            continue  # koprij of tussenkop

        naam, status = splits_status(cellen[idx["speler"]].get_text(" ", strip=True))
        club_ruw = cellen[idx["club"]].get_text(" ", strip=True)
        positie = parse_positie(cellen[idx["positie"]].get_text(" ", strip=True))
        prijs = parse_prijs(cellen[idx["prijs"]].get_text(" ", strip=True))

        # slug bij voorkeur uit de href -- dat is de bron van waarheid voor
        # de join met spelers.csv; alleen als die ontbreekt zelf afleiden
        href = SPELER_HREF.search(str(tr))
        slug = norm_slug(href.group(1)) if href else norm_slug(naam)

        if not naam or positie is None or prijs is None:
            overgeslagen.append((naam or "?", club_ruw, positie, prijs))
            continue

        rijen.append({
            "team": CLUB_ALIAS.get(club_ruw, club_ruw),
            "speler": naam,
            "positie": positie,
            "prijs": f"{prijs:.2f}",
            "speler_id": slug,
            "rol": status["rol"],
            "nieuw": status["nieuw"],
            "blessure": status["blessure"],
        })
    return rijen, overgeslagen


def volg_paginering(html, gezien):
    """Extra paginalinks, mocht de tabel toch gepagineerd zijn."""
    soup = BeautifulSoup(html, "html.parser")
    urls = set()
    for a in soup.select('a[href]'):
        h = a["href"]
        if "coach-van-het-jaar/spelers" not in h:
            continue
        vol = h if h.startswith("http") else BASE + h
        if vol.rstrip("/") != PRIJZEN_URL.rstrip("/") and vol not in gezien:
            urls.add(vol)
    return sorted(urls)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--uit", default=".", help="doelmap voor prijzen.csv")
    p.add_argument("--dump", metavar="BESTAND", help="ruwe HTML wegschrijven")
    p.add_argument("--min", type=int, default=MIN_SPELERS,
                   help=f"faal onder dit aantal spelers (standaard {MIN_SPELERS})")
    args = p.parse_args()

    print(f"ophalen: {PRIJZEN_URL}")
    html = get(PRIJZEN_URL)
    if args.dump:
        Path(args.dump).write_text(html, encoding="utf-8")
        print(f"  ruwe HTML -> {args.dump}")

    rijen, overgeslagen = parse_rijen(html)
    gezien = {PRIJZEN_URL}

    # alleen paginering volgen als de eerste pagina te weinig opleverde
    if len(rijen) < args.min:
        for url in volg_paginering(html, gezien):
            gezien.add(url)
            print(f"  vervolgpagina: {url}")
            try:
                extra, over_extra = parse_rijen(get(url))
            except RuntimeError:
                continue
            rijen.extend(extra)
            overgeslagen.extend(over_extra)
            if len(rijen) >= args.min:
                break

    # ontdubbelen op slug; de laatste waarde wint
    op_slug = {r["speler_id"]: r for r in rijen}
    rijen = sorted(op_slug.values(), key=lambda r: (r["team"], r["positie"], r["speler"]))

    if overgeslagen:
        print(f"  {len(overgeslagen)} rij(en) overgeslagen (onleesbare positie of prijs):")
        for naam, club, pos, prijs in overgeslagen[:10]:
            print(f"    - {naam} ({club}) positie={pos} prijs={prijs}")

    if len(rijen) < args.min:
        sys.exit(f"FOUT: slechts {len(rijen)} spelers gevonden, verwacht >= {args.min}. "
                 f"prijzen.csv NIET geschreven -- het model zou op halve data rekenen.")

    uit = Path(args.uit)
    uit.mkdir(parents=True, exist_ok=True)
    pad = uit / "prijzen.csv"
    with pad.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["team", "speler", "positie", "prijs",
                                          "speler_id", "rol", "nieuw", "blessure"])
        w.writeheader()
        w.writerows(rijen)

    per_positie = {}
    for r in rijen:
        per_positie[r["positie"]] = per_positie.get(r["positie"], 0) + 1
    prijzen = [float(r["prijs"]) for r in rijen]

    print(f"\n{len(rijen)} spelers -> {pad}")
    print(f"  clubs:   {len(set(r['team'] for r in rijen))}")
    print(f"  posities: " + ", ".join(f"{k}={v}" for k, v in sorted(per_positie.items())))
    print(f"  prijs:   {min(prijzen):.2f} - {max(prijzen):.2f} mln")
    print(f"  status:  {sum(1 for r in rijen if r['rol'])} met rol, "
          f"{sum(r['nieuw'] for r in rijen)} nieuw, "
          f"{sum(1 for r in rijen if r['blessure'])} geblesseerd")


if __name__ == "__main__":
    main()
