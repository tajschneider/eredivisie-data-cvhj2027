#!/usr/bin/env python3
"""
Regressietest voor scrape_sofascore.py -- zonder netwerk.

Waarom dit bestand er is: het script zelf kon in de bouwomgeving niet live
gedraaid worden (zie zijn moduledocstring). Wat WEL kon, is de echte respons
van het endpoint bekijken. De fixture hieronder is daarom geen verzinsel maar
een letterlijke kopie van echte velden en waarden uit die respons -- inclusief
Gjivai Zechiel bij Feyenoord (4 goals, 3 assists, xG 1.83, xAG 1.71, 440
minuten). Zo test dit bestand de omrekening en de koppeling tegen data die
echt zo uit Sofascore komt.

De belangrijkste test is de laatste: xg.csv moet door cvhj_model.lees_fbref()
gelezen kunnen worden EN de sleutel moet matchen met de schrijfwijze uit
pouletips. Sofascore schrijft "Gjivai Zechiel" (zonder trema), pouletips
"Gjivai Zechiël" (met). Als norm() die twee niet op elkaar afbeeldt, valt de
speler stil uit het model zonder dat er iets crasht -- precies het soort
stille fout waar dit project niet op wil vertrouwen.

    python test_sofascore.py
"""
import csv
import sys
import tempfile
from pathlib import Path

import scrape_sofascore as s

# Letterlijk de veldnamen en waarden zoals het echte endpoint ze teruggaf.
FIXTURE = [
    {"goals": 4, "assists": 3, "expectedGoals": 1.83, "expectedAssists": 1.71,
     "yellowCards": 1, "redCards": 0, "minutesPlayed": 440, "appearances": 5,
     "player": {"name": "Gjivai Zechiel"}, "team": {"name": "Feyenoord"}},
    {"goals": 2, "assists": 0, "expectedGoals": 0.62, "expectedAssists": 0.30,
     "yellowCards": 2, "redCards": 1, "minutesPlayed": 900, "appearances": 10,
     "player": {"name": "Irakli Yegoian"}, "team": {"name": "Excelsior"}},
    # Clubnamen die Sofascore anders schrijft dan clubs.csv.
    {"goals": 1, "assists": 1, "expectedGoals": 0.90, "expectedAssists": 0.80,
     "yellowCards": 0, "redCards": 0, "minutesPlayed": 450, "appearances": 5,
     "player": {"name": "Testspeler AZ"}, "team": {"name": "AZ Alkmaar"}},
    {"goals": 0, "assists": 0, "expectedGoals": 0.10, "expectedAssists": 0.05,
     "yellowCards": 0, "redCards": 0, "minutesPlayed": 90, "appearances": 1,
     "player": {"name": "Testspeler Ajax"}, "team": {"name": "AFC Ajax"}},
    # Zonder speeltijd: moet wegvallen, niet delen door nul.
    {"goals": 0, "assists": 0, "expectedGoals": 0, "expectedAssists": 0,
     "yellowCards": 0, "redCards": 0, "minutesPlayed": 0, "appearances": 0,
     "player": {"name": "Bankzitter Zonder Minuten"}, "team": {"name": "Telstar"}},
]

# Alle 18 clubnamen zoals Sofascore ze in seizoen 26/27 schrijft (nagelopen in
# de echte respons), met de schrijfwijze die clubs.csv/pouletips gebruikt.
CLUBS_ECHT = {
    "FC Groningen": "FC Groningen", "ADO Den Haag": "ADO Den Haag",
    "PEC Zwolle": "PEC Zwolle", "Fortuna Sittard": "Fortuna Sittard",
    "AZ Alkmaar": "AZ", "SC Cambuur": "SC Cambuur",
    "SC Heerenveen": "sc Heerenveen", "PSV Eindhoven": "PSV",
    "Feyenoord": "Feyenoord", "Sparta Rotterdam": "Sparta Rotterdam",
    "Excelsior": "Excelsior", "FC Utrecht": "FC Utrecht",
    "SC Telstar": "Telstar", "NEC Nijmegen": "NEC",
    "FC Twente": "FC Twente", "Willem II Tilburg": "Willem II",
    "Go Ahead Eagles": "Go Ahead Eagles", "AFC Ajax": "Ajax",
}


def bijna(a, b, marge=0.001):
    return abs(a - b) < marge


def test_omrekening():
    rijen = s.naar_rijen(FIXTURE)
    ok = True

    n_verwacht = len(FIXTURE) - 1          # de speler zonder minuten valt af
    goed = len(rijen) == n_verwacht
    print(f"  {'OK  ' if goed else 'FOUT'} {len(rijen)} rijen (verwacht {n_verwacht}: "
          f"speler zonder minuten valt weg)")
    ok = ok and goed

    z = next((r for r in rijen if r["speler"] == "Gjivai Zechiel"), None)
    if not z:
        print("  FOUT Zechiel niet in de uitvoer")
        return False

    # 440 minuten = 4,888... negentigers; alle per-90's daaruit.
    verwacht = {
        "minuten_90s": 440 / 90,
        "goals_per90": 4 / (440 / 90),
        "xg_per90": 1.83 / (440 / 90),
        "assists_per90": 3 / (440 / 90),
        "xag_per90": 1.71 / (440 / 90),
    }
    for sleutel, waarde in verwacht.items():
        goed = bijna(z[sleutel], waarde)
        print(f"  {'OK  ' if goed else 'FOUT'} {sleutel:14s} {z[sleutel]:.4f} "
              f"(verwacht {waarde:.4f})")
        ok = ok and goed

    # Kaarten blijven seizoenstotalen, geen per-90 -- net als in het oude fbref.csv,
    # want cvhj_model.py rekent ze daar zelf om.
    goed = z["gele_kaarten"] == 1 and z["rode_kaarten"] == 0
    print(f"  {'OK  ' if goed else 'FOUT'} kaarten blijven totalen: geel {z['gele_kaarten']}, "
          f"rood {z['rode_kaarten']}")
    ok = ok and goed

    goed = z["wedstrijden"] == 5
    print(f"  {'OK  ' if goed else 'FOUT'} wedstrijden {z['wedstrijden']} (verwacht 5)")
    return ok and goed


def test_clubnamen():
    ok = True
    for sofascore_naam, verwacht in CLUBS_ECHT.items():
        gekregen = s.norm_club(sofascore_naam)
        goed = gekregen == verwacht
        if not goed:
            print(f"  FOUT {sofascore_naam!r} -> {gekregen!r} (verwacht {verwacht!r})")
        ok = ok and goed
    if ok:
        print(f"  OK   alle {len(CLUBS_ECHT)} clubnamen worden goed omgezet")
    return ok


def test_paginering():
    """haal_spelers() moet doorpagineren tot een korte pagina komt."""
    paginas = [
        [{"player": {"name": f"Speler {i}"}, "team": {"name": "Feyenoord"},
          "minutesPlayed": 90, "goals": 0, "assists": 0, "expectedGoals": 0,
          "expectedAssists": 0, "yellowCards": 0, "redCards": 0, "appearances": 1}
         for i in range(100)],
        [{"player": {"name": "Laatste Speler"}, "team": {"name": "Feyenoord"},
          "minutesPlayed": 90, "goals": 0, "assists": 0, "expectedGoals": 0,
          "expectedAssists": 0, "yellowCards": 0, "redCards": 0, "appearances": 1}],
    ]
    beurten = []

    def nep_haal_json(url, params=None, **kw):
        beurten.append(params["offset"])
        return {"results": paginas[len(beurten) - 1]}

    echt, s.haal_json = s.haal_json, nep_haal_json
    s.time.sleep = lambda _: None
    try:
        alles = s.haal_spelers(37, 96143)
    finally:
        s.haal_json = echt

    goed = len(alles) == 101 and beurten == [0, 100]
    print(f"  {'OK  ' if goed else 'FOUT'} {len(alles)} spelers over {len(beurten)} pagina's "
          f"(offsets {beurten}; verwacht 101 over [0, 100])")
    return goed


def test_koppeling_met_model():
    """De kern: xg.csv moet leesbaar zijn voor het model EN matchen op naam.

    Sofascore schrijft 'Gjivai Zechiel', pouletips 'Gjivai Zechiël'. Beide
    moeten na cvhj_model.norm() dezelfde sleutel opleveren, anders valt de
    speler stilzwijgend uit de xG-verrijking.
    """
    import cvhj_model as m

    rijen = s.naar_rijen(FIXTURE)
    velden = ["speler", "club", "positie", "wedstrijden", "minuten_90s",
              "goals_per90", "xg_per90", "assists_per90", "xag_per90",
              "gele_kaarten", "rode_kaarten"]
    ok = True
    with tempfile.TemporaryDirectory() as d:
        pad = Path(d) / "xg.csv"
        with pad.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=velden)
            w.writeheader()
            for r in rijen:
                w.writerow(r)

        geladen = m.lees_fbref(str(pad))
        goed = geladen is not None and len(geladen) == len(rijen)
        print(f"  {'OK  ' if goed else 'FOUT'} lees_fbref() laadt {len(geladen or [])} spelers "
              f"uit xg.csv")
        ok = ok and goed

        # De sleutel zoals bouw_pool() hem opzoekt, met de POULETIPS-schrijfwijze
        # (met trema) -- die moet de Sofascore-regel (zonder trema) vinden.
        sleutel = f"{m.norm('Gjivai Zechiël')}|{m.norm(m.norm_club('Feyenoord'))}"
        fb = (geladen or {}).get(sleutel)
        goed = fb is not None
        print(f"  {'OK  ' if goed else 'FOUT'} pouletips-naam 'Gjivai Zechiël' vindt de "
              f"Sofascore-regel 'Gjivai Zechiel' (sleutel {sleutel!r})")
        ok = ok and goed

        if fb:
            goed = bijna(fb["xg_per90"], 1.83 / (440 / 90)) and bijna(fb["minuten_90s"], 440 / 90)
            print(f"  {'OK  ' if goed else 'FOUT'} waarden komen door: xg_per90 "
                  f"{fb['xg_per90']:.4f}, minuten_90s {fb['minuten_90s']:.4f}")
            ok = ok and goed

        # Ook de omgezette clubnamen moeten vindbaar zijn onder de clubs.csv-spelling.
        for naam, club in (("Testspeler AZ", "AZ"), ("Testspeler Ajax", "Ajax")):
            k = f"{m.norm(naam)}|{m.norm(club)}"
            goed = k in (geladen or {})
            print(f"  {'OK  ' if goed else 'FOUT'} {naam} vindbaar onder club {club!r}")
            ok = ok and goed

    return ok


def main():
    print("omrekening naar per-90\n")
    ok1 = test_omrekening()
    print("\nclubnamen\n")
    ok2 = test_clubnamen()
    print("\npaginering\n")
    ok3 = test_paginering()
    print("\nkoppeling met cvhj_model.py\n")
    ok4 = test_koppeling_met_model()

    print()
    if ok1 and ok2 and ok3 and ok4:
        print("OK: scrape_sofascore.py levert data die het model ongewijzigd kan lezen.")
    else:
        sys.exit("MISLUKT: zie hierboven.")


if __name__ == "__main__":
    main()
