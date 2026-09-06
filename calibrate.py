#!/usr/bin/env python3
"""
Zoekt KRIMP_SPELER en KRIMP_CLUB die de voorspelfout op de backtest
minimaliseren, in plaats van de waarden die nu op gevoel in cvhj_model.py staan.

Waarom dit uberhaupt geldig is: backtest.py evalueert ronde r met UITSLUITEND
data van ronden < r. Door de krimpconstanten te varieren en telkens dezelfde
backtest te draaien, wordt zichtbaar welke waarde de voorspelling op ONGEZIENE
rondes het best maakt. Dat is iets anders dan de constante fitten op de
trainingsdata zelf -- dat zou de vraag omzeilen, want de constante bepaalt
juist HOEVEEL de trainingsdata mag meewegen.

Gebruik:
    python calibrate.py                     # volledige grid, print tabel
    python calibrate.py --toepassen         # schrijft de beste RMSE-waarden
                                             # terug in cvhj_model.py

LET OP: met een paar evalueerbare rondes is dit een RICHTING, geen bewijs.
Zie backtest.py voor de beperkingen van de 'werkelijke punten'-proxy (geen
assists/kaarten/reddingen). Herhaal deze kalibratie zodra er meer rondes zijn
-- een instelling die nu wint kan bij 15 rondes weer verschuiven.

`auto_kalibreer.py` gebruikt `zoek_raster()` en `schrijf_constanten()` uit dit
bestand om dezelfde kalibratie periodiek en met waarborgen te draaien -- zie
daar voor de geautomatiseerde variant.
"""
import argparse
import itertools
import re
import sys
from pathlib import Path

from backtest import laad_model, evalueer_ronde

# Rond de huidige waarden heen (KRIMP_SPELER=8, KRIMP_CLUB=1.0), breed genoeg
# om ook een heel ander optimum te vinden als dat er is.
KRIMP_SPELER_GRID = [1, 2, 3, 4, 6, 8, 10, 12, 16, 20, 30]
KRIMP_CLUB_GRID = [0.25, 0.5, 1.0, 2.0, 4.0, 8.0]


def draai_backtest(m, clubrijen, spelerrijen, prijsrijen, vanaf, tot, venster, min_minuten):
    """Zelfde aggregatie als backtest.py's totaalregel, zonder de printregels."""
    resultaten = [evalueer_ronde(m, clubrijen, spelerrijen, prijsrijen, ronde, venster, min_minuten)
                  for ronde in range(vanaf, tot + 1)]
    resultaten = [r for r in resultaten if r]
    if not resultaten:
        return None
    n_tot = sum(r["n"] for r in resultaten)
    rmse = (sum(r["rmse"] ** 2 * r["n"] for r in resultaten) / n_tot) ** 0.5
    rhos = [r["spearman"] for r in resultaten if r["spearman"] is not None]
    rho = sum(rhos) / len(rhos) if rhos else None
    return {"rmse": rmse, "rho": rho, "n": n_tot, "per_ronde": resultaten}


def zoek_raster(m, clubrijen, spelerrijen, prijsrijen, vanaf, tot, venster, min_minuten,
                 grid_speler=None, grid_club=None):
    """Draait de backtest voor elke combinatie in het raster.

    Retourneert een lijst van (KRIMP_SPELER, KRIMP_CLUB, resultaat) tuples,
    resultaat zoals draai_backtest() die teruggeeft (inclusief 'per_ronde' voor
    een eventuele consistentiecheck). Herstelt m.KRIMP_SPELER/m.KRIMP_CLUB naar
    hun oorspronkelijke waarde voordat de functie teruggeeft.
    """
    grid_speler = grid_speler if grid_speler is not None else KRIMP_SPELER_GRID
    grid_club = grid_club if grid_club is not None else KRIMP_CLUB_GRID
    origineel_speler, origineel_club = m.KRIMP_SPELER, m.KRIMP_CLUB

    resultaten = []
    for ks, kc in itertools.product(grid_speler, grid_club):
        m.KRIMP_SPELER, m.KRIMP_CLUB = ks, kc
        r = draai_backtest(m, clubrijen, spelerrijen, prijsrijen, vanaf, tot, venster, min_minuten)
        if r:
            resultaten.append((ks, kc, r))

    m.KRIMP_SPELER, m.KRIMP_CLUB = origineel_speler, origineel_club  # herstellen voor de netheid
    return resultaten


def schrijf_constanten(pad, ks, kc):
    """Vervangt KRIMP_SPELER/KRIMP_CLUB in het gegeven bestand (Path of str).

    Retourneert True als er iets is aangepast, False als de regels niet zijn
    gevonden (bestand blijft dan ongewijzigd).
    """
    pad = Path(pad)
    s = pad.read_text(encoding="utf-8")
    s2 = re.sub(r"^KRIMP_CLUB = [\d.]+", f"KRIMP_CLUB = {float(kc)}", s, count=1, flags=re.M)
    s2 = re.sub(r"^KRIMP_SPELER = [\d.]+", f"KRIMP_SPELER = {float(ks)}", s2, count=1, flags=re.M)
    if s2 == s:
        return False
    pad.write_text(s2, encoding="utf-8")
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--clubs", default="clubs.csv")
    p.add_argument("--spelers", default="spelers.csv")
    p.add_argument("--prijzen", default="prijzen.csv")
    p.add_argument("--vanaf", type=int, default=2)
    p.add_argument("--tot", type=int)
    p.add_argument("--venster", type=int, default=6)
    p.add_argument("--min-minuten", type=int, default=60)
    p.add_argument("--toepassen", action="store_true",
                   help="schrijft de op RMSE beste waarden terug in cvhj_model.py")
    a = p.parse_args()

    m = laad_model()
    clubrijen = m.lees(a.clubs)
    spelerrijen = m.lees(a.spelers)
    prijsrijen = m.lees(a.prijzen)
    tot = a.tot or max(int(r["ronde"]) for r in clubrijen)

    origineel_speler, origineel_club = m.KRIMP_SPELER, m.KRIMP_CLUB

    print(f"Kalibratie op ronde {a.vanaf} t/m {tot}\n")
    print(f"{'KRIMP_SPELER':>13s}{'KRIMP_CLUB':>12s}{'RMSE':>8s}{'rho':>8s}{'n':>6s}")

    resultaten = zoek_raster(m, clubrijen, spelerrijen, prijsrijen, a.vanaf, tot, a.venster, a.min_minuten)

    if not resultaten:
        sys.exit("Geen enkele instelling leverde een evalueerbaar resultaat op.")

    for ks, kc, r in sorted(resultaten, key=lambda x: x[2]["rmse"]):
        rho_s = f"{r['rho']:.3f}" if r["rho"] is not None else "n.v.t."
        print(f"{ks:13d}{kc:12.2f}{r['rmse']:8.2f}{rho_s:>8s}{r['n']:6d}")

    huidige = next((r for ks, kc, r in resultaten if ks == origineel_speler and kc == origineel_club), None)
    beste_rmse = min(resultaten, key=lambda x: x[2]["rmse"])
    beste_rho = max((x for x in resultaten if x[2]["rho"] is not None),
                    key=lambda x: x[2]["rho"], default=None)

    print(f"\nHuidige instelling : KRIMP_SPELER={origineel_speler}  KRIMP_CLUB={origineel_club}")
    if huidige:
        rho_h = f"{huidige['rho']:.3f}" if huidige["rho"] is not None else "n.v.t."
        print(f"                     RMSE {huidige['rmse']:.2f}  rho {rho_h}")

    rho_rmse_s = f"{beste_rmse[2]['rho']:.3f}" if beste_rmse[2]["rho"] is not None else "n.v.t."
    print(f"\nBeste op RMSE      : KRIMP_SPELER={beste_rmse[0]}  KRIMP_CLUB={beste_rmse[1]:.2f}  "
          f"-> RMSE {beste_rmse[2]['rmse']:.2f}  rho {rho_rmse_s}")
    if beste_rho:
        print(f"Beste op rho       : KRIMP_SPELER={beste_rho[0]}  KRIMP_CLUB={beste_rho[1]:.2f}  "
              f"-> RMSE {beste_rho[2]['rmse']:.2f}  rho {beste_rho[2]['rho']:.3f}")

    if beste_rmse[:2] != beste_rho[:2] if beste_rho else False:
        print("\nLET OP: het optimum voor RMSE en voor rho ligt niet op dezelfde instelling.")
        print("Bij zo weinig rondes is dat te verwachten -- neem het verschil tussen de twee")
        print("als indicatie van hoe zeker deze kalibratie is, niet als een echte tegenstrijdigheid.")

    if a.toepassen:
        gekozen = beste_rmse  # RMSE als primair criterium: conservatiever dan rho bij een kleine steekproef
        if not schrijf_constanten("cvhj_model.py", gekozen[0], gekozen[1]):
            sys.exit("Kon KRIMP_SPELER/KRIMP_CLUB niet vinden om te vervangen -- bestand niet gewijzigd.")
        print(f"\ncvhj_model.py bijgewerkt: KRIMP_SPELER={gekozen[0]}, KRIMP_CLUB={gekozen[1]:.2f}")


if __name__ == "__main__":
    main()
