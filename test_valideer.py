#!/usr/bin/env python3
"""
Regressietest voor valideer.py -- zonder netwerk.

Het zwaartepunt ligt op twee dingen die stil fout kunnen gaan.

De POORTWACHTER, is_validatieweek(). Die bepaalt of er uberhaupt iets draait.
Staat hij te streng, dan gebeurt er maanden niets en valt dat niemand op: er
is geen foutmelding, alleen afwezigheid. Dat is dezelfde soort fout als de
regressietest die zichzelf oversloeg en toch groen meldde.

De TRENDREGEL. Een rapport dat bij ongewijzigde data "slechter" meldt, is
binnen twee metingen niet meer geloofwaardig -- en dan lees je ook het echte
signaal niet meer. Drijvende-kommaruis mag dus geen oordeel worden.

    python test_valideer.py
"""
import sys

import valideer as v

# Zoals perioden.csv: (periode, start_ronde). CVHJ heeft 8 perioden van 4-5 ronden.
PERIODEN = [(1, 1), (2, 5), (3, 9), (4, 13), (5, 18), (6, 22), (7, 26), (8, 30)]


def test_poortwachter():
    gevallen = [
        # ronde, venster, draait?, waarom
        (9, 1, True, "ronde 9 is zelf een periodestart"),
        (8, 1, True, "start over 1 ronde, binnen het venster"),
        (7, 1, False, "start over 2 ronden, buiten het venster"),
        (7, 2, True, "zelfde ronde, ruimer venster"),
        (5, 1, True, "ronde 5 is een periodestart"),
        (6, 1, False, "net na een start is er niets te doen"),
        (31, 1, False, "na de laatste periodestart"),
        (1, 1, True, "eerste ronde is ook een start"),
    ]
    ok = True
    for ronde, venster, verwacht, waarom in gevallen:
        draait, reden = v.is_validatieweek(ronde, PERIODEN, venster)
        goed = draait == verwacht
        if not goed:
            print(f"  FOUT ronde {ronde} venster {venster}: {draait}, verwacht "
                  f"{verwacht} ({waarom}) -- {reden}")
        ok = ok and goed
    if ok:
        print(f"  OK   {len(gevallen)} gevallen: draait op en vlak voor een periodestart, "
              f"niet erbuiten")

    # Zonder perioden.csv mag hij NIET stilletjes altijd draaien en ook niet
    # stilletjes nooit: hij moet zeggen dat het ritme onbekend is.
    draait, reden = v.is_validatieweek(9, [], 1)
    goed = draait is False and "perioden" in reden
    print(f"  {'OK  ' if goed else 'FOUT'} zonder perioden.csv: {reden}")
    return ok and goed


def test_trendregel_geen_ruis():
    """Twee identieke metingen mogen geen oordeel opleveren."""
    historie = [{"rho": "0.4639"}]
    regel = v.trendregel("rho", 0.4639 + 1e-15, historie, hoger_is_beter=True)
    goed = "ongewijzigd" in regel and "slechter" not in regel
    print(f"  {'OK  ' if goed else 'FOUT'} ruisverschil -> {regel.split('(')[-1].rstrip(')')}")
    return goed


def test_trendregel_richting():
    """Hoger-is-beter en lager-is-beter moeten tegengesteld geoordeeld worden."""
    historie = [{"rho": "0.40", "rmse": "3.40"}]
    proeven = [
        ("rho", 0.46, True, "beter"),      # rho omhoog = beter
        ("rho", 0.34, True, "slechter"),
        ("rmse", 3.20, False, "beter"),    # rmse omlaag = beter
        ("rmse", 3.60, False, "slechter"),
    ]
    ok = True
    for naam, nu, hoger_beter, verwacht in proeven:
        regel = v.trendregel(naam, nu, historie, hoger_is_beter=hoger_beter)
        goed = verwacht in regel
        if not goed:
            print(f"  FOUT {naam}={nu}: verwacht {verwacht!r} in {regel!r}")
        ok = ok and goed
    if ok:
        print("  OK   rho omhoog = beter, rmse omlaag = beter")
    return ok


def test_trendregel_eerste_meting():
    """Zonder voorgeschiedenis geen verzonnen vergelijking."""
    regel = v.trendregel("rho", 0.46, [], hoger_is_beter=True)
    goed = "eerste meting" in regel
    print(f"  {'OK  ' if goed else 'FOUT'} lege historie -> {regel}")
    return goed


def test_gat_gevangen():
    """De beslissingsmaat: 0 = willekeurig, 1 = perfect.

    Nagerekend met een pool waarin de voorspelling perfect met de
    werkelijkheid meeloopt (dan moet het 1,0 zijn) en een waarin hij precies
    omgekeerd loopt (dan ruim onder 0).
    """
    werkelijk = {f"s{i}": float(i) for i in range(40)}
    perfect_pool = [{"speler_id": f"s{i}", "E": float(i)} for i in range(40)]
    omgekeerd = [{"speler_id": f"s{i}", "E": float(-i)} for i in range(40)]

    g1 = v.gat_gevangen(None, perfect_pool, werkelijk)
    g2 = v.gat_gevangen(None, omgekeerd, werkelijk)
    goed = g1 is not None and abs(g1 - 1.0) < 1e-9 and g2 is not None and g2 < -0.5
    print(f"  {'OK  ' if goed else 'FOUT'} perfecte rangorde {g1:.3f} (verwacht 1.000), "
          f"omgekeerde {g2:.3f} (verwacht ruim negatief)")

    # Te weinig spelers om iets te zeggen: geen getal verzinnen.
    klein = v.gat_gevangen(None, perfect_pool[:5], werkelijk)
    goed2 = klein is None
    print(f"  {'OK  ' if goed2 else 'FOUT'} te kleine pool -> {klein} (verwacht None)")
    return goed and goed2


def test_halve_ronde_telt_niet_mee():
    """Een ronde waarvan het advies halverwege draaide, is geen meting.

    Het advies van ronde 6 liep op 12-09-2026, midden in een ronde die van
    11 tot 13 september duurde. Het programma bevatte toen 5 van de 9
    wedstrijden; acht clubs waren eruit en drie basisspelers kregen stil E=0.
    De 24,37 die eruit kwam is geen voorspelling van die ronde maar van de
    rest ervan.

    Dat ene paar trok de gemeten bias van -7,6 naar +0,05: precies de
    verkeerde conclusie, en dan nog de geruststellende. Een reeks met zo'n
    paar erin is slechter dan een kortere zonder.
    """
    import json, tempfile, os
    import valideer as v

    map_ = tempfile.mkdtemp()
    hist = os.path.join(map_, "historie")
    os.makedirs(hist)
    # Vier normale ronden plus een halve. De halve is zo gekozen dat hij de
    # bias van negatief naar bijna nul trekt, net als ronde 6 deed.
    ronden = {6: (24.37, 5), 7: (39.9, 9), 8: (42.5, 9), 9: (40.1, 9), 11: (51.8, 9)}
    for r, (verwacht, wedstrijden) in ronden.items():
        json.dump({"ronde": r, "huidig": {"verwacht": verwacht},
                   "programma": [{"thuis": f"C{i}", "uit": f"D{i}"}
                                 for i in range(wedstrijden)]},
                  open(os.path.join(hist, f"ronde-{r}.json"), "w"))
    punten = os.path.join(map_, "eigen_punten.csv")
    with open(punten, "w", encoding="utf-8") as f:
        f.write("ronde,punten\n6,55\n7,31\n8,22\n9,40\n11,51\n")

    uit = v.meet_eigen_ploeg(pad=punten, map_historie=hist)
    ok = True
    g = uit["eigen_gekoppeld"] == 4
    print(f"  {'OK  ' if g else 'FOUT'} vier ronden gekoppeld, de halve valt af "
          f"({uit['eigen_gekoppeld']})")
    ok = ok and g

    g = any(x.startswith("6 ") for x in uit["eigen_halve_ronden"])
    print(f"  {'OK  ' if g else 'FOUT'} ronde 6 wordt benoemd als overgeslagen: "
          f"{uit['eigen_halve_ronden']}")
    ok = ok and g

    # De bias moet het signaal laten zien, niet het artefact wegmiddelen.
    g = -9 < uit["eigen_bias"] < -6
    print(f"  {'OK  ' if g else 'FOUT'} bias {uit['eigen_bias']:+} (met de halve "
          f"ronde erbij zou dit rond nul uitkomen)")
    ok = ok and g

    # En een volledige ronde mag er NIET uitvallen.
    g = uit["eigen_gekoppeld"] == 4 and not uit["eigen_zonder_verwachting"]
    print(f"  {'OK  ' if g else 'FOUT'} de vier volledige ronden blijven allemaal "
          f"staan")
    return ok and g


def test_meetlat_volgt_de_gespeelde_ploeg():
    """Welke ploeg is de meetlat: voor of na de transfers van die ronde?

    huidig.verwacht is de ploeg ZONDER de transfers. Voerde Thomas het advies
    uit, dan speelde hij met een andere ploeg en meet je tegen iets wat nooit
    op het veld stond -- en systematisch te laag, want een geadviseerde
    transfer wint per definitie in de ogen van het model.

    Dat is niet te raden maar wel vast te stellen: staan alle geadviseerde
    aankopen in de elf van diezelfde ronde, dan is het advies uitgevoerd.
    Gemeten op de echte data: ronde 9 en 11 wel, ronde 7 en 8 niet -- daar
    kwamen Nijstad en Stepanov in plaats van de geadviseerde Propper en
    Viergever.
    """
    import json, tempfile, os
    import valideer as v

    map_ = tempfile.mkdtemp()
    hist = os.path.join(map_, "historie")
    os.makedirs(hist)

    def schrijf(r, huidig, advies=None, aankopen=()):
        d = {"ronde": r, "huidig": {"verwacht": huidig},
             "programma": [{"thuis": f"C{i}", "uit": f"D{i}"} for i in range(9)]}
        if advies is not None:
            d["advies"] = {"verwacht": advies,
                           "in": [{"speler": s} for s in aankopen]}
        json.dump(d, open(os.path.join(hist, f"ronde-{r}.json"), "w"))

    # 9: advies gevolgd (Til staat in de elf) -> meetlat 50.1
    # 8: eigen transfer (Viergever niet in de elf) -> meetlat 42.5
    # 10: geen advies -> meetlat 42.97
    schrijf(8, 42.5, 45.5, ["Nick Viergever"])
    schrijf(9, 40.1, 50.1, ["Guus Til"])
    schrijf(10, 42.97)

    elf = os.path.join(map_, "eigen_elf.csv")
    with open(elf, "w", encoding="utf-8") as f:
        f.write("ronde,speler,punten,plek\n")
        for r, namen in ((8, ["Ruud Nijstad", "Artem Stepanov"]),
                         (9, ["Guus Til", "Tyrone Owusu"]),
                         (10, ["Julian Brandt"])):
            for n in namen:
                f.write(f"{r},{n},3,basis\n")
    punten = os.path.join(map_, "eigen_punten.csv")
    with open(punten, "w", encoding="utf-8") as f:
        f.write("ronde,punten\n8,22\n9,40\n10,59\n")

    uit = v.meet_eigen_ploeg(pad=punten, map_historie=hist, pad_elf=elf)
    ok = True
    g = uit["eigen_advies_gevolgd"] == [9]
    print(f"  {'OK  ' if g else 'FOUT'} ronde 9 herkend als uitgevoerd advies "
          f"({uit['eigen_advies_gevolgd']})")
    ok = ok and g

    g = uit["eigen_meetlat_benadering"] == [8]
    print(f"  {'OK  ' if g else 'FOUT'} ronde 8 herkend als eigen transfer "
          f"({uit['eigen_meetlat_benadering']})")
    ok = ok and g

    # De bias moet op de GEKOZEN meetlatten rusten:
    # (22-42.5) + (40-50.1) + (59-42.97) = -14.57 over 3 -> -4.86
    g = abs(uit["eigen_bias"] - (-4.86)) < 0.02
    print(f"  {'OK  ' if g else 'FOUT'} bias {uit['eigen_bias']:+} "
          f"(verwacht -4.86: 42.5 voor ronde 8, 50.1 voor 9, 42.97 voor 10)")
    ok = ok and g

    # Zonder eigen_elf.csv valt alles terug op huidig.verwacht -- dan is
    # (40-40.1) in plaats van (40-50.1) en wordt de bias -1.52.
    zonder = v.meet_eigen_ploeg(pad=punten, map_historie=hist,
                                pad_elf=os.path.join(map_, "bestaat-niet.csv"))
    g = (not zonder["eigen_advies_gevolgd"]
         and abs(zonder["eigen_bias"] - (-1.52)) < 0.02)
    print(f"  {'OK  ' if g else 'FOUT'} zonder eigen_elf.csv valt het terug op de "
          f"ploeg voor de transfers (bias {zonder['eigen_bias']:+})")
    return ok and g


def main():
    print("poortwachter: draait de validatie deze week?\n")
    ok1 = test_poortwachter()

    print("\ntrendregel\n")
    ok2 = test_trendregel_geen_ruis()
    ok3 = test_trendregel_richting()
    ok4 = test_trendregel_eerste_meting()

    print("\nbeslissingsmaat\n")
    ok5 = test_gat_gevangen()

    print("\neen halve ronde is geen meting\n")
    ok6 = test_halve_ronde_telt_niet_mee()

    print("\nde meetlat volgt de ploeg die werkelijk speelde\n")
    ok7 = test_meetlat_volgt_de_gespeelde_ploeg()

    print()
    if all([ok1, ok2, ok3, ok4, ok5, ok6, ok7]):
        print("OK: de poortwachter kiest de juiste weken en het rapport oordeelt niet op ruis.")
    else:
        sys.exit("MISLUKT: zie hierboven.")


if __name__ == "__main__":
    main()
