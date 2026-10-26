#!/usr/bin/env python3
"""
Periodieke validatie: draait alles, meet de kwaliteit, en legt de TREND vast.

Waarom dit naast de bestaande controles bestaat. tests.yml draait bij elke
push en zegt of de code consistent is; wekelijks.yml draait de regressietest
en zegt of de twee zoekers het eens zijn. Allebei beantwoorden ze de vraag
"is het stuk?" -- geen van beide beantwoordt "wordt het beter?".

Dat tweede is precies wat je over een seizoen wilt weten. Er komt elke week
een ronde bij, dus de schattingen horen scherper te worden; gebeurt dat niet,
dan is dat een signaal dat geen enkele losse run kan geven. Daarom schrijft
dit script EEN REGEL per validatie naar validatie/historie.csv. De waarde zit
niet in de losse meting maar in de reeks.

Wat er gemeten wordt, en waarom juist dat:

  rmse / rho          de klassieke maten uit backtest.py, tegen de naieve
                      basislijn. Bekend zwak punt: RMSE over de hele pool is
                      een ongevoelige proxy, want de 200+ spelers die je nooit
                      koopt domineren hem. Staat er vooral in voor de
                      vergelijkbaarheid met eerdere metingen.
  top15_gevangen      DE beslissingsmaat: welk deel van het gat tussen
                      willekeurig kiezen en perfect kiezen vangt de top-15 van
                      het model? Dit is wat je in punten merkt, en het is een
                      orde van grootte gevoeliger dan RMSE (0,4% RMSE-verschil
                      bleek 2,6 procentpunt hier).
  markt / koppelgraad datadrift. Een scraper die stil de verkeerde kolom pakt
                      of spelers laat vallen, verandert deze getallen voordat
                      hij het advies merkbaar verpest.

Ritme: gekoppeld aan de periodestart, niet aan de kalender. Bij een
periodestart heb je drie transfers in plaats van een, dus daar tellen de
beslissingen het zwaarst -- je wilt met een gecontroleerd model die week in.
Draai dit dus wekelijks met --alleen-voor-periodestart; dan doet hij niets
behalve in de week ervoor.

    python valideer.py --ronde 12                      # nu meten
    python valideer.py --ronde 12 --alleen-voor-periodestart
    python valideer.py --ronde 12 --venster 2          # ruimer venster

Uitvoer: validatie/historie.csv (de reeks) en validatie/rapport.md (leesbaar,
en het bestand dat de driewekelijkse Claude-sessie leest).
"""
import argparse
import csv
import datetime
import importlib.util
import json
import random
import subprocess
import sys
from pathlib import Path

HIER = Path(__file__).parent
UIT = HIER / "validatie"
HISTORIE = UIT / "historie.csv"
RAPPORT = UIT / "rapport.md"

SUITES = ["test_workflows.py", "test_multi_periode.py", "test_scrape_prijzen.py",
          "test_statistieken.py", "test_synchroniseer.py", "test_notify.py"]

VELDEN = ["datum", "ronde", "periode", "ronden_tot_start", "rondes_geevalueerd",
          "rmse", "rmse_naief", "rho", "rho_naief", "top15_gevangen",
          "pool_grootte", "markt_grootte", "koppelgraad", "geblesseerd",
          "suites_geslaagd", "suites_totaal"]


def laad_model():
    spec = importlib.util.spec_from_file_location("cvhj_model", HIER / "cvhj_model.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def is_validatieweek(ronde, perioden, venster):
    """Draait deze week de validatie?

    Ja als er binnen `venster` ronden een periodestart aankomt, en ja op de
    periodestart zelf (dan is het de laatste kans om te merken dat er iets
    mis is voordat je drie transfers inzet).

    Aparte functie omdat dit stilletjes bepaalt of er UBERHAUPT iets draait.
    Zo'n poortwachter is het gevaarlijkste soort code: als hij te streng staat
    gebeurt er maanden niets en valt dat niemand op, want er is geen fout te
    zien. test_valideer.py toetst hem daarom expliciet.
    """
    if not perioden:
        return False, "geen perioden.csv -- ritme niet te bepalen"
    starts = [start for _nr, start in perioden]
    if ronde in starts:
        return True, f"ronde {ronde} IS een periodestart"
    komend = [s for s in starts if s > ronde]
    if not komend:
        return False, "geen periodestart meer in het seizoen"
    tot = min(komend) - ronde
    if tot <= venster:
        return True, f"periodestart over {tot} ronde(n) (venster {venster})"
    return False, f"volgende periodestart pas over {tot} ronden (venster {venster})"


def draai_suites():
    """Elke testsuite als los proces; retourneert [(naam, geslaagd, staart)]."""
    uit = []
    for suite in SUITES:
        if not (HIER / suite).exists():
            uit.append((suite, False, "bestand ontbreekt"))
            continue
        p = subprocess.run([sys.executable, suite], cwd=HIER,
                           capture_output=True, text=True, timeout=900)
        staart = (p.stdout + p.stderr).strip().splitlines()
        uit.append((suite, p.returncode == 0, staart[-1] if staart else ""))
    return uit


def gat_gevangen(m, pool, werkelijk, trekkingen=200, zaad=0):
    """Welk deel van het gat willekeurig -> perfect vangt de top-15 van het model?

    0% = niet beter dan blind grijpen, 100% = de best mogelijke vijftien.
    Dit is de enige maat in dit bestand die meet wat je in punten merkt: hij
    kijkt naar de spelers die je DAADWERKELIJK zou kopen, niet naar de
    voorspelfout over een hele markt die je grotendeels negeert.

    `werkelijk` is {speler_id: behaalde punten}. Geen perfecte grondwaarheid
    (backtest.py reconstrueert die uit spelers.csv en mist assists, kaarten en
    reddingen), dus de uitkomst is een ondergrens -- maar wel een die je week
    op week met zichzelf kunt vergelijken, en dat is hier het doel.
    """
    scoorbaar = [p for p in pool if p["speler_id"] in werkelijk]
    if len(scoorbaar) < 20:
        return None
    punten = {p["speler_id"]: werkelijk[p["speler_id"]] for p in scoorbaar}

    top = sorted(scoorbaar, key=lambda p: -p["E"])[:15]
    model = sum(punten[p["speler_id"]] for p in top)
    perfect = sum(sorted(punten.values(), reverse=True)[:15])

    rng = random.Random(zaad)
    ids = list(punten)
    willekeurig = sum(sum(punten[s] for s in rng.sample(ids, 15))
                      for _ in range(trekkingen)) / trekkingen

    if perfect - willekeurig < 1e-9:
        return None
    return (model - willekeurig) / (perfect - willekeurig)


def meet_model(m, venster, min_minuten):
    """backtest-maten plus de beslissingsmaat, over alle evalueerbare ronden."""
    import backtest

    clubrijen = m.lees("clubs.csv")
    spelerrijen = m.lees("spelers.csv")
    prijsrijen = m.lees("prijzen.csv")
    fbref = m.lees_spelerstats(m.stats_pad("spelerstats.csv"))

    rondes = sorted({int(r["ronde"]) for r in spelerrijen})
    fout2, rhos, rhos_naief, fout2_naief, gaten, n = [], [], [], [], [], 0
    pool_grootte = None
    for ronde in rondes[1:]:
        r = backtest.evalueer_ronde(m, clubrijen, spelerrijen, prijsrijen, ronde,
                                    venster, min_minuten, fbref=fbref)
        if not r:
            continue
        n += 1
        pool_grootte = r.get("n_pool")      # laatste ronde: de actueelste marktomvang
        fout2 += [x["fout"] ** 2 for x in r["rijen"]]
        if r.get("spearman") is not None:
            rhos.append(r["spearman"])
        b = backtest.basislijn(m, spelerrijen, prijsrijen, ronde, venster, min_minuten)
        if b:
            # basislijn() geeft alleen een samengevatte RMSE terug, geen losse
            # fouten. Voor een reeks over meerdere ronden tellen we hem daarom
            # met zijn eigen n mee, zodat een ronde met veel spelers ook zwaarder
            # weegt -- net als bij het model hierboven.
            fout2_naief += [b["rmse"] ** 2] * b["n"]
            if b.get("spearman") is not None:
                rhos_naief.append(b["spearman"])

        # r["rijen"] bevat per speler de voorspelling en de werkelijkheid, in
        # dezelfde volgorde -- genoeg voor de beslissingsmaat.
        pool = [{"speler_id": m.norm(x["speler"]), "speler": x["speler"],
                 "E": x["voorspeld"]} for x in r["rijen"]]
        werkelijk = {m.norm(x["speler"]): x["werkelijk"] for x in r["rijen"]}
        g = gat_gevangen(m, pool, werkelijk)
        if g is not None:
            gaten.append(g)

    def wortel(v):
        return (sum(v) / len(v)) ** 0.5 if v else None

    def gem(v):
        return sum(v) / len(v) if v else None

    return {
        "rondes_geevalueerd": n,
        "rmse": wortel(fout2),
        "rmse_naief": wortel(fout2_naief),
        "rho": gem(rhos),
        "rho_naief": gem(rhos_naief),
        "top15_gevangen": gem(gaten),
        "pool_grootte": pool_grootte,
    }


def meet_data(m):
    """Datadrift: de getallen die als eerste veranderen als een scraper stukgaat."""
    uit = {"markt_grootte": None, "koppelgraad": None, "geblesseerd": None}
    if not Path("prijzen.csv").exists():
        return uit
    prijsrijen = m.lees("prijzen.csv")
    uit["markt_grootte"] = len(prijsrijen)
    uit["geblesseerd"] = sum(1 for r in prijsrijen if r.get("blessure"))
    if Path("spelers.csv").exists():
        bekend = {r.get("speler_id") for r in m.lees("spelers.csv")}
        gevonden = sum(1 for r in prijsrijen if r.get("speler_id") in bekend)
        uit["koppelgraad"] = round(gevonden / len(prijsrijen), 4) if prijsrijen else None
    return uit


def lees_historie():
    if not HISTORIE.exists():
        return []
    with HISTORIE.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


# Hoeveel een enkele SPELENDE speler per ronde schommelt, gemeten op
# punten_historie.csv (ronde 8 en 9, 354 waarnemingen met een score ongelijk
# nul): sd 3.91 punt. Elf daarvan, onafhankelijk, geeft 3.91 * sqrt(11).
#
# Dit getal is het belangrijkste in deze hele functie. Zonder ruisvloer leest
# een RMSE van 14 als een slecht model, terwijl 13 het theoretische maximum is
# -- en dan ga je een model bijstellen dat al tegen de bodem zit.
SD_SPELER_PER_RONDE = 3.91
BASISSPELERS = 11
RUISVLOER = SD_SPELER_PER_RONDE * (BASISSPELERS ** 0.5)


def meet_eigen_ploeg(pad="eigen_punten.csv", map_historie="historie"):
    """Verwachting van het model tegen de WERKELIJK behaalde ploegscore.

    De meest directe toets die dit project heeft, en tot 26-10-2026 de enige
    die nergens stond: validatie/historie.csv meet RMSE en rho over de hele
    POOL, niet over de elf die je echt had.

    Invoer is optioneel. `eigen_punten.csv` met twee kolommen (ronde, punten)
    houd je met de hand bij -- die getallen staan alleen op de site van CVHJ en
    komen uit geen enkele scrape. Ontbreekt het bestand, dan levert deze
    functie None en verandert er niets.

    De verwachting per ronde komt uit historie/ronde-N.json, veld
    huidig.verwacht: wat het model dacht dat je ploeg ZONDER transfers zou
    opleveren. Dat is het juiste vergelijkingspunt, want dat is de ploeg waar
    je mee speelde.

    WAT HIER WEL EN NIET UIT TE HALEN VALT. De weekschommeling van een som van
    elf spelers is grotendeels onvermijdelijk (zie RUISVLOER). Op de stand van
    26-10-2026, met vijf gekoppelde ronden: waargenomen sd 14.94, ruisvloer
    12.97, dus 75% van de variantie is ruis. Een RMSE rond 13 is daarmee geen
    slecht model maar een model op de bodem. Wat deze reeks WEL kan vaststellen
    is het NIVEAU: voorspelt het model gemiddeld te hoog of te laag. Daar is
    geen ruis tegen, alleen tijd.
    """
    p = Path(pad)
    if not p.exists():
        return None
    echt = {}
    with p.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                echt[int(r["ronde"])] = float(r["punten"])
            except (KeyError, TypeError, ValueError):
                continue
    if not echt:
        return None

    verw = {}
    for j in Path(map_historie).glob("ronde-*.json"):
        try:
            d = json.loads(j.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        r, h = d.get("ronde"), (d.get("huidig") or {})
        if r is not None and h.get("verwacht") is not None:
            verw[int(r)] = float(h["verwacht"])

    paren = sorted((r, verw[r], echt[r]) for r in echt if r in verw)
    if len(paren) < 2:
        return {"eigen_ronden": len(paren), "eigen_gekoppeld": 0}

    fouten = [a - v for _, v, a in paren]
    n = len(fouten)
    gem_fout = sum(fouten) / n
    rmse = (sum(x * x for x in fouten) / n) ** 0.5
    alle = sorted(echt.values())
    gem_echt = sum(alle) / len(alle)
    # Spreiding van je uitslagen zelf; met minder dan twee ronden zinloos.
    sd_echt = ((sum((x - gem_echt) ** 2 for x in alle) / (len(alle) - 1)) ** 0.5
               if len(alle) > 1 else 0.0)
    # Standaardfout van de bias: zonder dit getal leest een bias van +3 als
    # een bevinding, terwijl hij bij vijf ronden volledig binnen de marge valt.
    sd_fout = ((sum((x - gem_fout) ** 2 for x in fouten) / (n - 1)) ** 0.5
               if n > 1 else 0.0)
    rest = rmse * rmse - RUISVLOER * RUISVLOER
    return {
        "eigen_ronden": len(echt),
        "eigen_gekoppeld": n,
        "eigen_gemiddeld": round(gem_echt, 2),
        "eigen_sd": round(sd_echt, 2),
        "eigen_bias": round(gem_fout, 2),
        "eigen_bias_se": round(sd_fout / (n ** 0.5), 2) if n > 1 else None,
        "eigen_rmse": round(rmse, 2),
        "eigen_ruisvloer": round(RUISVLOER, 2),
        "eigen_modelfout": round(rest ** 0.5, 2) if rest > 0 else 0.0,
        "eigen_ruisaandeel": (round(100 * RUISVLOER ** 2 / (sd_echt ** 2), 0)
                              if sd_echt > 0 else None),
        "eigen_zonder_verwachting": sorted(r for r in echt if r not in verw),
    }


def getal(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def trendregel(naam, nu, historie, hoger_is_beter, cijfers=3):
    """Een regel met de huidige waarde en de verandering sinds de vorige meting.

    De vorige meting, niet het gemiddelde: bij zes metingen per seizoen is een
    gemiddelde nietszeggend, en het gaat om de richting.
    """
    if nu is None:
        return f"- **{naam}**: niet gemeten"
    vorige = None
    for rij in reversed(historie):
        v = getal(rij.get(naam))
        if v is not None:
            vorige = v
            break
    if vorige is None:
        return f"- **{naam}**: {nu:.{cijfers}f} (eerste meting)"
    delta = nu - vorige
    # Afronden VOOR het oordeel. Anders leest een verschil van 3e-16 -- twee
    # identieke metingen op drijvende-kommaruis -- als "-0.000 slechter", en
    # een rapport dat bij ongewijzigde data achteruitgang meldt, is een rapport
    # dat je binnen twee metingen niet meer gelooft.
    afgerond = round(delta, cijfers)
    if afgerond == 0:
        return f"- **{naam}**: {nu:.{cijfers}f} (ongewijzigd sinds vorige meting)"
    richting = "beter" if (afgerond > 0) == hoger_is_beter else "slechter"
    return f"- **{naam}**: {nu:.{cijfers}f} ({afgerond:+.{cijfers}f} sinds vorige meting, {richting})"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ronde", type=int, required=True)
    p.add_argument("--perioden", default="perioden.csv")
    p.add_argument("--venster", type=int, default=1,
                   help="hoeveel ronden voor een periodestart de validatie draait")
    p.add_argument("--alleen-voor-periodestart", action="store_true",
                   help="doe niets als dit geen validatieweek is (voor de wekelijkse cron)")
    p.add_argument("--min-minuten", type=int, default=60)
    p.add_argument("--stats-venster", type=int, default=6)
    a = p.parse_args()

    m = laad_model()
    perioden = m.lees_perioden(a.perioden)
    draaien, reden = is_validatieweek(a.ronde, perioden, a.venster)
    periode, is_start, tot_volgende = m.periodestand(a.ronde, perioden)

    print(f"Ronde {a.ronde}, periode {periode}. {reden}")
    if a.alleen_voor_periodestart and not draaien:
        print("Geen validatieweek -- niets gedaan.")
        return

    print("\nTestsuites")
    suites = draai_suites()
    for naam, ok, staart in suites:
        print(f"  {'OK  ' if ok else 'FOUT'} {naam:26s} {staart[:80]}")
    geslaagd = sum(1 for _n, ok, _s in suites if ok)

    print("\nModelkwaliteit meten")
    try:
        model = meet_model(m, a.stats_venster, a.min_minuten)
    except Exception as e:                                   # noqa: BLE001
        print(f"  niet gelukt: {type(e).__name__}: {e}")
        model = {k: None for k in ("rondes_geevalueerd", "rmse", "rmse_naief",
                                   "rho", "rho_naief", "top15_gevangen",
                                   "pool_grootte")}
    for k, v in model.items():
        print(f"  {k:20s} {v if v is None else round(v, 4)}")

    data = meet_data(m)
    for k, v in data.items():
        print(f"  {k:20s} {v}")

    # De directe toets: wat het model voor JOUW elf voorspelde tegen wat je
    # werkelijk haalde. Optioneel -- zonder eigen_punten.csv verandert er niets.
    eigen = meet_eigen_ploeg()
    if eigen is None:
        print("\nEigen ploeg: geen eigen_punten.csv, dus niet gemeten "
              "(twee kolommen: ronde,punten)")
    elif eigen.get("eigen_gekoppeld", 0) < 2:
        print(f"\nEigen ploeg: {eigen['eigen_ronden']} ronde(n) ingevoerd, maar te "
              f"weinig met een verwachting in historie/ om iets te zeggen")
    else:
        print("\nEigen ploeg tegen de verwachting")
        print(f"  ronden gekoppeld      {eigen['eigen_gekoppeld']} van "
              f"{eigen['eigen_ronden']} ingevoerd")
        print(f"  gemiddeld werkelijk   {eigen['eigen_gemiddeld']} "
              f"(sd {eigen['eigen_sd']})")
        print(f"  bias                  {eigen['eigen_bias']:+} +/- "
              f"{eigen['eigen_bias_se']}")
        print(f"  RMSE                  {eigen['eigen_rmse']}")
        print(f"  ruisvloer             {eigen['eigen_ruisvloer']}  "
              f"({eigen['eigen_ruisaandeel']}% van de variantie is ruis)")
        print(f"  modelfout erboven     {eigen['eigen_modelfout']}")
        if abs(eigen["eigen_bias"]) < 2 * (eigen["eigen_bias_se"] or 0):
            print("  -> de bias valt binnen de marge; nog geen aanwijzing dat het "
                  "model structureel te hoog of te laag zit")
        if eigen["eigen_zonder_verwachting"]:
            print(f"  ronden zonder verwachting in historie/: "
                  f"{eigen['eigen_zonder_verwachting']}")

    historie = lees_historie()
    rij = {
        "datum": datetime.date.today().isoformat(),
        "ronde": a.ronde,
        "periode": periode,
        "ronden_tot_start": tot_volgende,
        "suites_geslaagd": geslaagd,
        "suites_totaal": len(suites),
        **{k: ("" if v is None else round(v, 4) if isinstance(v, float) else v)
           for k, v in {**model, **data}.items()},
    }

    UIT.mkdir(parents=True, exist_ok=True)
    nieuw = not HISTORIE.exists()
    # De reeks wordt AANGEVULD onder een kop die alleen bij het eerste bestand
    # is geschreven. Zet iemand later een veld in VELDEN, dan krijgt de nieuwe
    # regel meer kolommen dan de kop aangeeft en schuift alles een plek op --
    # zonder foutmelding, in een reeks die juist bedoeld is om trends in te
    # zien. Daarom eerst vergelijken, en bij verschil weigeren in plaats van
    # door te schrijven.
    if not nieuw:
        with HISTORIE.open(encoding="utf-8") as f:
            kop = (f.readline().strip().split(",") if HISTORIE.stat().st_size else [])
        if kop and kop != VELDEN:
            erbij = [v for v in VELDEN if v not in kop]
            eraf = [v for v in kop if v not in VELDEN]
            sys.exit(
                f"{HISTORIE} heeft een andere kop dan VELDEN en wordt niet "
                f"aangevuld.\n"
                f"  nieuw in VELDEN: {erbij or 'geen'}\n"
                f"  weg uit VELDEN:  {eraf or 'geen'}\n"
                f"Aanvullen zou de kolommen laten verschuiven in alle volgende "
                f"regels, zonder foutmelding. Schrijf het bestand eerst om naar "
                f"de nieuwe kolommen (met de hand, dan lees je het zelf), of zet "
                f"VELDEN terug.")
    with HISTORIE.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=VELDEN, extrasaction="ignore")
        if nieuw:
            w.writeheader()
        w.writerow(rij)

    regels = [
        f"# Validatie ronde {a.ronde} ({rij['datum']})",
        "",
        f"Periode {periode}; {reden}. Dit is meting {len(historie) + 1}.",
        "",
        "## Testsuites",
        "",
        f"{geslaagd} van de {len(suites)} geslaagd.",
        "",
    ]
    for naam, ok, staart in suites:
        regels.append(f"- {'OK' if ok else '**MISLUKT**'} `{naam}` — {staart[:120]}")
    regels += [
        "",
        "## Modelkwaliteit",
        "",
        f"Gemeten over {model['rondes_geevalueerd']} evalueerbare ronde(n).",
        "",
        trendregel("top15_gevangen", model["top15_gevangen"], historie, hoger_is_beter=True),
        trendregel("rho", model["rho"], historie, hoger_is_beter=True),
        trendregel("rmse", model["rmse"], historie, hoger_is_beter=False),
        "",
        "`top15_gevangen` is de beslissingsmaat: welk deel van het gat tussen "
        "willekeurig en perfect kiezen vangt de top-15 van het model. Dat is wat je "
        "in punten merkt; RMSE staat erbij voor de vergelijkbaarheid met eerdere metingen.",
        "",
        "## Datadrift",
        "",
        trendregel("markt_grootte", data["markt_grootte"], historie, hoger_is_beter=True, cijfers=0),
        trendregel("koppelgraad", data["koppelgraad"], historie, hoger_is_beter=True),
        trendregel("geblesseerd", data["geblesseerd"], historie, hoger_is_beter=False, cijfers=0),
        "",
        "Een sprong in deze drie is meestal geen echte verandering in de competitie "
        "maar een scraper die stil iets anders is gaan lezen.",
        "",
        "## Wat dit rapport NIET zegt",
        "",
        "- De waarheid in de backtest komt uit `spelers.csv` en mist assists, kaarten "
        "en keepersreddingen. Elke maat hierboven is dus een ondergrens.",
        f"- Met {model['rondes_geevalueerd']} ronde(n) is de onzekerheid groot; een "
        "verschil tussen twee metingen is pas een signaal als het zich herhaalt.",
        "- Groene testsuites zeggen dat de code consistent is, niet dat de "
        "voorspellingen goed zijn.",
        "",
    ]
    RAPPORT.write_text("\n".join(regels) + "\n", encoding="utf-8")
    print(f"\n-> {HISTORIE} ({len(historie) + 1} metingen)\n-> {RAPPORT}")

    # Bewust geen foutcode bij een slechte uitslag: dit is een meting, geen test.
    # Een dalende rho is informatie en mag de workflow niet rood maken -- anders
    # leer je een rode validatie negeren. Alleen een gevallen testsuite is een fout.
    if geslaagd < len(suites):
        sys.exit(f"MISLUKT: {len(suites) - geslaagd} testsuite(s) gevallen -- zie hierboven.")


if __name__ == "__main__":
    main()
