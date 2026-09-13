#!/usr/bin/env python3
"""
Probeert kandidaat-bronnen voor xG/assists/kaarten UIT DE OMGEVING WAAR HET DRAAIT.

WAAROM DIT BESTAAT
------------------
Twee keer op rij is een bron gekozen op basis van een test die ergens anders
draaide dan de uiteindelijke workflow:

  - FBref: leek te werken, gaf vanuit GitHub Actions een 403.
  - Sofascore: gaf hier een 200, gaf vanuit GitHub Actions een 403.

De conclusie die daaruit te trekken valt is niet "kies een betere site", maar
"de vraag is niet te beantwoorden zonder te meten op de plek waar het echt
moet draaien". Dat is wat dit script doet: het probeert een lijstje bronnen
en rapporteert per bron wat er gebeurt. Draai het als workflow, en de runner
vertelt je zelf welke bron bruikbaar is -- geen giswerk meer.

WAT HET RAPPORTEERT, PER BRON
-----------------------------
1. robots  -- staat robots.txt dit pad toe voor een generieke user-agent?
              Staat het niet toe, dan wordt er NIET opgehaald. Dit script
              omzeilt niets en negeert niets; een site die nee zegt, krijgt
              geen verzoek.
2. status  -- de HTTP-statuscode (200 = bruikbaar, 403 = geblokkeerd).
3. velden  -- welke van de gezochte veldnamen in het antwoord voorkomen.
              Een 200 zegt alleen dat je erbij kunt; dit zegt of er ook in
              staat wat het model nodig heeft.

Er wordt bewust NIETS gedaan om een blokkade te omzeilen: geen roterende
proxies, geen vervalste Referer-headers, geen "bypass"-diensten. Een 403 is
een antwoord, geen obstakel.

WAT HET MODEL NODIG HEEFT
-------------------------
In volgorde van belang. Pouletips levert al doelpunten en minuten, dus de
echte winst zit in de eerste twee:

    assists   -- ontbreekt volledig in de huidige data
    kaarten   -- ontbreekt volledig in de huidige data
    xG/xAG    -- minder ruizige schatter van productie; mooi meegenomen

Een bron die alleen assists en kaarten geeft is dus al waardevol; xG is de
kers. Dat staat in de kolom 'nut' hieronder.

Gebruik:
    python probeer_bronnen.py               # alle bronnen
    python probeer_bronnen.py --bron espn   # alleen bronnen met 'espn' in de naam
    python probeer_bronnen.py --dump map/   # antwoorden wegschrijven om te bekijken

Optionele sleutels (als env-variabele; zonder sleutel wordt de bron
overgeslagen in plaats van als "mislukt" gerapporteerd):
    API_FOOTBALL_KEY      api-sports.io, gratis laag van 100 verzoeken/dag
    FOOTBALL_DATA_TOKEN   football-data.org, gratis laag

Afhankelijkheden: pip install requests
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html;q=0.9",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

# De veldnamen waarop we het antwoord aftasten. Bewust ruim: verschillende
# bronnen noemen hetzelfde anders (expectedGoals / expected_goals / xG).
GEZOCHT = {
    "assists": ["assists", "assist", "goalAssists"],
    "kaarten": ["yellowCards", "yellow_cards", "yellowcards", "cards"],
    "xg": ["expectedGoals", "expected_goals", "xG", "xg_per90"],
    "minuten": ["minutesPlayed", "minutes_played", "minutes", "appearances"],
}

BRONNEN = [
    # --- keyless, spelerniveau ---
    {
        "naam": "espn-byathlete",
        "url": "https://site.web.api.espn.com/apis/common/v3/sports/soccer/ned.1/"
               "statistics/byathlete?limit=50&season=2026&seasontype=1",
        "toelichting": "ESPN's publieke JSON-API, spelerstatistieken Eredivisie. "
                       "Geen sleutel nodig. xG waarschijnlijk niet, assists/kaarten wel.",
    },
    {
        "naam": "espn-scoreboard",
        "url": "https://site.api.espn.com/apis/site/v2/sports/soccer/ned.1/scoreboard",
        "toelichting": "ANDER DOMEIN dan byathlete: site.api vs site.web.api. "
                       "Gaf 403 op de runner terwijl site.web.api 200 gaf -- daarom "
                       "blijft hij erin staan, als bewijs dat het per host verschilt.",
    },

    # --- ESPN-parametermatrix, op het domein dat op 13 september 2026 WEL 200 gaf.
    # De eerste poging gaf 200 met 309 tekens en geen velden. Dat kan twee dingen
    # betekenen: verkeerde parameters, of een antwoord in een andere vorm. Deze
    # varianten zoeken dat uit, en vat_samen() zet het antwoord in het log.
    # seizoenaanduiding: CVHJ 2026/27 kan bij ESPN zowel 2026 als 2027 heten;
    # seasontype 1 is doorgaans voorbereiding, 2 de reguliere competitie.
    {
        "naam": "espn-byathlete-s2026t2",
        "url": "https://site.web.api.espn.com/apis/common/v3/sports/soccer/ned.1/"
               "statistics/byathlete?limit=50&season=2026&seasontype=2",
        "toelichting": "Zelfde endpoint, seasontype=2 (reguliere competitie).",
    },
    {
        "naam": "espn-byathlete-s2027t1",
        "url": "https://site.web.api.espn.com/apis/common/v3/sports/soccer/ned.1/"
               "statistics/byathlete?limit=50&season=2027&seasontype=1",
        "toelichting": "Seizoen 2026/27 heet bij ESPN mogelijk 2027.",
    },
    {
        "naam": "espn-byathlete-kaal",
        "url": "https://site.web.api.espn.com/apis/common/v3/sports/soccer/ned.1/"
               "statistics/byathlete?limit=50",
        "toelichting": "Zonder seizoenparameters: laat ESPN zelf het huidige seizoen "
                       "kiezen. Als dit wel data geeft, lag het aan de parameters.",
    },
    {
        "naam": "espn-athletes",
        "url": "https://site.web.api.espn.com/apis/common/v3/sports/soccer/ned.1/athletes"
               "?limit=50",
        "toelichting": "Spelerslijst op hetzelfde (bereikbare) domein -- controleert of "
                       "ned.1 als competitiecode uberhaupt herkend wordt.",
    },
    {
        "naam": "espn-nl-statistiekpagina",
        "url": "https://www.espn.nl/voetbal/statistieken/_/competitie/NED.1/dutch-eredivisie",
        "toelichting": "De Nederlandse ESPN-site heeft een publieke statistiekpagina voor "
                       "de Eredivisie. Weer een ander domein (espn.nl), dus een eigen test.",
    },

    # --- pouletips: de site die al in de pijplijn zit en al weken bereikbaar is.
    # Hier zoeken kost niets extra's aan vertrouwen, en het zoeken elders heeft
    # in twee maanden niets opgeleverd. scrape_statistieken.py gebruikt nu vijf
    # ranglijsten die tot de top-40 reiken; deze pagina's kunnen dieper gaan.
    {
        "naam": "pouletips-spelers-index",
        "url": "https://pouletips.nl/eredivisie/spelers/",
        "toelichting": "Index 'statistieken per speler'. Als hier alle spelers in een "
                       "tabel staan, vervalt de top-40-grens van de ranglijsten.",
    },
    {
        "naam": "pouletips-cvhj-spelers",
        "url": "https://pouletips.nl/eredivisie/poule/coach-van-het-jaar/spelers/",
        "toelichting": "Alle spelerswaardes, behaalde en verwachte punten. Mogelijk "
                       "dezelfde bron als scrape_prijzen.py al gebruikt -- dat wil je weten.",
    },
    {
        "naam": "pouletips-cvhj-aanvallers",
        "url": "https://pouletips.nl/eredivisie/poule/coach-van-het-jaar/spelers/aanvallers/",
        "toelichting": "Per positie. Vier van deze pagina's dekken samen de hele markt, "
                       "zonder de top-40-afkapping van een ranglijst.",
    },
    {
        "naam": "pouletips-speler-detail",
        "url": "https://pouletips.nl/eredivisie/speler/tijs-velthuis/",
        "toelichting": "Per speler: goals en assists. De slug is DEZELFDE die al in "
                       "prijzen.csv staat, dus koppelen kost hier niets -- geen naam+club-"
                       "matching. Wel ~250 verzoeken per week; eerst kijken of de "
                       "indexpagina's hetzelfde bieden.",
    },
    {
        "naam": "sofascore",
        "url": "https://api.sofascore.com/api/v1/unique-tournament/37/season/96143/"
               "statistics?limit=5&order=-goals&accumulation=total"
               "&fields=goals,assists,expectedGoals,expectedAssists,yellowCards,minutesPlayed",
        "toelichting": "Bekend geval: werkt lokaal, gaf 403 vanaf GitHub Actions. "
                       "Staat erin als ijkpunt -- zo zie je meteen of dit rapport klopt.",
    },
    {
        "naam": "fbref",
        "url": "https://fbref.com/en/comps/23/stats/Eredivisie-Stats",
        "toelichting": "Tweede ijkpunt. Data is er sinds januari 2026 sowieso niet meer "
                       "(Opta-licentie weg), maar de bereikbaarheid is leerzaam.",
    },
    {
        "naam": "understat",
        "url": "https://understat.com/league/EPL",
        "toelichting": "Dekt de Eredivisie NIET (alleen de grote vijf). Alleen meegenomen "
                       "om te zien of de host bereikbaar is, mochten ze ooit uitbreiden.",
    },
    {
        "naam": "footystats",
        "url": "https://footystats.org/netherlands/eredivisie/xg",
        "toelichting": "Heeft Eredivisie-xG op een publieke pagina.",
    },
    {
        "naam": "whoscored",
        "url": "https://www.whoscored.com/Regions/155/Tournaments/13/Netherlands-Eredivisie",
        "toelichting": "Opta-gevoed, maar staat bekend om zware botdetectie.",
    },

    # --- met sleutel; overgeslagen als de env-variabele ontbreekt ---
    {
        "naam": "api-football",
        "url": "https://v3.football.api-sports.io/players?league=88&season=2026&page=1",
        "sleutel_env": "API_FOOTBALL_KEY",
        "sleutel_header": "x-apisports-key",
        "toelichting": "Gratis laag: 100 verzoeken/dag. league=88 is de Eredivisie. "
                       "Een sleutel-API hoort NIET op IP geblokkeerd te worden -- dat is "
                       "juist het punt: authenticatie in plaats van scrapen.",
    },
    {
        "naam": "football-data.org",
        "url": "https://api.football-data.org/v4/competitions/DED/scorers?limit=50",
        "sleutel_env": "FOOTBALL_DATA_TOKEN",
        "sleutel_header": "X-Auth-Token",
        "toelichting": "Gratis laag. Heeft assists bij de topscorers, geen xG.",
    },
]


def robots_toegestaan(url, cache={}):
    """(toegestaan, uitleg).

    Drie uitkomsten, bewust uit elkaar gehouden:
      - er is een robots.txt en die staat dit pad toe/niet toe;
      - er is er geen (404 e.d.): dan verbiedt niets;
      - we konden hem niet ophalen door een netwerkfout: dan weten we het NIET.
    Dat laatste geval als "toegestaan" rapporteren zou precies de fout zijn
    die dit project al twee keer heeft gemaakt -- iets melden dat niet
    gemeten is. Het wordt daarom apart gerapporteerd.
    """
    deel = urlparse(url)
    basis = f"{deel.scheme}://{deel.netloc}"
    if basis not in cache:
        try:
            r = requests.get(basis + "/robots.txt", headers=HEADERS, timeout=15,
                             allow_redirects=True)
            if r.status_code == 200:
                p = RobotFileParser()
                p.parse(r.text.splitlines())
                cache[basis] = p
            else:
                cache[basis] = "geen"        # geen leesbare robots.txt = niets verboden
        except requests.RequestException:
            cache[basis] = "onbereikbaar"
    p = cache[basis]
    if p == "geen":
        return True, "geen robots.txt"
    if p == "onbereikbaar":
        return True, "robots.txt niet op te halen"
    return p.can_fetch("*", url), "robots.txt"


def probeer(bron, dump=None):
    naam = bron["naam"]
    uitslag = {"naam": naam, "robots": "", "status": "", "velden": [], "opmerking": "",
               "vorm": ""}

    env = bron.get("sleutel_env")
    if env and not os.environ.get(env):
        uitslag["status"] = "overgeslagen"
        uitslag["opmerking"] = f"geen {env} ingesteld"
        return uitslag

    toegestaan, hoe = robots_toegestaan(bron["url"])
    uitslag["robots"] = ("?" if "niet op te halen" in hoe
                         else "ja" if toegestaan else "NEE")
    if not toegestaan:
        uitslag["status"] = "niet opgehaald"
        uitslag["opmerking"] = f"{hoe} verbiedt dit pad -- niet opgehaald"
        return uitslag

    headers = dict(HEADERS)
    if env:
        headers[bron["sleutel_header"]] = os.environ[env]

    try:
        r = requests.get(bron["url"], headers=headers, timeout=30)
    except requests.RequestException as e:
        uitslag["status"] = "fout"
        uitslag["opmerking"] = str(e)[:120]
        return uitslag

    uitslag["status"] = str(r.status_code)
    tekst = r.text or ""
    uitslag["opmerking"] = f"{len(tekst):,} tekens".replace(",", ".")

    if r.status_code == 200:
        for wat, varianten in GEZOCHT.items():
            if any(v in tekst for v in varianten):
                uitslag["velden"].append(wat)
        uitslag["vorm"] = vat_samen(tekst, r.headers.get("Content-Type", ""))
        if dump:
            Path(dump).mkdir(parents=True, exist_ok=True)
            pad = Path(dump) / f"{naam}.txt"
            pad.write_text(tekst[:2_000_000], encoding="utf-8")
            uitslag["opmerking"] += f"; -> {pad}"

    return uitslag


def vat_samen(tekst, content_type, max_tekens=240):
    """Wat zit er IN het antwoord? Kort genoeg voor een regel in het log.

    Dit ontbrak, en dat was precies het gat. Op 13 september 2026 gaf
    espn-byathlete HTTP 200 met 309 tekens en de conclusie "bereikbaar, velden
    niet gezien". Of dat een lege lijst was, een foutmelding over een onbekend
    seizoen, of gewoon andere veldnamen -- dat stond alleen in een bestand in
    de artifact, en de uitslagregel zei het niet. Een meting die je eerst moet
    downloaden om te kunnen lezen, lees je niet.

    JSON: de sleutels op het hoogste niveau, met het aantal elementen van
    lijsten erbij. HTML: de kopteksten van de eerste tabel en het aantal rijen.
    Iets anders, of niet te ontleden: de eerste tekens.
    """
    kort = " ".join(tekst[:max_tekens].split())
    if "json" in content_type.lower() or tekst.lstrip()[:1] in ("{", "["):
        try:
            d = json.loads(tekst)
        except ValueError:
            return f"geen geldige JSON: {kort}"
        if isinstance(d, list):
            return f"JSON-lijst met {len(d)} elementen"
        stukken = []
        for sleutel, waarde in list(d.items())[:8]:
            if isinstance(waarde, list):
                stukken.append(f"{sleutel}[{len(waarde)}]")
            elif isinstance(waarde, dict):
                stukken.append(f"{sleutel}{{{len(waarde)}}}")
            else:
                stukken.append(f"{sleutel}={str(waarde)[:30]}")
        # Een lege lijst waar de data hoort te staan is de meest voorkomende
        # stille misser: de URL klopt, de parameters niet.
        leeg = [s for s in stukken if s.endswith("[0]")]
        staart = "  <- LEEG, parameters kloppen waarschijnlijk niet" if leeg else ""
        return ", ".join(stukken) + staart

    if "<" in tekst[:200]:
        soup = BeautifulSoup(tekst, "html.parser")
        tabel = soup.find("table")
        if tabel is None:
            titel = soup.title.get_text(strip=True) if soup.title else "?"
            return f"HTML zonder <table>; titel: {titel[:60]}"
        koppen = [c.get_text(" ", strip=True) for c in tabel.find_all("th")][:8]
        rijen = len(tabel.find_all("tr")) - 1
        return f"tabel met {rijen} rij(en); koppen: {' | '.join(koppen) or '(geen th)'}"

    return kort


def oordeel(u):
    """Korte conclusie per bron, in termen van wat het model eraan heeft."""
    if u["status"] == "overgeslagen":
        return "-"
    if u["robots"] == "NEE":
        return "niet toegestaan"
    if u["status"] == "fout":
        return "onbereikbaar (netwerk)"
    if u["status"] != "200":
        return f"geblokkeerd ({u['status']})" if u["status"] in ("403", "429") else "geen data"
    kern = {"assists", "kaarten"} & set(u["velden"])
    if "xg" in u["velden"] and kern:
        return "VOLLEDIG"
    if kern:
        return "deels (geen xG)"
    return "bereikbaar, velden niet gezien"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bron", default=None, help="alleen bronnen met deze tekst in de naam")
    p.add_argument("--dump", default=None, help="map om de antwoorden in weg te schrijven")
    p.add_argument("--pauze", type=float, default=1.0, help="seconden tussen verzoeken")
    a = p.parse_args()

    bronnen = [b for b in BRONNEN if not a.bron or a.bron.lower() in b["naam"].lower()]
    if not bronnen:
        sys.exit(f"geen bron met {a.bron!r} in de naam")

    print(f"{len(bronnen)} bron(nen) proberen vanaf DEZE omgeving\n")
    uitslagen = []
    for i, b in enumerate(bronnen):
        u = probeer(b, a.dump)
        uitslagen.append(u)
        print(f"  {u['naam']:26s} robots {u['robots'] or '-':4s} status {u['status']:14s} "
              f"{', '.join(u['velden']) or '-':24s} {u['opmerking']}")
        if u.get("vorm"):
            print(f"       {u['vorm']}")
        if i < len(bronnen) - 1:
            time.sleep(a.pauze)

    print(f"\n{'bron':20s} {'oordeel':32s} toelichting")
    print("-" * 100)
    for u, b in zip(uitslagen, bronnen):
        print(f"{u['naam']:26s} {oordeel(u):32s} {b['toelichting'][:50]}")

    bruikbaar = [u["naam"] for u in uitslagen if oordeel(u) in ("VOLLEDIG", "deels (geen xG)")]
    onbereikbaar = sum(1 for u in uitslagen if u["status"] == "fout")
    geprobeerd = sum(1 for u in uitslagen if u["status"] != "overgeslagen")

    print()
    if bruikbaar:
        print(f"BRUIKBAAR VANAF DEZE OMGEVING: {', '.join(bruikbaar)}")
        print("Let op: dit geldt alleen voor de omgeving waarin dit nu draaide. "
              "Voor de automatisering telt uitsluitend de uitslag van bronnen.yml, "
              "want die draait op een GitHub-runner.")
    elif geprobeerd and onbereikbaar == geprobeerd:
        print("Geen enkele bron was bereikbaar -- ALLE verzoeken liepen stuk op het "
              "netwerk, niet op de sites zelf. Deze omgeving laat geen uitgaand "
              "verkeer toe; deze uitslag zegt dus niets over de bronnen. "
              "Draai bronnen.yml op GitHub Actions voor een echt antwoord.")
    else:
        print("Geen enkele bron leverde hier bruikbare velden op.")

    # Geen foutcode bij 'niets gevonden': dit script is een meting, geen test.
    # Een lege uitslag is een geldige uitkomst en mag een workflow niet rood maken.


if __name__ == "__main__":
    main()
