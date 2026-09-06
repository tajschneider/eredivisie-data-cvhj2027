#!/usr/bin/env python3
"""
Draait calibrate.py's rasterzoektocht automatisch, elke KALIBREER_ELKE ronden,
en past KRIMP_SPELER/KRIMP_CLUB alleen aan als het bewijs sterk genoeg is.

Dit bestaat omdat de handmatige kalibratie op ronde 2-4 een valkuil blootlegde:
de rastere winnaar (KRIMP_SPELER=20, KRIMP_CLUB=8.0) zag er in de TOTAALREGEL
beter uit dan de huidige waarden (RMSE 3.25 tegen 3.27), maar per ronde bleek
het verschil niet consistent -- ronde 2 werd er ZWAKKER van. Bij drie
evalueerbare rondes is 0,02 RMSE-verschil ruis, geen signaal. Dit script mag
dus niet zomaar de rastere winnaar overnemen; het moet dezelfde vraag stellen
die handmatig hierboven beantwoord is, en dat consequent bij elke automatische
ronde.

Vier waarborgen, elk direct tegen een manier waarop de vorige kalibratie mis
had kunnen gaan:

1. Minimum aantal evalueerbare rondes (--min-rondes, standaard 8). Met minder
   rondes wordt er niets aangepast, wat er ook uit het raster komt -- drie
   rondes was genoeg om KRIMP_SPELER=1 af te wijzen, niet genoeg om een fijnere
   waarde te kiezen.
2. Minimuemverbetering in RMSE (--min-verbetering, standaard 3% relatief).
   Een winnaar die het raster met 0,6% verslaat is geen winnaar, dat is de
   ruisvloer van dit soort tellingen.
3. Consistentie per ronde: de kandidaat moet de HUIDIGE instelling verslaan in
   een strikte meerderheid van de individuele backtestrondes, niet alleen in
   het gewogen gemiddelde. Dit is precies de check die de vorige keer liet
   zien dat het raster-optimum niet overal beter was.
4. Maximale stapgrootte per keer (--max-stap, standaard factor 2). Zelfs als
   de eerste drie waarborgen een verandering toestaan, mag KRIMP_SPELER/
   KRIMP_CLUB niet in een keer meer dan een factor 2 veranderen -- een enkele
   ruizige kalibratieronde mag niet meteen de instelling laten omslaan.

Bij elke run wordt het resultaat gelogd in kalibratie/status.json, ook als er
niets is aangepast -- zo is de geschiedenis van beslissingen (en de reden
erachter) achteraf te controleren.

Gebruik (zoals bedoeld voor de scheduled workflow):
    python auto_kalibreer.py                # gebruikt de standaardwaarden
    python auto_kalibreer.py --forceer      # negeert de "elke N ronden"-gate,
                                             # nuttig om het script handmatig
                                             # te proberen; de andere vier
                                             # waarborgen blijven wel gelden
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from backtest import laad_model
from calibrate import zoek_raster, schrijf_constanten

STATUS_PAD = Path("kalibratie/status.json")


def schrijf_output(sleutel, waarde):
    """Zelfde patroon als deadline.py: naar $GITHUB_OUTPUT binnen Actions, anders stdout."""
    pad = os.environ.get("GITHUB_OUTPUT")
    if pad:
        with open(pad, "a", encoding="utf-8") as f:
            f.write(f"{sleutel}={waarde}\n")


def lees_status(pad=STATUS_PAD):
    if pad.exists():
        return json.loads(pad.read_text(encoding="utf-8"))
    return {"laatst_gecontroleerd_tot_ronde": 0, "geschiedenis": []}


def schrijf_status(status, pad=STATUS_PAD):
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")


def per_ronde_rmse(resultaat):
    """{ronde: rmse} uit een resultaat-dict zoals draai_backtest() teruggeeft."""
    return {r["ronde"]: r["rmse"] for r in resultaat["per_ronde"]}


def is_consistent_beter(kandidaat, huidig):
    """True als kandidaat de huidige instelling verslaat in een strikte
    meerderheid van de rondes die in beide voorkomen (niet alleen gemiddeld).
    Retourneert (consistent: bool, gedeelde_rondes: list[int], n_beter: int)."""
    rk, rh = per_ronde_rmse(kandidaat), per_ronde_rmse(huidig)
    gedeeld = sorted(set(rk) & set(rh))
    if not gedeeld:
        return False, gedeeld, 0
    beter = sum(1 for ronde in gedeeld if rk[ronde] < rh[ronde])
    return beter > len(gedeeld) / 2, gedeeld, beter


def binnen_max_stap(oud, nieuw, max_stap):
    if oud == 0:
        return True
    verhouding = nieuw / oud
    return (1 / max_stap) <= verhouding <= max_stap


def stop(log, status, status_pad, tot, besluit, reden):
    """Legt een 'geen aanpassing'-besluit vast, schrijft de status en
    $GITHUB_OUTPUT, en print de reden. Gebruikt voor elk vroegtijdig einde."""
    log["besluit"] = besluit
    log["reden"] = reden
    status["laatst_gecontroleerd_tot_ronde"] = tot
    status["geschiedenis"].append(log)
    schrijf_status(status, status_pad)
    schrijf_output("aangepast", "nee")
    schrijf_output("reden", reden)
    print(reden)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--clubs", default="clubs.csv")
    p.add_argument("--spelers", default="spelers.csv")
    p.add_argument("--prijzen", default="prijzen.csv")
    p.add_argument("--venster", type=int, default=6)
    p.add_argument("--min-minuten", type=int, default=60)
    p.add_argument("--vanaf", type=int, default=2, help="eerste evalueerbare ronde (ronde 1 heeft geen trainingsdata)")
    p.add_argument("--elke", type=int, default=4,
                   help="controleer pas opnieuw als er sinds de vorige controle minstens dit aantal nieuwe ronden bij is (standaard 4, ~1 periode)")
    p.add_argument("--min-rondes", type=int, default=8,
                   help="minimum aantal evalueerbare rondes voordat een aanpassing ueberhaupt overwogen wordt")
    p.add_argument("--min-verbetering", type=float, default=0.03,
                   help="minimale relatieve RMSE-verbetering t.o.v. de huidige instelling (standaard 3%%)")
    p.add_argument("--max-stap", type=float, default=2.0,
                   help="maximale factor waarmee KRIMP_SPELER of KRIMP_CLUB in een keer mag veranderen")
    p.add_argument("--model", default="cvhj_model.py", help="bestand waarin de constanten staan")
    p.add_argument("--status", default=str(STATUS_PAD))
    p.add_argument("--forceer", action="store_true",
                   help="negeer de '--elke'-gate (voor handmatig testen); de andere waarborgen blijven gelden")
    p.add_argument("--droog", action="store_true",
                   help="doe alles behalve cvhj_model.py daadwerkelijk schrijven")
    a = p.parse_args()

    status_pad = Path(a.status)
    status = lees_status(status_pad)

    m = laad_model()
    clubrijen = m.lees(a.clubs)
    spelerrijen = m.lees(a.spelers)
    prijsrijen = m.lees(a.prijzen)
    tot = max(int(r["ronde"]) for r in clubrijen)
    n_evalueerbaar = max(0, tot - a.vanaf + 1)

    nu = datetime.now(timezone.utc).isoformat()
    log = {"tijdstip": nu, "tot_ronde": tot, "n_evalueerbaar": n_evalueerbaar}

    nieuwe_rondes = tot - status["laatst_gecontroleerd_tot_ronde"]
    if not a.forceer and nieuwe_rondes < a.elke:
        reden = (f"nog maar {nieuwe_rondes} nieuwe ronde(s) sinds de vorige controle "
                 f"(ronde {status['laatst_gecontroleerd_tot_ronde']}); wacht tot {a.elke}")
        log["besluit"] = "overgeslagen"
        log["reden"] = reden
        status["geschiedenis"].append(log)
        schrijf_status(status, status_pad)
        schrijf_output("aangepast", "nee")
        schrijf_output("reden", reden)
        print(reden)
        return

    if n_evalueerbaar < a.min_rondes:
        stop(log, status, status_pad, tot, "geen aanpassing",
             f"slechts {n_evalueerbaar} evalueerbare ronde(s), minimaal {a.min_rondes} vereist")
        return

    origineel_speler, origineel_club = m.KRIMP_SPELER, m.KRIMP_CLUB
    resultaten = zoek_raster(m, clubrijen, spelerrijen, prijsrijen, a.vanaf, tot, a.venster, a.min_minuten)

    if not resultaten:
        stop(log, status, status_pad, tot, "geen aanpassing",
             "geen enkele instelling leverde een evalueerbaar resultaat op")
        return

    huidig = next((r for ks, kc, r in resultaten if ks == origineel_speler and kc == origineel_club), None)
    if huidig is None:
        # De huidige waarden stonden niet in het raster (kan als iemand ze handmatig
        # buiten het raster om heeft gezet) -- reken ze apart uit als referentie.
        from calibrate import draai_backtest
        m.KRIMP_SPELER, m.KRIMP_CLUB = origineel_speler, origineel_club
        huidig = draai_backtest(m, clubrijen, spelerrijen, prijsrijen, a.vanaf, tot, a.venster, a.min_minuten)
        m.KRIMP_SPELER, m.KRIMP_CLUB = origineel_speler, origineel_club

    beste = min(resultaten, key=lambda x: x[2]["rmse"])
    ks_kand, kc_kand, r_kand = beste

    log["huidig"] = {"KRIMP_SPELER": origineel_speler, "KRIMP_CLUB": origineel_club, "rmse": huidig["rmse"]}
    log["kandidaat"] = {"KRIMP_SPELER": ks_kand, "KRIMP_CLUB": kc_kand, "rmse": r_kand["rmse"]}

    if (ks_kand, kc_kand) == (origineel_speler, origineel_club):
        stop(log, status, status_pad, tot, "geen aanpassing", "huidige instelling is zelf de rastere winnaar")
        return

    relatieve_verbetering = (huidig["rmse"] - r_kand["rmse"]) / huidig["rmse"] if huidig["rmse"] else 0
    log["relatieve_verbetering"] = relatieve_verbetering

    if relatieve_verbetering < a.min_verbetering:
        stop(log, status, status_pad, tot, "geen aanpassing",
             f"verbetering {relatieve_verbetering:.1%} onder de drempel van {a.min_verbetering:.0%} "
             "-- binnen de ruis van dit aantal rondes")
        return

    consistent, gedeeld, n_beter = is_consistent_beter(r_kand, huidig)
    log["consistentie"] = {"gedeelde_rondes": gedeeld, "n_beter": n_beter, "consistent_beter": consistent}

    if not consistent:
        stop(log, status, status_pad, tot, "geen aanpassing",
             "kandidaat is niet in een meerderheid van de individuele rondes beter dan de "
             "huidige instelling -- precies het patroon waardoor de vorige kalibratie is "
             "afgewezen; alleen een betere totaal-RMSE is onvoldoende bewijs")
        return

    stap_ok = binnen_max_stap(origineel_speler, ks_kand, a.max_stap) and binnen_max_stap(origineel_club, kc_kand, a.max_stap)
    log["stap_binnen_grens"] = stap_ok

    if not stap_ok:
        stop(log, status, status_pad, tot, "geen aanpassing",
             f"kandidaat (KRIMP_SPELER={ks_kand}, KRIMP_CLUB={kc_kand}) wijkt meer dan een factor "
             f"{a.max_stap:g} af van de huidige waarden -- te grote stap voor één automatische ronde")
        return

    # Alle waarborgen gehaald: toepassen.
    if a.droog:
        log["besluit"] = "zou aanpassen (--droog)"
        aangepast = False
    else:
        aangepast = schrijf_constanten(a.model, ks_kand, kc_kand)
        log["besluit"] = "aangepast" if aangepast else "mislukt: constanten niet gevonden in bestand"

    melding = (f"KRIMP_SPELER {origineel_speler} -> {ks_kand}, KRIMP_CLUB {origineel_club} -> {kc_kand} "
               f"(RMSE {huidig['rmse']:.2f} -> {r_kand['rmse']:.2f}, {relatieve_verbetering:.1%} beter, "
               f"consistent in {n_beter}/{len(gedeeld)} rondes)")
    log["reden"] = melding
    status["laatst_gecontroleerd_tot_ronde"] = tot
    if aangepast or a.droog:
        status["huidige_instelling"] = {"KRIMP_SPELER": ks_kand, "KRIMP_CLUB": kc_kand, "sinds_ronde": tot}
    status["geschiedenis"].append(log)
    schrijf_status(status, status_pad)

    print(melding)
    if a.droog:
        print("(--droog: cvhj_model.py NIET gewijzigd)")

    schrijf_output("aangepast", "ja" if aangepast else "nee")
    schrijf_output("reden", melding)
    schrijf_output("krimp_speler_oud", origineel_speler)
    schrijf_output("krimp_club_oud", origineel_club)
    schrijf_output("krimp_speler_nieuw", ks_kand)
    schrijf_output("krimp_club_nieuw", kc_kand)

    if not a.droog and not aangepast:
        sys.exit("Waarborgen gehaald maar KRIMP_SPELER/KRIMP_CLUB niet gevonden om te vervangen in " + a.model)


if __name__ == "__main__":
    main()
