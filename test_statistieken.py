#!/usr/bin/env python3
"""
Regressietest voor scrape_statistieken.py -- zonder netwerk.

De fixture-HTML is nagebouwd naar de echte ranglijstpagina: kolommen
'# / Speler / Assists', met de club achter een komma in de spelercel
("Irakli Yegoian, Excelsior"). Dat komma-formaat is waar de koppeling met
spelers.csv op staat of valt.

Er wordt ook een variant getest MET een per-90-kolom erbij. De site claimt
die te tonen, maar op de pagina die ik heb ingezien stond hij niet -- dus de
parser mag er niet van uitgaan en er ook niet over struikelen. Hij pakt de
totalen en rekent zelf om, met de minuten uit spelers.csv.

    python test_statistieken.py
"""
import sys

import scrape_statistieken as s

ZONDER_PER90 = """
<table>
  <tr><th>#</th><th>Speler</th><th>Assists</th></tr>
  <tr><td>1</td><td>Irakli Yegoian, Excelsior</td><td>4</td></tr>
  <tr><td>2</td><td>Mateo Chávez, AZ</td><td>3</td></tr>
  <tr><td>3</td><td>Gjivai Zechiël, Feyenoord</td><td>3</td></tr>
</table>
"""

MET_PER90 = """
<table>
  <tr><th>#</th><th>Speler</th><th>Assists</th><th>Per 90</th></tr>
  <tr><td>1</td><td>Irakli Yegoian, Excelsior</td><td>4</td><td>0,84</td></tr>
  <tr><td>2</td><td>Mateo Chávez, AZ</td><td>3</td><td>0,61</td></tr>
</table>
"""

# Een tabel met een andere kolomvolgorde, om te zien dat er op koptekst
# gezocht wordt en niet op positie.
ANDERE_VOLGORDE = """
<table>
  <tr><th>Speler</th><th>Club</th><th>Gele kaarten</th></tr>
  <tr><td>Bram Nuytinck, N.E.C.</td><td>N.E.C.</td><td>3</td></tr>
</table>
"""


def test_splits_speler():
    gevallen = [
        ("Irakli Yegoian, Excelsior", "Irakli Yegoian", "Excelsior"),
        ("Gjivai Zechiël, Feyenoord", "Gjivai Zechiël", "Feyenoord"),
        ("Bram Nuytinck, N.E.C.", "Bram Nuytinck", "N.E.C."),
        ("Zonder Komma", "Zonder Komma", ""),
        ("  dubbele   spaties , AZ ", "dubbele spaties", "AZ"),
    ]
    ok = True
    for invoer, vn, vc in gevallen:
        naam, club = s.splits_speler(invoer)
        goed = naam == vn and club == vc
        print(f"  {'OK  ' if goed else 'FOUT'} {invoer!r:34s} -> {naam!r}, {club!r}")
        ok = ok and goed
    return ok


def test_parse_ranglijst():
    ok = True

    rijen = s.parse_ranglijst(ZONDER_PER90, "assist")
    goed = rijen == [("Irakli Yegoian", "Excelsior", 4.0),
                     ("Mateo Chávez", "AZ", 3.0),
                     ("Gjivai Zechiël", "Feyenoord", 3.0)]
    print(f"  {'OK  ' if goed else 'FOUT'} zonder per-90-kolom: {rijen}")
    ok = ok and goed

    # Met een per-90-kolom erbij moeten de TOTALEN eruit komen, niet de per-90's.
    rijen = s.parse_ranglijst(MET_PER90, "assist")
    goed = rijen == [("Irakli Yegoian", "Excelsior", 4.0), ("Mateo Chávez", "AZ", 3.0)]
    print(f"  {'OK  ' if goed else 'FOUT'} met per-90-kolom, totalen gepakt: {rijen}")
    ok = ok and goed

    rijen = s.parse_ranglijst(ANDERE_VOLGORDE, "geel")
    goed = rijen == [("Bram Nuytinck", "N.E.C.", 3.0)]
    print(f"  {'OK  ' if goed else 'FOUT'} andere kolomvolgorde: {rijen}")
    ok = ok and goed

    goed = s.parse_ranglijst("<p>geen tabel</p>", "assist") == []
    print(f"  {'OK  ' if goed else 'FOUT'} pagina zonder tabel geeft een lege lijst")
    return ok and goed


def test_getal():
    gevallen = [("4", 4.0), ("0,84", 0.84), ("1.238", 1.238), ("", None),
                ("-", None), ("12 x", 12.0)]
    ok = True
    for invoer, verwacht in gevallen:
        gekregen = s.getal(invoer)
        goed = gekregen == verwacht
        if not goed:
            print(f"  FOUT {invoer!r} -> {gekregen!r} (verwacht {verwacht!r})")
        ok = ok and goed
    if ok:
        print(f"  OK   {len(gevallen)} getalformaten correct verwerkt")
    return ok


def test_koppeling_met_model():
    """spelerstats.csv uit dit script moet leesbaar zijn voor cvhj_model.lees_spelerstats()."""
    import csv
    import tempfile
    from pathlib import Path

    import cvhj_model as m

    velden = ["speler", "club", "positie", "wedstrijden", "minuten_90s",
              "goals_per90", "xg_per90", "assists_per90", "xag_per90",
              "gele_kaarten", "rode_kaarten"]
    rij = {"speler": "Gjivai Zechiël", "club": "Feyenoord", "positie": "",
           "wedstrijden": 5, "minuten_90s": 4.8889, "goals_per90": 0.8182,
           "xg_per90": 0.8182, "assists_per90": 0.6136, "xag_per90": 0.6136,
           "gele_kaarten": 1.0, "rode_kaarten": 0.0}
    ok = True
    with tempfile.TemporaryDirectory() as d:
        pad = Path(d) / "spelerstats.csv"
        with pad.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=velden)
            w.writeheader()
            w.writerow(rij)

        geladen = m.lees_spelerstats(str(pad))
        sleutel = f"{m.norm('Gjivai Zechiël')}|{m.norm(m.norm_club('Feyenoord'))}"
        fb = (geladen or {}).get(sleutel)
        goed = fb is not None
        print(f"  {'OK  ' if goed else 'FOUT'} lees_spelerstats() vindt de regel onder {sleutel!r}")
        ok = ok and goed
        if fb:
            # assists en xag zijn gelijk, dus het middelen in bouw_pool() is neutraal
            goed = abs(fb["assists_per90"] - fb["xag_per90"]) < 1e-9
            print(f"  {'OK  ' if goed else 'FOUT'} assists_per90 == xag_per90 "
                  f"({fb['assists_per90']}) -- middelen is een no-op, geen vertekening")
            ok = ok and goed
    return ok


def main():
    print("naam en club uit de spelercel\n")
    ok1 = test_splits_speler()
    print("\ngetalformaten\n")
    ok2 = test_getal()
    print("\nranglijst ontleden\n")
    ok3 = test_parse_ranglijst()
    print("\nkoppeling met cvhj_model.py\n")
    ok4 = test_koppeling_met_model()

    print()
    if all([ok1, ok2, ok3, ok4]):
        print("OK: scrape_statistieken.py levert data die het model ongewijzigd kan lezen.")
    else:
        sys.exit("MISLUKT: zie hierboven.")


if __name__ == "__main__":
    main()
