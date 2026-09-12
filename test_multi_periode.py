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


def vervuil_een_naam(prijsrijen, selectie_in, m):
    """Plakt ' basis' achter de naam van EEN speler uit de selectie.

    Dit is geen kunstje maar het naspelen van een echte situatie: pouletips
    zet statuswoorden in dezelfde cel als de naam, en als die er een keer niet
    uit gestript worden staat er letterlijk 'Tjaronn Chery basis' in
    prijzen.csv. Op 17 september 2026 liet precies dat deze test live falen --
    de MILP-tak repareerde zo'n naam via vind_bijna_match() en de brute-force-
    tak niet, dus vergeleken ze twee verschillende selecties.

    Retourneert de gewijzigde naam, of None als er niets te vervuilen viel.
    """
    namen = {m.norm(n) for n in selectie_in}
    for r in prijsrijen:
        if m.norm(r["speler"]) in namen:
            r["speler"] = r["speler"] + " basis"
            return r["speler"]
    return None


def e_waarde(naam, e_pool0, selectie_in):
    """De E waarmee BEIDE takken deze speler gewogen hebben.

    Staat hij in pool_0, dan die waarde. Staat hij er niet in, dan is hij een
    'dood slot': een speler uit de huidige selectie die de speeltijddrempel
    niet haalt, net is overgekomen, of geblesseerd gemeld staat. Beide takken
    kennen zo iemand expliciet E=0.0 toe -- koppel_selectie() in de MILP-tak,
    de terugval-dict in de brute-force-tak. Die 0.0 is dus geen aanname van
    deze test maar precies de waarde die in de optimalisatie gebruikt is.

    Eerder gaf deze opzoeking float('nan') voor iedereen buiten pool_0. Daar
    keurde de gelijkstand-controle een ECHTE gelijkstand op af, zodra er een
    dood slot in het verschil zat. In een ronde met weinig wedstrijden (bijna
    alle E gelijk aan 0, dus enorm veel gelijkwaardige oplossingen) is dat
    juist de normale situatie, en dan meldt de test een MILP-fout die er niet
    is -- precies wat er op 12 september 2026 gebeurde.

    Een naam die noch in pool_0 noch in de selectie voorkomt houdt bewust NaN:
    zo iemand KAN in geen van beide takken gekozen zijn, dus dat zou een echte
    inconsistentie zijn en hoort de test wel af te keuren.
    """
    if naam in e_pool0:
        return e_pool0[naam]
    return 0.0 if naam in selectie_in else float("nan")


def test_e_waarde():
    """De gelijkstand-opzoeking, los van de data.

    Nagespeeld naar het echte geval: twee takken die allebei een dood slot
    houden (MILP hield 'Stijn van Gassel', brute-force 'Lutsharel
    Geertruida'), plus aan elke kant een gekochte speler met E=0. Totaalscores
    identiek -- dit hoort een gelijkstand te heten, geen fout.
    """
    e_pool0 = {"Evert Linthorst": 0.0, "Jasper Schendelaar": 0.0, "Ricardo Pepi": 4.2}
    selectie_in = {"Stijn van Gassel": (), "Lutsharel Geertruida": ()}

    proeven = [
        ("speler in pool_0", "Ricardo Pepi", 4.2),
        ("dood slot (wel in selectie)", "Stijn van Gassel", 0.0),
        ("ander dood slot", "Lutsharel Geertruida", 0.0),
    ]
    ok = True
    for wat, naam, verwacht in proeven:
        gekregen = e_waarde(naam, e_pool0, selectie_in)
        if gekregen != verwacht:
            print(f"  FOUT e_waarde {wat}: {naam} -> {gekregen}, verwacht {verwacht}")
            ok = False

    # Nergens te vinden: moet NaN blijven, anders verdwijnt een echte fout.
    spook = e_waarde("Niemand Nergens", e_pool0, selectie_in)
    if spook == spook:
        print(f"  FOUT e_waarde: onbekende naam gaf {spook}, verwacht NaN")
        ok = False

    # En de gelijkstand-regel zelf, op het geval uit het echte log.
    es_milp = sorted(round(e_waarde(n, e_pool0, selectie_in), 6)
                     for n in ("Evert Linthorst", "Stijn van Gassel"))
    es_bf = sorted(round(e_waarde(n, e_pool0, selectie_in), 6)
                   for n in ("Jasper Schendelaar", "Lutsharel Geertruida"))
    if not (es_milp == es_bf and not any(v != v for v in es_milp + es_bf)):
        print(f"  FOUT gelijkstand niet herkend: {es_milp} vs {es_bf}")
        ok = False

    if ok:
        print("  gelijkstand-opzoeking: dood slot telt als E=0, onbekende naam blijft NaN")
    return ok


def test_inhaalronde_telt_mee():
    """Een ronde met UITSLUITEND inhaalduels moet een gevulde pool opleveren.

    Dit stond er niet omdat de eerste versie van bouw_horizon_pools afbrak op
    `if not programma`, zonder naar de inhaallijst te kijken. Gevolg: nul
    pools, een lege kandidatenlijst, de hele selectie als dood slot met E=0,
    en een MILP die 0.00 teruggaf met een ongewijzigd elftal -- oftewel het
    advies "doe niets", precies in een week waarin er wel degelijk gespeeld
    werd. De regressietest hierboven vond dat pas toen programma.csv voor het
    eerst zo'n ronde bevatte (12 september 2026, live).

    Deze test wacht daar niet op: hij bouwt zo'n ronde zelf.
    """
    m = laad_model()
    clubrijen = m.lees("clubs.csv")
    spelerrijen = m.lees("spelers.csv")
    prijsrijen = m.lees("prijzen.csv")
    aanval, verdediging, thuisvoordeel, _ = m.schat_clubratings(clubrijen)

    per_ronde = lees_programma_per_ronde("programma.csv", m)
    if not per_ronde:
        print("  overgeslagen: geen programma.csv")
        return True

    # Neem een bestaande ronde en gooi de reguliere duels eruit: wat overblijft
    # is een ronde die alleen uit inhaalduels bestaat.
    bron = max(per_ronde)
    programma, _ = per_ronde[bron]
    if not programma:
        print(f"  overgeslagen: ronde {bron} heeft geen reguliere duels om om te bouwen")
        return True
    thuis, uit = programma[0]
    kunstmatig = {bron: ([], {thuis: (uit, True), uit: (thuis, False)})}

    _reeksen, metadata, rondes = bouw_horizon_pools(
        m, prijsrijen, spelerrijen, aanval, verdediging, thuisvoordeel,
        kunstmatig, bron, 1, venster=6, min_minuten=60)

    if not rondes or not metadata:
        print(f"  FOUT inhaalronde: horizon brak af op een ronde met alleen "
              f"inhaalduels ({thuis}-{uit}); pool is leeg, MILP zou 0.00 geven")
        return False
    print(f"  inhaalronde ({thuis}-{uit}): pool gevuld, {len(metadata)} kandidaten")
    return True


def test_horizon_1_matcht_brute_force(ronde, transfers, vervuild=False):
    m = laad_model()
    clubrijen = m.lees("clubs.csv")
    spelerrijen = m.lees("spelers.csv")
    prijsrijen = m.lees("prijzen.csv")
    selectie_in = m.lees_selectie("selectie.csv") or m.SELECTIE

    if vervuild:
        naam = vervuil_een_naam(prijsrijen, selectie_in, m)
        if naam is None:
            print("  overgeslagen: geen selectiespeler in prijzen.csv om te vervuilen")
            return True

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
    # Dezelfde koppeling als koppel_selectie() gebruikt -- via m.koppel_speler(),
    # niet een eigen kopie. Anders vergelijkt deze test twee zoekers die al bij
    # de INVOER van elkaar verschillen, en dat is precies waar hij op 17
    # september 2026 op stukliep.
    selectie_0 = []
    for naam, (club, pos, prijs) in selectie_in.items():
        x, _ = m.koppel_speler(naam, club, pool_0)
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
    alleen_milp = alleen_bf = set()
    es_milp = es_bf = []
    if not ok_spelers:
        alleen_milp = namen_milp - namen_bf
        alleen_bf = namen_bf - namen_milp
        e_pool0 = {p["speler"]: p["E"] for p in pool_0}
        es_milp = sorted(round(e_waarde(n, e_pool0, selectie_in), 6) for n in alleen_milp)
        es_bf = sorted(round(e_waarde(n, e_pool0, selectie_in), 6) for n in alleen_bf)
        gelijkstand = len(alleen_milp) == len(alleen_bf) and es_milp == es_bf and not any(
            v != v for v in es_milp + es_bf)  # NaN uitsluiten (speler nergens gevonden)

    status = "gelijk" if ok_spelers else ("gelijkspel (E's kloppen exact)" if gelijkstand else "VERSCHILT")
    merk = " [vervuilde naam]" if vervuild else ""
    print(f"  ronde {ronde}, {transfers} transfer(s){merk}: MILP {score_milp:.2f} vs "
          f"brute-force {score_bf:.2f}  spelersgroep {status}")
    if not (ok_score and (ok_spelers or gelijkstand)) and vervuild:
        print("    Dit is het geval van 17 september 2026: als de twee takken een "
              "vervuilde naam verschillend koppelen, lopen ze hier uiteen. "
              "Controleer of beide via m.koppel_speler() gaan.")
    if not ok_spelers:
        print(f"    MILP:        {sorted(namen_milp)}")
        print(f"    brute-force: {sorted(namen_bf)}")
        # Het verschil zelf, met de E's waarop de gelijkstand-controle
        # besloten heeft. Zonder deze regels zie je alleen DAT hij afkeurde en
        # moet je de E's er met de hand bij zoeken; met deze regels staat het
        # antwoord in het log van de mislukte workflow.
        print(f"    alleen MILP:        {sorted(alleen_milp)}  E={es_milp}")
        print(f"    alleen brute-force: {sorted(alleen_bf)}  E={es_bf}")
        if any(v != v for v in es_milp + es_bf):
            print("    (NaN = speler zit niet in pool_0 en ook niet in de selectie "
                  "-- dat hoort niet te kunnen)")
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
        # En dezelfde vergelijking met een vervuilde naam in prijzen.csv. Dat
        # gebeurt in de echte data regelmatig, en het is de situatie waarin de
        # twee takken vroeger uiteenliepen -- zie vervuil_een_naam().
        if not test_horizon_1_matcht_brute_force(ronde, 1, vervuild=True):
            alles_ok = False

    if not test_e_waarde():
        alles_ok = False
    if not test_inhaalronde_telt_mee():
        alles_ok = False

    print()
    if alles_ok:
        print("OK: horizon=1 komt in elk geval overeen met de brute-force zoeker.")
    else:
        sys.exit("MISLUKT: zie hierboven -- de MILP-formulering wijkt af van de brute-force zoeker.")


if __name__ == "__main__":
    main()
