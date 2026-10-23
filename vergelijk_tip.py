#!/usr/bin/env python3
"""
Legt de WERKELIJK behaalde punten per speler vast en rekent ze om naar punten
per ronde -- de enige echte maatstaf die dit project heeft.

WAAROM DIT BESTAND NIET MEER VERGELIJKT
---------------------------------------
Dit script vergeleek cvhj_model.py met de puntenvoorspelling van pouletips
('Verwacht' op de prijzenpagina), als onafhankelijke tweede mening. Die
vergelijking is weg, en de kolom wordt niet meer gelezen. De reden:

    Verwachte punten, Totaal, Per miljoen en Basiskans zijn op die pagina
    GEMASKEERD voor wie geen Premium-account heeft. Je krijgt geen afgeronde
    of vertraagde cijfers -- je krijgt per request andere getallen.

Dat is ook te meten, en het is gemeten:

  - de waarden zijn uniform verdeeld over [1, 4], zonder enige piek;
  - tussen twee scrapes op 23 oktober veranderde 'verwacht' voor ALLE 507
    spelers, terwijl prijs, positie, club, naam, rol en nieuw voor 0 van de
    507 veranderden. Een voorspelling die per request verandert is geen
    voorspelling;
  - de getallen zijn onderling inconsistent: 62,0 + 2.683 is niet 1.954, en
    'Per miljoen' 473 past bij geen enkele combinatie van de andere twee;
  - Pepi stond op een basiskans van 70% terwijl hij geblesseerd was.

Een ijking tegen willekeurige getallen is erger dan geen ijking: hij levert
elke week een rangcorrelatie op die eruitziet als een meting. Daarom is de
vergelijking niet verzwakt maar verwijderd, en wordt de kolom niet meer
opgevraagd -- hij zit achter een betaalmuur en hoort daar te blijven.

WAT ER WEL IS, EN WAT HET WAARD IS
----------------------------------
'Behaald' op dezelfde pagina is NIET gemaskeerd en wel juist: tussen die twee
scrapes veranderde het voor 1 van de 507 spelers, en het hangt samen met het
rapportcijfer (r = +0,67). Dat zijn werkelijk gescoorde CVHJ-punten.

Het is een SEIZOENSTOTAAL. Om er per ronde mee te rekenen heb je opnamen op
verschillende momenten nodig en trek je ze van elkaar af. Dat is precies wat
dit script doet, en waarom het elke week meedraait: elke week die we niet
vastleggen is grondwaarheid die we kwijt zijn.

De waarde zit in het verschil met backtest.py: dat reconstrueert punten uit
spelers.csv en kan assists, kaarten en keepersreddingen niet meenemen -- het
RMSE-getal daar is expliciet een ONDERGRENS. Deze reeks heeft die beperking
niet.

WAT DIT SCRIPT BEWUST NIET DOET
-------------------------------
Het vergelijkt deze punten niet met de E van het model. Dat lijkt de logische
volgende stap, maar de pool wordt gebouwd uit spelers.csv ZOALS DIE NU IS --
dus met de vorm van na de ronde die je wilt voorspellen. Die vergelijking zou
vooruitkijken en daarmee te vleiend uitvallen. Het hoort in backtest.py en
kalibratie/, waar de stand per ronde bewaard is. Een getal dat alleen klopt
als je niet nadenkt over de herkomst, is geen meting.

Gebruik:
    python vergelijk_tip.py --ronde 11
    python vergelijk_tip.py --ronde 11 --top 20
    python vergelijk_tip.py --ronde 11 --geen-historie   # alleen rapporteren
"""
import argparse
import collections
import csv
import statistics
import sys
from pathlib import Path

HIER = Path(__file__).parent
HISTORIE = "punten_historie.csv"

# Een speler die een doelpunt maakte in een gewonnen wedstrijd zit op minstens
# 12 punten (doelpunt 12/10/8/6 plus winst 3). Het aandeel spelers dat daarboven
# uitkomt is daarmee een grove maat voor "hoeveel is hier gespeeld" -- bruikbaar
# om te zien of een interval meer dan één ronde beslaat.
TOPGRENS = 12.0


def leg_vast(rijen, ronde, pad=HISTORIE):
    """Momentopname van 'behaald' per speler wegschrijven.

    Append-only, één regel per (ronde, speler). Een ronde die er al in staat
    wordt niet nog eens toegevoegd -- zo is het veilig om dit script meerdere
    keren per week te draaien.
    """
    bestaand = set()
    p = Path(pad)
    if p.exists():
        with p.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                bestaand.add((r["ronde"], r["speler_id"]))

    nieuw = [r for r in rijen
             if r.get("behaald") not in (None, "")
             and (str(ronde), r["speler_id"]) not in bestaand]
    if not nieuw:
        return 0

    nieuw_bestand = not p.exists()
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ronde", "speler_id", "speler", "club", "behaald"])
        if nieuw_bestand:
            w.writeheader()
        for r in nieuw:
            w.writerow({"ronde": ronde, "speler_id": r["speler_id"], "speler": r["speler"],
                        "club": r["team"], "behaald": r["behaald"]})
    return len(nieuw)


def lees_opnamen(pad=HISTORIE):
    """({ronde: {speler_id: totaal}}, {speler_id: (naam, club)}).

    Het label is de ronde die op het moment van opname NOG MOEST WORDEN
    GESPEELD (de eerste regel van programma.csv). Een opname met label N bevat
    dus het seizoenstotaal tot en met ronde N-1.
    """
    p = Path(pad)
    if not p.exists():
        return {}, {}
    opnamen, namen = collections.defaultdict(dict), {}
    with p.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                opnamen[int(r["ronde"])][r["speler_id"]] = float(r["behaald"])
            except (ValueError, KeyError):
                continue
            namen[r["speler_id"]] = (r["speler"], r.get("club", ""))
    return dict(opnamen), namen


def per_ronde(opnamen):
    """[(ronde, {speler_id: punten})] -- het verschil tussen twee opnamen.

    Opname N bevat de stand tot en met ronde N-1, opname N-1 die tot en met
    N-2. Het verschil is dus wat er in ronde N-1 is gescoord. Spelers die in
    één van beide opnamen ontbreken (nieuw in de poule, of eruit) worden
    overgeslagen: voor hen is het verschil geen rondescore.
    """
    uit = []
    rondes = sorted(opnamen)
    for vorige, huidige in zip(rondes, rondes[1:]):
        a, b = opnamen[vorige], opnamen[huidige]
        uit.append((vorige, {s: b[s] - a[s] for s in b if s in a}))
    return uit


def beschrijf(punten):
    """Eén regel samenvatting van een rondeverdeling."""
    v = list(punten.values())
    if not v:
        return None
    return {
        "n": len(v), "gem": statistics.mean(v), "mediaan": statistics.median(v),
        "min": min(v), "max": max(v),
        "top": sum(1 for x in v if x >= TOPGRENS),
        "nul": sum(1 for x in v if x == 0),
    }


def rapporteer(reeks, namen, top=10):
    """De reeks per ronde op het scherm, met de laatste ronde uitgeschreven."""
    if not reeks:
        print("Nog geen twee opnamen op verschillende momenten, dus nog geen "
              "punten per ronde te berekenen. Dat lukt vanaf de volgende run.")
        return

    print("WERKELIJK BEHAALDE PUNTEN PER RONDE (uit het verschil tussen twee opnamen)")
    print(f"  {'ronde':>6}{'spelers':>9}{'gemiddeld':>11}{'mediaan':>9}"
          f"{'laagste':>9}{'hoogste':>9}{'>=' + str(int(TOPGRENS)):>6}{'nul':>6}")
    samenvattingen = []
    for ronde, punten in reeks:
        s = beschrijf(punten)
        if not s:
            continue
        samenvattingen.append((ronde, s))
        print(f"  {ronde:>6}{s['n']:>9}{s['gem']:>11.2f}{s['mediaan']:>9.1f}"
              f"{s['min']:>9.1f}{s['max']:>9.1f}{s['top']:>6}{s['nul']:>6}")

    # Een interval kan meer dan één ronde beslaan: een gemiste week, of
    # inhaalwedstrijden ertussen. Dat is geen fout in de data maar het maakt
    # het label onnauwkeurig, en dat hoort zichtbaar te zijn in plaats van
    # stilletjes in een gemiddelde te verdwijnen.
    # Hij kijkt naar twee kanten, want ze horen bij elkaar: een opname die te
    # vroeg is genomen laat het ene interval leeglopen in het andere. Dat zie
    # je in de reeks hierboven terug als een lage rij naast een hoge, en de
    # twee zijn samen één ronde te veel en één te weinig.
    if len(samenvattingen) >= 3:
        aandelen = [s["top"] / s["n"] for _, s in samenvattingen]
        midden = statistics.median(aandelen)
        if midden > 0:
            meldingen = []
            for (ronde, _), a in zip(samenvattingen, aandelen):
                if a > 2 * midden:
                    meldingen.append((ronde, a, "beslaat dit interval waarschijnlijk "
                                                "meer dan één ronde"))
                elif a < midden / 2:
                    meldingen.append((ronde, a, "is de opname erna waarschijnlijk te "
                                                "vroeg genomen, zodat punten uit deze "
                                                "ronde in het volgende interval staan"))
            for ronde, a, waarom in meldingen:
                print(f"\n  LET OP ronde {ronde}: {a * 100:.1f}% van de spelers haalde "
                      f"{int(TOPGRENS)}+ punten, tegen {midden * 100:.1f}% normaal -- "
                      f"{waarom}.")

    ronde, punten = reeks[-1]
    hoogste = sorted(punten.items(), key=lambda t: -t[1])[:top]
    print(f"\nHOOGSTE SCORES IN RONDE {ronde}")
    for speler_id, p in hoogste:
        naam, club = namen.get(speler_id, (speler_id, ""))
        print(f"  {naam:26s}{club:18s}{p:>7.1f}")

    laagste = [t for t in sorted(punten.items(), key=lambda t: t[1]) if t[1] < 0][:top]
    if laagste:
        print(f"\nNEGATIEF IN RONDE {ronde} (kaarten)")
        for speler_id, p in laagste:
            naam, club = namen.get(speler_id, (speler_id, ""))
            print(f"  {naam:26s}{club:18s}{p:>7.1f}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ronde", type=int, required=True,
                   help="de ronde die nog gespeeld moet worden (label van de opname)")
    p.add_argument("--prijzen", default="prijzen.csv")
    p.add_argument("--top", type=int, default=10, help="aantal spelers per lijst")
    p.add_argument("--geen-historie", action="store_true",
                   help="niets wegschrijven, alleen rapporteren wat er al staat")
    a = p.parse_args()

    if not a.geen_historie:
        pad = Path(a.prijzen)
        if not pad.exists():
            sys.exit(f"{a.prijzen} bestaat niet -- draai eerst scrape_prijzen.py.")
        with pad.open(encoding="utf-8") as f:
            prijsrijen = list(csv.DictReader(f))
        met_punten = [r for r in prijsrijen if r.get("behaald") not in (None, "")]
        if not met_punten:
            # Geen harde fout: het model werkt zonder deze kolom, en de
            # wekelijkse stap mag hier niet op omvallen. Maar het moet wel
            # opvallen, want dan stopt de enige grondwaarheid die we hebben.
            print(f"LET OP: geen enkele regel in {a.prijzen} heeft een waarde in "
                  f"'behaald'. Er is deze week dus niets vastgelegd. Controleer of "
                  f"de kolom nog op de bronpagina staat (python scrape_prijzen.py "
                  f"--bron).")
        else:
            n = leg_vast(met_punten, a.ronde)
            print(f"{HISTORIE}: {n} nieuwe regels weggeschreven "
                  f"({len(met_punten)} spelers met punten in {a.prijzen})")
        print()

    opnamen, namen = lees_opnamen()
    if not opnamen:
        sys.exit(f"{HISTORIE} is leeg of bestaat niet.")
    print(f"Opnamen aanwezig voor ronde(n) {sorted(opnamen)}\n")
    rapporteer(per_ronde(opnamen), namen, a.top)


if __name__ == "__main__":
    main()
