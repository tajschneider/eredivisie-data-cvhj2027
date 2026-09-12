#!/usr/bin/env python3
"""
Transferadvies over meerdere ronden vooruit, in plaats van alleen de eerst-
volgende -- stap 4 uit het optimalisatieplan.

Waarom dit een probleem is voor de bestaande zoeker: `beste_transfers` in
cvhj_model.py optimaliseert precies EEN ronde. Een speler met een zware
tegenstander deze week maar een makkelijke serie daarna wordt daardoor te laag
gewaardeerd, en andersom. Dit script telt de verwachte punten van de komende
`--horizon` ronden mee, met een aftakelende weging (`--decay`, standaard 0,84
per ronde verder weg) zodat een verre ronde meetelt maar niet even zwaar als
de eerstvolgende.

Wat er WEL en NIET verandert ten opzichte van cvhj_model.py:
- De clubratings en spelersproductie komen uit dezelfde `schat_clubratings` en
  `bouw_pool` als het bestaande model -- alleen het PROGRAMMA per toekomstige
  ronde verschilt, en dat komt uit dezelfde programma.csv (met --horizon
  gescrapet, zie scrape_programma.py).
- Voor toekomstige ronden zijn geen marktkansen nodig: bouw_pool gebruikt per
  wedstrijd alleen de twee clubs (via de clubratings), geen kans_thuis/
  kans_gelijk/kans_uit. Een ronde ver vooruit, zonder kansen vooraf, is dus
  even bruikbaar als de eerstvolgende.
- De bank-korting (zwakste per linie telt 50%) wordt toegepast op de
  SOM van de afgetakelde punten per speler, niet per ronde apart. Dat is een
  bewuste vereenvoudiging: wie er per toekomstige ronde op de bank zou moeten,
  simuleren zou het aantal variabelen met een factor `horizon` vermenigvuldigen
  voor weinig extra scherpte -- de daadwerkelijke opstelling per ronde blijft
  toch elke week een losse beslissing (cvhj_model.py's advies voor DIE ronde
  gebruikt gewoon zijn eigen E, ongewijzigd).
- Inhaalduels worden alleen voor de eerstvolgende ronde meegeteld, zoals in
  cvhj_model.py. Een inhaalduel drie ronden verderop zou dubbel tellen met de
  reguliere wedstrijd van die ronde, dus wordt dat risico hier vermeden door
  het simpelweg te laten liggen (kleine onderschatting op die ene ronde).

Oplosser: scipy.optimize.milp (HiGHS als backend -- geen extra installatie
nodig, scipy is al aanwezig). Het model kiest de spelersset EN de bankplek
per linie tegelijk als een lineair 0/1-probleem; zie de code voor de precieze
formulering. Dat vervangt de brute-force-opsomming uit cvhj_model.py, die voor
meerdere ronden tegelijk niet meer zou passen (elke extra ronde vermenigvuldigt
de kandidatenlijst die combinatorisch doorzocht moet worden).

Gebruik:
    python multi_periode.py --ronde 6 --transfers 1 --horizon 4
    python multi_periode.py --ronde 6 --transfers 1 --horizon 4 --vergelijk

--vergelijk draait ook cvhj_model.py's brute-force zoeker op ronde 0 alleen,
zodat je ziet OF en WAAROM het multi-ronde-advies afwijkt.

Validatie (zie test_multi_periode.py): met --horizon 1 moet dit script exact
dezelfde beste spelersgroep en score vinden als cvhj_model.py's brute-force
zoeker, voor hetzelfde aantal transfers -- de MILP is dan een ander
algoritme voor precies dezelfde vraag, dus het antwoord moet identiek zijn.
"""
import argparse
import collections
import importlib.util
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

HIER = Path(__file__).parent


def laad_model():
    spec = importlib.util.spec_from_file_location("cvhj_model", HIER / "cvhj_model.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def lees_programma_per_ronde(pad, m):
    """programma.csv -> {ronde: ([(thuis, uit)], {club: (tegenstander, is_thuis)})}.

    Net als cvhj_model.lees_programma, maar dan voor ALLE ronden die in het
    bestand staan in plaats van alleen de rijen zonder 'ronde'-filter -- nodig
    omdat --horizon meerdere ronden in hetzelfde bestand zet.
    """
    if not Path(pad).exists():
        return {}
    per_ronde = collections.defaultdict(lambda: ([], {}))
    for r in m.lees(pad):
        ronde = int(r["ronde"])
        thuis, uit = m.norm_club(r["thuis"]), m.norm_club(r["uit"])
        soort = r.get("soort", "regulier")
        programma, inhaal = per_ronde[ronde]
        if soort == "regulier":
            programma.append((thuis, uit))
        elif soort == "inhaal":
            inhaal[thuis] = (uit, True)
            inhaal[uit] = (thuis, False)
    return dict(per_ronde)


def bouw_horizon_pools(m, prijsrijen, spelerrijen, aanval, verdediging, thuisvoordeel,
                       per_ronde, start_ronde, horizon, venster, min_minuten, fbref=None):
    """Eén bouw_pool-aanroep per ronde in de horizon; retourneert
    {speler_id: [E_0, E_1, ...]} en de metadata-pool (van ronde 0, voor
    prijs/club/pos -- die veranderen niet binnen de horizon).

    `fbref` (m.lees_spelerstats()'s resultaat, of None) wordt ONGEWIJZIGD per ronde
    doorgegeven aan bouw_pool -- dezelfde xG/assist/kaart-schatting geldt voor
    elke ronde in de horizon, er is geen ronde-specifieke fbref-data."""
    reeksen = collections.defaultdict(list)
    metadata = None
    rondes_gebruikt = []
    for k in range(horizon):
        ronde = start_ronde + k
        if ronde not in per_ronde:
            break  # geen programma meer bekend -- horizon stopt hier
        programma, inhaal = per_ronde[ronde]
        if not programma:
            break
        inhaal_k = inhaal if k == 0 else {}  # zie module-docstring
        pool = m.bouw_pool(prijsrijen, spelerrijen, aanval, verdediging, thuisvoordeel,
                           programma, inhaal_k, laatste_ronde=start_ronde - 1,
                           venster=venster, min_minuten=min_minuten, fbref=fbref)
        if metadata is None:
            metadata = {p["speler_id"]: p for p in pool}
        for p in pool:
            reeksen[p["speler_id"]].append(p["E"])
        rondes_gebruikt.append(ronde)
    return reeksen, metadata or {}, rondes_gebruikt


def bereken_multi_E(reeksen, decay):
    """E_multi[speler_id] = som over k van decay**k * E_k."""
    return {sid: sum((decay ** k) * e for k, e in enumerate(waarden))
            for sid, waarden in reeksen.items()}


def som_horizon(reeksen, decay, spelers):
    """Gedecayde som over de horizon voor een gegeven groep spelers (dood slot
    of niet in de horizon-pool telt als 0, net als bereken_multi_E)."""
    return sum(sum((decay ** k) * e for k, e in enumerate(reeksen.get(s["speler_id"], [])))
              for s in spelers)


def koppel_selectie(m, selectie_in, kandidaten, extra_waarde=None):
    """Matcht selectie_in (uit lees_selectie) tegen de kandidatenlijst op naam+club.

    Voor een speler die niet exact matcht, wordt eerst m.vind_bijna_match()
    geprobeerd (zelfde club, naam-woorden een deelverzameling van elkaar --
    het vangnet voor een vervuilde naam in prijzen.csv, zie de docstring
    daar). Matcht ook dat niet (te weinig speeltijd, geblesseerd, of echt
    niet gevonden -- net als in cvhj_model.py's main()), dan wordt een dood
    slot toegevoegd aan `kandidaten` (in-place), met E=0. Als `extra_waarde`
    is meegegeven (bv. e_multi), krijgt dat dode slot daar ook een waarde
    0.0, in-place.

    Retourneert de speler_id's van de huidige 15, en (als tweede waarde) een
    lijst (selectienaam, gevonden marktnaam) voor elke bijna-match, zodat de
    aanroeper dit kan melden.
    """
    selectie_ids, bijna_match = set(), []
    for naam, (club, pos, prijs) in selectie_in.items():
        sid = m.norm(naam)
        match, was_bijna = m.koppel_speler(naam, club, kandidaten)
        if match:
            if was_bijna:
                bijna_match.append((naam, match["speler"]))
            selectie_ids.add(match["speler_id"])
        else:
            dood_id = f"__huidig__{sid}"
            kandidaten.append({"speler": naam, "speler_id": dood_id, "club": club,
                               "pos": pos, "prijs": prijs, "E": 0.0})
            if extra_waarde is not None:
                extra_waarde[dood_id] = 0.0
            selectie_ids.add(dood_id)
    return selectie_ids, bijna_match


def los_op(kandidaten, e_multi, selectie_ids, budget, transfers_toegestaan, formaties_dict):
    """De MILP: kies 15 spelers (met bankplek-korting), binnen budget/club/
    formatie/transferregels, die de som van e_multi maximaliseren.

    `kandidaten`: lijst van pool-dicts (speler, speler_id, club, pos, prijs).
    `selectie_ids`: speler_id's van de HUIDIGE 15 (voor de transferregel).
    `formaties_dict`: cvhj_model.FORMATIES, {(v,m,a)-telling: naam}.
    Retourneert (nieuwe_selectie: list[dict], score: float) of (None, None)
    als er geen toelaatbare oplossing is.
    """
    n = len(kandidaten)
    if n == 0:
        return None, None

    posities = ["K", "V", "M", "A"]
    formaties = list(formaties_dict.items())  # [((v,m,a), naam), ...]

    # Variabelen: x_0..x_{n-1} (in selectie), y_0..y_{n-1} (bankplek van zijn
    # linie), f_0..f_{len(formaties)-1} (welke formatie actief is).
    n_f = len(formaties)
    n_var = 2 * n + n_f

    def x(i): return i
    def y(i): return n + i
    def f(j): return 2 * n + j

    c = np.zeros(n_var)
    for i, p in enumerate(kandidaten):
        e = e_multi.get(p["speler_id"], 0.0)
        c[x(i)] = -e         # maximaliseren = minimaliseren van -e
        c[y(i)] = 0.5 * e    # de bankspeler levert -0.5*e op in de doelfunctie

    constraints = []
    A_eq_rows, b_eq = [], []

    def eq(row, waarde):
        A_eq_rows.append(row); b_eq.append(waarde)

    # 1. precies 15 spelers
    row = np.zeros(n_var)
    for i in range(n): row[x(i)] = 1
    eq(row, 15)

    # 2. precies 2 keepers
    row = np.zeros(n_var)
    for i, p in enumerate(kandidaten):
        if p["pos"] == "K": row[x(i)] = 1
    eq(row, 2)

    # 3. precies 1 actieve formatie
    row = np.zeros(n_var)
    for j in range(n_f): row[f(j)] = 1
    eq(row, 1)

    # 4. aantal per linie (V, M, A) volgt de actieve formatie
    for li, pos in enumerate(("V", "M", "A")):
        row = np.zeros(n_var)
        for i, p in enumerate(kandidaten):
            if p["pos"] == pos: row[x(i)] = 1
        for j, (telling, _naam) in enumerate(formaties):
            row[f(j)] = -telling[li]
        eq(row, 0)

    # 5. exact 1 bankplek per linie
    for pos in posities:
        row = np.zeros(n_var)
        for i, p in enumerate(kandidaten):
            if p["pos"] == pos: row[y(i)] = 1
        eq(row, 1)

    A_ub_rows, b_ub = [], []

    def ub(row, waarde):
        A_ub_rows.append(row); b_ub.append(waarde)

    # 6. y_i <= x_i (alleen een geselecteerde speler kan de bankplek zijn)
    for i in range(n):
        row = np.zeros(n_var)
        row[y(i)] = 1; row[x(i)] = -1
        ub(row, 0)

    # 7. budget
    row = np.zeros(n_var)
    for i, p in enumerate(kandidaten): row[x(i)] = p["prijs"]
    ub(row, budget)

    # 8. max 1 speler per club
    for club in {p["club"] for p in kandidaten}:
        row = np.zeros(n_var)
        for i, p in enumerate(kandidaten):
            if p["club"] == club: row[x(i)] = 1
        ub(row, 1)

    # 9. transferregel: hooguit `transfers_toegestaan` van de huidige 15 mogen weg
    # (selectie_ids zit altijd volledig in kandidaten -- de aanroeper vult
    # ontbrekende spelers aan met een dood slot, E=0, voordat los_op wordt
    # aangeroepen, dus de ondergrens is gewoon len(selectie_ids) - transfers).
    row = np.zeros(n_var)
    for i, p in enumerate(kandidaten):
        if p["speler_id"] in selectie_ids: row[x(i)] = 1
    constraints.append(LinearConstraint(row, len(selectie_ids) - transfers_toegestaan, np.inf))

    if A_eq_rows:
        constraints.append(LinearConstraint(np.array(A_eq_rows), np.array(b_eq), np.array(b_eq)))
    if A_ub_rows:
        constraints.append(LinearConstraint(np.array(A_ub_rows), -np.inf, np.array(b_ub)))

    integrality = np.ones(n_var)
    bounds = Bounds(0, 1)

    res = milp(c, constraints=constraints, integrality=integrality, bounds=bounds)
    if not res.success:
        return None, None

    xv = res.x[:n]
    gekozen = [kandidaten[i] for i in range(n) if xv[i] > 0.5]
    score = sum(e_multi.get(p["speler_id"], 0.0) for p in gekozen)
    bankspelers = {kandidaten[i]["speler_id"] for i in range(n) if res.x[y(i)] > 0.5}
    score -= 0.5 * sum(e_multi.get(sid, 0.0) for sid in bankspelers)
    return gekozen, score


def main():
    import math

    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--clubs", default="clubs.csv")
    p.add_argument("--spelers", default="spelers.csv")
    p.add_argument("--prijzen", default="prijzen.csv")
    p.add_argument("--programma", default="programma.csv")
    p.add_argument("--selectie", default="selectie.csv")
    p.add_argument("--perioden", default="perioden.csv")
    p.add_argument("--stats", "--xg", "--fbref", dest="xg", default="spelerstats.csv",
                   help="assists/kaarten van scrape_statistieken.py; ontbreekt het, dan "
                        "draait dit script zoals vóór stap 5")
    p.add_argument("--ronde", type=int, required=True)
    p.add_argument("--transfers", default="1",
                   help="aantal transfers, of 'auto' (3 bij een periodestart, anders 1)")
    p.add_argument("--horizon", default="auto",
                   help="aantal ronden vooruit (incl. de eerstvolgende), of 'auto' "
                        "(tot de volgende periodestart, of 6 zonder perioden.csv)")
    p.add_argument("--decay", type=float, default=0.84, help="gewicht per ronde verder weg")
    p.add_argument("--venster", type=int, default=6)
    p.add_argument("--min-minuten", type=int, default=60)
    p.add_argument("--json", metavar="BESTAND", help="besluit machineleesbaar wegschrijven, "
                                                      "zelfde vorm als cvhj_model.py --json")
    p.add_argument("--vergelijk", action="store_true",
                   help="ook cvhj_model.py's brute-force zoeker op ronde 0 draaien, ter vergelijking")
    a = p.parse_args()

    m = laad_model()

    clubrijen = m.lees(a.clubs)
    spelerrijen = m.lees(a.spelers)
    prijsrijen = m.lees(a.prijzen)
    selectie_in = m.lees_selectie(a.selectie) or m.SELECTIE

    perioden = m.lees_perioden(a.perioden)
    periode, is_start, tot_volgende = m.periodestand(a.ronde, perioden)

    if str(a.transfers).lower() == "auto":
        if not perioden:
            sys.exit(f"--transfers auto vraagt om {a.perioden}, maar die is er niet.")
        a.transfers = 3 if is_start else 1
        print(f"--transfers auto -> {a.transfers}")
    else:
        a.transfers = int(a.transfers)

    if str(a.horizon).lower() == "auto":
        # Tot de volgende periodestart: daarna is de keuze toch weer helemaal
        # vrij (3 transfers), dus verder vooruitkijken heeft geen zin. Zonder
        # perioden.csv (of in de laatste periode, die geen opvolger heeft) een
        # vaste bovengrens van 6 ronden -- ruim boven de langste periode (5).
        a.horizon = tot_volgende if tot_volgende else 6
        print(f"--horizon auto -> {a.horizon}")
    else:
        a.horizon = int(a.horizon)

    if periode:
        if is_start:
            print(f"\n*** RONDE {a.ronde} START PERIODE {periode}: 3 TRANSFERS TOEGESTAAN ***")
        elif tot_volgende == 1:
            print(f"\nLET OP: volgende ronde start een nieuwe periode met 3 transfers. "
                  f"Een transfer nu bewaren kan lonen.")
        elif tot_volgende:
            print(f"Periode {periode}; volgende periodestart over {tot_volgende} ronden.")

    aanval, verdediging, thuisvoordeel, n_obs = m.schat_clubratings(clubrijen)
    print(f"Clubratings uit {n_obs} wedstrijden (thuisvoordeel x{math.exp(thuisvoordeel):.2f})")

    pad_xg = m.stats_pad(a.xg)
    fbref = m.lees_spelerstats(pad_xg)
    if fbref is None:
        print(f"LET OP: {pad_xg} niet gevonden - doelpunten/assists/kaarten "
              f"draaien zonder assists/kaarten (zoals vóór stap 5). Draai scrape_statistieken.py.")
    else:
        print(f"spelerstats geladen: {len(fbref)} spelers uit {pad_xg}")

    per_ronde = lees_programma_per_ronde(a.programma, m)
    if a.ronde not in per_ronde:
        sys.exit(f"Geen programma voor ronde {a.ronde} in {a.programma}. "
                 f"Draai eerst scrape_programma.py --ronde {a.ronde} --horizon {a.horizon}.")

    reeksen, metadata, rondes_gebruikt = bouw_horizon_pools(
        m, prijsrijen, spelerrijen, aanval, verdediging, thuisvoordeel,
        per_ronde, a.ronde, a.horizon, a.venster, a.min_minuten, fbref=fbref)
    if len(rondes_gebruikt) < a.horizon:
        print(f"LET OP: programma dekt maar {len(rondes_gebruikt)}/{a.horizon} gevraagde ronden "
              f"({rondes_gebruikt}) -- horizon wordt daartoe beperkt. "
              f"Draai scrape_programma.py met --horizon {a.horizon} voor het volledige venster.")
    print(f"Horizon: ronde {rondes_gebruikt} (decay {a.decay})")

    e_multi = bereken_multi_E(reeksen, a.decay)
    kandidaten = list(metadata.values())

    # De huidige selectie moet ALTIJD als kandidaat meedoen, ook als een speler
    # (nog) niet in de horizon-pool zit (te weinig speeltijd, geblesseerd --
    # dan krijgt hij net als in cvhj_model.py een dood slot met E=0).
    selectie_ids, bijna_match = koppel_selectie(m, selectie_in, kandidaten, extra_waarde=e_multi)
    op_speler_id = {p["speler_id"]: p for p in kandidaten}

    # Huidig team (VOOR een eventuele transfer), met ronde-0-E -- exact wat
    # cvhj_model.py's "huidig" in besluit.json ook laat zien.
    selectie_huidig = [op_speler_id[sid] for sid in selectie_ids]
    basis_h, bank_h, totaal_h = m.opstelling(selectie_huidig)
    m.toon_selectie(basis_h, bank_h, totaal_h, sum(s["prijs"] for s in selectie_huidig))

    geblesseerd = {m.norm(r["speler"]): r.get("blessure", "") for r in prijsrijen if r.get("blessure")}
    eigen_bless = [(n, geblesseerd[m.norm(n)]) for n in selectie_in if m.norm(n) in geblesseerd]
    if eigen_bless:
        print("\nGEBLESSEERD IN JE SELECTIE:")
        for naam, duur in eigen_bless:
            print(f"    {naam} ({duur})")
    ontbreekt = [naam for naam in selectie_in
                if f"__huidig__{m.norm(naam)}" in selectie_ids]
    if ontbreekt:
        print(f"Zonder recente speeltijd (E=0): {', '.join(ontbreekt)}")
    if bijna_match:
        print("LET OP MOGELIJKE NAAM-BUG IN prijzen.csv (automatisch gerepareerd, "
              "maar controleer de brondata):")
        for naam, gevonden in bijna_match:
            print(f"    '{naam}' (jouw selectie) <-> '{gevonden}' (marktdata, zelfde club)")

    nieuw, score_horizon = los_op(kandidaten, e_multi, selectie_ids, m.BUDGET, a.transfers, m.FORMATIES)
    if nieuw is None:
        sys.exit("Geen toelaatbare oplossing gevonden (budget/formatie/transferregels "
                 "sluiten alles uit) -- controleer selectie.csv en --transfers.")

    nieuw_ids = {p["speler_id"] for p in nieuw}
    uit = [op_speler_id[sid] for sid in selectie_ids - nieuw_ids]
    inn = [p for p in nieuw if p["speler_id"] not in selectie_ids]

    # Voor het ADVIES gebruiken we, net als cvhj_model.py, de ronde-0-E van de
    # NIEUWE 15 -- niet de gedecayde horizon-som. Die som bepaalt WELKE
    # transfer wint, maar "verwacht"/"winst" in de mail betekenen overal
    # "punten voor de eerstvolgende ronde"; die betekenis blijft zo intact.
    basis_n, bank_n, totaal_n = m.opstelling(nieuw)
    winst = totaal_n - totaal_h
    t = collections.Counter(x["pos"] for x in nieuw)
    formatie = m.FORMATIES.get((t["V"], t["M"], t["A"]), "?")

    print(f"\nMULTI-RONDE ADVIES (horizon {len(rondes_gebruikt)}, decay {a.decay}, "
          f"{a.transfers} transfer(s))")
    score_horizon_huidig = som_horizon(reeksen, a.decay, selectie_huidig)
    print(f"  ronde {a.ronde}: verwacht {totaal_n:.1f} punten  ({formatie})  winst {winst:+.1f}")
    print(f"  gedecayde som over de horizon: {score_horizon:.2f}  (huidig team: {score_horizon_huidig:.2f})")
    if not uit:
        print("  geen transfer nodig -- de huidige selectie is al optimaal binnen de horizon.")
    for x in uit:
        print(f"    UIT  {x['speler']:26s}{x['club']:17s}EUR {x['prijs']:.2f}  E {x['E']:5.2f}")
    for x in inn:
        e_m = e_multi.get(x["speler_id"], 0.0)
        print(f"    IN   {x['speler']:26s}{x['club']:17s}EUR {x['prijs']:.2f}  "
              f"E {x['E']:5.2f}  E(horizon) {e_m:5.2f}")
    if winst < 1.0 and uit:
        print("  LET OP: winst < 1,0 punt -- dat is binnen de ruis van het model; "
              "niets doen is hier even verdedigbaar.")

    if a.vergelijk:
        print(f"\nTER VERGELIJKING: cvhj_model.py's brute-force zoeker (ronde {a.ronde} alleen)")
        programma_0, inhaal_0 = per_ronde[a.ronde]
        pool_0 = m.bouw_pool(prijsrijen, spelerrijen, aanval, verdediging, thuisvoordeel,
                             programma_0, inhaal_0, laatste_ronde=a.ronde - 1,
                             venster=a.venster, min_minuten=a.min_minuten, fbref=fbref)
        selectie_0 = []
        for naam, (club, pos, prijs) in selectie_in.items():
            x, _ = m.koppel_speler(naam, club, pool_0)   # zelfde koppeling als hierboven
            selectie_0.append(x or {"speler": naam, "club": club, "pos": pos, "prijs": prijs, "E": 0.0})
        for score_bf, uit_bf, in_bf, _ in m.beste_transfers(selectie_0, pool_0, a.transfers, top=1):
            print(f"  eenronde-optimum: verwacht {score_bf:.2f} (ronde {a.ronde} alleen, geen decay)")
            for x in uit_bf:
                print(f"    UIT  {x['speler']:26s}{x['club']:17s}E {x['E']:5.2f}")
            for x in in_bf:
                print(f"    IN   {x['speler']:26s}{x['club']:17s}E {x['E']:5.2f}")
            zelfde = {x["speler"] for x in in_bf} == {x["speler"] for x in inn}
            print(f"  {'ZELFDE' if zelfde else 'AFWIJKEND'} advies t.o.v. het multi-ronde-advies hierboven.")
            if not zelfde:
                print("  Dat is het hele punt van dit script: het eenronde-advies kijkt niet "
                      "verder dan komend weekend, het multi-ronde-advies wel.")

    if a.json:
        besluit = {
            "ronde": a.ronde,
            "gegenereerd": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "transfers_toegestaan": a.transfers,
            "periode": periode,
            "periodestart": is_start,
            "ronden_tot_volgende_periode": tot_volgende,
            "huidig": {
                "verwacht": round(totaal_h, 2),
                "kosten": round(sum(x["prijs"] for x in selectie_huidig), 2),
                "basis": [{"speler": x["speler"], "club": x["club"], "pos": x["pos"],
                           "E": round(x["E"], 3)} for x in basis_h],
                "bank": [{"speler": x["speler"], "club": x["club"], "pos": x["pos"],
                          "E": round(x["E"], 3)} for x in bank_h]},
            "zonder_speeltijd": ontbreekt,
            "bijna_match": [{"selectie": naam, "marktdata": gevonden} for naam, gevonden in bijna_match],
            "geblesseerd_in_selectie": [{"speler": n, "duur": d} for n, d in eigen_bless],
            "programma": [{"thuis": h, "uit": u} for h, u in per_ronde[a.ronde][0]],
            "inhaal": sorted(per_ronde[a.ronde][1]),
            "pool_grootte": len(metadata),
            "advies": {
                "verwacht": round(totaal_n, 2),
                "winst": round(winst, 2),
                "formatie": formatie,
                "uit": [{"speler": x["speler"], "club": x["club"], "pos": x["pos"],
                         "prijs": x["prijs"], "E": round(x["E"], 3)} for x in uit],
                "in": [{"speler": x["speler"], "club": x["club"], "pos": x["pos"],
                        "prijs": x["prijs"], "E": round(x["E"], 3)} for x in inn],
            } if uit or inn else None,
            # Extra t.o.v. cvhj_model.py's besluit.json -- notify.py negeert
            # onbekende velden, dus dit is achterwaarts compatibel.
            "multi_ronde": True,
            "horizon": len(rondes_gebruikt),
            "horizon_rondes": rondes_gebruikt,
            "decay": a.decay,
            "verwacht_horizon": round(score_horizon, 2)}
        Path(a.json).write_text(
            __import__("json").dumps(besluit, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nbesluit -> {a.json}")


if __name__ == "__main__":
    main()
