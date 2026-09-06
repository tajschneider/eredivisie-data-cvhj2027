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
   waargenomen doelpunten, gekrompen naar een positieprior.
4. Verwachte CVHJ-punten = ploegpunten + clean sheet + individuele productie,
   gewogen met de kans op een basisplaats.
5. Optimalisatie kiest de beste elf en de beste transfers binnen de spelregels.

Beperkingen die je moet kennen
------------------------------
- Assists ontbreken: de bron levert ze niet. Aangevende spelers worden
  daardoor structureel onderschat.
- Kaarten worden niet meegewogen (geel is -3 in CVHJ).
- Het model optimaliseert één ronde vooruit, niet de hele periode.
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


def norm_club(c: str) -> str:
    return "NEC" if c in ("N.E.C.", "N.E.C") else c


def norm(s: str) -> str:
    tr = str.maketrans({"ø": "o", "æ": "ae", "å": "a", "ð": "d", "þ": "th", "ł": "l"})
    s = (s or "").translate(tr)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.split()).lower()


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
def bouw_pool(prijsrijen, spelerrijen, aanval, verdediging, thuisvoordeel,
              programma, inhaal, laatste_ronde, venster=6, min_minuten=60):
    """Verwachte CVHJ-punten per speler voor de komende ronde."""
    recent = {str(r) for r in range(max(1, laatste_ronde - venster + 1), laatste_ronde + 1)}
    vorm = collections.defaultdict(lambda: {"min": 0, "goals": 0, "basis": 0, "duels": 0})
    for r in spelerrijen:
        if r["ronde"] not in recent or r["status"] == "afwezig":
            continue
        v = vorm[(norm(r["speler"]), norm_club(r["club"]))]
        v["min"] += int(r["minuten"] or 0)
        v["goals"] += int(r["goals"] or 0)
        v["basis"] += 1 if r["status"] == "basis" else 0
        v["duels"] += 1

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
        v = vorm.get((norm(r["speler"]), club))
        if not v or v["min"] < min_minuten:   # uitgestelde duels drukken de teller
            continue
        n90 = v["min"] / 90
        ind90 = (v["goals"] * GOALWAARDE[positie] + PRIOR_P90[positie] * KRIMP_SPELER) / (n90 + KRIMP_SPELER)
        p_basis = min(0.97, 0.15 + 0.85 * v["basis"] / max(v["duels"], 1))
        pos = KORT[positie]

        def punten(fixtures, weging=1.0):
            paar = lam(club, fixtures)
            if paar is None:
                return 0.0
            lv, lt = paar
            winst, gelijk, cs = uitkomstkansen(lv, lt)
            e = p_basis * (3 * winst + gelijk)
            e += p_basis * cs * CLEANSHEET[pos]
            e += p_basis * ind90 * (lv / gem_lambda)
            if pos == "K":
                e += p_basis * 1.6 * lt / 5      # ruwe schatting reddingspunten
            return weging * e

        E = punten(programma)
        if club in inhaal:
            tegen, is_thuis = inhaal[club]
            E += punten([(club, tegen)] if is_thuis else [(tegen, club)], INHAAL_FACTOR)

        pool.append({"speler": r["speler"], "club": club, "pos": pos,
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

    pool = bouw_pool(prijsrijen, spelerrijen, aanval, verdediging, thuisvoordeel,
                     programma, inhaal, laatste_ronde=a.ronde - 1,
                     venster=a.venster, min_minuten=a.min_minuten)
    print(f"{len(pool)} spelers met voldoende speeltijd in de pool")

    op_naam = {norm(x["speler"]): x for x in pool}
    selectie, ontbreekt = [], []
    for naam, (club, pos, prijs) in selectie_in.items():
        x = op_naam.get(norm(naam))
        if x and x["club"] == club:
            selectie.append(x)
        else:  # te weinig speeltijd of niet in de pool: dood slot, E = 0
            selectie.append({"speler": naam, "club": club, "pos": pos, "prijs": prijs,
                             "E": 0.0, "min": 0, "goals": 0, "basis": 0, "duels": 0})
            ontbreekt.append(naam)
    if ontbreekt:
        print(f"Zonder recente speeltijd (E=0): {', '.join(ontbreekt)}")

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
