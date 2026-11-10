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

    rijen = s.parse_ranglijst(ANDERE_VOLGORDE, "kaart")
    goed = rijen == [("Bram Nuytinck", "N.E.C.", 3.0)]
    print(f"  {'OK  ' if goed else 'FOUT'} andere kolomvolgorde: {rijen}")
    ok = ok and goed

    goed = s.parse_ranglijst("<p>geen tabel</p>", "assist") == []
    print(f"  {'OK  ' if goed else 'FOUT'} pagina zonder tabel geeft een lege lijst")
    return ok and goed


KAARTEN_MET_STOORKOLOM = """
<table>
  <tr><th>Speler</th><th>Wedstrijden</th><th>Gele kaarten</th></tr>
  <tr><td>Bram Nuytinck, N.E.C.</td><td>7</td><td>3</td></tr>
</table>
"""


def test_kaartkolom_op_koptekst():
    """De kaartkolom moet op de KOP gevonden worden, niet op "eerste getal".

    CATEGORIEEN zocht op "geel" en "rood", terwijl de kop "Gele kaarten" is --
    en `"geel" in "gele kaarten"` is onwaar. Beide kaartcategorieen vielen dus
    altijd terug op "de eerste cel na de spelernaam die een getal bevat". Met
    de kolomvolgorde van vandaag gaat dat toevallig goed; zet pouletips er een
    kolom Wedstrijden of Minuten tussen, dan wordt dat getal als kaartaantal
    weggeschreven. Geen crash, geen melding, en met -3,0 punt per gele kaart
    per 90 minuten een gesloopte rangorde in je verdediging.

    Deze test zet die stoorkolom er expliciet in: met de oude koptekst komt er
    7 uit (wedstrijden), met de nieuwe 3 (kaarten).
    """
    kopteksten = {sleutel: kop for sleutel, _pad, kop in s.CATEGORIEEN}
    ok = True
    for sleutel in ("gele_kaarten", "rode_kaarten"):
        kop = kopteksten[sleutel]
        goed = kop in "gele kaarten" or kop in "rode kaarten"
        print(f"  {'OK  ' if goed else 'FOUT'} {sleutel}: koptekst {kop!r} komt voor "
              f"in de echte kop")
        ok = ok and goed

    rijen = s.parse_ranglijst(KAARTEN_MET_STOORKOLOM, kopteksten["gele_kaarten"])
    goed = rijen == [("Bram Nuytinck", "N.E.C.", 3.0)]
    print(f"  {'OK  ' if goed else 'FOUT'} kolom Wedstrijden ertussen: {rijen} "
          f"(3.0 = kaarten, 7.0 zou wedstrijden zijn)")
    return ok and goed


# De opmaak zoals pouletips.nl die op 10-11-2026 serveerde: een eigen
# Club-kolom, de naam als link in de spelercel, en de clubnaam daar NOG EENS
# achter zonder scheidingsteken. Overgenomen van de echte pagina, niet verzonnen.
MET_CLUBKOLOM = """
<table>
  <tr><th>#</th><th>Speler</th><th>Club</th><th>Assists</th><th>Per 90</th>
      <th>Duels</th><th>Min.</th></tr>
  <tr><td>1</td>
      <td><a href="/eredivisie/speler/sondre-rjaster/">Sondre \u00d8rjas\u00e6ter</a> FC Twente</td>
      <td><img alt="FC Twente logo"/><a href="/eredivisie/twente/">FC Twente</a></td>
      <td>7</td><td>0,76</td><td>11</td><td>824</td></tr>
  <tr><td>2</td>
      <td><a href="/eredivisie/speler/oscar-gloukh/">Oscar Gloukh</a> Ajax</td>
      <td><img alt="Ajax logo"/><a href="/eredivisie/ajax/">Ajax</a></td>
      <td>6</td><td>0,71</td><td>12</td><td>759</td></tr>
  <tr><td>3</td>
      <td><a href="/eredivisie/speler/irakli-yegoian/">Irakli Yegoian</a> Excelsior</td>
      <td><img alt="Excelsior logo"/><a href="/eredivisie/excelsior/">Excelsior</a></td>
      <td>5</td><td>0,43</td><td>12</td><td>1.038</td></tr>
  <tr><td>4</td>
      <td><a href="/eredivisie/speler/nokkvi-thorisson/">N\u00f6kkvi Th\u00f3risson</a> Telstar, Sparta Rotterdam</td>
      <td>Telstar, Sparta Rotterdam</td>
      <td>1</td><td>0,13</td><td>11</td><td>694</td></tr>
</table>
"""


def test_clubkolom_in_plaats_van_komma():
    """De naam komt uit de link, de club uit de Club-kolom.

    Op 10-11-2026 koppelde geen enkele rij meer: 0 van 40 op assists,
    doelpunten en gele kaarten. splits_speler() splitst op een komma, en die
    staat er niet meer tussen naam en club -- de hele cel werd de naam.
    """
    verwacht = [
        ("Sondre \u00d8rjas\u00e6ter", "FC Twente", 7),
        ("Oscar Gloukh", "Ajax", 6),
        ("Irakli Yegoian", "Excelsior", 5),
        # Twee clubs: de komma scheidt hier de CLUBS, niet naam en club. De
        # naam blijft schoon doordat hij uit de link komt.
        ("N\u00f6kkvi Th\u00f3risson", "Telstar, Sparta Rotterdam", 1),
    ]
    gekregen = s.parse_ranglijst(MET_CLUBKOLOM, "assist")
    ok = gekregen == verwacht
    if not ok:
        print(f"  FOUT {gekregen!r}")
        print(f"       verwacht {verwacht!r}")
    else:
        print(f"  OK   {len(verwacht)} rijen: naam uit de link, club uit de kolom")
    return ok


def test_koppelt_aan_echte_spelers():
    """De gelezen namen moeten koppelen aan spelers.csv zoals het er staat.

    Dit is de toets die er werkelijk om gaat: parsen zonder koppelen levert nog
    steeds nul gevulde rijen. De sleutel is norm(speler)|norm(club), precies
    zoals main() hem bouwt.
    """
    import csv
    from pathlib import Path
    pad = Path(__file__).parent / "spelers.csv"
    if not pad.exists():
        print("  (spelers.csv ontbreekt, koppeling niet getoetst)")
        return True

    per = {}
    with pad.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = r.get("speler_id") or s.norm(r["speler"])
            per[sid] = {"speler": r["speler"], "club": r["club"]}
    op_naam_club = {f"{s.norm(d['speler'])}|{s.norm(d['club'])}": sid
                    for sid, d in per.items()}
    op_naam = {}
    for sid, d in per.items():
        op_naam.setdefault(s.norm(d["speler"]), []).append(sid)

    ok = True
    for naam, club, _ in s.parse_ranglijst(MET_CLUBKOLOM, "assist"):
        sid = op_naam_club.get(f"{s.norm(naam)}|{s.norm(club)}")
        if sid is None:
            kandidaten = op_naam.get(s.norm(naam), [])
            sid = kandidaten[0] if len(kandidaten) == 1 else None
        if sid is None:
            print(f"  FOUT {naam} ({club}) koppelt niet aan spelers.csv")
            ok = False
    if ok:
        print("  OK   elke gelezen rij koppelt aan een speler_id uit spelers.csv")
    return ok


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
    return ok


def test_afspraken_over_xg_en_xag():
    """xg_per90 == goals_per90 en xag_per90 == assists_per90, via de ECHTE code.

    Dit zijn de twee afspraken uit de moduledocstring van
    scrape_statistieken.py: er is geen xG-bron meer, dus xg_per90 is het
    seizoensdoelpunttempo, en xag_per90 is gelijkgezet aan assists_per90
    zodat het middelen in cvhj_model.py neutraal is in plaats van
    vertekenend.

    Deze test riep eerder s.bouw_rij() NIET aan. Hij schreef een rij met de
    hand weg, waarin assists en xag al gelijk waren gezet, en toetste daarna
    dat ze gelijk waren. Die test kon niet falen: je kon bouw_rij() willekeurig
    slopen en hij bleef groen. Nu komt de rij uit de productiecode.
    """
    rij = s.bouw_rij(
        {"speler": "Testspeler", "club": "Ajax", "duels": 4, "minuten": 360},
        {"assists": 3.0, "doelpunten": 2.0, "gele_kaarten": 1.0, "rode_kaarten": 0.0})

    proeven = [
        ("xg_per90 == goals_per90", rij["xg_per90"], rij["goals_per90"]),
        ("xag_per90 == assists_per90", rij["xag_per90"], rij["assists_per90"]),
    ]
    ok = True
    for wat, a, b in proeven:
        goed = abs(a - b) < 1e-9
        print(f"  {'OK  ' if goed else 'FOUT'} {wat} ({a} vs {b})")
        ok = ok and goed

    # En de per-90's moeten echt gedeeld zijn door de 90-tallen, niet de ruwe
    # telling doorgeven: 3 assists in 360 minuten is 0,75 per 90.
    goed = abs(rij["assists_per90"] - 0.75) < 1e-4 and abs(rij["minuten_90s"] - 4.0) < 1e-9
    print(f"  {'OK  ' if goed else 'FOUT'} 3 assists in 360 min -> "
          f"{rij['assists_per90']} per 90 (verwacht 0.75)")
    return ok and goed


def main():
    print("naam en club uit de spelercel\n")
    ok1 = test_splits_speler()
    print("\ngetalformaten\n")
    ok2 = test_getal()
    print("\nranglijst ontleden\n")
    ok3 = test_parse_ranglijst()
    print("\nkaartkolom op koptekst\n")
    ok3b = test_kaartkolom_op_koptekst()
    print("\nkoppeling met cvhj_model.py\n")
    ok4 = test_koppeling_met_model()
    print("\nafspraken over xg en xag (via bouw_rij)\n")
    ok5 = test_afspraken_over_xg_en_xag()

    print("\nde Club-kolom in plaats van een komma\n")
    ok6 = test_clubkolom_in_plaats_van_komma()

    print("\nkoppeling aan spelers.csv zoals het er staat\n")
    ok7 = test_koppelt_aan_echte_spelers()

    print()
    if all([ok1, ok2, ok3, ok3b, ok4, ok5, ok6, ok7]):
        print("OK: scrape_statistieken.py levert data die het model ongewijzigd kan lezen.")
    else:
        sys.exit("MISLUKT: zie hierboven.")


if __name__ == "__main__":
    main()
