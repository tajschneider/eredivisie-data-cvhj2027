#!/usr/bin/env python3
"""
Regressietest voor grenzen.py -- de hekken om een automatisch voorstel.

Dit is de test die het strengst moet zijn, want grenzen.py is het enige wat
tussen een automatisch gegenereerde wijziging en jouw repo staat. Een gat
hier is niet zichtbaar in een groene run: je merkt het pas als er iets is
gewijzigd wat niet gewijzigd had mogen worden.

Getest wordt vooral wat er MOET worden afgekeurd. Een hek dat alles doorlaat
is net zo nutteloos als geen hek, maar veel geruststellender om naar te
kijken -- en dat is precies het gevaar.

    python test_grenzen.py
"""
import sys

import grenzen as g


def test_verboden_paden():
    """Wat nooit automatisch mag wijzigen, moet ook echt afgekeurd worden."""
    gevallen = [
        ("inleggen.py", True, "legt echte transfers in"),
        (".github/workflows/wekelijks.yml", True, "workflow kan rechten uitbreiden"),
        (".github/workflows/nieuw.yml", True, "ook een nieuwe workflow"),
        ("grenzen.py", True, "het hek zelf"),
        ("test_grenzen.py", True, "de test van het hek"),
        ("prijzen.csv", True, "data komt van de scrapers"),
        ("data/spelers.csv", True, "ook in een submap"),
        ("validatie/historie.csv", True, "de meetreeks"),
        ("historie/ronde-6.json", True, "vastgelegd advies"),
        ("kalibratie/status.json", True, "kalibratiegeschiedenis"),
        # En wat wel mag:
        ("cvhj_model.py", False, "het model zelf"),
        ("multi_periode.py", False, "de zoeker"),
        ("backtest.py", False, "de evaluatie"),
        ("valideer.py", False, "de validatie"),
        ("scrape_prijzen.py", False, "een scraper"),
        ("notify.py", False, "de mail"),
        ("README.md", False, "documentatie"),
        ("test_multi_periode.py", False, "een test mag uitgebreid worden"),
    ]
    ok = True
    for pad, verwacht, waarom in gevallen:
        verboden, _reden = g.is_verboden(pad)
        if verboden != verwacht:
            print(f"  FOUT {pad}: verboden={verboden}, verwacht {verwacht} ({waarom})")
            ok = False
    if ok:
        print(f"  OK   {len(gevallen)} paden correct beoordeeld "
              f"({sum(1 for _p, v, _w in gevallen if v)} verboden, "
              f"{sum(1 for _p, v, _w in gevallen if not v)} toegestaan)")
    return ok


def test_verboden_pad_keurt_af():
    """Een verboden pad moet een FOUT opleveren, niet alleen een opmerking."""
    fouten, _opm = g.controleer(["cvhj_model.py", "inleggen.py"])
    goed = len(fouten) == 1 and "inleggen.py" in fouten[0]
    print(f"  {'OK  ' if goed else 'FOUT'} gemengde PR: {len(fouten)} fout(en) "
          f"-- {fouten[0][:60] if fouten else 'geen'}")
    return goed


def test_alleen_toegestane_paden():
    """Een nette PR levert geen enkele fout op.

    Staat er eerst, met opzet: een controle die bij een gewone wijziging al
    piept, leer je binnen twee weken negeren.
    """
    fouten, _opm = g.controleer(["cvhj_model.py", "test_multi_periode.py", "README.md"])
    goed = fouten == []
    print(f"  {'OK  ' if goed else 'FOUT'} normale PR -> {fouten or 'geen fouten'}")
    return goed


def test_tellen_van_tests():
    """tel_tests() moet testfuncties tellen en niets anders."""
    tekst = (
        "def test_een():\n    pass\n\n"
        "def hulpje():\n    pass\n\n"
        "    def test_genest():\n        pass\n\n"
        "# def test_in_commentaar():\n"
        "def testiets():\n    pass\n"          # geen underscore: geen testfunctie
    )
    n = g.tel_tests(tekst)
    goed = n == 2
    print(f"  {'OK  ' if goed else 'FOUT'} telt {n} testfuncties (verwacht 2: "
          f"'def test_' met underscore, ook ingesprongen; niet in commentaar)")
    return goed


def test_krimpende_test_wordt_afgekeurd(monkeypatch_dir=None):
    """Een test die functies verliest, is de klassieke manier om een hek te slopen.

    We spelen dat na zonder git: bestand_bij_basis() en de bestandslezing
    worden tijdelijk vervangen, zodat deze test geen repository nodig heeft.
    """
    import pathlib

    oude_basis = g.bestand_bij_basis
    oude_regels = g.regels_gewijzigd
    oud_bestaat = pathlib.Path.exists
    oud_lees = pathlib.Path.read_text

    voor = "def test_a():\n    pass\n\ndef test_b():\n    pass\n\ndef test_c():\n    pass\n"
    na = "def test_a():\n    pass\n"

    g.bestand_bij_basis = lambda pad, basis: voor
    g.regels_gewijzigd = lambda basis: 10
    pathlib.Path.exists = lambda self: True
    pathlib.Path.read_text = lambda self, **kw: na
    try:
        fouten, _opm = g.controleer(["test_multi_periode.py"], basis="origin/main")
    finally:
        g.bestand_bij_basis = oude_basis
        g.regels_gewijzigd = oude_regels
        pathlib.Path.exists = oud_bestaat
        pathlib.Path.read_text = oud_lees

    goed = any("verliest testfuncties" in f and "3 -> 1" in f for f in fouten)
    print(f"  {'OK  ' if goed else 'FOUT'} 3 tests naar 1 -> "
          f"{fouten[0][:70] if fouten else 'GEEN FOUT (dat is fout)'}")
    return goed


def test_omvang():
    """Een herschrijving van honderden regels wordt afgekeurd, een kleine niet."""
    oude = g.regels_gewijzigd
    ok = True
    for n, mag in ((50, True), (399, True), (401, False), (2000, False)):
        g.regels_gewijzigd = lambda basis, n=n: n
        try:
            fouten, _opm = g.controleer(["cvhj_model.py"], basis="origin/main")
        finally:
            pass
        doorgelaten = not any("gewijzigde regels" in f for f in fouten)
        if doorgelaten != mag:
            print(f"  FOUT {n} regels: doorgelaten={doorgelaten}, verwacht {mag}")
            ok = False
    g.regels_gewijzigd = oude
    if ok:
        print(f"  OK   omvanggrens: tot {g.MAX_REGELS} regels door, daarboven afgekeurd")
    return ok


def main():
    print("welke bestanden een voorstel mag raken\n")
    ok1 = test_verboden_paden()
    ok2 = test_verboden_pad_keurt_af()
    ok3 = test_alleen_toegestane_paden()

    print("\ntests mogen niet verzwakt worden\n")
    ok4 = test_tellen_van_tests()
    ok5 = test_krimpende_test_wordt_afgekeurd()

    print("\nomvang\n")
    ok6 = test_omvang()

    print()
    if all([ok1, ok2, ok3, ok4, ok5, ok6]):
        print("OK: de grenzen keuren af wat ze horen af te keuren, en laten de rest door.")
    else:
        sys.exit("MISLUKT: zie hierboven -- een gat hier is niet zichtbaar in een "
                 "groene run.")


if __name__ == "__main__":
    main()
