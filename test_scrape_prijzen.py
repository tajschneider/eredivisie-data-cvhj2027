#!/usr/bin/env python3
"""
Regressietest voor scrape_prijzen.py's splits_status() en cvhj_model.py's
vind_bijna_match() -- het vangnet voor precies het faalpatroon dat Thomas op
6 september 2026 meldde: een advies om "Gjivai Zechiël" te transfereren voor
"Gjivai Zechiël" (dezelfde speler), veroorzaakt door een niet-gestript
statuswoord in prijzen.csv's naamkolom ("Gjivai Zechiël basis" i.p.v.
"Gjivai Zechiël") waardoor de naam niet meer matcht met selectie.csv.

Draai dit na elke wijziging aan STATUS_RE/splits_status() of aan
vind_bijna_match():

    python test_scrape_prijzen.py

Vereist geen CSV-bestanden -- alle invoer is synthetisch.
"""
import sys

from scrape_prijzen import splits_status


def test_splits_status():
    gevallen = [
        # (invoer, verwachte naam, verwachte rol)
        ("Sekou Sylla bank", "Sekou Sylla", "bank"),
        ("Calvin Stengs basis nieuw", "Calvin Stengs", "basis"),
        ("Gjivai Zechiël basis", "Gjivai Zechiël", "basis"),
        ("Gjivai Zechiël", "Gjivai Zechiël", ""),
        # De hoofdletterongevoelige fix (case 6 sept. 2026): een status-woord
        # met een andere hoofdletter moet nu ook gestript worden.
        ("Gjivai Zechiël Basis", "Gjivai Zechiël", "basis"),
        ("Gjivai Zechiël BASIS", "Gjivai Zechiël", "basis"),
        ("Calvin Stengs Bank", "Calvin Stengs", "bank"),
        ("Calvin Stengs Nieuw", "Calvin Stengs", ""),  # nieuw is een vlag, geen rol
        # Non-breaking space (\xa0), zoals &nbsp; uit HTML kan opleveren.
        ("Gjivai Zechiël\xa0basis", "Gjivai Zechiël", "basis"),
        # Haakjes rond het statuswoord mogen geen lege "()" achterlaten.
        ("Gjivai Zechiël (basis)", "Gjivai Zechiël", "basis"),
        # Blessuremarkering blijft ongewijzigd werken (regressie t.o.v. bestaand gedrag).
        ("Jordan Bos ! geblesseerd tot en met 1 januari", "Jordan Bos", ""),
    ]
    ok = True
    for invoer, verw_naam, verw_rol in gevallen:
        naam, status = splits_status(invoer)
        goed = naam == verw_naam and status["rol"] == verw_rol
        print(f"  {'OK  ' if goed else 'FOUT'} {invoer!r:45s} -> {naam!r}, rol={status['rol']!r}"
              + ("" if goed else f"  (verwacht {verw_naam!r}, rol={verw_rol!r})"))
        ok = ok and goed
    return ok


def test_status_restant():
    """De controle die scrape_prijzen.py na elke run zelf uitvoert.

    Hij moet een statuswoord vinden dat aan een naam blijft plakken, en met
    rust laten wat gewoon een Nederlandse achternaam is -- 'Nieuwkoop' mag
    geen vals alarm geven, anders leert het je de melding te negeren.
    """
    from scrape_prijzen import STATUS_RESTANT

    schoon = ["Bas Dost", "Sebastiaan Bornauw", "Nieuwkoop", "Bastian Nieuwkoop",
              "Basim Ahmed", "Gjivai Zechiël", "Tjaronn Chery", "Nieuwenhuis"]
    vervuild = ["Tjaronn Chery basis", "Kjetil Haug nieuw", "Rafik El Arguioui bank",
                "Gjivai Zechiël Basis", "Iemand basisspeler", "Iemand bankzitter"]
    ok = True
    for n in schoon:
        goed = STATUS_RESTANT.search(n) is None
        if not goed:
            print(f"  FOUT {n!r} wordt ten onrechte als vervuild gezien")
        ok = ok and goed
    for n in vervuild:
        goed = STATUS_RESTANT.search(n) is not None
        if not goed:
            print(f"  FOUT {n!r} wordt niet als vervuild herkend")
        ok = ok and goed
    if ok:
        print(f"  OK   {len(schoon)} schone namen met rust gelaten, "
              f"{len(vervuild)} vervuilde namen herkend")
    return ok


def test_vind_bijna_match():
    import cvhj_model as m

    pool = [
        {"speler": "Gjivai Zechiël basis", "club": "Feyenoord", "E": 7.60},
        {"speler": "Calvin Stengs", "club": "Feyenoord", "E": 5.0},
        {"speler": "Jordan Bos", "club": "AZ", "E": 4.0},
    ]
    ok = True

    # 1. De hoofdcasus: een vervuilde naam in de pool moet gevonden worden.
    y = m.vind_bijna_match("Gjivai Zechiël", "Feyenoord", pool)
    goed = y is not None and y["speler"] == "Gjivai Zechiël basis"
    print(f"  {'OK  ' if goed else 'FOUT'} vind_bijna_match('Gjivai Zechiël', 'Feyenoord', ...) -> "
          f"{y['speler'] if y else None!r}")
    ok = ok and goed

    # 2. Andere club: geen match, ook al is de naam (bijna) gelijk.
    y = m.vind_bijna_match("Gjivai Zechiël", "AZ", pool)
    goed = y is None
    print(f"  {'OK  ' if goed else 'FOUT'} andere club -> geen match ({y!r})")
    ok = ok and goed

    # 3. Compleet andere speler, zelfde club: geen match.
    y = m.vind_bijna_match("Ramiz Zerrouki", "Feyenoord", pool)
    goed = y is None
    print(f"  {'OK  ' if goed else 'FOUT'} andere speler, zelfde club -> geen match ({y!r})")
    ok = ok and goed

    # 4. Exacte match hoort hier NIET als "bijna"-match uit te komen (die wordt
    #    al gewoon rechtstreeks gematcht, dit vangnet is alleen voor het niet-
    #    exacte geval).
    y = m.vind_bijna_match("Calvin Stengs", "Feyenoord", pool)
    goed = y is None
    print(f"  {'OK  ' if goed else 'FOUT'} exacte match geeft geen bijna-match ({y!r})")
    ok = ok and goed

    return ok


def main():
    print("splits_status()\n")
    ok1 = test_splits_status()
    print("\nnaam-restcontrole (draait na elke scrape)\n")
    ok3 = test_status_restant()
    print("\nvind_bijna_match()\n")
    ok2 = test_vind_bijna_match()

    print()
    if ok1 and ok2 and ok3:
        print("OK: splits_status() en vind_bijna_match() gedragen zich zoals verwacht.")
    else:
        sys.exit("MISLUKT: zie hierboven.")


if __name__ == "__main__":
    main()
