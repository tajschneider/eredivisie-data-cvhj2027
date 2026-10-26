#!/usr/bin/env python3
"""
Backtest: voorspel ronde r met UITSLUITEND data uit ronden < r, vergelijk met
wat er werkelijk gebeurde.

Zonder dit heeft geen enkele modelwijziging een meetbaar effect -- je weet
alleen dat de uitvoer anders is, niet of hij beter is. Met dit script wordt
elke wijziging aan cvhj_model.py (krimpconstanten, assists, kaarten, meertraps)
een voor/na-vergelijking op dezelfde ronden.

Belangrijke beperking, vooraf: de "werkelijke punten" die dit script gebruikt
zijn een RECONSTRUCTIE uit clubs.csv en spelers.csv --
    ploegpunten + clean_sheet_bonus(positie) + goals * doelpuntwaarde(positie)
Dat mist precies dezelfde termen die het model zelf nog niet kent: assists,
kaarten, keeper-reddingen. Dit is dus geen vergelijking met je echte CVHJ-score
per speler, maar wel een eerlijke (appels-met-appels) toets van het deel dat
het model NU probeert te voorspellen. Zodra assists/kaarten in het model
komen, moet ook deze reconstructie worden uitgebreid, anders meet je jezelf
voorbij een doel dat intussen is verschoven.

Gebruik:
    python backtest.py                              # alle mogelijke ronden
    python backtest.py --vanaf 3 --tot 4
    python backtest.py --venster 3                  # kortere vormperiode
    python backtest.py --per-speler uit.csv          # ruwe voorspelling/werkelijkheid

Metrieken per ronde en totaal:
    RMSE, MAE          -- puntafwijking per speler
    Spearman-rho        -- rangcorrelatie (voor de opstellingskeuze belangrijker
                            dan de absolute foutmarge)
    dekking             -- hoeveel spelers kregen een voorspelling (E>0 in pool)
"""
import argparse
import collections
import csv
import importlib.util
import math
import unicodedata
import sys
from pathlib import Path

HIER = Path(__file__).parent


def laad_model():
    spec = importlib.util.spec_from_file_location("cvhj_model", HIER / "cvhj_model.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def werkelijke_punten(spelerrijen, ronde, m):
    """{speler_id: (punten, club, positie_kort)} voor de daadwerkelijk GESPEELDE
    ronde, gereconstrueerd uit dezelfde termen die het model kent.

    `spelers.csv` bevat geen positie -- die komt uit prijzen.csv. Omdat we hier
    alleen spelers scoren die ook in de pool zaten, wordt de positie in
    `evalueer_ronde` bijgeplakt vanuit de voorspelling zelf.
    """
    uit = {}
    for r in spelerrijen:
        if r["ronde"] != str(ronde) or r["status"] == "afwezig":
            continue
        sid = r.get("speler_id") or m.norm(r["speler"])
        cs = 1 if r.get("clean_sheet") in ("1", 1, "True", True) else 0
        uit[sid] = {
            "speler": r["speler"], "club": m.norm_club(r["club"]),
            "ploegpunten": int(r["ploegpunten"] or 0),
            "clean_sheet": cs, "goals": int(r["goals"] or 0),
            "minuten": int(r["minuten"] or 0),
        }
    return uit


def punten_met_positie(w, positie_kort, m):
    """Werkelijke CVHJ-punten voor deze speler-ronde, gegeven zijn positie.

    RECONSTRUCTIE, geen meting. spelers.csv heeft ploegpunten, clean sheets en
    doelpunten, maar geen assists, kaarten of keepersreddingen. Hoe groot dat
    gat is, is op 26-10-2026 voor het eerst gemeten tegen 86 speler-ronden met
    echte punten uit eigen_elf.csv:

      exact goed        67 van 86 (78%)
      gemiddelde fout   -0.48   (te laag: gemiste assists)
      RMSE              2.31
      te laag / te hoog 14 / 5  (elke overschatting was een gemiste kaart)

    Dat is geen kleinigheid naast een gerapporteerde model-RMSE van 3.42: als
    de twee fouten onafhankelijk zijn, komt 46% van de gemeten variantie uit de
    meetlat en niet uit het model. Gebruik daarom echte_punten() waar die
    bestaan -- zie lees_echte_punten().
    """
    lang = {"K": "Goalkeeper", "V": "Defender", "M": "Midfielder", "A": "Forward"}[positie_kort]
    p = w["ploegpunten"]
    p += w["clean_sheet"] * m.CLEANSHEET[positie_kort]
    p += w["goals"] * m.GOALWAARDE[lang]
    return p


def lees_echte_punten(pad="eigen_elf.csv"):
    """{(ronde, genormaliseerde naam): punten} uit eigen_elf.csv, of {}.

    Handmatig bijgehouden: Thomas leest ze wekelijks van de CVHJ-app af. Het
    zijn de ENIGE echte CVHJ-punten die dit project heeft -- alles wat uit
    spelers.csv komt is een reconstructie zonder assists, kaarten en
    reddingen.

    Alleen zijn eigen elf, dus hooguit elf spelers per ronde. Dat is een
    VERTEKENDE steekproef (spelers die het model hoog had staan), en daarom
    rapporteert evalueer_ronde() apart hoeveel rijen echt zijn en wat de
    maten los over die rijen doen. Een gemengde meetlat die je niet uit elkaar
    kunt halen, is geen verbetering.

    Ontbreekt het bestand, dan levert dit {} en draait backtest.py exact als
    voorheen.

    De sleutel is de ACHTERNAAM, kleingeschreven en zonder accenten. Dat is
    grof, maar eigen_elf.csv bevat alleen achternamen zoals de app ze toont,
    en binnen elf spelers per ronde is een botsing onwaarschijnlijk. Botst het
    toch, dan wint de reconstructie: zie evalueer_ronde().
    """
    bestand = Path(pad)
    if not bestand.exists():
        return {}
    uit, dubbel = {}, set()
    with bestand.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not (r.get("punten") or "").strip():
                continue          # niet gespeeld of geen wedstrijd: geen waarneming
            try:
                sleutel = (int(r["ronde"]), achternaam(r["speler"]))
                waarde = float(r["punten"])
            except (KeyError, TypeError, ValueError):
                continue
            if sleutel in uit and uit[sleutel] != waarde:
                dubbel.add(sleutel)
            uit[sleutel] = waarde
    for s in dubbel:
        uit.pop(s, None)          # tegenstrijdig: liever geen waarde dan de verkeerde
    return uit


def achternaam(naam):
    """Laatste woord, kleingeschreven, zonder accenten of leestekens."""
    deel = (naam or "").strip().split()
    if not deel:
        return ""
    s = unicodedata.normalize("NFKD", deel[-1]).encode("ascii", "ignore").decode()
    return "".join(ch for ch in s.lower() if ch.isalpha())


def spearman(x, y):
    """Rangcorrelatie zonder scipy: Pearson op de rangnummers."""
    n = len(x)
    if n < 2:
        return None
    def rangen(v):
        volgorde = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[volgorde[j + 1]] == v[volgorde[i]]:
                j += 1
            gem = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[volgorde[k]] = gem
            i = j + 1
        return r
    rx, ry = rangen(x), rangen(y)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (sx * sy) if sx > 0 and sy > 0 else None


def evalueer_ronde(m, clubrijen, spelerrijen, prijsrijen, ronde, venster, min_minuten,
                   fbref=None, echte_punten=None):
    """Eén ronde: fit op < ronde, voorspel ronde, vergelijk met werkelijkheid."""
    training = [r for r in clubrijen if int(r["ronde"]) < ronde]
    if not training:
        return None

    aanval, verdediging, thuisvoordeel, n_obs = m.schat_clubratings(training)
    if n_obs < 5:
        return None  # te weinig marktdata om iets zinnigs te fitten

    # Programma van de te voorspellen ronde: de WERKELIJKE paringen, uit
    # clubs.csv gehaald (dat weet immers al hoe de ronde liep). Voor de
    # puntenschatting zelf gebruikt bouw_pool alleen clubratings uit de
    # training, dus dit lekt geen toekomstige uitslagen in de voorspelling --
    # het levert alleen de WIE-tegen-WIE, die op de daadwerkelijke deadline
    # ook al bekend is.
    programma = sorted({(m.norm_club(r["club"]), m.norm_club(r["tegenstander"]))
                        for r in clubrijen if int(r["ronde"]) == ronde and r["thuis_uit"] == "thuis"})
    if not programma:
        return None

    # fbref DOORGEVEN. Zonder dit argument meet deze backtest een modelvariant
    # die niemand draait: productie (cvhj_model.py en multi_periode.py) geeft
    # spelerstats.csv wel mee, dus de assist- en kaarttermen zaten wel in het
    # advies en niet in de ijking. KRIMP_SPELER en KRIMP_CLUB werden daardoor
    # gekalibreerd op een ander model dan het model dat je gebruikt.
    #
    # Blijvende beperking, en die blijft staan: de WERKELIJKHEID hiernaast
    # (punten_met_positie) kan assists, kaarten en keepersreddingen niet
    # reconstrueren uit spelers.csv. De voorspelling bevat ze nu wel, de
    # waarheid niet. Dat maakt de RMSE een ondergrens, geen exacte maat --
    # maar het is eerlijker dan twee verschillende modellen vergelijken.
    pool = m.bouw_pool(prijsrijen, spelerrijen, aanval, verdediging, thuisvoordeel,
                       programma, {}, laatste_ronde=ronde - 1,
                       venster=venster, min_minuten=min_minuten, fbref=fbref)
    if not pool:
        return None

    werkelijk = werkelijke_punten(spelerrijen, ronde, m)

    # Echte CVHJ-punten gaan voor op de reconstructie. Ze bestaan alleen voor
    # Thomas' eigen elf (eigen_elf.csv), dus hooguit elf per ronde; de rest
    # blijft gereconstrueerd. Elke rij draagt daarom een veld `bron`, zodat de
    # twee uit elkaar te houden zijn. Een gemengde meetlat die je niet kunt
    # ontwarren is geen verbetering -- zie de samenvatting onderaan.
    echte = echte_punten if echte_punten is not None else lees_echte_punten()

    voorspeld, echt, rijen = [], [], []
    for p in pool:
        w = werkelijk.get(p["speler_id"])
        if w is None or w["minuten"] == 0:
            continue  # niet gespeeld deze ronde (blessure, bank, transfer) -- geen "fout", geen data
        gemeten = echte.get((ronde, achternaam(p["speler"])))
        if gemeten is None:
            wp, bron = punten_met_positie(w, p["pos"], m), "reconstructie"
        else:
            wp, bron = gemeten, "gemeten"
        voorspeld.append(p["E"]); echt.append(wp)
        rijen.append({"ronde": ronde, "speler": p["speler"], "club": p["club"], "pos": p["pos"],
                     "voorspeld": round(p["E"], 3), "werkelijk": round(wp, 3),
                     "fout": round(p["E"] - wp, 3), "bron": bron})

    if len(voorspeld) < 5:
        return None

    n = len(voorspeld)
    rmse = math.sqrt(sum((v - e) ** 2 for v, e in zip(voorspeld, echt)) / n)
    mae = sum(abs(v - e) for v, e in zip(voorspeld, echt)) / n
    bias = sum(v - e for v, e in zip(voorspeld, echt)) / n
    rho = spearman(voorspeld, echt)

    # Apart, over alleen de gemeten rijen: dat is het enige getal dat op een
    # ECHTE meetlat rust. Het is een vertekende steekproef (zijn eigen ploeg),
    # dus het hoort naast de hoofdmaat te staan en er niet in te verdwijnen.
    gem_rijen = [r for r in rijen if r["bron"] == "gemeten"]
    rmse_gemeten = (math.sqrt(sum(r["fout"] ** 2 for r in gem_rijen) / len(gem_rijen))
                    if len(gem_rijen) >= 3 else None)

    return {"ronde": ronde, "n": n, "n_pool": len(pool), "n_training_wedstrijden": n_obs,
            "n_gemeten": len(gem_rijen), "rmse_gemeten": rmse_gemeten,
            "rmse": rmse, "mae": mae, "bias": bias, "spearman": rho, "rijen": rijen}


def basislijn(m, spelerrijen, prijsrijen, ronde, venster, min_minuten):
    """Naïeve vergelijker: 'volgende ronde = gemiddelde van het venster',
    zonder clubratings, zonder programma. Als het model deze niet klopt,
    doet al het Poisson- en ridge-werk niets."""
    recent = {str(r) for r in range(max(1, ronde - venster), ronde)}
    vorm = collections.defaultdict(lambda: {"min": 0, "goals": 0, "duels": 0})
    for r in spelerrijen:
        if r["ronde"] not in recent or r["status"] == "afwezig":
            continue
        v = vorm[r.get("speler_id") or m.norm(r["speler"])]
        v["min"] += int(r["minuten"] or 0); v["goals"] += int(r["goals"] or 0); v["duels"] += 1

    werkelijk = werkelijke_punten(spelerrijen, ronde, m)
    prijs_pos = {r.get("speler_id") or m.norm(r["speler"]): r["positie"] for r in prijsrijen}
    KORT = {"Goalkeeper": "K", "Defender": "V", "Midfielder": "M", "Forward": "A"}

    voorspeld, echt = [], []
    for sid, v in vorm.items():
        if v["min"] < min_minuten or sid not in prijs_pos:
            continue
        w = werkelijk.get(sid)
        if w is None or w["minuten"] == 0:
            continue
        pos = KORT[prijs_pos[sid]]
        # gemiddelde CVHJ-punten per gespeelde wedstrijd in het venster,
        # geschat uit dezelfde drie termen als het echte model
        gem_goals = v["goals"] / v["duels"]
        naief = 1.5 + gem_goals * m.GOALWAARDE[prijs_pos[sid]]  # 1.5 ~ gem. ploegpunten
        voorspeld.append(naief); echt.append(punten_met_positie(w, pos, m))

    if len(voorspeld) < 5:
        return None
    n = len(voorspeld)
    rmse = math.sqrt(sum((v - e) ** 2 for v, e in zip(voorspeld, echt)) / n)
    rho = spearman(voorspeld, echt)
    return {"rmse": rmse, "n": n, "spearman": rho}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--clubs", default="clubs.csv")
    p.add_argument("--spelers", default="spelers.csv")
    p.add_argument("--prijzen", default="prijzen.csv")
    p.add_argument("--vanaf", type=int, help="eerste te voorspellen ronde (default: vroegst mogelijke)")
    p.add_argument("--tot", type=int, help="laatste te voorspellen ronde (default: laatst bekende)")
    p.add_argument("--venster", type=int, default=6)
    p.add_argument("--min-minuten", type=int, default=60)
    p.add_argument("--per-speler", metavar="BESTAND", help="ruwe voorspelling/werkelijkheid per speler wegschrijven")
    a = p.parse_args()

    m = laad_model()
    clubrijen = m.lees(a.clubs)
    spelerrijen = m.lees(a.spelers)
    prijsrijen = m.lees(a.prijzen)

    max_ronde = max(int(r["ronde"]) for r in clubrijen)
    vanaf = a.vanaf or 2
    tot = a.tot or max_ronde

    print(f"Backtest ronde {vanaf} t/m {tot} (data beschikbaar t/m ronde {max_ronde})\n")
    print(f"{'ronde':>5s}{'n_train':>9s}{'n_pool':>8s}{'n_eval':>8s}"
          f"{'RMSE':>8s}{'MAE':>7s}{'bias':>7s}{'rho':>7s}{'RMSE naief':>12s}{'rho naief':>11s}")

    # Dezelfde statistieken als productie gebruikt; zie evalueer_ronde().
    fbref = m.lees_spelerstats(m.stats_pad("spelerstats.csv"))
    print("spelerstats: " + (f"{len(fbref)} spelers" if fbref else
                             "niet gevonden -- de ijking meet dan het model ZONDER "
                             "assists en kaarten, terwijl het advies ze wel gebruikt"))

    resultaten, alle_rijen = [], []
    for ronde in range(vanaf, tot + 1):
        r = evalueer_ronde(m, clubrijen, spelerrijen, prijsrijen, ronde, a.venster,
                           a.min_minuten, fbref=fbref)
        b = basislijn(m, spelerrijen, prijsrijen, ronde, a.venster, a.min_minuten)
        if r is None:
            print(f"{ronde:5d}   -- onvoldoende data om te voorspellen of te evalueren --")
            continue
        resultaten.append(r)
        alle_rijen += r["rijen"]
        rho_s = f"{r['spearman']:.3f}" if r["spearman"] is not None else "n.v.t."
        b_rmse = f"{b['rmse']:.2f}" if b else "n.v.t."
        b_rho = f"{b['spearman']:.3f}" if b and b["spearman"] is not None else "n.v.t."
        print(f"{ronde:5d}{r['n_training_wedstrijden']:9d}{r['n_pool']:8d}{r['n']:8d}"
              f"{r['rmse']:8.2f}{r['mae']:7.2f}{r['bias']:+7.2f}{rho_s:>7s}{b_rmse:>12s}{b_rho:>11s}")

    if not resultaten:
        sys.exit("\nGeen enkele ronde kon worden geëvalueerd. Te weinig data of --vanaf/--tot buiten bereik.")

    n_tot = sum(r["n"] for r in resultaten)
    rmse_tot = math.sqrt(sum(r["rmse"] ** 2 * r["n"] for r in resultaten) / n_tot)
    mae_tot = sum(r["mae"] * r["n"] for r in resultaten) / n_tot
    bias_tot = sum(r["bias"] * r["n"] for r in resultaten) / n_tot
    rhos = [r["spearman"] for r in resultaten if r["spearman"] is not None]
    rho_tot = sum(rhos) / len(rhos) if rhos else None

    print(f"\n{'TOTAAL':>5s}{'':9s}{'':8s}{n_tot:8d}{rmse_tot:8.2f}{mae_tot:7.2f}{bias_tot:+7.2f}"
          f"{(f'{rho_tot:.3f}' if rho_tot is not None else 'n.v.t.'):>7s}")

    print(f"\nInterpretatie:")
    print(f"  bias > 0  : model voorspelt structureel te HOOG")
    print(f"  bias < 0  : model voorspelt structureel te LAAG")
    print(f"  rho dicht bij 1 : het model zet spelers in de juiste volgorde,")
    print(f"                    ook als de absolute punten afwijken -- voor de")
    print(f"                    opstellingskeuze is dit belangrijker dan RMSE.")
    # Hoeveel van de waarheid hierboven GEMETEN is, en hoeveel gereconstrueerd.
    # Die twee horen uit elkaar gehouden te worden: de hoofdmaat hierboven is
    # een mengsel, en een mengsel dat je niet kunt ontwarren is geen meting.
    gemeten_n = sum(r.get("n_gemeten", 0) for r in resultaten)
    alle_n = sum(r["n"] for r in resultaten)
    if gemeten_n:
        gem_fouten = [x["fout"] for r in resultaten for x in r["rijen"]
                      if x.get("bron") == "gemeten"]
        rec_fouten = [x["fout"] for r in resultaten for x in r["rijen"]
                      if x.get("bron") != "gemeten"]
        def _rmse(v):
            return math.sqrt(sum(x * x for x in v) / len(v)) if v else float("nan")
        print(f"\nWAARHEID: GEMETEN TEGENOVER GERECONSTRUEERD")
        print(f"  {gemeten_n} van {alle_n} rijen ({100*gemeten_n/alle_n:.1f}%) komen uit "
              f"eigen_elf.csv en zijn ECHTE CVHJ-punten.")
        print(f"    RMSE over alleen die rijen        {_rmse(gem_fouten):.2f}")
        print(f"    RMSE over de gereconstrueerde rest {_rmse(rec_fouten):.2f}")
        print(f"  De eerste rust op een echte meetlat maar is een VERTEKENDE steekproef")
        print(f"  (Thomas' eigen ploeg: spelers die het model hoog had staan). De tweede")
        print(f"  mist nog steeds assists, kaarten en reddingen. Vergelijk ze dus niet")
        print(f"  alsof het dezelfde maat is.")
    else:
        print(f"\n  Geen eigen_elf.csv gevonden: alle waarheid hierboven is")
        print(f"  gereconstrueerd uit spelers.csv.")

    print(f"\n  LET OP: waar 'werkelijk' gereconstrueerd is, mist het assists, kaarten")
    print(f"  en keeper-reddingen, want die staan niet in spelers.csv. Gemeten tegen 86")
    print(f"  echte speler-ronden is die reconstructie 78% exact, met een RMSE van 2.31")
    print(f"  en een gemiddelde van -0.48 (te laag door gemiste assists, te hoog door")
    print(f"  gemiste kaarten). Dat is geen kleinigheid naast een model-RMSE rond 3.4:")
    print(f"  bij onafhankelijke fouten komt ~46% van de gemeten variantie uit de")
    print(f"  meetlat. Gebruik dit OM WIJZIGINGEN TE VERGELIJKEN, niet om een RMSE-doel")
    print(f"  op zich na te jagen.")

    if a.per_speler:
        with open(a.per_speler, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["ronde", "speler", "club", "pos",
                                              "voorspeld", "werkelijk", "fout"])
            w.writeheader(); w.writerows(alle_rijen)
        print(f"\nper-speler resultaten -> {a.per_speler}")


if __name__ == "__main__":
    main()
