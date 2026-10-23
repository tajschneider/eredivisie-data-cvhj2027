#!/usr/bin/env python3
"""
Eredivisie-data ophalen voor het CVHJ-model en wegschrijven naar CSV.

Bron: pouletips.nl. Vijf verschillende pagina's, want sinds oktober 2026 staat
niet alles meer op de wedstrijdpagina:

  /eredivisie/uitslagen/              uitslagen van alle speelronden
  /eredivisie/wedstrijd/<slug>/       kansen, VERWACHTE GOALS, over/under
  /eredivisie/<club>/opstelling/      AFWEZIGEN met reden en terugkeerdatum,
                                      plus basiskans per speler
  /eredivisie/speler/<slug>/          minuten, basisplaatsen, goals, ASSISTS
  /eredivisie/statistieken/           gele en rode KAARTEN

Let op: de officiele basiself, de bank, de wissels en de doelpuntenmakers
worden pas in de browser ingeladen. Met requests zijn die niet te zien. De
basiself komt daarom uit de vermoedelijke opstelling (met basiskans), en de
individuele productie uit de seizoenstotalen per speler, die hier wekelijks
worden bevroren en tegen elkaar worden afgetrokken.

Gebruik:
    python scrape_eredivisie.py --alles
    python scrape_eredivisie.py --clubs --ronde 10
    python scrape_eredivisie.py --spelers --max-spelers 20
    python scrape_eredivisie.py --afwezigen
    python scrape_eredivisie.py --debug https://pouletips.nl/eredivisie/uitslagen/

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
UITSLAGEN_URL = BASE + "/eredivisie/uitslagen/"
SPELERS_URL = BASE + "/eredivisie/spelers/"
OPSTELLING_URL = BASE + "/eredivisie/{slug}/opstelling/"
SPELER_URL = BASE + "/eredivisie/speler/{slug}/"
GEEL_URL = BASE + "/eredivisie/statistieken/gele-kaarten/"
ROOD_URL = BASE + "/eredivisie/statistieken/rode-kaarten/"
PRIJZEN_URL = BASE + "/eredivisie/poule/coach-van-het-jaar/spelers/"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cvhj-model/2.0)"}
# De slug mag accenten bevatten ('mateo-chávez'); die worden pas door norm()
# gelijkgetrokken, zodat één speler niet twee identiteiten krijgt.
SPELER_HREF = re.compile(r"/eredivisie/speler/([^/\"'>\s]+)/")
OUT = Path(__file__).parent
VANDAAG = time.strftime("%Y-%m-%d")
SEIZOEN = "2026/27"
VOORUIT_RONDEN = 2        # hoeveel komende ronden per run verse odds krijgen

# ----------------------------------------------------------------- clubnamen
# De korte vorm is wat in clubs.csv en in de CVHJ-prijslijst staat. De bron
# gebruikt op de spelersindex lange vormen ("PSV Eindhoven", "AFC Ajax") en op
# de uitslagenpagina korte. Alles wordt via norm() op de korte vorm gebracht.
CLUB_SLUG = {
    "psv": "PSV", "feyenoord": "Feyenoord", "ajax": "Ajax", "az": "AZ",
    "fc-twente": "FC Twente", "fc-utrecht": "FC Utrecht", "nec": "NEC",
    "sc-heerenveen": "sc Heerenveen", "fc-groningen": "FC Groningen",
    "sparta-rotterdam": "Sparta Rotterdam", "fortuna-sittard": "Fortuna Sittard",
    "go-ahead-eagles": "Go Ahead Eagles", "pec-zwolle": "PEC Zwolle",
    "excelsior": "Excelsior", "telstar": "Telstar", "willem-ii": "Willem II",
    "ado-den-haag": "ADO Den Haag", "sc-cambuur": "SC Cambuur",
}
CLUB_ALIAS = {
    "psv-eindhoven": "PSV", "feyenoord-rotterdam": "Feyenoord",
    "afc-ajax": "Ajax", "az-alkmaar": "AZ", "fc-twente-enschede": "FC Twente",
    "nec-nijmegen": "NEC", "sbv-excelsior": "Excelsior",
    "sc-telstar": "Telstar", "willem-ii-tilburg": "Willem II",
    "n-e-c": "NEC", "heerenveen": "sc Heerenveen", "cambuur": "SC Cambuur",
    "zwolle": "PEC Zwolle", "groningen": "FC Groningen", "twente": "FC Twente",
    "utrecht": "FC Utrecht", "sparta": "Sparta Rotterdam",
    "fortuna": "Fortuna Sittard", "go-ahead": "Go Ahead Eagles",
}
POSITIE = {"keepers": "Goalkeeper", "verdedigers": "Defender",
           "middenvelders": "Midfielder", "aanvallers": "Forward"}
# enkelvoud, zoals in de CVHJ-spelerslijst
POSITIE_ENKEL = {"keeper": "Goalkeeper", "verdediger": "Defender",
                 "middenvelder": "Midfielder", "aanvaller": "Forward"}
# redenen zoals ze op de clubpagina achter een naam staan
REDEN_WOORDEN = ("blessure", "schorsing", "vertrokken", "ziek", "twijfel",
                 "persoonlijk", "transfer")

# ------------------------------------------------------------------- kolommen
CLUB_COLS = ["ronde", "datum", "club", "tegenstander", "thuis_uit", "voor",
             "tegen", "resultaat", "ploegpunten", "clean_sheet", "formatie",
             "kans_winst", "kans_gelijk", "kans_verlies", "verwacht_voor",
             "verwacht_tegen", "xg_voor", "xg_tegen", "beide_scoren",
             "over_25", "opgehaald"]
# seizoenstotalen, een bevroren stand per ophaaldatum
SEIZOEN_COLS = ["opgehaald", "speler_id", "speler", "club", "positie",
                "duels", "basisplaatsen", "minuten", "goals", "assists",
                "overtredingen", "reddingen", "nul_achter", "cijfer",
                "geel", "rood", "status_tekst"]
# per ronde, door twee seizoensstanden van elkaar af te trekken
SPELER_COLS = ["ronde", "datum", "speler_id", "speler", "club", "positie",
               "duels", "basis", "minuten", "goals", "assists", "geel",
               "rood", "reddingen", "clean_sheet", "ploegpunten", "venster",
               "opgehaald"]
AFWEZIG_COLS = ["opgehaald", "club", "speler", "speler_id", "reden",
                "verwacht_terug", "tegenstander", "datum"]
# De CVHJ-spelerslijst. speler_id staat erin zodat de koppeling met de
# gescrapete spelers exact is en niet op naam hoeft.
PRIJS_COLS = ["team", "speler", "positie", "prijs", "speler_id", "opgehaald"]
OPSTELLING_COLS = ["opgehaald", "club", "speler", "speler_id", "kans_basis",
                   "tegenstander", "thuis_uit", "datum", "ronde"]

MAANDEN = {"jan": 1, "feb": 2, "mrt": 3, "maart": 3, "apr": 4, "mei": 5,
           "jun": 6, "juni": 6, "jul": 7, "juli": 7, "aug": 8, "augustus": 8,
           "sep": 9, "september": 9, "okt": 10, "oktober": 10, "nov": 11,
           "november": 11, "dec": 12, "december": 12, "januari": 1,
           "februari": 2, "april": 4, "juli": 7}


# ------------------------------------------------------------------- hulpjes
TRANS = str.maketrans({
    "ø": "o", "Ø": "O", "æ": "ae", "Æ": "Ae",
    "å": "a", "Å": "A", "ð": "d", "Ð": "D",
    "þ": "th", "Þ": "Th", "ł": "l", "Ł": "L",
    "đ": "d", "Đ": "D", "ß": "ss", "ı": "i",
})


def norm(s):
    """'Soren Tengstedt' -> 'soren-tengstedt', gelijk aan de link-slug.

    ASCII-normalisatie alleen is niet genoeg: o-slash, ae en a-ring hebben geen
    ontbinding in NFKD en zouden zonder deze tabel stilletjes wegvallen.
    """
    s = (s or "").translate(TRANS)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def club_naam(s):
    """Elke schrijfwijze van een club naar de korte vorm uit clubs.csv."""
    k = norm(s)
    if k in CLUB_SLUG:
        return CLUB_SLUG[k]
    if k in CLUB_ALIAS:
        return CLUB_ALIAS[k]
    return (s or "").strip()


def getal(s, komma=True):
    """'7,06' of '95,18%' of '2.3' -> float. Leeg of onleesbaar -> None."""
    if s is None:
        return None
    t = str(s).strip().replace("%", "").replace(" ", " ").strip()
    if komma and "," in t and "." not in t:
        t = t.replace(",", ".")
    t = t.replace(" ", "")
    m = re.fullmatch(r"-?\d+(?:\.\d+)?", t)
    return float(m.group(0)) if m else None


def heel(s):
    g = getal(s)
    return int(round(g)) if g is not None else None


def datum_iso(tekst, jaar_hint=2026):
    """'zo 18 okt, 20:00' of 'zondag 25 oktober 2026, 14:30' -> '2026-10-18'."""
    if not tekst:
        return ""
    m = re.search(r"(\d{1,2})\s+([a-zA-Z]+)\.?\s*(\d{4})?", tekst)
    if not m:
        return ""
    dag, maand_w, jaar = m.group(1), m.group(2).lower(), m.group(3)
    maand = MAANDEN.get(maand_w) or MAANDEN.get(maand_w[:3])
    if not maand:
        return ""
    j = int(jaar) if jaar else (jaar_hint if maand >= 7 else jaar_hint + 1)
    return f"{j:04d}-{maand:02d}-{int(dag):02d}"


def get(url, pauze=1.2, pogingen=4, toestaan_404=False):
    """Haal een pagina op, met geduld. Bij 429 of 5xx wachten we steeds langer;
    anders knijpt de bron ons halverwege een grote run af."""
    wacht = 5
    for poging in range(1, pogingen + 1):
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 404 and toestaan_404:
            return None
        if r.status_code in (429, 500, 502, 503, 504) and poging < pogingen:
            print(f"      ({r.status_code}, {wacht}s wachten)")
            time.sleep(wacht)
            wacht *= 2
            continue
        r.raise_for_status()
        time.sleep(pauze)
        return BeautifulSoup(r.text, "html.parser")
    raise RuntimeError(f"niet op te halen: {url}")


def vlak(soup_of_tekst):
    """Platte tekst met enkele spaties, regels bewaard."""
    if isinstance(soup_of_tekst, str):
        t = soup_of_tekst
    else:
        t = soup_of_tekst.get_text("\n", strip=True)
    t = t.replace(" ", " ").replace("’", "'")
    return re.sub(r"[ \t]+", " ", t)


def blok_na_kop(ruw, patroon, niveaus="1-6"):
    """(begin, eind, html) van het blok onder de eerste kop die matcht.

    Ankeren op de KOP en niet op een volzin eronder. Dat laatste heeft op
    19-10-2026 twee parsers tegelijk omgelegd: de bron verving "Niet
    beschikbaar:" door "Wie ontbreekt er op dit moment bij PSV Eindhoven?" en
    toen was er geen blok meer. Een kop is structuur, een zin is tekst die
    morgen anders kan luiden.
    """
    for m in re.finditer(r"<h([" + niveaus + r"])[^>]*>(.*?)</h\1>",
                         ruw, re.S | re.I):
        tekst = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(2)))
        if re.search(patroon, tekst, re.I):
            niveau = int(m.group(1))
            # Eindigen bij de volgende kop van HETZELFDE of een HOGER niveau,
            # niet bij elke kop. Het opstellingsblok is zelf onderverdeeld in
            # "Keeper", "Verdediging", "Middenveld" en "Aanval"; stoppen bij de
            # eerste daarvan gaf een leeg blok, en dus nul basiskansen terwijl
            # de percentages er wel stonden.
            volgend = re.search(r"<h[1-" + str(niveau) + r"][^>]*>",
                                ruw[m.end():], re.I)
            eind = m.end() + (volgend.start() if volgend else 6000)
            return m.start(), eind, ruw[m.end():eind]
    return None, None, ""


def stukken_per_speler(soup, marge=90, uniek=True):
    """[(speler_id, naam, tekst_erachter)] voor elke spelerslink, op volgorde.

    De platte tekst wordt geknipt op de spelersnamen: wat tussen een naam en
    de volgende naam staat, hoort bij die speler. Zo hoeft er niets te worden
    aangenomen over de opmaak — of de reden, de club of het aantal in hetzelfde
    element staat als de naam, in een zuster-element of in een tabelcel, maakt
    niet uit. Dat is tot twee keer de reden geweest dat een parser omviel.

    `marge` is hoeveel tekens er na de laatste naam nog meedoen.
    """
    links = []
    for a in soup.select('a[href*="/eredivisie/speler/"]'):
        sm = SPELER_HREF.search(a.get("href", ""))
        if not sm:
            continue
        naam = vlak(a).strip()
        if naam:
            links.append((norm(sm.group(1)), naam))
    if not links:
        return []

    plat = re.sub(r"\s+", " ", vlak(soup))
    posities, cursor = [], 0
    for _, naam in links:
        i = plat.find(naam, cursor)
        if i < 0:                       # linktekst wijkt af van de bloktekst
            i = plat.find(naam)
        posities.append(i if i >= 0 else cursor)
        cursor = max(cursor, posities[-1] + len(naam))

    uit, gezien = [], set()
    for k, (sid, naam) in enumerate(links):
        # Met uniek=False komt ELKE vermelding terug. Nodig wanneer de eerste
        # vermelding van een naam niet de gezochte is: op de clubpagina staan
        # starters ook in een tipblok ("64 punten") en in de FAQ, en alleen de
        # opstellingsregel heeft een percentage achter de naam.
        if uniek and sid in gezien:
            continue
        gezien.add(sid)
        start = posities[k] + len(naam)
        eind = (posities[k + 1] if k + 1 < len(links)
                else min(len(plat), start + marge))
        uit.append((sid, naam, plat[start:max(start, eind)]))
    return uit


def gemeld_aantal(soup):
    """'Top 40 van 160 spelers' -> (40, 160); anders (None, None).

    De ranglijstpagina's kondigen zelf aan hoeveel rijen er staan en hoeveel
    spelers er in totaal in de lijst thuishoren. Dat is een betere maatstaf dan
    een ondergrens die ik verzin: gele kaarten leveren 40 van 160 rijen op,
    rode kaarten na negen ronden 4 van 4. Een vaste drempel van vijf verklaarde
    die laatste lijst onterecht stuk, en zou tegelijk '12 van de 40 gelezen'
    hebben doorgelaten.
    """
    m = re.search(r"Top\s+(\d{1,4})\s+van\s+(\d{1,4})\s+spelers",
                  re.sub(r"\s+", " ", vlak(soup)))
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def club_in_tekst(t):
    """De eerste bekende clubnaam die in deze tekst voorkomt, anders ''.

    Zoekt op voorkomen in plaats van op gelijkheid, zodat omringende ruis
    ('Telstar logo Telstar') geen lege club oplevert. Langste naam eerst,
    anders matcht 'AZ' binnen een langere naam.
    """
    t = t or ""
    for naam in sorted(CLUB_SLUG.values(), key=len, reverse=True):
        if re.search(r"(?<![A-Za-z])" + re.escape(naam) + r"(?![A-Za-z])", t):
            return naam
    return ""


def tabellen(soup):
    """[(koppen, [rijen])] voor elke tabel, als lijsten van celteksten."""
    uit = []
    for tab in soup.find_all("table"):
        koppen = [vlak(th).strip() for th in tab.find_all("th")]
        rijen = []
        for tr in tab.find_all("tr"):
            cellen = [vlak(td).strip() for td in tr.find_all("td")]
            if cellen:
                rijen.append(cellen)
        if rijen:
            uit.append((koppen, rijen))
    return uit


# --------------------------------------------------------------- uitslagen
def parse_uitslagen(soup):
    """Alle wedstrijden met ronde, datum, clubs, uitslag en wedstrijd-URL.

    Twee vormen op dezelfde pagina. Onder "Net gespeeld" staat de ronde in de
    rij zelf:
        zo 18 okt, 20:00 Ronde 9 FC Twente 1-2 FC Utrecht
    Onder "Alle speelrondes" staat de ronde alleen in de kop erboven en is de
    score met spaties geschreven:
        Speelronde 9  ->  vr 16 okt, 20:00 sc Heerenveen 4 - 0 Excelsior

    De HELE RIJ is de link. Daarom begint het zoeken bij de linktekst zelf en
    niet bij de ouder: de eerstvolgende voorouder is op deze pagina de
    container met alle negen rijen, en die liep ruim over de tekenlimiet heen
    waardoor elke rij werd overgeslagen.

    De clubs komen uit de slug en niet uit de tekst. De slug is de bron van
    waarheid over wie thuis speelt, en dat scheelt het uiteenrafelen van
    clubnamen rond een score.
    """
    uit, per_slug = [], {}
    kop_ronde = None
    # In documentvolgorde lopen, zodat een kop "Speelronde 12" kan invullen wat
    # een rij zelf niet zegt. Boven de lijst staat "Net gespeeld" met dezelfde
    # wedstrijden als in de rondelijsten, dus dubbelen zijn normaal.
    for el in soup.find_all(["h1", "h2", "h3", "h4", "a"]):
        if el.name != "a":
            km = re.search(r"Speelronde\s+(\d{1,2})", vlak(el))
            if km:
                kop_ronde = int(km.group(1))
            continue
        href = el.get("href", "")
        if "/eredivisie/wedstrijd/" not in href:
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        paar = slug_naar_clubs(slug)
        if not paar:
            continue
        thuis, uitc = paar

        # kandidaten van klein naar groot: eerst de link, dan hoogstens drie
        # voorouders zolang de tekst nog op een rij lijkt
        kandidaten = [re.sub(r"\s+", " ", vlak(el)).strip()]
        ouder = el
        for _ in range(3):
            ouder = getattr(ouder, "parent", None)
            if ouder is None or getattr(ouder, "name", None) in (
                    None, "body", "html", "[document]"):
                break
            t = re.sub(r"\s+", " ", vlak(ouder)).strip()
            if len(t) > 220:
                break
            kandidaten.append(t)

        # Per onderdeel de kleinste kandidaat die het bevat. Ronde, uitslag en
        # datum staan niet noodzakelijk in hetzelfde element: in de ene vorm
        # zit alles in de linktekst, in de andere staat de datum in een cel
        # ernaast. Eén kandidaat kiezen voor alles liet daarom rijen vallen.
        SCORE = r"(?<!\d)(\d{1,2})\s*-\s*(\d{1,2})(?!\d)"
        ronde, gh, ga, datum, rijtekst = None, None, None, "", kandidaten[0]
        for t in kandidaten:
            if ronde is None:
                rm = re.search(r"\bRonde\s+(\d{1,2})\b", t)
                if rm:
                    ronde = int(rm.group(1))
            # Een nog niet gespeeld duel krijgt op deze pagina een VOORSPELDE
            # uitslag mee: "za 23 jan, 16:30 Ajax 2-1 voorspelling Telstar".
            # Zonder deze uitzondering belandde die 2-1 als echte uitslag in
            # clubs.csv, met resultaat, ploegpunten en clean sheet erbij — voor
            # 225 van de 306 duels, en de clubratings werden erop gefit.
            if gh is None and not re.search(r"voorspelling|verwachte uitslag",
                                            t, re.I):
                # 'Ronde 9' eerst weg, zodat een rondenummer geen score wordt
                sm = re.search(SCORE, re.sub(r"\bRonde\s+\d{1,2}\b", " ", t))
                if sm:
                    gh, ga = int(sm.group(1)), int(sm.group(2))
            if not datum:
                datum = datum_iso(t)
            if len(t) > len(rijtekst):
                rijtekst = t
        if ronde is None:
            ronde = kop_ronde
        if ronde is None:
            continue

        rij = {
            "ronde": ronde, "datum": datum,
            "datum_tekst": rijtekst.split("Ronde")[0].strip(),
            "thuis": thuis, "uit": uitc, "thuis_goals": gh, "uit_goals": ga,
            "url": href if href.startswith("http") else BASE + href,
        }
        # Bij een dubbele vermelding wint de rij MET uitslag. Anders zou de
        # rondelijst de uitslag uit "Net gespeeld" kunnen overschrijven.
        eerder = per_slug.get(slug)
        if eerder is None:
            per_slug[slug] = rij
            uit.append(rij)
        elif eerder["thuis_goals"] is None and gh is not None:
            eerder.update(rij)
    return uit


def slug_naar_clubs(slug):
    """'sc-heerenveen-excelsior' -> ('sc Heerenveen', 'Excelsior').

    De slug is thuisclub + uitclub aan elkaar. Omdat clubslugs zelf streepjes
    bevatten moet er gezocht worden naar de splitsing die twee geldige clubs
    oplevert; de langste match vooraan wint.
    """
    s = slug.strip("-")
    for n in sorted(CLUB_SLUG, key=len, reverse=True):
        if s.startswith(n + "-"):
            rest = s[len(n) + 1:]
            if rest in CLUB_SLUG:
                return CLUB_SLUG[n], CLUB_SLUG[rest]
    return None


# ------------------------------------------------------------ wedstrijdpagina
def parse_wedstrijd(soup, thuis, uitc):
    """Kansen, verwachte goals en de over/under-percentages.

    Geverifieerd op 19-10-2026. De opmaak is:
        50% 21% 29%            met daaronder "PSV wint Gelijkspel Feyenoord wint"
        Verwachte goals PSV 2.3
        Verwachte goals Feyenoord 1.73
        Beide ploegen scoren 71%
        Meer dan 2,5 goals 75%
    De oude ankertekst "Kansen vooraf" bestaat niet meer.
    """
    plat = vlak(soup)
    een = re.sub(r"\s+", " ", plat)
    d = {"kans_thuis": "", "kans_gelijk": "", "kans_uit": "",
         "xg_thuis": "", "xg_uit": "", "beide_scoren": "", "over_25": "",
         "verwacht_thuis": "", "verwacht_uit": "", "ronde": "", "datum": ""}

    # verwachte goals: eerst per club op naam. Komma of punt als decimaalteken.
    for club, sleutel in ((thuis, "xg_thuis"), (uitc, "xg_uit")):
        m = re.search(r"Verwachte goals\s+" + re.escape(club) +
                      r"\s*:?\s*(\d+(?:[.,]\d+)?)", een)
        if m:
            d[sleutel] = getal(m.group(1))

    # Terugval als het label niet per club wordt herhaald. Vormen die kunnen
    # voorkomen:
    #   "Verwachte goals PSV 2.3 Verwachte goals Feyenoord 1.73"  -> hierboven
    #   "Verwachte goals PSV 2.3 Feyenoord 1.73"                  -> label 1x
    #   "Verwachte goals PSV Verwachte goals Feyenoord 2.3 1.73"  -> eerst labels
    # De tweede vorm leverde precies de helft van de rijen zonder verwachte
    # goals op: per duel werd alleen de thuisclub gevonden. Daarom het blok
    # achter het eerste "Verwachte goals" uiteenleggen in clubnamen en getallen
    # en op POSITIE koppelen in plaats van op het label.
    if d["xg_thuis"] == "" or d["xg_uit"] == "":
        i = een.find("Verwachte goals")
        if i >= 0:
            blok = een[i:i + 220]
            p_t, p_u = blok.find(thuis), blok.find(uitc)
            # percentages overslaan: die horen bij over/under en beide scoren
            nums = [(m.start(), getal(m.group(1)))
                    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(?!%)", blok)
                    if not blok[m.end():m.end() + 1] == "%"]
            nums = [(p, v) for p, v in nums if v is not None and 0.2 <= v <= 6.0]
            if p_t >= 0 and p_u >= 0 and len(nums) >= 2:
                if nums[0][0] > max(p_t, p_u):
                    # Eerst beide clubnamen, dan beide getallen. In deze vorm
                    # is de koppeling per label per definitie fout: die pakt
                    # het eerstvolgende getal, en dat hoort bij de andere club.
                    # Daarom hier OVERSCHRIJVEN en niet alleen gaten vullen.
                    eerst, tweede = nums[0][1], nums[1][1]
                    d["xg_thuis"], d["xg_uit"] = (
                        (eerst, tweede) if p_t < p_u else (tweede, eerst))
                else:
                    # Getal staat achter zijn eigen clubnaam; alleen aanvullen.
                    na_t = [v for p, v in nums if p > p_t and (p < p_u or p_u < p_t)]
                    na_u = [v for p, v in nums if p > p_u and (p < p_t or p_t < p_u)]
                    if d["xg_thuis"] == "" and na_t:
                        d["xg_thuis"] = na_t[0]
                    if d["xg_uit"] == "" and na_u:
                        d["xg_uit"] = na_u[0]

    m = re.search(r"Beide ploegen scoren\s*:?\s*(\d{1,3})\s*%", een)
    if m:
        d["beide_scoren"] = int(m.group(1))
    m = re.search(r"Meer dan 2[.,]5 goals\s*:?\s*(\d{1,3})\s*%", een)
    if m:
        d["over_25"] = int(m.group(1))

    # kansen: drie percentages met daarna de labels. Anker op het label, niet
    # op de positie, want zo kan de thuiskans niet in de gelijkspelkolom
    # belanden zoals eerder gebeurde.
    pat = (r"(\d{1,3})\s*%\s*(\d{1,3})\s*%\s*(\d{1,3})\s*%\s*" +
           re.escape(thuis) + r"\s+wint\s+Gelijkspel\s+" + re.escape(uitc) +
           r"\s+wint")
    m = re.search(pat, een)
    if not m:
        # zelfde drieling, zonder de labels erachter
        m = re.search(r"(\d{1,3})\s*%\s*(\d{1,3})\s*%\s*(\d{1,3})\s*%", een)
    if m:
        a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # De drie kansen tellen bij deze bron altijd op tot precies 100, want
        # de marge is eruit gehaald. Een drieling die dat niet doet is iets
        # anders op de pagina (passnauwkeurigheid, balbezit) en wordt genegeerd.
        if 99 <= a + b + c <= 101:
            d["kans_thuis"], d["kans_gelijk"], d["kans_uit"] = a, b, c

    ms = re.search(r"Meest waarschijnlijke uitslagen(.{0,300})", een)
    if ms:
        sc = re.search(r"(\d)\s*-\s*(\d)\s*(?:\d+[.,]\d+\s*%)?", ms.group(1))
        if sc:
            d["verwacht_thuis"], d["verwacht_uit"] = int(sc.group(1)), int(sc.group(2))

    rm = re.search(r"Speelronde\s+(\d{1,2})", een)
    if rm:
        d["ronde"] = int(rm.group(1))
    dm = re.search(r"Speelronde\s+\d{1,2}\s*[·•|-]\s*([^|\n]{6,60})", een)
    if dm:
        d["datum"] = datum_iso(dm.group(1))
    return d


# ---------------------------------------------------- opstelling + afwezigen
def parse_opstelling(soup, club):
    """Vermoedelijke basiself met basiskans, en de afwezigen met reden.

    Geverifieerd op /eredivisie/feyenoord/opstelling/, 19-10-2026:
        h1   "Vermoedelijke opstelling Feyenoord tegen PSV"
        "Niet beschikbaar:"  Gijs Smal blessure
                             Thomas Beelen schorsing - verwacht terug rond 29-01-2027
                             Ayase Ueda vertrokken - verwacht terug rond 30-06-2027
        per speler een percentage: hoe vaak hij begon
    """
    ruw = str(soup)
    plat = vlak(soup)
    een = re.sub(r"\s+", " ", plat)

    tegen = ""
    h1 = soup.find("h1")
    if h1:
        m = re.search(r"tegen\s+(.+?)\s*$", vlak(h1).strip())
        if m:
            tegen = club_naam(m.group(1))
    datum = ""
    dm = re.search(r"(?:op\s+)?((?:ma|di|wo|do|vr|za|zo)[a-z]*dag\s+\d{1,2}\s+"
                   r"[a-z]+\s+\d{4})", een, re.I)
    if dm:
        datum = datum_iso(dm.group(1))
    thuis_uit = ""
    if re.search(r"\bthuis\b", een[:1200], re.I):
        thuis_uit = "thuis"
    elif re.search(r"\buit\b", een[:1200], re.I):
        thuis_uit = "uit"
    rm = re.search(r"speelronde\s+(\d{1,2})", een, re.I)
    ronde = int(rm.group(1)) if rm else ""

    # --- afwezigen. Het blok begint bij "Niet beschikbaar:" en loopt tot de
    # volgende kop. Elke speler is een link; reden en datum staan erachter.
    afwezig = []
    # Op de KOP ankeren ("Blessures en schorsingen PSV"), met de oude
    # tekstankers als terugval.
    blok_van, blok_tot, blok_html = blok_na_kop(
        ruw, r"blessure|schorsing|ontbreek|niet beschikbaar")
    if blok_van is None:
        im = re.search(r"Niet beschikbaar|Wie ontbreekt", ruw, re.I)
        if im:
            volgend = re.search(r"<h[1-6][^>]*>", ruw[im.end():], re.I)
            blok_van = im.start()
            blok_tot = im.end() + (volgend.start() if volgend else 4000)
            blok_html = ruw[im.end():blok_tot]
        else:
            print(f"    {club}: geen blok met blessures of schorsingen gevonden")

    # Per REGEL lezen en niet per spelerslink: op 19-10-2026 stond
    # "Ricardo Daniel Pepi blessure" zonder link in de lijst, en die slaat een
    # linkgebaseerde parser over. De REDEN is het anker, de naam is wat ervoor
    # staat. Zonder reden is het geen afwezige — nodig omdat de FAQ dezelfde
    # spelers nog eens noemt, en een speler die onterecht als afwezig wordt
    # gemerkt valt volledig uit de pool. Liever een afwezige missen dan een
    # basisspeler weggooien.
    sub = BeautifulSoup(blok_html, "html.parser")
    for el in sub.find_all(["li", "tr", "p", "div", "span"]):
        t = re.sub(r"\s+", " ", vlak(el)).strip()
        if not t or len(t) > 160:
            continue
        rm = re.search(r"\b(" + "|".join(REDEN_WOORDEN) + r")\b", t, re.I)
        if not rm:
            continue
        naam = re.sub(r"^\s*\d{1,3}\s+", "", t[:rm.start()])
        naam = naam.strip(" -\u00b7|\u2013:")
        if not naam or len(naam) > 60:
            continue
        a = el.select_one('a[href*="/eredivisie/speler/"]')
        hm = SPELER_HREF.search(a.get("href", "")) if a else None
        sid = norm(hm.group(1)) if hm else norm(naam)
        if not sid:
            continue
        tm = re.search(r"verwacht terug rond\s*(\d{2}-\d{2}-\d{4})", t, re.I)
        terug = ""
        if tm:
            d_, m_, j_ = tm.group(1).split("-")
            terug = f"{j_}-{m_}-{d_}"
        afwezig.append({"opgehaald": VANDAAG, "club": club,
                        "speler": (vlak(a).strip() if a else naam),
                        "speler_id": sid, "reden": rm.group(1).lower(),
                        "verwacht_terug": terug, "tegenstander": tegen,
                        "datum": datum})

    # geen dubbelen, eerste vermelding wint
    gezien, uniek = set(), []
    for r in afwezig:
        if r["speler_id"] in gezien:
            continue
        gezien.add(r["speler_id"])
        uniek.append(r)
    afwezig = uniek
    afwezig_ids = {r["speler_id"] for r in afwezig}

    # --- vermoedelijke basiself.
    #
    # DERDE SELECTIEMANIER, en de reden staat in de bron en niet in mijn code:
    # het percentage achter de naam is er op 23-10-2026 niet meer. De pagina
    # toont de elf nu als een veldopstelling met avatars, zonder enig getal per
    # speler; de enige percentages die er nog staan zijn de wedstrijdkansen
    # (48/21/31). Selecteren op dat percentage -- wat hier stond -- matcht dan
    # nergens, en dat is precies wat er gebeurde: nul van elf, bij elke club.
    #
    # Wat er volgens de --debug van die dag WEL staat, en waar dit nu op rust:
    #   <h1> Vermoedelijke opstelling PSV tegen Feyenoord
    #   <h2> Live: de officiele opstelling zodra die bekend is
    #   <h2> Verwachte opstelling PSV tegen Feyenoord      <- de elf
    #   <h3> PSV
    #   <h2> Wat deze opstelling betekent                  <- einde van het blok
    #   <h2> Blessures en schorsingen PSV
    #   <h2> Veelgestelde vragen
    # en: 16 spelerslinks op de pagina, 16 UNIEK -- elf starters plus vijf
    # gelinkte afwezigen, geen enkele naam twee keer. De FAQ herhaalt de
    # spelers dus niet als link, en dat was eerder juist de vervuiling.
    #
    # Daarom: ankeren op de h2 "Verwachte opstelling" en de spelerslinks in dat
    # blok nemen, in documentvolgorde. blok_na_kop() eindigt bij de volgende kop
    # van hetzelfde of hoger niveau, dus de h3 "PSV" erbinnen breekt het blok
    # niet af en de h2 erna wel. Op de kop ankeren kon eerder niet omdat er twee
    # koppen met "opstelling" in stonden; "Verwachte opstelling" is nu specifiek
    # genoeg, en de h1 ("Vermoedelijke opstelling") matcht er niet op.
    _, _, elf_html = blok_na_kop(ruw, r"Verwachte\s+opstelling")
    bron_blok = "kop"
    if not elf_html:
        # Terugval op de hele pagina. Die rust op de meting hierboven: alle
        # spelerslinks minus de afwezigen IS de elf, want er staat geen enkele
        # naam dubbel. Zwakker dan het blok -- een nieuw linkblok elders op de
        # pagina vervuilt dit -- maar beter dan niets, en de plausibiliteits-
        # controle verderop vangt het als het misgaat.
        elf_html, bron_blok = ruw, "hele pagina"

    elf, gezien2 = [], set()
    for m in SPELER_HREF.finditer(elf_html):
        sid = m.group(1)
        if sid in afwezig_ids or sid in gezien2:
            continue
        gezien2.add(sid)
        # Het percentage blijft OPTIONEEL meegenomen. Nu levert het niets op,
        # maar als de bron het terugzet, staat het er weer in zonder dat hier
        # iemand aan te pas komt. Leeg is geldig: cvhj_model.lees_opstellingen()
        # verdraagt een lege kans_basis en houdt de speler in de elf.
        # Het venster loopt tot het EINDE VAN DE LINK van deze speler, niet
        # tot een zelfgekozen aantal tekens: een percentage daarbuiten hoort
        # bij de volgende speler of bij de wedstrijdkansen.
        staart = elf_html[m.end():]
        eind_a = staart.find("</a>")
        venster = staart[:eind_a] if eind_a != -1 else staart[:400]
        pm = re.search(r"(\d{1,3})\s*%", venster)
        kans = int(pm.group(1)) if pm and 0 <= int(pm.group(1)) <= 100 else ""
        naam = None
        am = re.search(r'alt="([^"]{2,60})"', staart)
        if am:
            naam = htmllib.unescape(am.group(1)).strip()
        elf.append({"opgehaald": VANDAAG, "club": club,
                    "speler": naam or slug_naar_naam(sid),
                    "speler_id": sid, "kans_basis": kans,
                    "tegenstander": tegen, "thuis_uit": thuis_uit,
                    "datum": datum, "ronde": ronde})

    # Plausibiliteit vóór aflevering. Elf namen is een opstelling; twintig
    # namen is een pagina die ergens doorloopt, en die mogen er niet uit als
    # een nette CSV, want dan ziet vervuiling eruit als data. Te weinig is net
    # zo verdacht. Afkappen op elf zou de fout juist verbergen.
    if len(elf) != 11:
        print(f"    {club}: {len(elf)} spelerslinks in het opstellingsblok "
              f"({bron_blok}), verwacht 11 — niet weggeschreven")
        return [], afwezig
    if bron_blok != "kop":
        print(f"    {club}: elf gevonden via de terugval op de {bron_blok}; "
              f"de kop 'Verwachte opstelling' is niet gevonden")
    return elf, afwezig


def slug_naar_naam(slug):
    kleine = {"van", "de", "der", "den", "het", "ter", "te", "op", "in"}
    delen = (slug or "").split("-")
    return " ".join(w if w in kleine and i else w.capitalize()
                    for i, w in enumerate(delen))


# ------------------------------------------------------------- spelersindex
def parse_spelersindex(soup):
    """[(slug, naam, club, positie)] voor alle ~504 spelers.

    Opbouw: h2 = club, h3 = Keepers / Verdedigers / Middenvelders / Aanvallers,
    daaronder de spelerslinks. De linktekst begint met het rugnummer.
    """
    ruw = str(soup)
    koppen = []
    for m in re.finditer(r"<h([23])[^>]*>(.*?)</h\1>", ruw, re.S | re.I):
        naam = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        koppen.append((m.start(), m.end(), int(m.group(1)), naam))

    uit, gezien = [], set()
    for i, (pos, eind, niveau, naam) in enumerate(koppen):
        if niveau != 3 or norm(naam) not in POSITIE:
            continue
        positie = POSITIE[norm(naam)]
        club = ""
        for j in range(i - 1, -1, -1):
            if koppen[j][2] == 2:
                club = club_naam(koppen[j][3])
                break
        blok_eind = koppen[i + 1][0] if i + 1 < len(koppen) else len(ruw)
        blok = ruw[eind:blok_eind]
        for a in BeautifulSoup(blok, "html.parser").select(
                'a[href*="/eredivisie/speler/"]'):
            sm = SPELER_HREF.search(a.get("href", ""))
            if not sm:
                continue
            slug = norm(sm.group(1))
            if slug in gezien:
                continue
            gezien.add(slug)
            tekst = re.sub(r"^\s*\d{1,2}\s+", "", vlak(a).strip())
            uit.append((slug, tekst or slug_naar_naam(slug), club, positie))
    return uit


# ------------------------------------------------------- CVHJ-spelerslijst
def parse_poule_prijzen(soup):
    """[(speler_id, naam, club, positie, prijs)] uit de CVHJ-spelerslijst.

    Rij: "Guus Til basis | PSV | Middenvelder | 4,0 mln | ..." met de naam en
    de club elk als link. Daarmee zijn speler_id en club exact bekend en hoeft
    er niets op naam gekoppeld te worden — precies de zwakke schakel die de
    bevroren CVHJ-sheet opleverde.

    BEWUST NIET GELEZEN: de kolommen 'Verwachte punten', 'Per miljoen' en de
    basiskans. De pagina zegt zelf dat die er "voor leden" bij staan; dat is
    Pouletips Premium en dat halen we hier niet weg. Alleen naam, club,
    positie en waarde, en die zijn vrij toegankelijk.
    """
    # Per RIJ lezen en niet per spelerslink. Van de 507 aangekondigde spelers
    # kwamen er 477 binnen terwijl er maar een om een bijgehouden reden werd
    # overgeslagen: de overige 29 hadden helemaal geen spelerslink, net als
    # "Ricardo Daniel Pepi" in de afwezigenlijst. De PRIJS is het anker — elke
    # rij heeft er precies een — en de link levert het speler_id als hij er is.
    uit, gezien, mist, geraden = [], set(), {}, []
    for el in soup.find_all(["tr", "li", "div"]):
        t = re.sub(r"\s+", " ", vlak(el)).strip()
        if not t or len(t) > 220:
            continue
        gm = re.search(r"(\d+(?:[.,]\d+)?)\s*mln", t, re.I)
        pm = re.search(r"\b(Keeper|Verdediger|Middenvelder|Aanvaller)s?\b",
                       t, re.I)
        if not gm or not pm:
            continue

        club, club_pos = "", len(t)
        for a in el.find_all("a"):
            cm = re.search(r"/eredivisie/([a-z0-9-]+)/?$", a.get("href", "") or "")
            if cm and cm.group(1) in CLUB_SLUG:
                club = CLUB_SLUG[cm.group(1)]
                break
        if not club:
            club = club_in_tekst(t)
        if club:
            i = t.find(club)
            if i >= 0:
                club_pos = i

        pa = el.select_one('a[href*="/eredivisie/speler/"]')
        hm = SPELER_HREF.search(pa.get("href", "") or "") if pa else None
        if pa:
            naam = vlak(pa).strip()
        else:
            # geen link: naam is wat voor de club en de positie staat, zonder
            # rugnummer en zonder markeringen als "basis", "nieuw" of een
            # blessurenoot die met een uitroepteken begint
            naam = t[:min(club_pos, pm.start())]
            naam = re.sub(r"!.*$", "", naam)
            naam = re.sub(r"\b(basis|nieuw)\b", "", naam, flags=re.I)
            naam = re.sub(r"^\s*\d{1,3}\s+", "", naam).strip(" -·|–")
        sid = norm(hm.group(1)) if hm else norm(naam)
        if not sid or sid in gezien:
            continue
        gezien.add(sid)
        if not hm:
            # Zonder link is het id een gok uit de naam. Dat werkt meestal,
            # maar het verlaagt de koppeling met de gescrapete spelers van
            # exact naar naamgebaseerd, en dat hoort zichtbaar te zijn.
            geraden.append(naam or sid)

        prijs = getal(gm.group(1))
        # Per overgeslagen rij vastleggen WAAROM. Zonder die uitsplitsing kost
        # elke diagnose een extra run, en dat is drie keer gebeurd.
        if not naam:
            mist.setdefault("geen naam", []).append(sid)
        elif prijs is None or not 0.5 <= prijs <= 10.0:
            mist.setdefault("prijs onzinnig", []).append(f"{naam}={gm.group(1)}")
        elif not club:
            mist.setdefault("geen club", []).append(naam)
        else:
            uit.append((sid, naam, club,
                        POSITIE_ENKEL[pm.group(1).lower()], prijs))
    for reden, namen in sorted(mist.items()):
        print(f"    overgeslagen, {reden} ({len(namen)}): "
              f"{', '.join(namen[:8])}{' ...' if len(namen) > 8 else ''}")
    if geraden:
        print(f"    speler_id geraden uit de naam, want geen link "
              f"({len(geraden)}): {', '.join(geraden[:8])}"
              f"{' ...' if len(geraden) > 8 else ''}")
    return uit


def taak_prijzen():
    """prijzen.csv: de actuele CVHJ-spelerslijst met prijs per speler."""
    print("CVHJ-spelerslijst ophalen")
    soup = get(PRIJZEN_URL)
    rijen = parse_poule_prijzen(soup)
    gemeld = re.search(r"Alle\s+(\d{2,4})\s+spelers",
                       re.sub(r"\s+", " ", vlak(soup)))
    verwacht = int(gemeld.group(1)) if gemeld else None
    print(f"  {len(rijen)} spelers gelezen"
          + (f" van de {verwacht} aangekondigde" if verwacht else "")
          + f", {len({c for _, _, c, _, _ in rijen})} clubs")
    if verwacht and len(rijen) < verwacht * 0.95:
        print("  ! minder dan aangekondigd — draai --debug op de lijstpagina")
    if not rijen:
        print("  ! leeg, prijzen.csv blijft ongemoeid")
        return
    uit = [{"team": club, "speler": naam, "positie": pos, "prijs": prijs,
            "speler_id": sid, "opgehaald": VANDAAG}
           for sid, naam, club, pos, prijs in rijen]
    schrijf(OUT / "prijzen.csv", PRIJS_COLS, uit, ["speler_id"])


# --------------------------------------------------------------- spelerspagina
def parse_speler(soup, seizoen=SEIZOEN):
    """Seizoenstotalen van een speler.

    De betrouwbaarste bron op de pagina is de seizoenstabel:
        veldspeler  Seizoen | Club | Duels | Min. | Goals | Assists | Cijfer
        keeper      Seizoen | Club | Duels | Min. | Reddingen | Tegen |
                    Nul achter | Cijfer
    Daarnaast staan de labels los op de pagina ("Basisplaatsen 8",
    "Overtredingen 3"); die worden als aanvulling gelezen.
    """
    d = {k: "" for k in ("duels", "basisplaatsen", "minuten", "goals",
                         "assists", "overtredingen", "reddingen",
                         "nul_achter", "cijfer", "status_tekst")}
    plat = vlak(soup)
    een = re.sub(r"\s+", " ", plat)

    for koppen, rijen in tabellen(soup):
        kop = [norm(k) for k in koppen]
        if not any(k.startswith("seizoen") for k in kop):
            continue
        for rij in rijen:
            if not rij or seizoen not in rij[0]:
                continue
            paar = dict(zip(kop[:len(rij)], rij)) if len(kop) >= len(rij) else {}
            for bron, doel in (("duels", "duels"), ("min", "minuten"),
                               ("goals", "goals"), ("assists", "assists"),
                               ("reddingen", "reddingen"),
                               ("nul-achter", "nul_achter"),
                               ("cijfer", "cijfer")):
                for k, v in paar.items():
                    if k.startswith(bron) and d[doel] == "":
                        g = getal(v)
                        if g is not None:
                            d[doel] = g if doel == "cijfer" else int(round(g))
            break

    # losse labels; alleen invullen wat de tabel niet gaf
    for label, doel in (("Basisplaatsen", "basisplaatsen"),
                        ("Overtredingen", "overtredingen"),
                        ("Minuten", "minuten"), ("Duels", "duels"),
                        ("Goals", "goals"), ("Assists", "assists"),
                        ("Reddingen", "reddingen")):
        if d[doel] != "":
            continue
        m = re.search(re.escape(label) + r"\s*:?\s*(\d+(?:[.,]\d+)?)", een)
        if m:
            d[doel] = heel(m.group(1))
    if d["nul_achter"] == "":
        m = re.search(r"(?:Nul achter|Wedstrijden zonder tegendoelpunt)"
                      r"\s*:?\s*(\d+)", een)
        if m:
            d["nul_achter"] = int(m.group(1))
    if d["cijfer"] == "":
        m = re.search(r"Gemiddeld cijfer\s*:?\s*(\d+(?:[.,]\d+)?)", een)
        if m:
            d["cijfer"] = getal(m.group(1))

    # "kwam in 2026/27 nog niet in actie" -> alles nul, geen leeg
    if re.search(re.escape(seizoen) + r"\s+nog niet in actie", een):
        for k in ("duels", "basisplaatsen", "minuten", "goals", "assists",
                  "overtredingen", "reddingen", "nul_achter"):
            d[k] = 0
    sm = re.search(r"\bis\s+(geblesseerd|geschorst|niet beschikbaar)[^.]{0,60}\.",
                   een)
    if sm:
        d["status_tekst"] = sm.group(0).strip()[:120]

    # Welke velden werkelijk op de pagina stonden. Dit is nodig voor de
    # broncontrole: hieronder worden lege tellers op nul gezet, en daarna is
    # een verdwenen kolom niet meer te onderscheiden van een echte nul.
    d["_gevonden"] = ",".join(k for k in
                              ("duels", "basisplaatsen", "minuten", "goals",
                               "assists", "overtredingen", "reddingen",
                               "nul_achter", "cijfer") if d[k] != "")

    # Wie gespeeld heeft, heeft nul assists als er geen assists staan — niet
    # "onbekend". Keepers hebben geen assistkolom in hun seizoenstabel; zonder
    # deze stap wordt hun verschil per ronde leeg en rekent het model er niet
    # mee. Een keeper die wel een assist gaf, staat met het losse label op de
    # pagina en is hierboven al opgepikt.
    if d["duels"] != "":
        for k in ("basisplaatsen", "minuten", "goals", "assists",
                  "overtredingen", "reddingen", "nul_achter"):
            if d[k] == "":
                d[k] = 0
    return d


# ------------------------------------------------------------------- kaarten
def parse_kaartenlijst(soup, kolom_woord):
    """{speler_id: (naam, club, aantal)} uit een statistiekenranglijst.

    Een rij ziet er zo uit:
        1   Abdelnour Soualhia  Telstar   3

    Niet op <table>, <th> of de ouder van de link leunen. Beide zijn op
    19-10-2026 geprobeerd en beide leverden nul rijen op, terwijl de pagina er
    visueel wel als een tabel uitziet en de kopteksten er wel staan ('#',
    'Speler', 'Gele kaarten'). Daarom hetzelfde recept als bij de afwezigen:
    de platte tekst knippen op de spelersnamen. Achter de naam komen eerst de
    club en dan het aantal; het eerste getal in dat stuk is het aantal, want
    het rangnummer staat vóór de naam en geen clubnaam bevat een cijfer.

    De clubtabel verderop heeft clublinks en geen spelerslinks, en valt
    daardoor automatisch af.
    """
    uit = {}
    for sid, naam, span in stukken_per_speler(soup, marge=60):
        # Het getal moet dicht achter de naam staan, met alleen de clubnaam
        # ertussen. Dat houdt losse spelerslinks elders op de pagina buiten de
        # lijst: bij die staat geen aantal binnen een handvol woorden.
        m = re.match(r"[^0-9]{0,40}(\d{1,3})", span)
        if not m:
            continue
        aantal = int(m.group(1))
        if not 1 <= aantal <= 40:
            continue                      # geen kaartenaantal maar iets anders
        uit[sid] = (naam, club_in_tekst(span[:m.start(1)]), aantal)
    return uit


# ----------------------------------------------------------- per ronde maken
def ronde_uit_verschil(vorig, nu, rondes, datum):
    """Trek twee seizoensstanden van elkaar af en maak er ronderijen van.

    Een momentopname geeft seizoenstotalen. Het model wil productie per ronde.
    Het verschil tussen de stand van vorige week en die van nu is precies wat
    er in de tussenliggende ronde(n) gebeurde. Vallen er meer ronden in het
    venster, dan wordt dat in de kolom 'venster' vastgelegd in plaats van
    stilletjes aan de laatste ronde toegerekend.
    """
    tellers = ("duels", "basisplaatsen", "minuten", "goals", "assists",
               "geel", "rood", "reddingen", "nul_achter")
    oud = {r["speler_id"]: r for r in vorig}
    ronde = rondes[-1] if rondes else ""
    venster = ",".join(str(r) for r in rondes)
    uit = []
    for r in nu:
        v = oud.get(r["speler_id"], {})
        delta = {}
        for k in tellers:
            a, b = getal(r.get(k)), getal(v.get(k))
            delta[k] = (int(a) - int(b or 0)) if a is not None else ""
        if not any(isinstance(delta[k], int) and delta[k] > 0
                   for k in ("duels", "minuten")):
            continue                      # niet gespeeld in dit venster
        uit.append({
            "ronde": ronde, "datum": datum, "speler_id": r["speler_id"],
            "speler": r["speler"], "club": r["club"], "positie": r["positie"],
            "duels": delta["duels"], "basis": delta["basisplaatsen"],
            "minuten": delta["minuten"], "goals": delta["goals"],
            "assists": delta["assists"], "geel": delta["geel"],
            "rood": delta["rood"], "reddingen": delta["reddingen"],
            "clean_sheet": delta["nul_achter"], "ploegpunten": "",
            "venster": venster, "opgehaald": VANDAAG})
    return uit


# ------------------------------------------------------------- wegschrijven
def lees(pad):
    if not pad.exists():
        return []
    with open(pad, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def schrijf(pad, cols, nieuw, sleutel):
    """Bijwerken op sleutel; nieuwe data overschrijft oude. Als het kolomformaat
    is veranderd begint het bestand opnieuw, anders ontstaat er een mengsel."""
    rijen, index = [], {}
    bestaand = lees(pad)
    if bestaand and set(bestaand[0]) == set(cols):
        for r in bestaand:
            k = tuple(str(r.get(c, "")) for c in sleutel)
            index[k] = len(rijen)
            rijen.append(r)
    elif bestaand and all(c in bestaand[0] for c in sleutel):
        # Kolomformaat gewijzigd: de bestaande rijen MEEVERHUIZEN en niet
        # weggooien. Hier stond "bestand wordt opnieuw opgebouwd", en dat was
        # geen opmerking maar dataverlies met een aankondiging: spelers.csv had
        # negen ronden geschiedenis en de volgende volledige run zou daar één
        # ronde van maken. Gemeten gevolg voor de pool: 273 spelers terug naar
        # 175, en erger dan dat getal is dat rol_kenmerken() dan één waarneming
        # per speler krijgt, waardoor p_speelt en p_60plus nul of één worden
        # zonder enige demping.
        #
        # De nieuwe kolommen blijven leeg. Dat is eerlijk: die data bestaat voor
        # die ronden niet meer en valt niet te reconstrueren. Voor het model
        # maakt het niets uit -- bouw_pool() leest ronde, speler_id, club,
        # minuten, goals, basis en de rol, en die staan er allemaal in.
        #
        # Voorwaarde is dat de SLEUTELKOLOMMEN er zijn; zonder die krijgt elke
        # oude rij dezelfde lege sleutel en overschrijven ze elkaar. Mist er
        # een, dan valt dit terug op het oude gedrag -- met de melding erbij.
        nieuw_in = sorted(set(cols) - set(bestaand[0]))
        for r in bestaand:
            rij = {c: r.get(c, "") for c in cols}
            k = tuple(str(rij.get(c, "")) for c in sleutel)
            index[k] = len(rijen)
            rijen.append(rij)
        print(f"  {pad.name}: kolommen gewijzigd, {len(rijen)} bestaande rijen "
              f"meegenomen; nieuw en leeg: {', '.join(nieuw_in) or '(geen)'}")
    elif bestaand:
        ontbreekt = sorted(set(sleutel) - set(bestaand[0]))
        print(f"  {pad.name}: kolommen gewijzigd EN de sleutelkolom(men) "
              f"{ontbreekt} ontbreken — de bestaande {len(bestaand)} rijen zijn "
              f"niet over te nemen en het bestand wordt opnieuw opgebouwd")
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


# ------------------------------------------------------------------ taken
def taak_clubs(rondes=None):
    """clubs.csv: uitslagen + kansen + verwachte goals per club per ronde."""
    print("Uitslagen ophalen")
    soup = get(UITSLAGEN_URL)
    duels = parse_uitslagen(soup)
    print(f"  {len(duels)} wedstrijden gevonden, "
          f"{sum(1 for d in duels if d['thuis_goals'] is not None)} gespeeld")
    if not duels:
        print("  ! geen wedstrijden gevonden — draai --debug op de uitslagenpagina")
        return

    # Twee bronnen, twee kosten. De uitslag staat op deze ene pagina en is dus
    # gratis: die wordt voor ALLE duels bijgewerkt. De kansen en verwachte
    # goals kosten een pagina per wedstrijd en veranderen na het duel niet
    # meer, dus die worden eenmalig opgehaald en daarna overgenomen. Zonder
    # die scheiding kreeg een ronde die als 'komend' was opgehaald nooit meer
    # zijn uitslag erbij.
    # Sleutels als tekst: uit het CSV komt de ronde als string, uit de bron als
    # int; zonder gelijktrekken matcht niets.
    oud = {(str(r.get("ronde")), r.get("club")): r
           for r in lees(OUT / "clubs.csv")}

    def kansen_bekend(d):
        r = oud.get((str(d["ronde"]), d["thuis"]))
        return r is not None and str(r.get("kans_winst", "")).strip() != ""

    gespeeld = {d["ronde"] for d in duels if d["thuis_goals"] is not None}
    open_ = sorted({d["ronde"] for d in duels} - gespeeld)
    binnenkort = set(open_[:VOORUIT_RONDEN])

    if rondes:
        haal = {d["url"] for d in duels if d["ronde"] in rondes}
    else:
        # De uitslagenpagina noemt alle 34 ronden, ruim driehonderd duels. Odds
        # van ronde 30 zijn in oktober zinloos en zouden bovendien verouderen
        # voordat die ronde wordt gespeeld, dus alleen ophalen wat bruikbaar
        # is: gespeelde ronden waarvan de kansen nog missen, plus de komende
        # paar ronden. Die laatste elke run opnieuw, want de odds scherpen naar
        # de aftrap toe aan.
        haal = {d["url"] for d in duels
                if d["ronde"] in binnenkort
                or (d["ronde"] in gespeeld and not kansen_bekend(d))}
    print(f"  wedstrijdpagina's op te halen: {len(haal)} "
          f"(komende ronden: {sorted(binnenkort) or 'geen'})")

    rijen = []
    for d in sorted(duels, key=lambda x: (x["ronde"], x["url"])):
        if d["url"] in haal:
            print(f"  r{d['ronde']} {d['thuis']} - {d['uit']}")
            try:
                w = parse_wedstrijd(get(d["url"]), d["thuis"], d["uit"])
            except Exception as e:
                print(f"    ! mislukt: {type(e).__name__}: {e}")
                w = None
        else:
            w = None
        if w is None:
            # kansen uit de vorige run overnemen; de thuisrij is de bron
            b = oud.get((str(d["ronde"]), d["thuis"]), {})
            w = {"kans_thuis": b.get("kans_winst", ""),
                 "kans_gelijk": b.get("kans_gelijk", ""),
                 "kans_uit": b.get("kans_verlies", ""),
                 "xg_thuis": b.get("xg_voor", ""), "xg_uit": b.get("xg_tegen", ""),
                 "beide_scoren": b.get("beide_scoren", ""),
                 "over_25": b.get("over_25", ""),
                 "verwacht_thuis": b.get("verwacht_voor", ""),
                 "verwacht_uit": b.get("verwacht_tegen", ""),
                 "ronde": d["ronde"], "datum": b.get("datum", "")}
        datum = d["datum"] or w["datum"]
        gh, ga = d["thuis_goals"], d["uit_goals"]
        for club, tegen, gf, gc, tu in ((d["thuis"], d["uit"], gh, ga, "thuis"),
                                        (d["uit"], d["thuis"], ga, gh, "uit")):
            if gf is None:
                res, ppt, cs = "", "", ""
            else:
                res = "W" if gf > gc else ("G" if gf == gc else "V")
                ppt = 3 if res == "W" else (1 if res == "G" else 0)
                cs = int(gc == 0)
            rijen.append({
                "ronde": d["ronde"], "datum": datum, "club": club,
                "tegenstander": tegen, "thuis_uit": tu,
                "voor": "" if gf is None else gf,
                "tegen": "" if gc is None else gc,
                "resultaat": res, "ploegpunten": ppt, "clean_sheet": cs,
                "formatie": "",
                "kans_winst": w["kans_thuis"] if tu == "thuis" else w["kans_uit"],
                "kans_gelijk": w["kans_gelijk"],
                "kans_verlies": w["kans_uit"] if tu == "thuis" else w["kans_thuis"],
                "verwacht_voor": w["verwacht_thuis"] if tu == "thuis" else w["verwacht_uit"],
                "verwacht_tegen": w["verwacht_uit"] if tu == "thuis" else w["verwacht_thuis"],
                "xg_voor": w["xg_thuis"] if tu == "thuis" else w["xg_uit"],
                "xg_tegen": w["xg_uit"] if tu == "thuis" else w["xg_thuis"],
                "beide_scoren": w["beide_scoren"], "over_25": w["over_25"],
                "opgehaald": VANDAAG})
        if d["url"] in haal:
            xg = f"{w['xg_thuis']}-{w['xg_uit']}"
            # Ook de UITclub toetsen. Eerder keek dit alleen naar de thuisclub,
            # en dus bleef het stil als alleen die werd gevonden — precies de
            # situatie die 18 van de 36 rijen zonder verwachte goals opleverde.
            vlag = ("" if w["xg_thuis"] != "" and w["xg_uit"] != ""
                    and w["kans_thuis"] != "" else "   <-- CONTROLEER")
            print(f"    kansen {w['kans_thuis']}/{w['kans_gelijk']}/"
                  f"{w['kans_uit']}, verwachte goals {xg}{vlag}")
    if rijen:
        schrijf(OUT / "clubs.csv", CLUB_COLS, rijen, ["ronde", "club"])
    return duels


def taak_afwezigen():
    """afwezigen.csv en opstellingen.csv uit de 18 clubpagina's."""
    print("Afwezigen en vermoedelijke opstellingen")
    afw, elf = [], []
    for slug, club in CLUB_SLUG.items():
        try:
            soup = get(OPSTELLING_URL.format(slug=slug))
        except Exception as e:
            print(f"  {club}: ! {type(e).__name__}: {e}")
            continue
        e_, a_ = parse_opstelling(soup, club)
        elf += e_
        afw += a_
        vlag = "" if e_ else "   <-- CONTROLEER"
        print(f"  {club}: {len(e_)} basis, {len(a_)} afwezig{vlag}")
    if afw:
        schrijf(OUT / "afwezigen.csv", AFWEZIG_COLS, afw,
                ["opgehaald", "club", "speler_id"])
    if elf:
        schrijf(OUT / "opstellingen.csv", OPSTELLING_COLS, elf,
                ["opgehaald", "club", "speler_id"])
    return afw, elf


def taak_spelers(max_spelers=None, duels=None):
    """spelers_seizoen.csv (momentopname) en spelers.csv (verschil per ronde)."""
    print("Kaarten ophalen")
    geel = rood = {}
    try:
        geel = parse_kaartenlijst(get(GEEL_URL), "gele kaarten")
        print(f"  geel: {len(geel)} spelers")
    except Exception as e:
        print(f"  ! gele kaarten mislukt: {e}")
    try:
        rood = parse_kaartenlijst(get(ROOD_URL), "rode kaarten")
        print(f"  rood: {len(rood)} spelers")
    except Exception as e:
        print(f"  ! rode kaarten mislukt: {e}")

    print("Spelersindex ophalen")
    index = parse_spelersindex(get(SPELERS_URL))
    print(f"  {len(index)} spelers, {len({c for _, _, c, _ in index})} clubs")
    if not index:
        print("  ! leeg — draai --debug op de spelersindex")
        return
    if max_spelers:
        index = index[:max_spelers]

    nu = []
    for n, (slug, naam, club, positie) in enumerate(index, 1):
        try:
            soup = get(SPELER_URL.format(slug=slug), toestaan_404=True)
        except Exception as e:
            print(f"  ! {slug}: {type(e).__name__}: {e}")
            continue
        if soup is None:
            continue
        d = parse_speler(soup)
        d.update({"opgehaald": VANDAAG, "speler_id": slug, "speler": naam,
                  "club": club, "positie": positie,
                  "geel": geel.get(slug, ("", "", 0))[2],
                  "rood": rood.get(slug, ("", "", 0))[2]})
        nu.append(d)
        if n % 50 == 0:
            print(f"  {n}/{len(index)} ...")
    print(f"  {len(nu)} spelers gelezen, "
          f"{sum(1 for r in nu if getal(r.get('assists')) )} met assists")

    # Hier stond dat een spelers.csv met het oude kolomformaat apart werd gezet
    # als spelers_vorig_formaat.csv, met "de data blijft bewaard" erbij. Dat
    # gebeurde ook -- maar op de runner, en die wordt na de run weggegooid. De
    # vastlegstap in scrape.yml doet `[ -f "$f" ] && git add "$f"`, dus een
    # VERDWENEN bestand slaat hij stil over, en spelers_vorig_formaat.csv staat
    # niet in zijn lijst. Op 23-10-2026 overleefden negen ronden geschiedenis
    # dus bij toeval: de verplaatsing is nooit vastgelegd.
    #
    # De verplaatsing is er daarom uit. schrijf() neemt de bestaande rijen nu
    # mee bij een gewijzigd kolomformaat, dus er valt niets apart te zetten, en
    # een kopie die niet wordt vastgelegd is geen reservekopie. De echte
    # reservekopie is de git-geschiedenis van dit bestand.
    oud_alles = lees(OUT / "spelers_seizoen.csv")
    schrijf(OUT / "spelers_seizoen.csv", SEIZOEN_COLS, nu,
            ["opgehaald", "speler_id"])

    # verschil met de vorige momentopname
    data = [r for r in oud_alles if r.get("opgehaald") != VANDAAG]
    if not data:
        print("  (eerste momentopname; volgende week zijn er ronderijen)")
        return
    vorige = max(r["opgehaald"] for r in data)
    vorig = [r for r in data if r["opgehaald"] == vorige]
    rondes, datum = rondes_in_venster(vorige, VANDAAG, duels)
    if not rondes:
        # Twee momentopnamen zonder speelronde ertussen. Dat gebeurt bij een
        # extra run binnen dezelfde week. Rijen wegschrijven zou ze aan ronde
        # "" toekennen en de vorige ronde overschrijven, dus niets doen.
        print(f"  venster {vorige} -> {VANDAAG}: geen ronde gespeeld, "
              f"geen ronderijen")
        return
    rijen = ronde_uit_verschil(vorig, nu, rondes, datum)
    print(f"  venster {vorige} -> {VANDAAG}: ronden {rondes}, "
          f"{len(rijen)} spelers met speeltijd")
    if rijen:
        schrijf(OUT / "spelers.csv", SPELER_COLS, rijen,
                ["ronde", "speler_id", "club"])


def rondes_in_venster(van, tot, duels):
    """Welke ronden zijn er tussen twee ophaaldata gespeeld?"""
    if not duels:
        return [], tot
    rondes, laatste = set(), ""
    for d in duels:
        if d["thuis_goals"] is None or not d["datum"]:
            continue
        if van < d["datum"] <= tot:
            rondes.add(d["ronde"])
            laatste = max(laatste, d["datum"])
    return sorted(rondes), laatste or tot


# ------------------------------------------------------------------- debug
def debug(url):
    soup = get(url)
    ruw = str(soup)
    print(f"=== {url}\n")
    print("KOPPEN:")
    for h in soup.find_all(["h1", "h2", "h3", "h4"]):
        print(f"  <{h.name}> {vlak(h).strip()[:95]}")
    print(f"\nTABELLEN: {len(soup.find_all('table'))}")
    for i, (koppen, rijen) in enumerate(tabellen(soup)[:4]):
        print(f"  tabel {i}: koppen {koppen}")
        for r in rijen[:3]:
            print(f"    {r}")
    links = SPELER_HREF.findall(ruw)
    print(f"\nSPELERSLINKS: {len(links)} totaal, {len(set(links))} uniek")
    print("  eerste 8:", list(dict.fromkeys(links))[:8])
    een = re.sub(r"\s+", " ", vlak(soup))
    for woord in ("Verwachte goals", "Beide ploegen scoren", "Meer dan 2",
                  "Niet beschikbaar", "verwacht terug rond", "Ronde ",
                  "Basisplaatsen", "Assists", "Overtredingen", "wint"):
        i = een.find(woord)
        print(f"\n'{woord}': " + (f"...{een[max(0, i - 60): i + 140]}..."
                                  if i >= 0 else "NIET GEVONDEN"))
    print("\nPERCENTAGES (eerste 12):")
    for m in list(re.finditer(r"(\d{1,3})\s*%", een))[:12]:
        print(f"  {een[max(0, m.start() - 50): m.end() + 40]}")

    # Ruwe HTML rond de ankers. Platte tekst is niet genoeg om te zien hoe een
    # rij is opgebouwd, en juist dat is twee keer de oorzaak geweest: of de
    # reden en het aantal in hetzelfde element staan als de naam of in een
    # zuster-element is in de tekst niet te zien.
    print("\n=== RUWE HTML ROND DE ANKERS ===")
    for anker in ("Niet beschikbaar", "Gele kaarten", "Rode kaarten",
                  "Verwachte goals"):
        i = ruw.find(anker)
        if i < 0:
            print(f"\n--- '{anker}': niet in de ruwe HTML")
            continue
        print(f"\n--- '{anker}' op positie {i}:")
        print(ruw[max(0, i - 250): i + 2000])
    m = SPELER_HREF.search(ruw)
    if m:
        print(f"\n--- rond de eerste spelerslink (positie {m.start()}):")
        print(ruw[max(0, m.start() - 700): m.start() + 700])
    else:
        print("\n--- GEEN spelerslink in de ruwe HTML")


# -------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--alles", action="store_true", help="alle taken")
    p.add_argument("--clubs", action="store_true")
    p.add_argument("--spelers", action="store_true")
    p.add_argument("--afwezigen", action="store_true")
    p.add_argument("--prijzen", action="store_true",
                   help="de CVHJ-spelerslijst met prijzen")
    p.add_argument("--ronde", type=int, action="append", default=[])
    p.add_argument("--max-spelers", type=int)
    p.add_argument("--debug", metavar="URL",
                   help="een of meer URL's, gescheiden door komma's")
    a = p.parse_args()

    if a.debug:
        for url in [u.strip() for u in a.debug.split(",") if u.strip()]:
            debug(url)
            print("\n" + "#" * 70 + "\n")
        return
    if not (a.alles or a.clubs or a.spelers or a.afwezigen or a.prijzen):
        sys.exit("Geef --alles, of --clubs / --spelers / --afwezigen / "
                 "--prijzen / --debug URL")

    duels = None
    if a.alles or a.clubs:
        duels = taak_clubs(a.ronde or None)
    if a.alles or a.afwezigen:
        taak_afwezigen()
    if a.alles or a.prijzen:
        try:
            taak_prijzen()
        except Exception as e:
            print(f"! prijslijst niet op te halen: {type(e).__name__}: {e}")
    if a.alles or a.spelers:
        if duels is None:
            try:
                duels = parse_uitslagen(get(UITSLAGEN_URL))
            except Exception as e:
                print(f"! uitslagen niet op te halen: {e}")
        taak_spelers(a.max_spelers, duels)


if __name__ == "__main__":
    main()
