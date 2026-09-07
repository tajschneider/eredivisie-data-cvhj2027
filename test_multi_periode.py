#!/usr/bin/env python3
"""
Regressietest: met --horizon 1 moet multi_periode.py's MILP exact dezelfde
score vinden als cvhj_model.py's brute-force zoeker, voor 1 EN 3 transfers,
met dezelfde spelersgroep TENZIJ er een exacte gelijkstand is (twee spelers
met bit-voor-bit dezelfde E -- bijvoorbeeld twee bankspelers die allebei
volledig op de positieprior terugvallen). Het zijn twee verschillende
algoritmes voor precies dezelfde vraag (kies de beste transfer(s) voor de
eerstvolgende ronde) -- elk verschil dat niet als zo'n gelijkstand te
verklaren is, betekent een fout in een van de twee, niet een verbeterd
inzicht.

Draai dit na elke wijziging aan multi_periode.py of aan de spelregels-
constraints in los_op() (budget, formatie, club, transfers):

    python test_multi_periode.py

Vereist clubs.csv, spelers.csv, prijzen.csv, programma.csv, selectie.csv in de
huidige map (dezelfde bestanden als voor cvhj_model.py).
"""
import sys

from multi_periode import bereken_multi_E, bouw_horizon_pools, koppel_selectie, laad_model, lees_programma_per_ronde, los_op


def test_horizon_1_matcht_brute_force(ronde, transfers):
    m = laad_model()
    clubrijen = m.lees("clubs.csv")
    spelerrijen = m.lees("spelers.csv")
    prijsrijen = m.lees("prijzen.csv")
    selectie_in = m.lees_selectie("selectie.csv") or m.SELECTIE

    aanval, verdediging, thuisvoordeel, _ = m.schat_clubratings(clubrijen)
    per_ronde = lees_programma_per_ronde("programma.csv", m)
    if ronde not in per_ronde:
        print(f"  overgeslagen: geen programma voor ronde {ronde}")
        return True

    # --- multi_periode.py, horizon=1 ---
    reeksen, metadata, rondes_gebruikt = bouw_horizon_pools(
        m, prijsrijen, spelerrijen, aanval, verdediging, thuisvoordeel,
        per_ronde, ronde, 1, venster=6, min_minuten=60)
    e_multi = bereken_multi_E(reeksen, decay=0.84)  # decay is irrelevant bij horizon=1
    kandidaten = list(metadata.values())
    selectie_ids, _bijna_match = koppel_selectie(m, selectie_in, kandidaten, extra_waarde=e_multi)
    nieuw, score_milp = los_op(kandidaten, e_multi, selectie_ids, m.BUDGET, transfers, m.FORMATIES)

    # --- cvhj_model.py, brute force ---
    programma_0, inhaal_0 = per_ronde[ronde]
    pool_0 = m.bouw_pool(prijsrijen, spelerrijen, aanval, verdediging, thuisvoordeel,
                         programma_0, inhaal_0, laatste_ronde=ronde - 1, venster=6, min_minuten=60)
    selectie_0 = []
    for naam, (club, pos, prijs) in selectie_in.items():
        x = next((p for p in pool_0 if m.norm(p["speler"]) == m.norm(naam) and p["club"] == club), None)
        selectie_0.append(x or {"speler": naam, "club": club, "pos": pos, "prijs": prijs, "E": 0.0})
    resultaten = m.beste_transfers(selectie_0, pool_0, transfers, top=1)

    if nieuw is None or not resultaten:
        print(f"  FOUT: geen oplossing (MILP={nieuw is not None}, brute-force={bool(resultaten)})")
        return False

    score_bf, uit_bf, in_bf, _ = resultaten[0]
    namen_milp = {p["speler"] for p in nieuw}
    namen_bf = {s["speler"] for s in selectie_0 if s["speler"] not in {x["speler"] for x in uit_bf}} | {x["speler"] for x in in_bf}

    ok_score = abs(score_milp - score_bf) < 0.05
    ok_spelers = namen_milp == namen_bf

    # Verschilt de spelersgroep, dan is dat alleen onschuldig als het om een
    # EXACTE gelijkstand gaat: precies zoveel spelers anders aan elke kant,
    # en die twee kantjes hebben (multiset-gewijs) bit-voor-bit dezelfde
    # E-waarden. Dat bewijst een gelijkspel-wissel, geen scoreverschil dat
    # toevallig wegvalt in de som.
    gelijkstand = False
    if not ok_spelers:
        alleen_milp = namen_milp - namen_bf
        alleen_bf = namen_bf - namen_milp
        e_pool0 = {p["speler"]: p["E"] for p in pool_0}
        es_milp = sorted(round(e_pool0.get(n, float("nan")), 6) for n in alleen_milp)
        es_bf = sorted(round(e_pool0.get(n, float("nan")), 6) for n in alleen_bf)
        gelijkstand = len(alleen_milp) == len(alleen_bf) and es_milp == es_bf and not any(
            v != v for v in es_milp + es_bf)  # NaN uitsluiten (speler niet in pool_0 gevonden)

    status = "gelijk" if ok_spelers else ("gelijkspel (E's kloppen exact)" if gelijkstand else "VERSCHILT")
    print(f"  ronde {ronde}, {transfers} transfer(s): MILP {score_milp:.2f} vs brute-force {score_bf:.2f}"
          f"  spelersgroep {status}")
    if not ok_spelers:
        print(f"    MILP:        {sorted(namen_milp)}")
        print(f"    brute-force: {sorted(namen_bf)}")
    return ok_score and (ok_spelers or gelijkstand)


def main():
    m = laad_model()
    clubrijen = m.lees("clubs.csv")
    per_ronde = lees_programma_per_ronde("programma.csv", m)
    rondes = sorted(per_ronde) or [max(int(r["ronde"]) for r in clubrijen) + 1]

    print("Regressietest multi_periode.py vs cvhj_model.py (horizon=1)\n")
    alles_ok = True
    for ronde in rondes:
        for transfers in (1, 3):
            if not test_horizon_1_matcht_brute_force(ronde, transfers):
                alles_ok = False

    print()
    if alles_ok:
        print("OK: horizon=1 komt in elk geval overeen met de brute-force zoeker.")
    else:
        sys.exit("MISLUKT: zie hierboven -- de MILP-formulering wijkt af van de brute-force zoeker.")


if __name__ == "__main__":
    main()
