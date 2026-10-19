#!/usr/bin/env python3
"""
CVHJ-optimalisatiemodel  —  Coach van het Jaar 2026/27
======================================================

Zelfstandig model dat op deze bestanden draait:

  clubs.csv         per club per ronde: uitslag, ploegpunten, clean sheet, de
                    marktnoteringen (kans_winst / kans_gelijk / kans_verlies)
                    en de verwachte goals (xg_voor / xg_tegen)
  spelers.csv       per speler per ronde: minuten, basis, goals, assists,
                    geel, rood, reddingen, clean_sheet
  prijzen.csv       de CVHJ-spelerslijst: team, speler, positie, prijs
  afwezigen.csv     optioneel: wie er geblesseerd of geschorst is, met reden
  opstellingen.csv  optioneel: de vermoedelijke basiself met basiskans

Alles behalve prijzen.csv komt uit de scraper (pouletips). De prijslijst is de
CVHJ-lijst; exporteer die als CSV met de kolommen team, speler, positie, prijs.
De twee optionele bestanden mogen ontbreken; het model valt dan terug op wat
het uit de minuten kan afleiden, en zegt dat ook.

Gebruik
-------
    python cvhj_model.py --ronde 6                 # opstelling + transfers
    python cvhj_model.py --ronde 6 --transfers 1   # alleen de rondewissel
    python cvhj_model.py --ronde 6 --toon-pool 30  # top 30 van de hele markt

Pas SELECTIE, BUDGET, PROGRAMMA en INHAAL onderin aan; de rest is generiek.

Methode in het kort
-------------------
1. De verwachte goals per wedstrijd komen rechtstreeks uit de bron
   (xg_voor / xg_tegen). Staan ze er niet, dan worden ze uit de marktkansen
   teruggerekend met een Poisson-zoektocht.
2. Daaruit worden met ridge-regressie aanval- en verdedigingswaarden per club
   geschat, gekrompen naar een prior uit het vorige seizoen.
3. Per speler wordt de productie per 90 minuten geschat uit doelpunten,
   assists en kaarten, gekrompen naar een positieprior.
4. Verwachte CVHJ-punten = ploegpunten + clean sheet + individuele productie,
   gewogen met de kans op een basisplaats. Afwezigen vallen af.
5. Optimalisatie kiest de beste elf en de beste transfers binnen de spelregels.

Beperkingen die je moet kennen
------------------------------
- De officiele opstelling is niet te scrapen; die staat pas een uur voor de
  aftrap in de browser. Het model gebruikt de vermoedelijke opstelling met de
  basiskans van de bron. Loop de echte opstelling elke ronde zelf na.
- Productie per ronde komt uit het verschil tussen twee seizoensstanden. Valt
  er meer dan een ronde in dat venster, dan staat dat in de kolom 'venster'
  en is de toerekening aan een ronde niet exact.
- Het model optimaliseert een ronde vooruit, niet de hele periode.
- Het maximaliseert de verwachting, niet de kans op een hoge klassering. Bij
  duizenden deelnemers wint niet het hoogste gemiddelde maar de beste staart.
"""
from __future__ import annotations

import argparse
import collections
import csv
import functools
import itertools
import math
import re
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

FIXTURE_DEMPING = 0.5          # zie opmerking bij bouw_pool

GOALWAARDE = {"Goalkeeper": 12, "Defender": 10, "Midfielder": 8, "Forward": 6}
ASSISTWAARDE = {"Goalkeeper": 5, "Defender": 4, "Midfielder": 3, "Forward": 2}
GEEL = -3.0
ROOD = -8.0
CLEANSHEET = {"K": 5.0, "V": 3.0, "M": 0.0, "A": 0.0}
# priors in CVHJ-punten per 90 minuten, waar de individuele productie naartoe
# krimpt zolang er weinig speeltijd is
PRIOR_P90 = {"Goalkeeper": 0.30, "Defender": 0.85, "Midfielder": 1.25, "Forward": 1.75}
PRIOR_ASSIST_P90 = {"Goalkeeper": 0.05, "Defender": 0.32, "Midfielder": 0.45,
                    "Forward": 0.25}
PRIOR_KAART_P90 = {"Goalkeeper": -0.06, "Defender": -0.42, "Midfielder": -0.48,
                   "Forward": -0.30}
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


def norm_club(c: str) -> str:
    return "NEC" if c in ("N.E.C.", "N.E.C") else c


def norm(s: str) -> str:
    """Naar dezelfde vorm als de speler_id van de scraper: 'Gjivai Zechiel'
    en 'gjivai-zechiel' worden beide 'gjivai-zechiel'. Zo matcht de CVHJ-naam
    uit prijzen.csv op de speler_id uit spelers.csv.

    De tabel is nodig omdat o-slash, ae en a-ring geen ontbinding in NFKD
    hebben en er zonder deze stap stilletjes uit zouden vallen."""
    tr = str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "Æ": "Ae", "å": "a",
                        "Å": "A", "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th",
                        "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ß": "ss",
                        "ı": "i"})
    s = (s or "").translate(tr)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ------------------------------------------------------------- wedstrijdmodel
def uitkomstkansen(lam_v: float, lam_t: float, K: int = 10):
    """(winst, gelijk, clean sheet) uit twee Poisson-verwachtingen."""
    pv = [math.exp(-lam_v) * lam_v ** i / math.factorial(i) for i in range(K)]
    pt = [math.exp(-lam_t) * lam_t ** j / math.factorial(j) for j in range(K)]
    winst = sum(pv[i] * pt[j] for i in range(K) for j in range(K) if i > j)
    gelijk = sum(pv[i] * pt[i] for i in range(K))
    return winst, gelijk, math.exp(-lam_t)


@functools.lru_cache(maxsize=4096)
def lambdas_uit_kansen(p_winst: float, p_gelijk: float):
    """Zoek de (lambda_thuis, lambda_uit) die de marktkansen reproduceren.

    Grof naar fijn in plaats van één raster van 172x172. Dat laatste kostte
    bijna 30.000 Poisson-evaluaties per wedstrijd, en dit pad is géén
    uitzondering: de bron publiceert verwachte goals alleen voor de
    eerstvolgende ronde en haalt ze na de wedstrijd weg, dus voor de hele
    historie — waarop de clubratings worden gefit — wordt altijd
    teruggerekend. Gemeten: 0 van 162 gespeelde rijen had verwachte goals.

    De drie beste grove punten worden allemaal verfijnd, zodat een plaatselijk
    minimum niet voor het echte wordt aangezien. Het resultaat wordt gecached;
    veel wedstrijden hebben dezelfde kansendrieling.
    """
    def fout(lh, la):
        w, g, _ = uitkomstkansen(lh, la)
        return (w - p_winst) ** 2 + (g - p_gelijk) ** 2

    # grof: stap 0,2 over het hele bereik
    punten = [(fout(lh, la), lh, la)
              for lh in (0.2 + 0.2 * i for i in range(23))
              for la in (0.2 + 0.2 * j for j in range(23))]
    punten.sort()
    beste = punten[0]
    for _, lh0, la0 in punten[:3]:
        stap, lh, la = 0.2, lh0, la0
        for _ in range(3):                 # 0,05 -> 0,0125 -> 0,003125
            stap /= 4
            kandidaten = [(fout(max(0.05, lh + a * stap),
                                max(0.05, la + b * stap)),
                           max(0.05, lh + a * stap), max(0.05, la + b * stap))
                          for a in (-2, -1, 0, 1, 2)
                          for b in (-2, -1, 0, 1, 2)]
            kandidaten.sort()
            _, lh, la = kandidaten[0]
        if fout(lh, la) < beste[0]:
            beste = (fout(lh, la), lh, la)
    return beste[1], beste[2]


def _f(x):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


def schat_clubratings(clubrijen):
    """Ridge-regressie op log-schaal, gekrompen naar de prior van vorig seizoen.

    De verwachte goals komen bij voorkeur rechtstreeks uit de bron. Daarvoor
    werden ze teruggerekend uit de winstkansen met een raster van 170x170
    Poisson-evaluaties per wedstrijd: duur en per definitie een benadering,
    want twee verschillende lambdaparen kunnen dezelfde winstkans geven.
    """
    waarnemingen, gezien, uit_bron, gerekend = [], set(), 0, 0
    for r in clubrijen:
        sleutel = (r["ronde"], r["club"])
        if sleutel in gezien or r["thuis_uit"] != "thuis":
            continue
        xg_v, xg_t = _f(r.get("xg_voor")), _f(r.get("xg_tegen"))
        if xg_v and xg_t:
            lh, la = xg_v, xg_t
            uit_bron += 1
        elif r.get("kans_winst") and r.get("kans_gelijk"):
            lh, la = lambdas_uit_kansen(int(r["kans_winst"]) / 100,
                                        int(r["kans_gelijk"]) / 100)
            gerekend += 1
        else:
            continue
        gezien.add(sleutel)
        waarnemingen.append((norm_club(r["club"]), norm_club(r["tegenstander"]), lh, la))
    if waarnemingen:
        print(f"  verwachte goals: {uit_bron} uit de bron, "
              f"{gerekend} teruggerekend uit de kansen")

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
def bouw_pool(prijsrijen, spelerrijen, aanval, verdediging, thuisvoordeel,
              programma, inhaal, laatste_ronde, venster=6, min_minuten=60,
              afwezig=None, kans_basis=None):
    """Verwachte CVHJ-punten per speler voor de komende ronde.

    `afwezig` is een verzameling speler_id's die geblesseerd of geschorst zijn;
    die komen niet in de pool. `kans_basis` is {speler_id: percentage} uit de
    vermoedelijke opstelling van de bron, en gaat voor op de schatting uit de
    minuten.
    """
    afwezig = afwezig or set()
    kans_basis = kans_basis or {}
    recent = {str(r) for r in range(max(1, laatste_ronde - venster + 1), laatste_ronde + 1)}
    leeg = {"min": 0, "goals": 0, "assists": 0, "geel": 0, "rood": 0,
            "basis": 0, "duels": 0}
    vorm = collections.defaultdict(lambda: dict(leeg))

    def ihv(r, *namen):
        """Eerste kolom die bestaat en een getal bevat; anders 0."""
        for n in namen:
            g = _f(r.get(n))
            if g is not None:
                return int(g)
        return 0

    for r in spelerrijen:
        if str(r.get("ronde")) not in recent:
            continue
        if r.get("status") == "afwezig":        # oude bestandsvorm
            continue
        sid = norm(r.get("speler_id") or r.get("speler") or "")
        v = vorm[(sid, norm_club(r["club"]))]
        v["min"] += ihv(r, "minuten")
        v["goals"] += ihv(r, "goals")
        v["assists"] += ihv(r, "assists")
        v["geel"] += ihv(r, "geel")
        v["rood"] += ihv(r, "rood")
        # 'basis' is in de nieuwe bestandsvorm een aantal, in de oude een status
        if r.get("basis") not in (None, ""):
            v["basis"] += ihv(r, "basis")
        elif r.get("status") == "basis":
            v["basis"] += 1
        v["duels"] += max(1, ihv(r, "duels"))

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

    # Vormdata per club, voor het koppelen van de prijslijst aan de bron.
    per_club = collections.defaultdict(dict)
    for (sid_, club_), v_ in vorm.items():
        per_club[club_][sid_] = v_

    def koppel(sid, club):
        """(vormdata, hoe) voor een naam uit de prijslijst.

        De prijslijst en de bron schrijven namen niet altijd gelijk: de
        CVHJ-lijst heeft 'Yarek Gasiorowski', de bron 'Yarek Gąsiorowski
        Hernandis'. Daarom na de exacte match een voorvoegselmatch binnen
        DEZELFDE club, en alleen als die precies één kandidaat oplevert.
        Twee kandidaten betekent gokken, en dan liever niet koppelen.
        """
        binnen = per_club.get(club, {})
        if sid in binnen:
            return binnen[sid], "exact"
        kand = [k for k in binnen
                if k.startswith(sid + "-") or sid.startswith(k + "-")]
        if len(kand) == 1:
            return binnen[kand[0]], f"via {kand[0]}"
        return None, "geen"

    pool, geblokkeerd = [], []
    tel = collections.Counter()
    losse_koppels, niet_gekoppeld = [], []
    for r in prijsrijen:
        club, positie = norm_club(r["team"]), r["positie"]
        if club not in aanval or positie not in GOALWAARDE:
            continue
        # speler_id uit de prijslijst gaat voor op de naam. Komt die lijst uit
        # de bron, dan staat het id erin en is de koppeling exact; komt hij uit
        # de bevroren CVHJ-sheet, dan is er alleen een naam en blijft de
        # voorvoegselmatch hieronder nodig.
        sid = norm(r.get("speler_id") or "") or norm(r["speler"])
        if sid in afwezig:
            geblokkeerd.append(r["speler"])
            continue
        v, hoe = koppel(sid, club)
        tel[hoe.split()[0]] += 1
        if hoe.startswith("via"):
            losse_koppels.append(f"{r['speler']} -> {hoe[4:]}")
        elif hoe == "geen":
            niet_gekoppeld.append(f"{r['speler']} ({club})")
        if not v or v["min"] < min_minuten:   # uitgestelde duels drukken de teller
            continue
        n90 = v["min"] / 90
        pos = KORT[positie]

        # Aanvallende productie en discipline apart, want ze reageren anders op
        # de tegenstander. Doelpunten en assists lopen mee met de verwachte
        # goals van de ploeg; een gele kaart niet.
        aanval90 = (v["goals"] * GOALWAARDE[positie]
                    + v["assists"] * ASSISTWAARDE[positie]
                    + (PRIOR_P90[positie] + PRIOR_ASSIST_P90[positie]) * KRIMP_SPELER
                    ) / (n90 + KRIMP_SPELER)
        disc90 = (v["geel"] * GEEL + v["rood"] * ROOD
                  + PRIOR_KAART_P90[positie] * KRIMP_SPELER) / (n90 + KRIMP_SPELER)

        # Basiskans: het percentage van de bron gaat voor. Dat is hoe vaak de
        # speler dit seizoen begon, en dus beter dan wat uit de minuten in het
        # venster valt af te leiden — zeker bij uitgestelde duels.
        if sid in kans_basis:
            p_basis = min(0.97, max(0.03, kans_basis[sid] / 100))
        else:
            p_basis = min(0.97, 0.15 + 0.85 * v["basis"] / max(v["duels"], 1))

        def punten(fixtures, weging=1.0):
            paar = lam(club, fixtures)
            if paar is None:
                return 0.0
            lv, lt = paar
            winst, gelijk, cs = uitkomstkansen(lv, lt)
            e = p_basis * (3 * winst + gelijk)
            e += p_basis * cs * CLEANSHEET[pos]
            # De tegenstander doet voor individuele productie veel minder dan
            # voor ploegpunten en clean sheets; daarom de demping. Zonder haar
            # zette het model in augustus Ihattaren op de bank op grond van de
            # tegenstander, terwijl hij scoorde.
            e += p_basis * aanval90 * (lv / gem_lambda) ** FIXTURE_DEMPING
            e += p_basis * disc90
            if pos == "K":
                e += p_basis * 1.6 * lt / 5      # ruwe schatting reddingspunten
            return weging * e

        E = punten(programma)
        if club in inhaal:
            tegen, is_thuis = inhaal[club]
            E += punten([(club, tegen)] if is_thuis else [(tegen, club)], INHAAL_FACTOR)

        pool.append({"speler": r["speler"], "club": club, "pos": pos,
                     "prijs": float(r["prijs"]), "E": E, "p_basis": p_basis,
                     "min": v["min"], "goals": v["goals"],
                     "assists": v["assists"], "geel": v["geel"],
                     "rood": v["rood"], "basis": v["basis"], "duels": v["duels"]})
    if geblokkeerd:
        print(f"  afwezig, niet in de pool ({len(geblokkeerd)}): "
              f"{', '.join(geblokkeerd[:12])}"
              f"{' ...' if len(geblokkeerd) > 12 else ''}")

    # De koppeling tussen prijslijst en bron is de zwakste schakel: wie niet
    # koppelt kan het model niet kopen, hoe goed hij ook speelt. Daarom het
    # getal expliciet rapporteren in plaats van stil overslaan.
    totaal = sum(tel.values())
    if totaal:
        print(f"  prijslijst gekoppeld aan de bron: {tel['exact']} exact, "
              f"{tel['via']} op naamvariant, {tel['geen']} niet "
              f"({100 * (totaal - tel['geen']) // totaal}% van {totaal})")
    if losse_koppels:
        print(f"    naamvarianten: {'; '.join(losse_koppels[:8])}"
              f"{' ...' if len(losse_koppels) > 8 else ''}")
    if niet_gekoppeld:
        print(f"    niet gekoppeld ({len(niet_gekoppeld)}): "
              f"{', '.join(niet_gekoppeld[:10])}"
              f"{' ...' if len(niet_gekoppeld) > 10 else ''}")
        print("    Let op: dit zijn vertrokken spelers (onschadelijk) of "
              "aanwinsten zonder prijs in de CVHJ-lijst (die kun je dan niet "
              "kopen; vul hun prijs met de hand bij in prijzen.csv).")
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
def lees(pad, verplicht=True):
    p = Path(pad)
    if not p.exists():
        if verplicht:
            raise SystemExit(f"bestand ontbreekt: {pad}")
        return []
    with open(p, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def programma_uit_clubs(clubrijen, ronde):
    """[(thuisclub, uitclub)] voor een ronde, uit clubs.csv.

    Sinds de scraper het hele speelschema wegschrijft hoeft het programma niet
    meer met de hand in dit bestand te staan.
    """
    uit = []
    for r in clubrijen:
        if str(r.get("ronde")) == str(ronde) and r.get("thuis_uit") == "thuis":
            uit.append((norm_club(r["club"]), norm_club(r["tegenstander"])))
    return sorted(set(uit))


def seizoen_als_rijen(rijen, ronde):
    """De laatste momentopname uit spelers_seizoen.csv als één pseudo-ronde.

    Nodig omdat productie per ronde uit het verschil tussen twee standen komt:
    na de eerste scraperrun is er nog geen verschil, maar de seizoenstotalen
    zijn er wel. Over negen gespeelde ronden is dat zelfs een stabielere
    schatting dan een venster van zes.
    """
    if not rijen:
        return [], ""
    datum = max(r.get("opgehaald", "") for r in rijen)
    uit = []
    for r in rijen:
        if r.get("opgehaald") != datum:
            continue
        uit.append({"ronde": str(ronde), "speler_id": r.get("speler_id"),
                    "speler": r.get("speler"), "club": r.get("club", ""),
                    "positie": r.get("positie", ""),
                    "duels": r.get("duels"), "basis": r.get("basisplaatsen"),
                    "minuten": r.get("minuten"), "goals": r.get("goals"),
                    "assists": r.get("assists"), "geel": r.get("geel"),
                    "rood": r.get("rood"), "reddingen": r.get("reddingen"),
                    "clean_sheet": r.get("nul_achter")})
    return uit, datum


def rondes_aanwezig(rijen, laatste_ronde, venster):
    recent = {str(r) for r in
              range(max(1, laatste_ronde - venster + 1), laatste_ronde + 1)}
    return {str(r.get("ronde")) for r in rijen} & recent


def laatste_afwezigen(rijen):
    """{speler_id} uit de meest recente ophaaldatum in afwezigen.csv.

    Alleen de laatste momentopname telt: wie in september geblesseerd was mag
    in oktober niet meer uit de pool vallen.
    """
    if not rijen:
        return set(), ""
    datum = max(r.get("opgehaald", "") for r in rijen)
    weg = {"vertrokken", "blessure", "schorsing", "ziek"}
    return ({norm(r.get("speler_id") or r.get("speler", ""))
             for r in rijen
             if r.get("opgehaald") == datum and r.get("reden", "") in weg},
            datum)


def laatste_basiskansen(rijen):
    """{speler_id: percentage} uit de meest recente ophaaldatum."""
    if not rijen:
        return {}, ""
    datum = max(r.get("opgehaald", "") for r in rijen)
    uit = {}
    for r in rijen:
        if r.get("opgehaald") != datum:
            continue
        g = _f(r.get("kans_basis"))
        if g is not None:
            uit[norm(r.get("speler_id") or r.get("speler", ""))] = g
    return uit, datum


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
    p.add_argument("--afwezigen", default="afwezigen.csv")
    p.add_argument("--opstellingen", default="opstellingen.csv")
    p.add_argument("--ronde", type=int, required=True, help="komende speelronde")
    p.add_argument("--transfers", type=int, default=3, help="0 = alleen opstelling")
    p.add_argument("--toon-pool", type=int, default=0, help="top N van de hele markt")
    p.add_argument("--venster", type=int, default=6, help="hoeveel ronden vorm meetellen")
    p.add_argument("--min-minuten", type=int, default=60, help="drempel om in de pool te komen")
    p.add_argument("--seizoen", default="spelers_seizoen.csv",
                   help="seizoenstotalen, als terugval op spelers.csv")
    p.add_argument("--bron", choices=("auto", "ronden", "seizoen"),
                   default="auto", help="waaruit de vorm wordt bepaald")
    p.add_argument("--negeer-afwezigen", action="store_true",
                   help="afwezigen.csv niet gebruiken")
    a = p.parse_args()

    clubrijen, prijsrijen = lees(a.clubs), lees(a.prijzen)
    spelerrijen = lees(a.spelers, verplicht=False)

    # Productie per ronde komt uit het verschil tussen twee seizoensstanden.
    # Zolang er maar één stand is, zijn er geen ronderijen; dan rekenen we met
    # de seizoenstotalen in plaats van met een lege pool.
    beschikbaar = rondes_aanwezig(spelerrijen, a.ronde - 1, a.venster)
    gebruik_seizoen = (a.bron == "seizoen" or
                       (a.bron == "auto" and len(beschikbaar) < 2))
    if gebruik_seizoen:
        szrijen, szdatum = seizoen_als_rijen(lees(a.seizoen, verplicht=False),
                                             a.ronde - 1)
        if szrijen:
            spelerrijen = szrijen
            print(f"Vorm uit de seizoenstotalen van {szdatum} "
                  f"({len(szrijen)} spelers); "
                  f"{len(beschikbaar)} ronde(n) met losse data")
        elif not spelerrijen:
            raise SystemExit(f"geen spelersdata: {a.spelers} en {a.seizoen} "
                             f"zijn beide leeg of ontbreken")
    else:
        print(f"Vorm uit {len(beschikbaar)} ronden: "
              f"{', '.join(sorted(beschikbaar, key=int))}")
    aanval, verdediging, thuisvoordeel, n_obs = schat_clubratings(clubrijen)
    print(f"Clubratings uit {n_obs} wedstrijden met marktnotering "
          f"(thuisvoordeel x{math.exp(thuisvoordeel):.2f})")

    afwezig, afw_datum = set(), ""
    if not a.negeer_afwezigen:
        afwezig, afw_datum = laatste_afwezigen(lees(a.afwezigen, verplicht=False))
    kansen, ops_datum = laatste_basiskansen(lees(a.opstellingen, verplicht=False))
    if afwezig:
        print(f"  {len(afwezig)} afwezigen, stand van {afw_datum}")
    else:
        print("  geen afwezigenbestand: blessures zitten niet in het model")
    if kansen:
        print(f"  basiskansen voor {len(kansen)} spelers, stand van {ops_datum}")
    else:
        print("  geen opstellingenbestand: basiskans geschat uit de minuten")

    programma = programma_uit_clubs(clubrijen, a.ronde) or PROGRAMMA
    if len(programma) != 9:
        print(f"  let op: {len(programma)} wedstrijden in ronde {a.ronde}, "
              f"geen negen")
    print("  programma: " + ", ".join(f"{t}-{u}" for t, u in programma))

    pool = bouw_pool(prijsrijen, spelerrijen, aanval, verdediging, thuisvoordeel,
                     programma, INHAAL, laatste_ronde=a.ronde - 1,
                     venster=a.venster, min_minuten=a.min_minuten,
                     afwezig=afwezig, kans_basis=kansen)
    print(f"{len(pool)} spelers met voldoende speeltijd in de pool")

    op_naam = {norm(x["speler"]): x for x in pool}
    selectie, ontbreekt = [], []
    for naam, (club, pos, prijs) in SELECTIE.items():
        x = op_naam.get(norm(naam))
        if x and x["club"] == club:
            selectie.append(x)
        else:  # te weinig speeltijd, afwezig of niet in de pool: E = 0
            selectie.append({"speler": naam, "club": club, "pos": pos, "prijs": prijs,
                             "E": 0.0, "p_basis": 0.0, "min": 0, "goals": 0,
                             "assists": 0, "geel": 0, "rood": 0, "basis": 0,
                             "duels": 0})
            reden = "AFWEZIG" if norm(naam) in afwezig else "weinig speeltijd"
            ontbreekt.append(f"{naam} ({reden})")
    if ontbreekt:
        print(f"Op E=0 gezet: {', '.join(ontbreekt)}")

    basis, bank, totaal = opstelling(selectie)
    toon_selectie(basis, bank, totaal, sum(s["prijs"] for s in selectie))

    if a.toon_pool:
        print(f"\nTOP {a.toon_pool} VAN DE HELE MARKT")
        for x in sorted(pool, key=lambda x: -x["E"])[:a.toon_pool]:
            kaart = (f" {x['geel']}gl" if x["geel"] else "") + \
                    (f" {x['rood']}rd" if x["rood"] else "")
            print(f"  {x['speler']:26s}{x['club']:17s}{x['pos']}  EUR {x['prijs']:.2f}  "
                  f"E {x['E']:5.2f}  ({x['min']}' {x['goals']}g {x['assists']}a"
                  f"{kaart}, basis {x['p_basis'] * 100:.0f}%)")

    if a.transfers:
        print(f"\nBESTE {a.transfers} TRANSFER(S)")
        for score, uit, inn, nieuw in beste_transfers(selectie, pool, a.transfers):
            t = collections.Counter(s["pos"] for s in nieuw)
            print(f"\n  verwacht {score:.1f}  ({FORMATIES.get((t['V'], t['M'], t['A']), '?')})"
                  f"   winst {score - totaal:+.1f}")
            for s in uit:
                print(f"    UIT  {s['speler']:26s}{s['club']:17s}EUR {s['prijs']:.2f}  E {s['E']:5.2f}")
            for s in inn:
                print(f"    IN   {s['speler']:26s}{s['club']:17s}EUR {s['prijs']:.2f}  E {s['E']:5.2f}")


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
    "Guus Til": ("PSV", "M", 4.00),
    "Tyrone Owusu": ("Telstar", "M", 1.25),
    "Deveron Fonville": ("NEC", "V", 2.00),
    "Nijstad": ("FC Twente", "V", 2.00),
    "Sekou Sylla": ("ADO Den Haag", "V", 1.50),
    "Oscar Gloukh": ("Ajax", "M", 2.75),
    "Gjivai Zechiël": ("Feyenoord", "M", 2.00),
    "Marvin Young": ("Sparta", "V", 1.75),
    "Mohamed Ihattaren": ("Fortuna Sittard", "M", 2.00),
    "Mexx Meerdink": ("AZ", "A", 2.50),
    "Artem Stepanov": ("FC Utrecht", "A", 2.25),
    "Brynjólfur Willumsson": ("FC Groningen", "A", 1.75),
    "Jacob Trenskow": ("sc Heerenveen", "A", 2.25),
}
# =============================================================================

if __name__ == "__main__":
    main()
