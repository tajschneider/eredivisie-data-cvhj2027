#!/usr/bin/env python3
"""
Vergelijkt cvhj_model.py's schatting met die van pouletips -- ijking op een
onafhankelijke tweede mening.

WAT DIT WEL EN NIET IS
----------------------
Pouletips publiceert op dezelfde pagina waar prijzen.csv vandaan komt ook zijn
eigen puntenvoorspelling per speler ('Verwacht'), en wat een speler al
daadwerkelijk scoorde ('Behaald'). Dat zijn twee heel verschillende dingen:

    verwacht  -- een TWEEDE SCHATTING van precies wat cvhj_model.py schat.
                 Niet "het goede antwoord": een ander model, met andere fouten.
                 Waar twee onafhankelijke schatters het eens zijn, is de kans
                 groot dat ze allebei echt signaal oppikken. Waar ze sterk van
                 elkaar afwijken, valt iets te leren -- meestal mist een van
                 beide iets wat de ander wel ziet.

    behaald   -- WERKELIJK gescoorde punten. Dit is wel het goede antwoord,
                 en daarmee op termijn veel waardevoller: backtest.py
                 reconstrueert de werkelijke punten nu uit spelers.csv en kan
                 assists, kaarten en keepersreddingen niet meenemen, dus het
                 RMSE-getal daar is expliciet een ONDERGRENS. Met 'behaald'
                 wordt dat een echte meting.

                 Let op: 'behaald' is een SEIZOENSTOTAAL, geen ronde-score.
                 Om er per ronde mee te kunnen rekenen heb je twee opnamen op
                 verschillende momenten nodig en neem je het verschil. Daarom
                 legt dit script elke run een momentopname vast in
                 punten_historie.csv. Na twee weken is de eerste ronde-score
                 te berekenen; daarvoor kan het nog niet.

DE VERGELIJKING IS OP RANG, NIET OP SCHAAL
------------------------------------------
Het getalformaat op de bronpagina is niet ondubbelzinnig (zie parse_punten in
scrape_prijzen.py), en de twee modellen hebben sowieso geen gedeelde eenheid:
cvhj_model.py schat punten voor EEN ronde, pouletips voor de rest van het
seizoen. Een absolute vergelijking zou dus nergens op slaan. Wat wel betekenis
heeft is de VOLGORDE: zetten beide modellen dezelfde spelers bovenaan? Daarom
wordt hier Spearman-rangcorrelatie gebruikt, die ongevoelig is voor schaal en
voor een factor duizend in het getalformaat.

Gebruik:
    python vergelijk_tip.py --ronde 7
    python vergelijk_tip.py --ronde 7 --top 20      # meer afwijkingen tonen
    python vergelijk_tip.py --ronde 7 --geen-historie

Vereist prijzen.csv met de kolom 'verwacht' (nieuwe scrape_prijzen.py), plus
clubs.csv, spelers.csv en programma.csv.
"""
import argparse
import csv
import importlib.util
import sys
from pathlib import Path

HIER = Path(__file__).parent
HISTORIE = "punten_historie.csv"


def laad_model():
    spec = importlib.util.spec_from_file_location("cvhj_model", HIER / "cvhj_model.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def rangen(waarden):
    """Rangnummers, met gedeelde rang bij gelijke waarden (nodig voor Spearman)."""
    volgorde = sorted(range(len(waarden)), key=lambda i: waarden[i])
    r = [0.0] * len(waarden)
    i = 0
    while i < len(volgorde):
        j = i
        while j + 1 < len(volgorde) and waarden[volgorde[j + 1]] == waarden[volgorde[i]]:
            j += 1
        gemiddelde_rang = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[volgorde[k]] = gemiddelde_rang
        i = j + 1
    return r


def spearman(a, b):
    """Rangcorrelatie zonder scipy -- Pearson over de rangen."""
    if len(a) < 3:
        return float("nan")
    ra, rb = rangen(a), rangen(b)
    n = len(ra)
    ma, mb = sum(ra) / n, sum(rb) / n
    teller = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    noemer = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return teller / noemer if noemer else float("nan")


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


def rondes_in_historie(pad=HISTORIE):
    p = Path(pad)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return sorted({int(r["ronde"]) for r in csv.DictReader(f)})


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ronde", type=int, required=True)
    p.add_argument("--clubs", default="clubs.csv")
    p.add_argument("--spelers", default="spelers.csv")
    p.add_argument("--prijzen", default="prijzen.csv")
    p.add_argument("--programma", default="programma.csv")
    p.add_argument("--venster", type=int, default=6)
    p.add_argument("--min-minuten", type=int, default=60)
    p.add_argument("--top", type=int, default=10, help="aantal afwijkingen per kant")
    p.add_argument("--geen-historie", action="store_true",
                   help="geen momentopname wegschrijven in punten_historie.csv")
    a = p.parse_args()

    m = laad_model()
    prijsrijen = m.lees(a.prijzen)

    if not prijsrijen or "verwacht" not in prijsrijen[0]:
        sys.exit(
            f"{a.prijzen} heeft geen kolom 'verwacht'. Draai eerst de nieuwe "
            f"scrape_prijzen.py -- die leest de punten-kolommen van pouletips mee.")

    # --- momentopname van de werkelijke punten -------------------------------
    if not a.geen_historie:
        n = leg_vast(prijsrijen, a.ronde)
        rondes = rondes_in_historie()
        print(f"{HISTORIE}: {n} nieuwe regels weggeschreven; opnamen voor ronde(n) {rondes}")
        if len(rondes) < 2:
            print("  (nog te weinig opnamen om punten PER RONDE te berekenen -- "
                  "dat kan zodra er twee opnamen op verschillende momenten staan)")
        else:
            print(f"  vanaf nu is per ronde te berekenen wat een speler echt scoorde, "
                  f"door twee opnamen af te trekken")
        print()

    # --- de pool van het model -----------------------------------------------
    clubrijen = m.lees(a.clubs)
    spelerrijen = m.lees(a.spelers)
    aanval, verdediging, thuisvoordeel, _ = m.schat_clubratings(clubrijen)
    programma, inhaal = m.lees_programma(a.programma)
    pool = m.bouw_pool(prijsrijen, spelerrijen, aanval, verdediging, thuisvoordeel,
                       programma, inhaal, laatste_ronde=a.ronde - 1,
                       venster=a.venster, min_minuten=a.min_minuten,
                       fbref=m.lees_fbref(m.xg_pad("xg.csv")))

    tip = {r["speler_id"] or m.norm(r["speler"]): r["verwacht"]
           for r in prijsrijen if r.get("verwacht") not in (None, "")}

    paren = []
    for x in pool:
        v = tip.get(x["speler_id"])
        if v in (None, ""):
            continue
        paren.append((x, float(v)))

    if len(paren) < 3:
        sys.exit(f"te weinig spelers met een cijfer van pouletips ({len(paren)}) "
                 f"om iets zinnigs te vergelijken.")

    ons = [x["E"] for x, _ in paren]
    hun = [v for _, v in paren]
    rho = spearman(ons, hun)

    print(f"VERGELIJKING met pouletips (ronde {a.ronde})")
    print(f"  {len(paren)} spelers in beide bronnen, van {len(pool)} in de pool")
    print(f"  Spearman-rangcorrelatie: {rho:.3f}")
    print(f"    1,0 = exact dezelfde volgorde; 0,0 = geen verband.")
    if rho > 0.6:
        print(f"    Beide modellen zetten grotendeels dezelfde spelers bovenaan.")
    elif rho > 0.3:
        print(f"    Enige overeenstemming, maar de modellen verschillen wezenlijk.")
    else:
        print(f"    Weinig verband -- de moeite waard om uit te zoeken waarom.")

    # Afwijkingen op RANG, niet op waarde: de eenheden verschillen.
    r_ons, r_hun = rangen(ons), rangen(hun)
    n = len(paren)
    verschil = []
    for i, (x, v) in enumerate(paren):
        # rang 1 = laagste; omrekenen naar "plaats van boven" leest prettiger
        plaats_ons, plaats_hun = n - r_ons[i] + 1, n - r_hun[i] + 1
        verschil.append((plaats_hun - plaats_ons, x, plaats_ons, plaats_hun, v))

    # Lage plaats = hoog gewaardeerd (plaats 1 is de beste). Het verschil is
    # hun plaats min de onze, dus sterk NEGATIEF = zij zetten hem veel hoger.
    verschil.sort(key=lambda t: t[0])
    kop = f"  {'speler':26s}{'club':17s}{'onze plaats':>12s}{'hun plaats':>12s}{'onze E':>9s}"

    print(f"\nPOULETIPS ZET VEEL HOGER DAN WIJ (zien zij iets dat het model mist?)")
    print(kop)
    for _, x, po, ph, v in verschil[:a.top]:
        print(f"  {x['speler']:26s}{x['club']:17s}{po:>12.0f}{ph:>12.0f}{x['E']:>9.2f}")

    print(f"\nWIJ ZETTEN VEEL HOGER DAN POULETIPS (onze voorsprong, of onze fout)")
    print(kop)
    for _, x, po, ph, v in verschil[-a.top:][::-1]:
        print(f"  {x['speler']:26s}{x['club']:17s}{po:>12.0f}{ph:>12.0f}{x['E']:>9.2f}")

    print(f"\nLees dit niet als 'zij hebben gelijk'. Het is een tweede mening met "
          f"eigen fouten;\nde rijen hierboven zijn de plekken waar het de moeite "
          f"waard is om zelf te kijken.")


if __name__ == "__main__":
    main()
