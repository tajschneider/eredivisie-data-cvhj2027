#!/usr/bin/env python3
"""
CVHJ-optimalisatiemodel  —  Coach van het Jaar 2026/27
======================================================

Zelfstandig model dat op drie bestanden draait:

  clubs.csv    per club per ronde: uitslag, ploegpunten, clean sheet en de
               marktnoteringen (kans_winst / kans_gelijk / kans_verlies)
  spelers.csv  per speler per ronde: status, minuten, goals
  prijzen.csv  de CVHJ-spelerslijst: team, speler, positie, prijs

De eerste twee komen uit de scraper (pouletips). De derde is de CVHJ-lijst;
exporteer die als CSV met de kolommen team, speler, positie, prijs.

Gebruik
-------
    python cvhj_model.py --ronde 6                 # opstelling + transfers
    python cvhj_model.py --ronde 6 --transfers 1   # alleen de rondewissel
    python cvhj_model.py --ronde 6 --toon-pool 30  # top 30 van de hele markt

Pas SELECTIE, BUDGET, PROGRAMMA en INHAAL onderin aan; de rest is generiek.

Methode in het kort
-------------------
1. Uit de marktnoteringen per wedstrijd wordt met een Poisson-model een
   (lambda_thuis, lambda_uit) teruggerekend.
2. Daaruit worden met ridge-regressie aanval- en verdedigingswaarden per club
   geschat, gekrompen naar een prior uit het vorige seizoen.
3. Per speler wordt de individuele productie per 90 minuten geschat uit de
   waargenomen doelpunten, gekrompen naar een positieprior -- recency-gewogen
   (ROL_DECAY, stap 1+2) zodat een recente rolwijziging (net basisspeler
   geworden, of juist verloren) sneller doorwerkt dan een vlak seizoens-
   gemiddelde zou doen. Optioneel aangevuld met seizoenscijfers (stap 5).
4. Verwachte CVHJ-punten = ploegpunten (kans dat hij meedoet) + clean sheet
   (kans op minstens CLEANSHEET_MINUTEN_DREMPEL minuten) + individuele
   productie (doelpunten/assists/kaarten, geschaald naar VERWACHTE speeltijd
   in plaats van alleen basisplaats-kans -- zie rol_kenmerken()).
5. Optimalisatie kiest de beste elf en de beste transfers binnen de spelregels.

Beperkingen die je moet kennen
------------------------------
- ROL_DECAY en CLEANSHEET_MINUTEN_DREMPEL (stap 1+2) zijn gevalideerd met
  backtest.py op een vroeg-seizoensdataset van maar 3 evalueerbare ronden --
  een reële, maar zwakke, verbetering (RMSE 3.27->3.25, rho 0.44->0.46) die
  met zoveel data nauwelijks gevoelig bleek voor de precieze ROL_DECAY-
  waarde. Draai backtest.py opnieuw zodra er meer ronden data zijn, en
  overweeg dan de waarde bij te stellen.
- CLEANSHEET_MINUTEN_DREMPEL=60 is een AANNAME (de gangbare conventie in
  de meeste fantasy-competities), niet bevestigd bij CVHJ zelf.
- Assists en kaarten kunnen worden meegewogen via spelerstats.csv
  (scrape_statistieken.py, stap 5) -- optioneel: zonder dat bestand draait dit
  script exact als voorheen. LET OP: dat bestand bevat GEEN expected goals,
  ondanks de historie van de kolomnamen; zie de docstring van
  scrape_statistieken.py. Er is ook geen backtestbron voor assists/kaarten
  (spelers.csv houdt ze niet bij), dus de nauwkeurigheid van dat deel is
  niet gemeten, alleen wiskundig gecontroleerd op het terugvalgedrag.
- Het model optimaliseert één ronde vooruit, niet de hele periode (zie
  multi_periode.py voor een meerdere-ronden-vooruit variant).
- Het maximaliseert de verwachting, niet de kans op een hoge klassering.
"""
from __future__ import annotations

import argparse
import collections
import csv
import itertools
import math
import sys
import unicodedata
from pathlib import Path

import numpy as np

# ----------------------------------------------------------------- instellingen
BUDGET = 32.0
GEM_DOELPUNTEN = 1.38          # competitiegemiddelde per ploeg per duel
KRIMP_CLUB = 1.0               # ridge-krimp clubratings naar de prior
KRIMP_SPELER = 8.0             # wedstrijden prior bij de individuele productie
BANK_FACTOR = 0.5              # een niet-ingevallen reserve scoort 50%
INHAAL_FACTOR = 0.85           # inhaalduel telt mee, maar met onzekerheid

# --------------------------------------------------- stap 1+2: rol en speeltijd
# ROL_DECAY: gewicht van een ronde geleden t.o.v. de meest recente ronde in het
# venster (per ronde terug in de tijd, dus 2 ronden terug weegt ROL_DECAY**2).
# Een vlak gemiddelde over `venster` ronden (het oude gedrag, ROL_DECAY=1.0)
# reageert traag op een rolwijziging: een speler die twee weken geleden net
# basisspeler werd, sleept dan nog 4 oude bankronden mee. Met een kleinere
# waarde wegen de laatste 1-2 ronden veel zwaarder, zodat zo'n wijziging
# vrijwel meteen doorwerkt -- zie bouw_pool()/rol_kenmerken() en de README.
ROL_DECAY = 0.65
# Aanname (niet geverifieerd bij CVHJ zelf, wel de gangbare conventie in bijna
# elke fantasy-competitie, waaronder de officiele Premier League-competitie):
# de clean-sheet-bonus telt alleen als de speler minstens dit aantal minuten
# heeft gespeeld. Pas aan als CVHJ een andere grens hanteert.
CLEANSHEET_MINUTEN_DREMPEL = 60

GOALWAARDE = {"Goalkeeper": 12, "Defender": 10, "Midfielder": 8, "Forward": 6}
CLEANSHEET = {"K": 5.0, "V": 3.0, "M": 0.0, "A": 0.0}
PRIOR_P90 = {"Goalkeeper": 0.30, "Defender": 0.85, "Midfielder": 1.25, "Forward": 1.75}
KORT = {"Goalkeeper": "K", "Defender": "V", "Midfielder": "M", "Forward": "A"}
# geldige selectiesamenstellingen (verdedigers, middenvelders, aanvallers);
# de bank telt 1 per linie, dus de samenstelling legt de formatie vast
FORMATIES = {(5, 4, 4): "4-3-3", (4, 5, 4): "3-4-3", (5, 5, 3): "4-4-2",
             (4, 6, 3): "3-5-2", (6, 4, 3): "5-3-2"}

# prior uit seizoen 25/26: doelpunten voor en tegen per duel
PRIOR_AANVAL = {
    "PSV": 2.15, "Ajax": 1.80, "Feyenoord": 1.85, "FC Twente": 1.55, "AZ": 1.70,
    "NEC": 1.45, "FC Utrecht": 1.45, "sc Heerenveen": 1.35, "FC Groningen": 1.25,
    "Go Ahead Eagles": 1.20, "Sparta Rotterdam": 1.20, "Fortuna Sittard": 1.15,
    "PEC Zwolle": 1.15, "Excelsior": 1.05, "Telstar": 1.00, "Willem II": 0.95,
    "ADO Den Haag": 0.95, "SC Cambuur": 0.90}
PRIOR_TEGEN = {
    "PSV": 1.10, "Ajax": 1.20, "Feyenoord": 1.20, "FC Twente": 1.15, "FC Utrecht": 1.25,
    "AZ": 1.20, "NEC": 1.45, "sc Heerenveen": 1.45, "FC Groningen": 1.50,
    "Sparta Rotterdam": 1.45, "Go Ahead Eagles": 1.55, "Fortuna Sittard": 1.60,
    "PEC Zwolle": 1.65, "Excelsior": 1.75, "Telstar": 1.75, "Willem II": 1.85,
    "ADO Den Haag": 1.85, "SC Cambuur": 1.95}

# ---------------------------------------------- stap 5: assists en kaarten
# Assists en kaarten ontbreken in de pouletips-prijzenlijst; een seizoenstempo
# is bovendien een minder ruizige schatter van doelpuntenproductie dan de ruwe
# telling uit een venster van een paar duels. Alle drie komen uit
# spelerstats.csv (scrape_statistieken.py). Ontbreekt dat bestand, of staat een
# speler er niet in, dan telt dit blok voor 0 mee -- zie de commentaren in
# bouw_pool() voor de precieze terugvalgarantie.
ASSISTWAARDE = {"Goalkeeper": 5, "Defender": 4, "Midfielder": 3, "Forward": 2}
KAART_GEEL_PUNTEN = -3.0
KAART_ROOD_PUNTEN = -8.0
XG_GEWICHT = 0.5        # hoeveel een seizoens-90-tal weegt t.o.v. een lokaal 90-tal
KRIMP_ASSIST = 8.0      # prior-gewicht (in 90-tallen) bij de assistschatting
KRIMP_KAART = 20.0      # kaarten zijn zeldzaam; sterker krimpen dan assists

# Impliciete doelpunten-per-90-prior achter PRIOR_P90 (dat staat al in punten).
PRIOR_GOAL_RATE = {pos: PRIOR_P90[pos] / GOALWAARDE[pos] for pos in PRIOR_P90}
PRIOR_ASSIST_RATE = {"Goalkeeper": 0.01, "Defender": 0.08, "Midfielder": 0.20, "Forward": 0.15}
# kaartpriors op de korte positiecode (K/V/M/A): verdedigers en middenvelders
# maken de meeste overtredingen, keepers vrijwel nooit.
PRIOR_GEEL_RATE = {"K": 0.05, "V": 0.22, "M": 0.20, "A": 0.12}
PRIOR_ROOD_RATE = {"K": 0.005, "V": 0.015, "M": 0.012, "A": 0.008}


def norm_club(c: str) -> str:
    return "NEC" if c in ("N.E.C.", "N.E.C") else c


def norm(s: str) -> str:
    tr = str.maketrans({"ø": "o", "æ": "ae", "å": "a", "ð": "d", "þ": "th", "ł": "l"})
    s = (s or "").translate(tr)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.split()).lower()


def vind_bijna_match(naam, club, pool):
    """Vangnet voor een naam die niet EXACT matcht met de pool, maar er wel
    duidelijk hetzelfde-speler-uitziet: zelfde club, en de genormaliseerde
    naam-woorden van de een zijn een deelverzameling van de ander (bv.
    'gjivai zechiel' zit in 'gjivai zechiel basis').

    Waarom dit nodig is: prijzen.csv's naamkolom hoort schoon te zijn --
    scrape_prijzen.py's splits_status() strript statuswoorden als 'basis'/
    'bank'/'nieuw' uit de brontekst. Maar die stripping is een regex tegen
    een website die Claude niet live kan controleren; een ongeziene
    schrijfwijze (andere hoofdletter, extra woord, ander scheidingsteken)
    kan een keer door de mazen glippen. Zonder dit vangnet krijgt zo'n
    speler dan een 'dood slot' (E=0, want geen match in selectie.csv) EN
    verschijnt hij ALS APARTE MARKTSPELER in de pool (met zijn echte E) --
    en dat levert precies een zinloos "verkoop X, koop X"-advies op, zoals
    Thomas meldde met Gjivai Zechiël op 6 september 2026 (prijzen.csv bevatte
    kennelijk 'Gjivai Zechiel basis' i.p.v. 'Gjivai Zechiel').

    Dit repareert het symptoom (de speler telt weer gewoon als 'in bezit'
    mee, met zijn echte E in plaats van 0), maar is bewust een vangnet en
    geen vervanging voor het schoonhouden van de brondata -- de aanroeper
    hoort dit luid te melden zodat de onderliggende scraper-bug alsnog
    wordt opgemerkt en gefixt, niet stilzwijgend weg te laten vallen.

    Retourneert het pool-item van de dichtstbijzijnde niet-exacte match, of
    None als er geen (eenduidige) kandidaat is.
    """
    woorden = set(norm(naam).split())
    if not woorden:
        return None
    kandidaten = []
    for p in pool:
        if p["club"] != club:
            continue
        pw = set(norm(p["speler"]).split())
        if pw == woorden:
            continue  # exacte match: hoort al gewoon gematcht te zijn, geen "bijna"
        if woorden <= pw or pw <= woorden:
            kandidaten.append(p)
    # Bij meer dan 1 kandidaat is het niet meer eenduidig welke de bedoelde
    # speler is (bv. twee bankspelers met een deels overlappende naam) --
    # dan liever terugvallen op het oude dode-slot-gedrag dan gokken.
    return kandidaten[0] if len(kandidaten) == 1 else None


def koppel_speler(naam, club, pool):
    """DE manier waarop een speler uit selectie.csv aan de pool gekoppeld wordt.

    Retourneert (pool-item of None, of het een bijna-match was).

    Waarom dit een eigen functie is, en niet vier keer los: deze koppeling
    gebeurde op vier plekken -- cvhj_model.main(), multi_periode's
    koppel_selectie(), de brute-force-tak in test_multi_periode.py, en het
    --vergelijk-blok van multi_periode.py. Toen vind_bijna_match() werd
    toegevoegd, kreeg maar de helft daarvan die stap. Gevolg: bij een
    vervuilde naam in prijzen.csv koppelde de MILP-tak de speler wél en de
    brute-force-tak niet, kwamen ze op verschillende scores uit, en sloeg
    test_multi_periode.py terecht alarm (17 september 2026, live).

    De test had gelijk: twee zoekers die dezelfde vraag anders beantwoorden
    IS een fout. Alleen zat de fout niet in de zoekers maar in de koppeling
    ervoor. Eén implementatie kan niet meer uit elkaar lopen.
    """
    sleutel = norm(naam)
    exact = next((p for p in pool
                  if norm(p["speler"]) == sleutel and p["club"] == club), None)
    if exact:
        return exact, False
    bijna = vind_bijna_match(naam, club, pool)
    return (bijna, True) if bijna else (None, False)


# ------------------------------------------------------------- wedstrijdmodel
def uitkomstkansen(lam_v: float, lam_t: float, K: int = 10):
    """(winst, gelijk, clean sheet) uit twee Poisson-verwachtingen."""
    pv = [math.exp(-lam_v) * lam_v ** i / math.factorial(i) for i in range(K)]
    pt = [math.exp(-lam_t) * lam_t ** j / math.factorial(j) for j in range(K)]
    winst = sum(pv[i] * pt[j] for i in range(K) for j in range(K) if i > j)
    gelijk = sum(pv[i] * pt[i] for i in range(K))
    return winst, gelijk, math.exp(-lam_t)


# Het raster van kandidaat-lambdas is bij elke aanroep hetzelfde; alleen het
# doelwit verschuift. Eenmalig voorrekenen scheelt een factor ~1300 en levert
# exact dezelfde argmin als de oorspronkelijke dubbele lus.
_GRID = np.array([x / 40 for x in range(8, 180)])
_K = np.arange(10)
_FACT = np.array([math.factorial(k) for k in range(10)], dtype=float)
_PMF = np.exp(-_GRID)[:, None] * (_GRID[:, None] ** _K[None, :]) / _FACT[None, :]
_WIN = _PMF @ (_K[:, None] > _K[None, :]).astype(float) @ _PMF.T
_GELIJK = np.einsum("ai,bi->ab", _PMF, _PMF)


def lambdas_uit_kansen(p_winst: float, p_gelijk: float):
    """Zoek de (lambda_thuis, lambda_uit) die de marktkansen reproduceren."""
    fout = (_WIN - p_winst) ** 2 + (_GELIJK - p_gelijk) ** 2
    lh, la = divmod(int(np.argmin(fout)), len(_GRID))
    return float(_GRID[lh]), float(_GRID[la])


def schat_clubratings(clubrijen):
    """Ridge-regressie op log-schaal, gekrompen naar de prior van vorig seizoen."""
    waarnemingen, gezien = [], set()
    for r in clubrijen:
        sleutel = (r["ronde"], r["club"])
        if sleutel in gezien or r["thuis_uit"] != "thuis" or not r.get("kans_winst"):
            continue
        gezien.add(sleutel)
        lh, la = lambdas_uit_kansen(int(r["kans_winst"]) / 100, int(r["kans_gelijk"]) / 100)
        waarnemingen.append((norm_club(r["club"]), norm_club(r["tegenstander"]), lh, la))

    clubs = sorted({c for h, a, _, _ in waarnemingen for c in (h, a)})
    ix = {c: i for i, c in enumerate(clubs)}
    n = len(clubs)
    A, y = [], []
    for h, a, lh, la in waarnemingen:
        rij = [0.0] * (2 * n + 1); rij[ix[h]] = 1; rij[n + ix[a]] = -1; rij[-1] = 1
        A.append(rij); y.append(math.log(lh / GEM_DOELPUNTEN))
        rij = [0.0] * (2 * n + 1); rij[ix[a]] = 1; rij[n + ix[h]] = -1
        A.append(rij); y.append(math.log(la / GEM_DOELPUNTEN))
    A, y = np.array(A), np.array(y)

    mu = np.array(
        [math.log(PRIOR_AANVAL.get(c, 1.2) / GEM_DOELPUNTEN) for c in clubs]
        + [math.log(GEM_DOELPUNTEN / PRIOR_TEGEN.get(c, 1.5)) for c in clubs]
        + [math.log(1.14)])
    P = np.eye(2 * n + 1) * KRIMP_CLUB
    P[-1, -1] = 4.0
    sol = np.linalg.solve(A.T @ A + P, A.T @ y + P @ mu)
    aanval = {c: sol[ix[c]] for c in clubs}
    verdediging = {c: sol[n + ix[c]] for c in clubs}
    return aanval, verdediging, sol[-1], len(waarnemingen)


# ------------------------------------------------------------------ spelerspool
def rol_kenmerken(rijen, decay):
    """Recency-gewogen rol-/speeltijdkenmerken uit een lijst
    (ronde_offset, minuten, goals, status) -- offset 0 is de meest recente
    ronde in het venster. Vervangt het oude vlakke gemiddelde (stap 1+2):

    - p_speelt: kans dat de speler AAN het spel komt (elke minuut telt).
      Stuurt de ploegpunten -- die krijg je zodra je meedoet.
    - p_60plus: kans dat hij minstens CLEANSHEET_MINUTEN_DREMPEL minuten
      speelt. Stuurt de clean-sheet-bonus, die (aanname, zie de constante)
      aan die drempel gebonden is -- een invaller van 20 minuten telt voor
      de ploegpunten mee, maar niet voor de clean sheet.
    - speelfractie: verwacht aandeel van de wedstrijd dat hij speelt
      (gewogen minuten / 90). Zet een per-90-productieschatting (doelpunten,
      assists, kaarten) om in een verwachting VOOR DEZE WEDSTRIJD -- een
      speler die vaak na 60 minuten wordt gewisseld, moet minder productie
      toegerekend krijgen dan iemand die altijd de volle wedstrijd speelt,
      ook al starten ze allebei even vaak.
    - n90/goals: gewogen minuten/90 en gewogen doelpunten, voor dezelfde
      krimpformule als voorheen (ind90) maar dan recency-gewogen in plaats
      van een plat seizoensgemiddelde.

    Retourneert None als `rijen` leeg is (kan niet voorkomen via bouw_pool()'s
    eigen aanroep, want die filtert al op v["min"] >= min_minuten, maar wel
    verdedigd voor los hergebruik/tests).
    """
    totaal_gewicht = gew_minuten = gew_goals = 0.0
    gew_speelt = gew_60plus = gew_basis = 0.0
    for offset, minuten, goals, status in rijen:
        g = decay ** offset
        totaal_gewicht += g
        gew_minuten += g * minuten
        gew_goals += g * goals
        if minuten > 0:
            gew_speelt += g
        if minuten >= CLEANSHEET_MINUTEN_DREMPEL:
            gew_60plus += g
        if status == "basis":
            gew_basis += g
    if totaal_gewicht == 0:
        return None
    return {
        "n90": gew_minuten / 90,
        "goals": gew_goals,
        "p_speelt": gew_speelt / totaal_gewicht,
        "p_60plus": gew_60plus / totaal_gewicht,
        "speelfractie": min(0.97, gew_minuten / (90 * totaal_gewicht)),
        "p_basis": min(0.97, 0.15 + 0.85 * gew_basis / totaal_gewicht),
    }


def bouw_pool(prijsrijen, spelerrijen, aanval, verdediging, thuisvoordeel,
              programma, inhaal, laatste_ronde, venster=6, min_minuten=60, fbref=None):
    """Verwachte CVHJ-punten per speler voor de komende ronde.

    `fbref` is het resultaat van lees_spelerstats(), of None. Achterwaartse
    compatibiliteit is hier bewust getoetst, niet aangenomen:
    - fbref=None (bestand ontbreekt): de doelpuntenschatting is WISKUNDIG
      IDENTIEK aan de oude formule (de fbref-term krijgt gewicht 0, dus valt
      volledig weg uit de breuk), en assists/kaarten dragen exact 0.0 bij.
      Dit is precies het gedrag van vóór stap 5.
    - fbref is geladen maar een speler staat er niet in (transfer, te weinig
      minuten bij FBref, naam/club niet gematcht): dezelfde 0-bijdrage voor
      die ene speler, alsof fbref voor hem afwezig was.
    - fbref is geladen EN de speler is gematcht: de doelpuntenschatting wordt
      een gewogen drieweg-menging (lokaal venster, FBref-seizoen, prior) in
      plaats van de oude tweeweg-menging (lokaal, prior); assists en kaarten
      krijgen een eigen tweeweg-menging (FBref, prior).
    """
    recent = {str(r) for r in range(max(1, laatste_ronde - venster + 1), laatste_ronde + 1)}
    vorm = collections.defaultdict(lambda: {"min": 0, "goals": 0, "basis": 0, "duels": 0, "rijen": []})
    for r in spelerrijen:
        if r["ronde"] not in recent or r["status"] == "afwezig":
            continue
        v = vorm[r.get("speler_id") or norm(r["speler"])]
        minuten, goals = int(r["minuten"] or 0), int(r["goals"] or 0)
        v["min"] += minuten
        v["goals"] += goals
        v["basis"] += 1 if r["status"] == "basis" else 0
        v["duels"] += 1
        # offset 0 = meest recente ronde in het venster, groter = ouder --
        # invoer voor rol_kenmerken()'s recency-weging (stap 1+2).
        v["rijen"].append((laatste_ronde - int(r["ronde"]), minuten, goals, r["status"]))

    gem_lambda = sum(GEM_DOELPUNTEN * math.exp(a) for a in aanval.values()) / len(aanval)

    def lam(club, fixtures):
        for thuis, uit in fixtures:
            if club == thuis:
                return (GEM_DOELPUNTEN * math.exp(aanval[thuis] - verdediging[uit] + thuisvoordeel),
                        GEM_DOELPUNTEN * math.exp(aanval[uit] - verdediging[thuis]))
            if club == uit:
                return (GEM_DOELPUNTEN * math.exp(aanval[uit] - verdediging[thuis]),
                        GEM_DOELPUNTEN * math.exp(aanval[thuis] - verdediging[uit] + thuisvoordeel))
        return None

    pool = []
    for r in prijsrijen:
        club, positie = norm_club(r["team"]), r["positie"]
        if club not in aanval or positie not in GOALWAARDE:
            continue
        # Joinen op de slug, niet op de naam: die is stabiel over accenten
        # ('Soren Tengstedt') en immuun voor spelling die per pagina verschilt.
        v = vorm.get(r.get("speler_id") or norm(r["speler"]))
        if r.get("blessure"):
            # Pouletips markeert de speler als geblesseerd. Hem in de pool laten
            # betekent dat de zoeker hem kan KOPEN; dat wil je nooit.
            continue
        if not v or v["min"] < min_minuten:   # uitgestelde duels drukken de teller
            continue
        rol = rol_kenmerken(v["rijen"], ROL_DECAY)
        n90 = rol["n90"]           # recency-gewogen i.p.v. het vlakke seizoenstotaal
        p_speelt = rol["p_speelt"]
        p_60plus = rol["p_60plus"]
        speelfractie = rol["speelfractie"]

        # fbref-entry opzoeken (of niets: telt dan overal voor 0 mee, zie de
        # docstring hierboven). sleutel exact zoals lees_spelerstats() hem opbouwt.
        fb = fbref.get(f"{norm(r['speler'])}|{norm(club)}") if fbref is not None else None
        fb_n90 = fb["minuten_90s"] if fb else 0.0

        # 1. doelpunten: drieweg-menging lokaal venster (nu recency-gewogen) /
        #    fbref-xG / prior. fb_n90=0 (fbref ontbreekt of speler niet
        #    gematcht) elimineert de fbref-term volledig uit teller EN noemer.
        fb_gewicht = fb_n90 * XG_GEWICHT
        fb_doel_punten = (fb["xg_per90"] * GOALWAARDE[positie]) if fb else 0.0
        ind90 = (rol["goals"] * GOALWAARDE[positie]
                 + fb_gewicht * fb_doel_punten
                 + PRIOR_P90[positie] * KRIMP_SPELER) / (n90 + fb_gewicht + KRIMP_SPELER)

        pos = KORT[positie]

        # 2. assists: fbref (gemiddelde van assists/90 en xAG/90, ter demping
        #    van ruis) gekrompen naar een positieprior. Zonder fbref-bestand
        #    (fbref is None) is dit exact 0.0 -- de "poort" uit de docstring.
        e_assist90 = 0.0
        if fbref is not None:
            assist_obs = ((fb["assists_per90"] + fb["xag_per90"]) / 2) if fb else 0.0
            e_assist90 = ((fb_n90 * assist_obs + KRIMP_ASSIST * PRIOR_ASSIST_RATE[positie])
                          * ASSISTWAARDE[positie] / (fb_n90 + KRIMP_ASSIST))

        # 3. kaarten: fbref-totalen omgerekend naar per-90, gekrompen naar een
        #    positieprior (korte code). Ook hier: geen fbref-bestand -> 0.0.
        e_kaart90 = 0.0
        if fbref is not None:
            geel_obs = (fb["gele_kaarten"] / fb_n90) if fb and fb_n90 > 0 else 0.0
            rood_obs = (fb["rode_kaarten"] / fb_n90) if fb and fb_n90 > 0 else 0.0
            geel90 = (fb_n90 * geel_obs + KRIMP_KAART * PRIOR_GEEL_RATE[pos]) / (fb_n90 + KRIMP_KAART)
            rood90 = (fb_n90 * rood_obs + KRIMP_KAART * PRIOR_ROOD_RATE[pos]) / (fb_n90 + KRIMP_KAART)
            e_kaart90 = geel90 * KAART_GEEL_PUNTEN + rood90 * KAART_ROOD_PUNTEN

        def punten(fixtures, weging=1.0):
            paar = lam(club, fixtures)
            if paar is None:
                return 0.0
            lv, lt = paar
            winst, gelijk, cs = uitkomstkansen(lv, lt)
            # p_speelt/p_60plus/speelfractie i.p.v. één vlakke p_basis (stap 1+2):
            # ploegpunten en kaartrisico horen bij "komt aan het spel", een
            # clean sheet (aanname: CLEANSHEET_MINUTEN_DREMPEL) bij "speelt
            # lang genoeg", en per-90-schattingen (doelpunten/assists) horen
            # geschaald te worden naar VERWACHTE speelminuten, niet naar
            # basisplaats-kans alleen -- zie rol_kenmerken().
            e = p_speelt * (3 * winst + gelijk)
            e += p_60plus * cs * CLEANSHEET[pos]
            e += speelfractie * ind90 * (lv / gem_lambda)
            e += speelfractie * e_assist90 * (lv / gem_lambda)   # assists volgen de aanval, net als doelpunten
            e += speelfractie * e_kaart90                        # kaartrisico schaalt met speelminuten
            if pos == "K":
                e += speelfractie * 1.6 * lt / 5     # ruwe schatting reddingspunten
            return weging * e

        E = punten(programma)
        if club in inhaal:
            tegen, is_thuis = inhaal[club]
            E += punten([(club, tegen)] if is_thuis else [(tegen, club)], INHAAL_FACTOR)

        pool.append({"speler": r["speler"], "speler_id": r.get("speler_id") or norm(r["speler"]),
                     "club": club, "pos": pos,
                     "prijs": float(r["prijs"]), "E": E,
                     "min": v["min"], "goals": v["goals"], "basis": v["basis"],
                     "duels": v["duels"]})
    return pool


# ---------------------------------------------------------------- optimalisatie
def opstelling(selectie):
    """Beste elf: per linie gaat de zwakste naar de bank en telt voor 50%."""
    basis, bank, totaal = [], [], 0.0
    for pos in "KVMA":
        lijn = sorted([s for s in selectie if s["pos"] == pos], key=lambda s: -s["E"])
        if not lijn:
            continue
        basis += lijn[:-1]
        bank.append(lijn[-1])
        totaal += sum(s["E"] for s in lijn[:-1]) + BANK_FACTOR * lijn[-1]["E"]
    return basis, bank, totaal


def samenstelling_geldig(selectie):
    t = collections.Counter(s["pos"] for s in selectie)
    return t["K"] == 2 and (t["V"], t["M"], t["A"]) in FORMATIES


def beste_transfers(selectie, pool, aantal, budget=BUDGET, top=5, per_slot=2):
    """Verkoop `aantal` spelers en koop er evenveel terug, binnen de spelregels."""
    kandidaten = [p for p in pool if norm(p["speler"]) not in {norm(s["speler"]) for s in selectie}]
    resultaten = []
    for uit in itertools.combinations(range(len(selectie)), aantal):
        rest = [selectie[i] for i in range(len(selectie)) if i not in uit]
        bezet = {s["club"] for s in rest}
        ruimte = budget - sum(s["prijs"] for s in rest)
        groepen = collections.defaultdict(list)
        for k in kandidaten:
            if k["club"] not in bezet and k["prijs"] <= ruimte:
                groepen[(k["club"], k["pos"])].append(k)
        kort = []
        for v in groepen.values():
            kort += sorted(v, key=lambda x: -x["E"])[:per_slot]
        for combo in itertools.combinations(kort, aantal):
            if len({c["club"] for c in combo}) < aantal:
                continue
            if sum(c["prijs"] for c in combo) > ruimte + 1e-9:
                continue
            nieuw = rest + list(combo)
            if not samenstelling_geldig(nieuw):
                continue
            _, _, score = opstelling(nieuw)
            resultaten.append((score, [selectie[i] for i in uit], list(combo), nieuw))
    resultaten.sort(key=lambda x: -x[0])
    uniek, gezien = [], set()
    for r in resultaten:
        sleutel = tuple(sorted(s["speler"] for s in r[1]))
        if sleutel in gezien:
            continue
        gezien.add(sleutel)
        uniek.append(r)
        if len(uniek) >= top:
            break
    return uniek


# ------------------------------------------------------------------------ i/o
def lees(pad):
    with open(pad, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def lees_programma(pad):
    """programma.csv -> (PROGRAMMA, INHAAL).

    PROGRAMMA is [(thuis, uit)] voor de komende ronde; INHAAL is
    {club: (tegenstander, is_thuis)} voor uitgestelde duels in dezelfde periode.
    Zonder bestand valt het model terug op de blokken onderin dit script.
    """
    if not Path(pad).exists():
        return None, None
    programma, inhaal = [], {}
    for r in lees(pad):
        thuis, uit = norm_club(r["thuis"]), norm_club(r["uit"])
        soort = r.get("soort", "regulier")
        if soort == "regulier":
            programma.append((thuis, uit))
        elif soort == "inhaal":
            inhaal[thuis] = (uit, True)
            inhaal[uit] = (thuis, False)
        # "inhaal_later" wordt bewust genegeerd: dat duel valt na de deadline
        # van deze ronde en hoort bij de volgende beslissing. Meetellen zou de
        # betrokken spelers een dubbele wedstrijd toedichten die ze deze ronde
        # niet spelen.
    return programma, inhaal


def lees_perioden(pad):
    """perioden.csv -> [(periode, start_ronde)], oplopend.

    CVHJ deelt het seizoen in 8 perioden van 4 of 5 ronden. Voorafgaand aan
    elke periode mag je 3 transfers doen in plaats van 1. Die grenzen staan
    vast in de spelregels, dus ze horen in een bestand en niet in een schatting.
    """
    if not Path(pad).exists():
        return []
    uit = []
    for r in lees(pad):
        uit.append((int(r["periode"]), int(r["start_ronde"])))
    return sorted(uit, key=lambda x: x[1])


def periodestand(ronde, perioden):
    """(periode_nr, is_start, ronden_tot_volgende_start) voor deze ronde."""
    if not perioden:
        return None, False, None
    huidig = None
    for nr, start in perioden:
        if start <= ronde:
            huidig = nr
    is_start = any(start == ronde for _, start in perioden)
    volgende = [start for _, start in perioden if start > ronde]
    tot = (min(volgende) - ronde) if volgende else None
    return huidig, is_start, tot


def lees_selectie(pad):
    """selectie.csv (speler, club, positie, prijs) -> {naam: (club, pos, prijs)}.

    `positie` mag Engels of de korte vorm K/V/M/A zijn. Dit bestand is de
    toestand van je ploeg: na een doorgevoerde transfer wordt het bijgewerkt,
    zodat de volgende ronde zonder handwerk start.
    """
    if not Path(pad).exists():
        return None
    selectie = {}
    for r in lees(pad):
        pos = r["positie"].strip()
        pos = KORT.get(pos, pos)
        if pos not in ("K", "V", "M", "A"):
            raise SystemExit(f"onbekende positie {r['positie']!r} voor {r['speler']}")
        selectie[r["speler"]] = (norm_club(r["club"]), pos, float(r["prijs"]))
    if len(selectie) != 15:
        raise SystemExit(f"{pad}: {len(selectie)} spelers, verwacht 15")
    return selectie


def stats_pad(pad, standaard="spelerstats.csv", terugval=("xg.csv", "fbref.csv")):
    """Het te gebruiken statistiekenbestand: `pad`, of een oudere naam ervan.

    Het bestand is drie keer van bron gewisseld en twee keer van naam, en het
    FORMAAT is al die tijd identiek gebleven. De naamgeschiedenis, nieuw naar
    oud: spelerstats.csv (pouletips) <- xg.csv (Sofascore) <- fbref.csv
    (FBref). Een repo waar nog een van de oude namen in staat blijft dus gewoon
    werken -- die data is alleen niet meer actueel.

    De laatste naam is bewust NIET meer naar de inhoud vernoemd als "xG": daar
    zit geen expected-goals-model achter (zie scrape_statistieken.py). Een
    bestandsnaam die je met documentatie moet corrigeren, is een verkeerde naam.
    """
    if Path(pad).exists():
        return pad
    if pad == standaard:
        for oud in terugval:
            if Path(oud).exists():
                return oud
    return pad


def lees_spelerstats(pad):
    """spelerstats.csv (scrape_statistieken.py) -> {norm(speler)|norm(club): {...}}, of None.

    None betekent "bestand ontbreekt" en is het signaal voor bouw_pool() om de
    hele stap-5-bijdrage over te slaan (0.0), niet alleen de prior te gebruiken
    -- zie de docstring van bouw_pool(). De sleutel wordt hier met cvhj_model.py's
    EIGEN norm() opgebouwd uit de losse speler/club-kolommen, niet met de
    interne speler_key van de bron: die twee normaliseren verschillend (spaties vs. streepjes)
    en zouden nooit matchen.
    """
    if not Path(pad).exists():
        return None
    uit = {}
    for r in lees(pad):
        club = norm_club(r["club"])
        sleutel = f"{norm(r['speler'])}|{norm(club)}"
        uit[sleutel] = {
            "minuten_90s": float(r["minuten_90s"] or 0),
            "goals_per90": float(r["goals_per90"] or 0),
            "xg_per90": float(r["xg_per90"] or 0),
            "assists_per90": float(r["assists_per90"] or 0),
            "xag_per90": float(r["xag_per90"] or 0),
            "gele_kaarten": float(r["gele_kaarten"] or 0),
            "rode_kaarten": float(r["rode_kaarten"] or 0),
        }
    return uit


def toon_selectie(basis, bank, totaal, kosten):
    t = collections.Counter(s["pos"] for s in basis + bank)
    formatie = FORMATIES.get((t["V"], t["M"], t["A"]), "?")
    print(f"\nOPSTELLING  {formatie}   verwacht {totaal:.1f} punten   kosten EUR {kosten:.2f}")
    for pos, naam in (("K", "Keeper"), ("V", "Verdediging"), ("M", "Middenveld"), ("A", "Aanval")):
        rij = [s for s in basis if s["pos"] == pos]
        for s in sorted(rij, key=lambda s: -s["E"]):
            print(f"  {naam:12s} {s['speler']:26s}{s['club']:17s}EUR {s['prijs']:.2f}  E {s['E']:5.2f}")
    print("  ---- bank (50%) ----")
    for s in sorted(bank, key=lambda s: -s["E"]):
        print(f"  {s['pos']:12s} {s['speler']:26s}{s['club']:17s}EUR {s['prijs']:.2f}  E {s['E']:5.2f}")


def main():
    p = argparse.ArgumentParser(description="CVHJ-optimalisatie")
    p.add_argument("--clubs", default="clubs.csv")
    p.add_argument("--spelers", default="spelers.csv")
    p.add_argument("--prijzen", default="prijzen.csv")
    p.add_argument("--ronde", type=int, required=True, help="komende speelronde")
    p.add_argument("--transfers", default="3",
                   help="aantal transfers, of 'auto' (3 bij een periodestart, anders 1)")
    p.add_argument("--perioden", default="perioden.csv",
                   help="periodegrenzen; leeg bestand = geen periodelogica")
    p.add_argument("--toon-pool", type=int, default=0, help="top N van de hele markt")
    p.add_argument("--venster", type=int, default=6, help="hoeveel ronden vorm meetellen")
    p.add_argument("--min-minuten", type=int, default=60, help="drempel om in de pool te komen")
    p.add_argument("--programma", default="programma.csv",
                   help="programma van de komende ronde (scrape_programma.py)")
    p.add_argument("--selectie", default="selectie.csv",
                   help="huidige vijftien; valt terug op het blok onderin")
    # --xg en --fbref blijven als alias werken: het bestand heette eerder zo.
    # Het BESTANDSFORMAAT is nooit veranderd, alleen de naam -- stats_pad()
    # vindt een oude xg.csv of fbref.csv vanzelf nog.
    p.add_argument("--stats", "--xg", "--fbref", dest="xg", default="spelerstats.csv",
                   help="assists/kaarten van scrape_statistieken.py; ontbreekt het, dan "
                        "draait dit script zoals vóór stap 5")
    p.add_argument("--json", metavar="BESTAND",
                   help="besluit machineleesbaar wegschrijven")
    a = p.parse_args()

    programma, inhaal = lees_programma(a.programma)
    if programma is None:
        programma, inhaal = PROGRAMMA, INHAAL
        print(f"LET OP: {a.programma} niet gevonden - het hardgecodeerde "
              f"PROGRAMMA onderin wordt gebruikt.")
    selectie_in = lees_selectie(a.selectie)
    if selectie_in is None:
        selectie_in = SELECTIE
        print(f"LET OP: {a.selectie} niet gevonden - de hardgecodeerde "
              f"SELECTIE onderin wordt gebruikt.")
    if len(programma) != 9:
        print(f"LET OP: {len(programma)} wedstrijden in het programma, verwacht 9.")

    perioden = lees_perioden(a.perioden)
    periode, is_start, tot_volgende = periodestand(a.ronde, perioden)
    if str(a.transfers).lower() == "auto":
        if not perioden:
            sys.exit(f"--transfers auto vraagt om {a.perioden}, maar die is er niet.")
        a.transfers = 3 if is_start else 1
        print(f"--transfers auto -> {a.transfers}")
    else:
        a.transfers = int(a.transfers)

    if periode:
        if is_start:
            print(f"\n*** RONDE {a.ronde} START PERIODE {periode}: 3 TRANSFERS TOEGESTAAN ***")
            if a.transfers != 3:
                print(f"    (je draait nu met {a.transfers}; met --transfers 3 benut je ze)")
        elif tot_volgende == 1:
            print(f"\nLET OP: volgende ronde start een nieuwe periode met 3 transfers. "
                  f"Een transfer nu bewaren kan lonen.")
        elif tot_volgende:
            print(f"Periode {periode}; volgende periodestart over {tot_volgende} ronden.")

    clubrijen, spelerrijen, prijsrijen = lees(a.clubs), lees(a.spelers), lees(a.prijzen)
    aanval, verdediging, thuisvoordeel, n_obs = schat_clubratings(clubrijen)
    print(f"Clubratings uit {n_obs} wedstrijden met marktnotering "
          f"(thuisvoordeel x{math.exp(thuisvoordeel):.2f})")

    pad_xg = stats_pad(a.xg)
    fbref = lees_spelerstats(pad_xg)
    if fbref is None:
        print(f"LET OP: {pad_xg} niet gevonden - doelpunten/assists/kaarten "
              f"draaien zonder assists/kaarten (zoals vóór stap 5). Draai scrape_statistieken.py.")

    pool = bouw_pool(prijsrijen, spelerrijen, aanval, verdediging, thuisvoordeel,
                     programma, inhaal, laatste_ronde=a.ronde - 1,
                     venster=a.venster, min_minuten=a.min_minuten, fbref=fbref)
    print(f"{len(pool)} spelers met voldoende speeltijd in de pool")
    if fbref is not None:
        pool_sleutels = {f"{norm(x['speler'])}|{norm(x['club'])}" for x in pool}
        n_match = len(pool_sleutels & fbref.keys())
        print(f"  spelerstats gekoppeld: {n_match}/{len(pool)} spelers uit de pool "
              f"({pad_xg} bevat {len(fbref)} spelers)")

    geblesseerd = {norm(r["speler"]): r.get("blessure", "")
                   for r in prijsrijen if r.get("blessure")}
    selectie, ontbreekt, bijna_match = [], [], []
    for naam, (club, pos, prijs) in selectie_in.items():
        x, was_bijna = koppel_speler(naam, club, pool)
        if x:
            selectie.append(x)
            if was_bijna:   # vermoedelijk dezelfde speler, vervuilde naam in prijzen.csv
                bijna_match.append((naam, x["speler"]))
        else:  # te weinig speeltijd of niet in de pool: dood slot, E = 0
            selectie.append({"speler": naam, "club": club, "pos": pos, "prijs": prijs,
                             "E": 0.0, "min": 0, "goals": 0, "basis": 0, "duels": 0})
            ontbreekt.append(naam)
    if bijna_match:
        print("LET OP MOGELIJKE NAAM-BUG IN prijzen.csv (automatisch gerepareerd, "
              "maar controleer de brondata):")
        for naam, gevonden in bijna_match:
            print(f"    '{naam}' (jouw selectie) <-> '{gevonden}' (marktdata, zelfde club)")
    if ontbreekt:
        print(f"Zonder recente speeltijd (E=0): {', '.join(ontbreekt)}")
    eigen_bless = [(n, geblesseerd[norm(n)]) for n in selectie_in if norm(n) in geblesseerd]
    if eigen_bless:
        print("\nGEBLESSEERD IN JE SELECTIE:")
        for naam, duur in eigen_bless:
            print(f"    {naam} ({duur})")

    basis, bank, totaal = opstelling(selectie)
    toon_selectie(basis, bank, totaal, sum(s["prijs"] for s in selectie))

    if a.toon_pool:
        print(f"\nTOP {a.toon_pool} VAN DE HELE MARKT")
        for x in sorted(pool, key=lambda x: -x["E"])[:a.toon_pool]:
            print(f"  {x['speler']:26s}{x['club']:17s}{x['pos']}  EUR {x['prijs']:.2f}  "
                  f"E {x['E']:5.2f}  ({x['min']}' {x['goals']}g basis {x['basis']}/{x['duels']})")

    opties = []
    if a.transfers:
        print(f"\nBESTE {a.transfers} TRANSFER(S)")
        for score, uit, inn, nieuw_sel in beste_transfers(selectie, pool, a.transfers):
            t = collections.Counter(x["pos"] for x in nieuw_sel)
            print(f"\n  verwacht {score:.1f}  ({FORMATIES.get((t['V'], t['M'], t['A']), '?')})"
                  f"   winst {score - totaal:+.1f}")
            for x in uit:
                print(f"    UIT  {x['speler']:26s}{x['club']:17s}EUR {x['prijs']:.2f}  E {x['E']:5.2f}")
            for x in inn:
                print(f"    IN   {x['speler']:26s}{x['club']:17s}EUR {x['prijs']:.2f}  E {x['E']:5.2f}")
            opties.append({
                "verwacht": round(score, 2),
                "winst": round(score - totaal, 2),
                "formatie": FORMATIES.get((t["V"], t["M"], t["A"]), "?"),
                "uit": [{"speler": x["speler"], "club": x["club"], "pos": x["pos"],
                         "prijs": x["prijs"], "E": round(x["E"], 3)} for x in uit],
                "in": [{"speler": x["speler"], "club": x["club"], "pos": x["pos"],
                        "prijs": x["prijs"], "E": round(x["E"], 3)} for x in inn],
                "selectie": [{"speler": x["speler"], "club": x["club"], "pos": x["pos"],
                              "prijs": x["prijs"]} for x in nieuw_sel]})

    if a.json:
        besluit = {
            "ronde": a.ronde,
            "gegenereerd": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "transfers_toegestaan": a.transfers,
            "periode": periode,
            "periodestart": is_start,
            "ronden_tot_volgende_periode": tot_volgende,
            "huidig": {
                "verwacht": round(totaal, 2),
                "kosten": round(sum(x["prijs"] for x in selectie), 2),
                "basis": [{"speler": x["speler"], "club": x["club"], "pos": x["pos"],
                           "E": round(x["E"], 3)} for x in basis],
                "bank": [{"speler": x["speler"], "club": x["club"], "pos": x["pos"],
                          "E": round(x["E"], 3)} for x in bank]},
            "zonder_speeltijd": ontbreekt,
            "bijna_match": [{"selectie": naam, "marktdata": gevonden} for naam, gevonden in bijna_match],
            "geblesseerd_in_selectie": [{"speler": n, "duur": d} for n, d in eigen_bless],
            "programma": [{"thuis": h, "uit": u} for h, u in programma],
            "inhaal": sorted(inhaal),
            "pool_grootte": len(pool),
            "opties": opties,
            "advies": opties[0] if opties else None}
        Path(a.json).write_text(
            __import__("json").dumps(besluit, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nbesluit -> {a.json}")


# ==================== WEKELIJKS AANPASSEN ====================================
# Programma van de komende ronde: (thuisclub, uitclub)
PROGRAMMA = [
    ("FC Twente", "ADO Den Haag"), ("Go Ahead Eagles", "FC Groningen"),
    ("Fortuna Sittard", "Ajax"), ("SC Cambuur", "NEC"),
    ("Excelsior", "FC Utrecht"), ("sc Heerenveen", "Telstar"),
    ("PSV", "Sparta Rotterdam"), ("PEC Zwolle", "Feyenoord"),
    ("AZ", "Willem II"),
]
# Inhaalwedstrijden in dezelfde periode: club -> (tegenstander, thuis?)
INHAAL = {
    "Ajax": ("Willem II", True), "Willem II": ("Ajax", False),
}
# Huidige selectie: naam -> (club, positie, prijs)
SELECTIE = {
    "Kjetil Haug": ("Go Ahead Eagles", "K", 1.50),
    "Stijn van Gassel": ("Excelsior", "K", 1.75),
    "Ryan Flamingo": ("PSV", "V", 3.00),
    "Jeff Hardeveld": ("Telstar", "V", 2.00),
    "Deveron Fonville": ("NEC", "V", 2.00),
    "Aske Adelgaard": ("FC Twente", "V", 1.50),
    "Sekou Sylla": ("ADO Den Haag", "V", 1.50),
    "Oscar Gloukh": ("Ajax", "M", 2.75),
    "Gjivai Zechiël": ("Feyenoord", "M", 2.00),
    "Shunsuke Mito": ("Sparta Rotterdam", "M", 2.00),
    "Mohamed Ihattaren": ("Fortuna Sittard", "M", 2.00),
    "Mexx Meerdink": ("AZ", "A", 2.50),
    "David Min": ("FC Utrecht", "A", 1.75),
    "Brynjólfur Willumsson": ("FC Groningen", "A", 1.75),
    "Jacob Trenskow": ("sc Heerenveen", "A", 2.25),
}
# =============================================================================

if __name__ == "__main__":
    main()
