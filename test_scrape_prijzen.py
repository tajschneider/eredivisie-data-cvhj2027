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


# --------------------------------------------------------- vermoedelijke elf
# De opstellingsparser is drie keer omgevallen op een gewijzigde bron, en elke
# keer bleek dat pas uit een live run. Deze test bouwt de pagina na zoals de
# --debug van 23-10-2026 hem laat zien, zodat de LOGICA hier faalt in plaats
# van zaterdag in de scrape. Wat hieruit is overgenomen en dus gemeten is:
# de koppenreeks met hun niveaus, de elf starters als spelerslinks in het blok
# onder de h2 "Verwachte opstelling" met een h3 "PSV" erbinnen, geen enkel
# percentage naast een speler, en een FAQ die de spelers niet opnieuw linkt
# (16 links op de pagina, 16 uniek).
#
# Deze cases horen in een eigen bestand. Ze staan hier omdat tests.yml elk
# testbestand bij naam aanroept en grenzen.py een voorstel verbiedt dat
# .github/workflows/ aanraakt -- een nieuw bestand zou dus nooit draaien, en
# een test die niet draait is geen test. Wil je ze apart, voeg dan met de hand
# "python test_opstelling.py" toe aan tests.yml.
# Twee clubs, want een reparatie die alleen op PSV werkt is geen reparatie.
# Ajax voegt drie dingen toe die PSV niet heeft: het is de UITPLOEG (de
# kansenregel staat omgekeerd), er zijn VIER afwezigen in plaats van vijf (dus
# 15 spelerslinks op de pagina in plaats van 16, wat de terugval anders laat
# rekenen), en er staat een naam met een tussenvoegsel in ("Marc ter Stegen").
# Beide koppenreeksen komen letterlijk uit de --debug van 23-10-2026 en zijn
# identiek van opbouw, en dat is wat de kopanker-aanpak hier draagt.
_PSV = {
    "club": "PSV", "tegen": "Feyenoord", "thuis": True,
    "elf": [("matej-kovar", "Matej Kovar"), ("filip-kostic", "Filip Kostic"),
            ("armando-obispo", "Armando Obispo"), ("lutsharel-geertruida", "Lutsharel Geertruida"),
            ("sergino-dest", "Sergino Dest"), ("kodai-sano", "Kodai Sano"),
            ("mauro-junior", "Mauro Junior"), ("ayoni-santos", "Ayoni Santos"),
            ("dennis-man", "Dennis Man"), ("ivan-perisic", "Ivan Perisic"),
            ("mikkel-bro-hansen", "Mikkel Bro Hansen")],
    "afwezig": [("paul-wanner", "Paul Wanner", "blessure", ""),
                ("sam-lammers", "Sam Lammers", "blessure", ""),
                ("jerdy-schouten", "Jerdy Schouten", "blessure", "01-05-2027"),
                ("adamo-nagalo", "Adamo Nagalo", "schorsing", "28-01-2027"),
                ("alassane-plea", "Alassane Plea", "schorsing", "28-01-2027")],
}
_AJAX = {
    "club": "Ajax", "tegen": "Sparta Rotterdam", "thuis": False,
    "elf": [("marc-ter-stegen", "Marc ter Stegen"), ("owen-wijndal", "Owen Wijndal"),
            ("dies-janse", "Dies Janse"), ("aaron-bouwman", "Aaron Bouwman"),
            ("lucas-rosa", "Lucas Rosa"), ("sofyan-amrabat", "Sofyan Amrabat"),
            ("jorthy-mokio", "Jorthy Mokio"), ("oscar-gloukh", "Oscar Gloukh"),
            ("wout-weghorst", "Wout Weghorst"), ("mika-godts", "Mika Godts"),
            ("raul-moro", "Raul Moro")],
    "afwezig": [("oliver-valaker-edvardsen", "Oliver Valaker Edvardsen", "blessure", ""),
                ("kasper-dolberg", "Kasper Dolberg", "blessure", "01-07-2027"),
                ("steven-berghuis", "Steven Berghuis", "blessure", ""),
                ("daley-blind", "Daley Blind", "blessure", "")],
}


def _kaart(slug, naam, percentage=None):
    """Een starter zoals de bron hem neerzet: een link met avatar en naam."""
    pct = f"<span>{percentage}%</span>" if percentage is not None else ""
    return (f'<a class="flex flex-col items-center" href="/eredivisie/speler/{slug}/">'
            f'<div class="relative">'
            f'<img alt="{naam}" src="https://cdn.example/1.png"/>'
            f'<span class="absolute -bottom-1 -right-1">9</span></div>'
            f'<span class="text-[11px]">{naam}</span>{pct}</a>')


def _pagina(d, met_percentage=False, faq_met_links=False, extra_links=0):
    club, tegen = d["club"], d["tegen"]
    rijen = "".join(_kaart(s, n, (90 - i) if met_percentage else None)
                    for i, (s, n) in enumerate(d["elf"]))
    afw = "".join(f'<div><a href="/eredivisie/speler/{s}/">{n}</a> {reden}'
                  + (f' &middot; verwacht terug rond {t}' if t else "") + '</div>'
                  for s, n, reden, t in d["afwezig"])
    faq = ("".join(f'<a href="/eredivisie/speler/{s}/">{n}</a>' for s, n in d["elf"][:4])
           if faq_met_links else "")
    rommel = "".join(f'<a href="/eredivisie/speler/vreemd-{i}/">Vreemd {i}</a>'
                     for i in range(extra_links))
    # De kansenregel staat in de volgorde thuis - uit, dus omgekeerd voor een
    # uitploeg. Alleen deze percentages staan nog op de pagina; als de parser
    # ze per ongeluk als basiskans oppikt, valt dat hier op.
    links, rechts = (club, tegen) if d["thuis"] else (tegen, club)
    return f"""<!doctype html><html><body>
<h1>Vermoedelijke opstelling {club} tegen {tegen}</h1>
<p>Kansen op {links} - {rechts} 48% {links} 21% gelijk {rechts} 31%</p>
<h2>Live: de officiele opstelling zodra die bekend is</h2>
<h2>Verwachte opstelling {club} tegen {tegen}</h2>
<h3>{club}</h3>
<div class="relative flex flex-col-reverse">{rijen}{rommel}</div>
<h2>Wat deze opstelling betekent</h2>
<h2>Blessures en schorsingen {club}</h2>
<div>{afw}</div>
<h2>Veelgestelde vragen</h2>
<h3>Wat is de vermoedelijke opstelling van {club}?</h3>
<p>{faq} De vermoedelijke opstelling staat hierboven.</p>
<h3>Welke spelers van {club} zijn geblesseerd of geschorst?</h3>
<p>Zie het blok hierboven.</p>
</body></html>"""


def test_vermoedelijke_elf():
    from bs4 import BeautifulSoup
    import scrape_eredivisie as s

    ok = True
    for d in (_PSV, _AJAX):
        club, n_elf, n_afw = d["club"], len(d["elf"]), len(d["afwezig"])
        print(f"  --- {club} ({'thuis' if d['thuis'] else 'uit'}, "
              f"{n_elf} starters, {n_afw} afwezigen) ---")

        def draai(html):
            return s.parse_opstelling(BeautifulSoup(html, "html.parser"), club)

        gevallen = []

        # 1. De pagina van vandaag: de elf, de afwezigen, GEEN percentages. Een
        #    lege kans_basis is geldig -- cvhj_model.lees_opstellingen() houdt
        #    de speler dan in de elf, en alleen dat lidmaatschap weegt mee. De
        #    namen moeten uit het alt-attribuut komen, dus met tussenvoegsel
        #    ("Marc ter Stegen") en niet uit de slug met hoofdletters.
        elf, afw = draai(_pagina(d))
        namen_goed = [e["speler"] for e in elf] == [n for _, n in d["elf"]]
        gevallen.append((len(elf) == n_elf and len(afw) == n_afw
                         and all(e["kans_basis"] == "" for e in elf) and namen_goed
                         and not ({e["speler_id"] for e in elf} & {a["speler_id"] for a in afw}),
                         f"zonder percentages: {len(elf)} starters, {len(afw)} afwezigen, "
                         f"kans leeg, namen letterlijk, geen overlap"))

        # 2. Zet de bron de percentages terug, dan worden ze weer opgepikt
        #    zonder dat hier iemand aan te pas komt.
        elf2, _ = draai(_pagina(d, met_percentage=True))
        gevallen.append((len(elf2) == n_elf and [e["kans_basis"] for e in elf2][:3] == [90, 89, 88],
                         f"met percentages: {[e['kans_basis'] for e in elf2][:3]}"))

        # 3. De FAQ die dezelfde spelers nog eens linkt -- de vervuiling die de
        #    afwezigenparser eerder op 15 namen bracht. Het blok moet erbuiten
        #    eindigen.
        elf3, _ = draai(_pagina(d, faq_met_links=True))
        gevallen.append((len(elf3) == n_elf, f"FAQ met dezelfde links: {len(elf3)} starters"))

        # 4. Vervuiling BINNEN het blok: dan niets afleveren. Afkappen op elf
        #    zou de fout verbergen, en vijftien namen in een CSV zien er
        #    volwaardig uit.
        elf4, afw4 = draai(_pagina(d, extra_links=4))
        gevallen.append((elf4 == [] and len(afw4) == n_afw,
                         f"vier vreemde links in het blok: {len(elf4)} starters "
                         f"(0 verwacht), afwezigen blijven {len(afw4)}"))

        # 5. Kop weg: terugval op de hele pagina. Die rust erop dat alle
        #    spelerslinks minus de afwezigen de elf zijn -- bij PSV 16-5, bij
        #    Ajax 15-4 -- en werkt alleen zolang het afwezigenblok gelezen wordt.
        elf5, _ = draai(_pagina(d).replace(
            f"<h2>Verwachte opstelling {club} tegen {d['tegen']}</h2>", "<h2>Elftal</h2>"))
        gevallen.append((len(elf5) == n_elf,
                         f"zonder de kop: {len(elf5)} starters via de terugval "
                         f"({n_elf + n_afw} links min {n_afw} afwezigen)"))

        for goed, tekst in gevallen:
            print(f"  {'OK  ' if goed else 'FOUT'} {tekst}")
            ok = ok and goed
    return ok

# ------------------------------------------------- kolomformaat van spelers.csv
def test_spelers_formaat():
    """De afspraak tussen de scraper en het model over spelers.csv.

    Hier zat een stille tijdbom. De scraper schrijft sinds de ombouw naar
    momentopnamen een nieuw kolomformaat ZONDER de kolom `status`, en
    bouw_pool() las die zonder terugval. Dat is nooit opgevallen omdat het
    nieuwe formaat tot 23-10-2026 niet is weggeschreven: de eerste
    momentopname levert geen ronderijen op, en tussen de eerste en de tweede
    was geen ronde gespeeld. De eerste echte productierun zou een KeyError
    hebben gegeven op het model EN op zijn terugval.

    Twee dingen worden hier vastgelegd: dat het model beide formaten leest, en
    dat een formaatwissel de bestaande rijen niet weggooit.
    """
    import csv, tempfile
    from pathlib import Path
    import cvhj_model as m
    import scrape_eredivisie as s

    ok = True

    # 1. rijstatus(): de kolom wint als hij er is, anders afleiden.
    gevallen = [
        ({"status": "bank", "basis": 1, "minuten": 90}, "bank", "kolom wint van afleiding"),
        ({"basis": "1", "minuten": "90"}, "basis", "begon -> basis"),
        ({"basis": "0", "minuten": "23"}, "invaller", "speelde zonder te beginnen"),
        ({"basis": "0", "minuten": "0"}, "bank", "geen minuten -> bank, niet afwezig"),
        ({"basis": "", "minuten": ""}, "bank", "lege velden"),
        ({"basis": "2", "minuten": "170", "duels": "2"}, "basis", "vensterrij met twee basisplaatsen"),
    ]
    for rij, verwacht, waarom in gevallen:
        uit = m.rijstatus(rij)
        goed = uit == verwacht
        print(f"  {'OK  ' if goed else 'FOUT'} rijstatus: {waarom} -> {uit!r}")
        ok = ok and goed

    # "afwezig" mag NOOIT worden afgeleid: bouw_pool() slaat zo'n rij helemaal
    # over, en een rij met nul minuten hoort juist mee te tellen als een duel
    # waarin hij niet speelde.
    nooit = [m.rijstatus({"basis": b, "minuten": mi})
             for b in ("0", "", "1") for mi in ("0", "", "90")]
    goed = "afwezig" not in nooit
    print(f"  {'OK  ' if goed else 'FOUT'} rijstatus leidt nooit 'afwezig' af")
    ok = ok and goed

    # 2. bouw_pool() op BEIDE formaten, met dezelfde data.
    def rij(ronde, sid, oud):
        kern = {"ronde": str(ronde), "speler": sid.replace("-", " ").title(),
                "speler_id": sid, "club": "Ajax", "minuten": "90", "goals": "0",
                "basis": "1"}
        if oud:
            return {**kern, "status": "basis", "tegenstander": "PSV",
                    "thuis_uit": "thuis", "clean_sheet": "0", "ploegpunten": "3",
                    "datum": "", "afwezig_reden": "", "opgehaald": "2026-10-23"}
        return {**{c: "" for c in s.SPELER_COLS}, **kern,
                "duels": "1", "venster": str(ronde)}

    prijs = [{"team": "Ajax", "speler": "Speler Een", "positie": "Midfielder",
              "prijs": "2.0", "speler_id": "speler-een"}]
    # norm_club() verlaagt geen kapitalen, dus de sleutels zijn de clubnamen
    # zoals ze in de CSV's staan -- niet de kleine-letterversie.
    aanval = {"Ajax": 0.1, "PSV": 0.1}
    verdediging = {"Ajax": 0.0, "PSV": 0.0}
    uitkomst = {}
    for naam, oud in (("oud", True), ("nieuw", False)):
        rijen = [rij(ro, "speler-een", oud) for ro in range(4, 10)]
        try:
            pool = m.bouw_pool(prijs, rijen, aanval, verdediging, 0.1,
                               [("Ajax", "PSV")], {}, laatste_ronde=9)
            uitkomst[naam] = round(pool[0]["E"], 6) if pool else None
        except Exception as e:                                   # noqa: BLE001
            uitkomst[naam] = f"{type(e).__name__}: {e}"
    goed = (uitkomst["oud"] is not None and uitkomst["oud"] == uitkomst["nieuw"])
    print(f"  {'OK  ' if goed else 'FOUT'} bouw_pool: oud {uitkomst['oud']} == "
          f"nieuw {uitkomst['nieuw']}")
    ok = ok and goed

    # 3. schrijf(): een formaatwissel mag de bestaande rijen niet weggooien.
    map_ = Path(tempfile.mkdtemp())
    pad = map_ / "spelers.csv"
    oude_rijen = [rij(ro, f"speler-{i}", True) for ro in (7, 8, 9) for i in range(4)]
    with open(pad, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(oude_rijen[0]))
        w.writeheader(); w.writerows(oude_rijen)
    s.schrijf(pad, s.SPELER_COLS, [rij(10, "speler-0", False)],
              ["ronde", "speler_id", "club"])
    na = s.lees(pad)
    goed = (len(na) == len(oude_rijen) + 1
            and sorted({int(r["ronde"]) for r in na}) == [7, 8, 9, 10]
            and set(na[0]) == set(s.SPELER_COLS))
    print(f"  {'OK  ' if goed else 'FOUT'} schrijf: {len(oude_rijen)} oude rijen "
          f"-> {len(na)} totaal, ronden {sorted({int(r['ronde']) for r in na})}")
    ok = ok and goed

    # En het model moet dat geconverteerde bestand nog kunnen lezen. De
    # prijslijst moet wel over DEZE spelers gaan: speler-0 heeft rijen in de
    # ronden 7 t/m 9 (oud formaat) en een in ronde 10 (nieuw), dus hij komt uit
    # het geconverteerde bestand met beide soorten rijen tegelijk.
    prijs_na = [{"team": "Ajax", "speler": "Speler 0", "positie": "Midfielder",
                 "prijs": "2.0", "speler_id": "speler-0"}]
    try:
        pool = m.bouw_pool(prijs_na, na, aanval, verdediging, 0.1,
                           [("Ajax", "PSV")], {}, laatste_ronde=9)
        goed = len(pool) == 1 and pool[0]["duels"] == 3
    except Exception as e:                                       # noqa: BLE001
        goed, pool = False, f"{type(e).__name__}: {e}"
    print(f"  {'OK  ' if goed else 'FOUT'} model leest het geconverteerde bestand "
          f"({len(pool) if goed else pool})")
    return ok and goed


# --------------------------------------------- terugkeerdatum per ronde
def test_terugkeerdatum():
    """Een afwezige met een terugkeerdatum binnen de horizon doet vanaf die
    ronde weer mee -- en een datum die al verstreken is, telt niet.

    De bron levert deze datums sinds 23-10-2026, bij 18 van de 59 afwezigen.
    Ze zijn GROF: blessuredatums staan op de eerste van de maand, en zes
    schorsingen bij vier clubs delen twee datums twee dagen na elkaar. Een te
    late datum houdt iemand onnodig buiten de pool (dezelfde kant op als de
    oude blinde uitsluiting), een te vroege laat iemand toe die niet mag
    spelen. Daarom staan hier beide grenzen vast.
    """
    import datetime
    import cvhj_model as m

    morgen = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
    gisteren = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()

    ok = True
    clubrijen = [{"ronde": "10", "datum": "2026-10-23"},
                 {"ronde": "10", "datum": "2026-10-25"},
                 {"ronde": "11", "datum": "2026-10-31"},
                 {"ronde": "12", "datum": ""},
                 {"ronde": "x", "datum": "2026-11-06"}]
    datums = m.ronde_datums(clubrijen)
    goed = datums == {"10": "2026-10-23", "11": "2026-10-31"} or datums == {10: "2026-10-23", 11: "2026-10-31"}
    print(f"  {'OK  ' if goed else 'FOUT'} ronde_datums: de EERSTE speeldag per "
          f"ronde, lege en onleesbare rijen overgeslagen -> {datums}")
    ok = ok and goed

    prijs = [{"team": "Ajax", "speler": "Speler Een", "positie": "Midfielder",
              "prijs": "2.0", "speler_id": "speler-een"}]
    spelerrijen = [{"ronde": str(ro), "speler": "Speler Een", "speler_id": "speler-een",
                    "club": "Ajax", "minuten": "90", "goals": "0", "basis": "1",
                    "status": "basis"} for ro in range(4, 10)]
    aanval, verdediging = {"Ajax": 0.1, "PSV": 0.1}, {"Ajax": 0.0, "PSV": 0.0}

    def pool(afwezig, peildatum):
        return m.bouw_pool(prijs, spelerrijen, aanval, verdediging, 0.1,
                           [("Ajax", "PSV")], {}, laatste_ronde=9,
                           afwezig=afwezig, peildatum=peildatum, meld=False)

    afw = {"speler-een": {"speler": "Speler Een", "club": "Ajax",
                          "reden": "schorsing", "verwacht_terug": morgen}}
    gevallen = [
        (None, None, 1, "geen afwezigenlijst: in de pool"),
        (afw, None, 0, "afwezig, geen peildatum: uitgesloten (oud gedrag)"),
        (afw, "2026-10-23", 0, "peildatum VOOR de terugkeerdatum: uitgesloten"),
        (afw, morgen, 1, "peildatum OP de terugkeerdatum: weer in de pool"),
        (afw, "2099-01-01", 1, "peildatum na de terugkeerdatum: in de pool"),
    ]
    for a, peil, verwacht, waarom in gevallen:
        n = len(pool(a, peil))
        goed = n == verwacht
        print(f"  {'OK  ' if goed else 'FOUT'} {waarom} -> {n} speler(s)")
        ok = ok and goed

    # Een verstreken datum telt niet: staat hij nog op de lijst, dan is de
    # lijst betrouwbaarder dan de datum.
    verstreken = {"speler-een": {**afw["speler-een"], "verwacht_terug": gisteren}}
    n = len(pool(verstreken, "2099-01-01"))
    goed = n == 0
    print(f"  {'OK  ' if goed else 'FOUT'} terugkeerdatum in het verleden -> "
          f"{n} speler(s), blijft uitgesloten")
    ok = ok and goed

    # Een onleesbare datum mag niemand vrijgeven.
    for rommel in ("binnenkort", "02-11-2026", "2026-11", ""):
        stuk = {"speler-een": {**afw["speler-een"], "verwacht_terug": rommel}}
        n = len(pool(stuk, "2099-01-01"))
        goed = n == 0
        print(f"  {'OK  ' if goed else 'FOUT'} onleesbare datum {rommel!r} -> "
              f"{n} speler(s), blijft uitgesloten")
        ok = ok and goed
    return ok


# ------------------------------------- seizoensstand als terugval voor stats
def test_stats_uit_seizoen():
    """spelers_seizoen.csv als terugval voor een ontbrekende spelerstats.csv.

    Zonder dat bestand droegen assists en kaarten EXACT NUL bij aan elke
    verwachting, terwijl een assist 5/4/3/2 punten waard is en een gele kaart
    -3. De seizoensmomentopname heeft die getallen gewoon -- maar geen xG, en
    daar zat de valkuil: met xg_per90 op 0 en een gematchte speler trok de
    doelpuntenbreuk IEDERE verwachting naar nul (som over de pool 648 -> 580,
    de topspelers het hardst). Daarom hangt het gewicht van die term nu aan de
    vraag of er werkelijk een xG-waarde is.
    """
    import csv, tempfile
    from pathlib import Path
    import cvhj_model as m

    ok = True
    map_ = Path(tempfile.mkdtemp())
    pad = map_ / "spelers_seizoen.csv"
    kolommen = ["opgehaald", "speler_id", "speler", "club", "positie", "duels",
                "basisplaatsen", "minuten", "goals", "assists", "overtredingen",
                "reddingen", "nul_achter", "cijfer", "geel", "rood", "status_tekst"]

    def rij(opgehaald, sid, minuten, goals=0, assists=0, geel=0, rood=0):
        return {**{k: "" for k in kolommen}, "opgehaald": opgehaald,
                "speler_id": sid, "speler": sid.replace("-", " ").title(),
                "club": "Ajax", "positie": "Midfielder", "minuten": str(minuten),
                "goals": str(goals), "assists": str(assists),
                "geel": str(geel), "rood": str(rood)}

    # Twee momentopnamen naast elkaar: alleen de nieuwste mag meedoen, anders
    # telt een speler dubbel en verdubbelt zijn seizoenstotaal.
    rijen = [rij("2026-10-19", "speler-een", 450, goals=2, assists=1),
             rij("2026-10-23", "speler-een", 810, goals=4, assists=3, geel=2),
             rij("2026-10-23", "speler-nul", 0, goals=0, assists=0)]
    with open(pad, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=kolommen)
        w.writeheader(); w.writerows(rijen)

    stats = m.stats_uit_seizoen(pad)
    sleutel = f"{m.norm('Speler Een')}|{m.norm('Ajax')}"
    e = (stats or {}).get(sleutel, {})
    gevallen = [
        (stats is not None and len(stats) == 1, f"alleen de nieuwste stand, "
         f"en niemand zonder minuten: {len(stats or {})} speler(s)"),
        (abs(e.get("minuten_90s", 0) - 9.0) < 1e-9, f"minuten_90s = 810/90 = "
         f"{e.get('minuten_90s')}"),
        (abs(e.get("assists_per90", 0) - 3/9) < 1e-9, f"assists_per90 = 3/9 = "
         f"{e.get('assists_per90')}"),
        (e.get("gele_kaarten") == 2.0, f"gele kaarten als TOTAAL, niet per 90: "
         f"{e.get('gele_kaarten')}"),
        (e.get("xg_per90") == 0.0 and e.get("xag_per90") == 0.0,
         "xg en xag blijven leeg -- de bron heeft ze niet"),
    ]
    for goed, tekst in gevallen:
        print(f"  {'OK  ' if goed else 'FOUT'} {tekst}")
        ok = ok and goed

    goed = m.stats_uit_seizoen(map_ / "bestaat-niet.csv") is None
    print(f"  {'OK  ' if goed else 'FOUT'} ontbrekend bestand -> None")
    ok = ok and goed

    # De kern: een bron ZONDER xG mag de doelpuntenschatting niet aanraken.
    prijs = [{"team": "Ajax", "speler": "Speler Een", "positie": "Midfielder",
              "prijs": "2.0", "speler_id": "speler-een"}]
    spelerrijen = [{"ronde": str(ro), "speler": "Speler Een", "speler_id": "speler-een",
                    "club": "Ajax", "minuten": "90", "goals": "1", "basis": "1",
                    "status": "basis"} for ro in range(4, 10)]
    aanval, verdediging = {"Ajax": 0.1, "PSV": 0.1}, {"Ajax": 0.0, "PSV": 0.0}

    def e_van(fb):
        p = m.bouw_pool(prijs, spelerrijen, aanval, verdediging, 0.1,
                        [("Ajax", "PSV")], {}, laatste_ronde=9, fbref=fb, meld=False)
        return p[0]["E"] if p else None

    zonder = e_van(None)
    met_seizoen = e_van(stats)
    # xg kunstmatig gevuld: dan MOET de doelpuntenterm wel meebewegen, anders
    # is de schakelaar te grof en doet echte xG ook niets meer.
    met_xg = e_van({sleutel: {**stats[sleutel], "xg_per90": 0.9}})
    goed = met_seizoen > zonder
    print(f"  {'OK  ' if goed else 'FOUT'} assists tellen mee: E {zonder:.3f} -> "
          f"{met_seizoen:.3f} (hoger verwacht)")
    ok = ok and goed
    goed = abs(met_xg - met_seizoen) > 1e-6
    print(f"  {'OK  ' if goed else 'FOUT'} met echte xG beweegt de doelpuntenterm "
          f"wel: E {met_seizoen:.3f} -> {met_xg:.3f}")
    return ok and goed


def test_reddingspunten():
    """De reddingsterm moet aan de constanten hangen, en alleen bij keepers.

    De constante stond op 1.6 zonder dat er ooit aan gerekend was. Gemeten op
    20 keepers met >=270 minuten (510 reddingen in 155 hele wedstrijden) komt
    er 2.4 uit: 3.257 reddingen per 90 tegen 1.353 verwachte tegengoals per
    90. De oude waarde gaf 0.433 punt per 90 waar 0.651 +/- 0.041 werd
    gemeten, een gat van 5.3 standaardfouten.

    Deze test controleert niet of 2.4 het juiste getal is -- dat is een
    meting, geen eigenschap van de code. Hij controleert dat de term
    daadwerkelijk aan de constanten hangt en lineair meebeweegt, zodat een
    volgende herijking ook echt doorwerkt, en dat hij veldspelers niet raakt.
    """
    import cvhj_model as m

    ok = True
    prijs = [{"team": "Ajax", "speler": "De Keeper", "positie": "Goalkeeper",
              "prijs": "2.0", "speler_id": "de-keeper"},
             {"team": "Ajax", "speler": "De Spits", "positie": "Forward",
              "prijs": "2.0", "speler_id": "de-spits"}]
    spelerrijen = [{"ronde": str(ro), "speler": naam, "speler_id": sid,
                    "club": "Ajax", "minuten": "90", "goals": "0", "basis": "1",
                    "status": "basis"}
                   for ro in range(4, 10)
                   for naam, sid in (("De Keeper", "de-keeper"), ("De Spits", "de-spits"))]
    # PSV een flinke aanval geven, zodat er werkelijk tegendoelpunten verwacht
    # worden -- met lt = 0 zou de hele term 0 zijn en zou de test niets zeggen.
    aanval, verdediging = {"Ajax": 0.1, "PSV": 0.6}, {"Ajax": 0.0, "PSV": 0.0}

    def e_van(k):
        bewaard = m.REDDINGEN_PER_TEGENGOAL
        m.REDDINGEN_PER_TEGENGOAL = k
        try:
            pool = m.bouw_pool(prijs, spelerrijen, aanval, verdediging, 0.1,
                               [("Ajax", "PSV")], {}, laatste_ronde=9, meld=False)
            return {p["speler_id"]: p["E"] for p in pool}
        finally:
            m.REDDINGEN_PER_TEGENGOAL = bewaard

    uit0, uit1, uit2 = e_van(0.0), e_van(2.4), e_van(4.8)
    term1 = uit1["de-keeper"] - uit0["de-keeper"]
    term2 = uit2["de-keeper"] - uit0["de-keeper"]

    gevallen = [
        (m.REDDINGEN_PER_PUNT == 5,
         f"1 punt per 5 reddingen is een spelregel: REDDINGEN_PER_PUNT = "
         f"{m.REDDINGEN_PER_PUNT}"),
        (abs(m.REDDINGEN_PER_TEGENGOAL - 2.4) < 1e-9,
         f"de gemeten constante staat op 2.4 (nu {m.REDDINGEN_PER_TEGENGOAL}) -- "
         f"wijzig je die, werk dan de meting in cvhj_model.py bij"),
        (term1 > 0.01,
         f"de keeper krijgt werkelijk reddingspunten: {term1:.3f}"),
        (abs(term2 - 2 * term1) < 1e-9,
         f"de term is lineair in de constante: {term1:.3f} -> {term2:.3f} "
         f"(tweemaal verwacht)"),
        (abs(uit0["de-spits"] - uit1["de-spits"]) < 1e-9,
         f"de spits blijft onaangeroerd: {uit0['de-spits']:.3f} vs "
         f"{uit1['de-spits']:.3f}"),
    ]
    for goed, tekst in gevallen:
        print(f"  {'OK  ' if goed else 'FOUT'} {tekst}")
        ok = ok and goed

    # En de richting van het bedrag: met de oude 1.6 lag de keeper lager. Hoe
    # veel precies hangt af van de tegenstander in de fixture -- PSV heeft hier
    # bewust een zware aanval, dus het is meer dan de ~0.22 punt die bij een
    # competitiegemiddelde tegenstander hoort. De grens is daarom ruim: de test
    # hoort te vallen als de term niet meer meebeweegt, niet als iemand de
    # fixture bijstelt.
    oud = e_van(1.6)["de-keeper"]
    winst = uit1["de-keeper"] - oud
    verwacht = term1 * (2.4 - 1.6) / 2.4
    goed = abs(winst - verwacht) < 1e-9 and winst > 0
    print(f"  {'OK  ' if goed else 'FOUT'} herijking levert de keeper "
          f"{winst:+.3f} punt op, precies (2.4-1.6)/2.4 van de hele term "
          f"({verwacht:+.3f})")
    return ok and goed


def test_premiumkolommen_worden_niet_gelezen():
    """De betaalde kolommen mogen ook niet gelezen worden als ze ER STAAN.

    Dit is het hek om een betaalmuur. `Verwachte punten`, `Totaal` en
    `Per miljoen` zijn gemaskeerd voor bezoekers zonder Premium: je krijgt per
    request andere getallen (gemeten 23 oktober: uniform over [1,4], veranderd
    voor ALLE 507 spelers tussen twee scrapes terwijl prijs/positie/club/naam
    voor 0 van de 507 veranderden). Ze hier weer inlezen haalt een betaalmuur
    omlaag EN voert ruis het model in -- vandaar een test en niet alleen een
    opmerking in de code.

    De fixture zet die kolommen bewust wél op de pagina. Een test met een
    pagina zonder die kolommen zou altijd slagen en dus niets bewaken.
    """
    from scrape_prijzen import parse_rijen

    html = """<table>
      <tr><th>Speler</th><th>Club</th><th>Positie</th><th>Waarde</th>
          <th>Behaald</th><th>Verwachte punten</th><th>Totaal</th>
          <th>Per miljoen</th><th>Basiskans</th></tr>
      <tr><td><a href="/speler/jan-jansen">Jan Jansen</a></td><td>Ajax</td>
          <td>Middenvelder</td><td>2,5 mln</td>
          <td>41,0</td><td>3,17</td><td>2.683</td><td>473</td><td>82%</td></tr>
      <tr><td><a href="/speler/piet-pieters">Piet Pieters</a></td><td>PSV</td>
          <td>Verdediger</td><td>1,5 mln</td>
          <td>-7,0</td><td>1,04</td><td>1.954</td><td>488</td><td>61%</td></tr>
    </table>"""
    rijen, _, _ = parse_rijen(html)

    ok = True
    goed = len(rijen) == 2
    print(f"  {'OK  ' if goed else 'FOUT'} twee spelers gelezen ({len(rijen)})")
    ok = ok and goed
    if not goed:
        return False

    # 1. De betaalde kolommen komen in geen enkele rij voor, onder geen naam.
    verboden = ("verwacht", "totaal", "per_miljoen", "per miljoen", "basiskans")
    for r in rijen:
        gevonden = [k for k in r if any(v in k.lower() for v in verboden)]
        goed = not gevonden
        print(f"  {'OK  ' if goed else 'FOUT'} {r['speler']:14s} geen betaalde kolom "
              f"in de uitvoer{'' if goed else f': {gevonden}'}")
        ok = ok and goed

    # 2. 'behaald' wordt wel gelezen, en met het juiste teken -- die kolom is
    #    niet gemaskeerd en is de enige grondwaarheid die het project heeft.
    verw = {"Jan Jansen": 41.0, "Piet Pieters": -7.0}
    for r in rijen:
        goed = r["behaald"] == verw[r["speler"]]
        print(f"  {'OK  ' if goed else 'FOUT'} {r['speler']:14s} behaald = "
              f"{r['behaald']!r} (verwacht {verw[r['speler']]})")
        ok = ok and goed

    # 3. De prijs is niet per ongeluk uit een van de puntenkolommen gehaald.
    prijzen = {r["speler"]: r["prijs"] for r in rijen}
    goed = prijzen == {"Jan Jansen": "2.50", "Piet Pieters": "1.50"}
    print(f"  {'OK  ' if goed else 'FOUT'} prijzen ongemoeid: {prijzen}")
    return ok and goed


def test_eerste_wissels_vervuilt_de_elf_niet():
    """Op 26-10-2026 zette de bron "Eerste wissels:" in het opstellingsblok.

    Zeven extra spelerslinks, binnen dezelfde h2 als de elf. De teller kwam op
    18 en de aannemelijkheidscontrole weigerde weg te schrijven -- bij ALLE 18
    clubs tegelijk. Dat was het juiste gedrag (18 spelers wegschrijven als een
    basiself is erger), maar het betekende wel een week zonder opstellingsdata.

    De afwezigen werden al op speler_id weggefilterd; invallers zijn niet
    afwezig, dus daar hielp dat niet.

    De oplossing ankert op STRUCTUUR: de elf staan in <li> binnen <ul>, de
    andere spelers in <p>. Filteren op de tekst "Eerste wissels" zou werken tot
    de bron die zin anders formuleert, en precies dat gebeurde op 19-10-2026
    met "Niet beschikbaar:".

    In dezelfde wijziging kwamen de percentages terug, nu in een <span> NA
    </a> binnen dezelfde <li>. Het oude venster liep tot </a> en miste ze dus.
    """
    import scrape_eredivisie as s
    from bs4 import BeautifulSoup

    def speler(nr, slug, naam, pct=None):
        extra = f'<span class="ml-auto font-mono">{pct}%</span>' if pct is not None else ""
        return (f'<li><span class="w-6">{nr}</span>'
                f'<a href="/eredivisie/speler/{slug}/">{naam}</a>{extra}</li>')

    elf = [("32", "matej-kovar", "Matej Kovar", 91), ("8", "sergino-dest", "Sergino Dest", 85),
           ("4", "armando-obispo", "Armando Obispo", 80), ("18", "filip-kostic", "Filip Kostic", 68),
           ("2", "lutsharel-geertruida", "L Geertruida", 68), ("20", "guus-til", "Guus Til", 88),
           ("17", "mauro-junior", "Mauro Junior", 88), ("24", "kodai-sano", "Kodai Sano", 87),
           ("5", "ivan-perisic", "Ivan Perisic", 58), ("19", "esmir-b", "Esmir B", 51),
           ("7", "ruben-van-bommel", "Ruben van Bommel", 62)]
    afwezig = ["paul-wanner", "ricardo-pepi", "alassane-plea"]
    wissels = ["sven-mijnans", "ayoni-santos", "dennis-man", "ryan-flamingo",
               "sami-ouaissa", "noah-fernandez", "yarek-gasiorowski"]

    def links(slugs):
        return ", ".join(f'<a href="/eredivisie/speler/{x}/">{x}</a>' for x in slugs)

    def pagina(met_percentage, met_wissels):
        r = [speler(*x) if met_percentage else speler(x[0], x[1], x[2]) for x in elf]
        w = f'<p><span>Eerste wissels:</span> {links(wissels)}.</p>' if met_wissels else ""
        return (f'<html><body><h1>Vermoedelijke opstelling PSV tegen Willem II</h1>'
                f'<h2>Live: de officiele opstelling</h2>'
                f'<h2>Verwachte opstelling PSV tegen Willem II</h2>'
                f'<div><p>Keeper</p><ul>{r[0]}</ul></div>'
                f'<div><p>Verdediging</p><ul>{"".join(r[1:5])}</ul></div>'
                f'<div><p>Middenveld</p><ul>{"".join(r[5:10])}</ul></div>'
                f'<div><p>Aanval</p><ul>{r[10]}</ul></div>'
                f'<p><span>Niet beschikbaar:</span> {links(afwezig)} (blessure).</p>'
                f'{w}'
                f'<h2>Wat deze opstelling betekent</h2>'
                f'<h2>Blessures en schorsingen PSV</h2>'
                f'<p><a href="/eredivisie/speler/paul-wanner/">Paul Wanner</a> blessure</p>'
                f'</body></html>')

    ok = True
    gevallen = [
        ("met wissels en percentages (de pagina van 26-10)", True, True, 11),
        ("met wissels, zonder percentages", False, True, 0),
        ("zonder wissels, zonder percentages (zoals 23-10)", False, False, 0),
        ("zonder wissels, met percentages", True, False, 11),
    ]
    for wat, pct, wis, verw_kansen in gevallen:
        rij, _ = s.parse_opstelling(BeautifulSoup(pagina(pct, wis), "html.parser"), "PSV")
        kansen = sum(1 for x in rij if x["kans_basis"] != "")
        goed = len(rij) == 11 and kansen == verw_kansen
        print(f"  {'OK  ' if goed else 'FOUT'} {wat}: {len(rij)} spelers, "
              f"{kansen} kansen (verwacht 11 en {verw_kansen})")
        ok = ok and goed

    # De percentages horen bij de JUISTE speler: het venster mag niet
    # doorlopen naar de volgende <li>.
    rij, _ = s.parse_opstelling(BeautifulSoup(pagina(True, True), "html.parser"), "PSV")
    paren = {x["speler_id"]: x["kans_basis"] for x in rij}
    verwacht = {x[1]: x[3] for x in elf}
    fout = {k: (paren.get(k), v) for k, v in verwacht.items() if paren.get(k) != v}
    goed = not fout
    print(f"  {'OK  ' if goed else 'FOUT'} elk percentage bij de juiste speler"
          f"{'' if goed else f': {fout}'}")
    return ok and goed


def test_kaarten_top40():
    """De zichtbare kaartenlijst is een TOP-N; de JSON-LD is de volledige.

    Op 26-10-2026 lieten drie controles tegelijk af. Zes spelers gingen van 2
    naar 0 gele kaarten en Lucas Rosa van 0 naar 3 -- in een ronde waarin dat
    allebei onmogelijk is. Oorzaak: de tabel toont 40 rijen terwijl de pagina
    zelf "numberOfItems": 175 meldt. Een speler met 2 kaarten viel uit de top
    toen er genoeg spelers op 3 kwamen, en kreeg 0 toegekend omdat een slug
    die niet in de lijst stond terugviel op nul.

    Drie niveaus, en de test controleert alle drie: zichtbare lijst (met
    slug), JSON-LD (op naam en club), en anders LEEG -- niet nul. Het verschil
    tussen "nul kaarten" en "niet in de lijst" is precies waar dit op stuk
    liep.
    """
    import scrape_eredivisie as s
    from bs4 import BeautifulSoup

    jsonld = ('{"@context":"https://schema.org","@type":"ItemList",'
              '"numberOfItems":175,"itemListElement":['
              '{"@type":"ListItem","position":1,"name":"Ayoub Oufkir",'
              '"description":"Ayoub Oufkir (AZ): 4 gele kaarten"},'
              '{"@type":"ListItem","position":8,"name":"Shiloh \u0027t Zand",'
              '"description":"Shiloh \u0027t Zand (Fortuna Sittard): 3 gele kaarten"},'
              '{"@type":"ListItem","position":60,"name":"Youri Baas",'
              '"description":"Youri Baas (Ajax): 2 gele kaarten"}]}')
    html = (f'<html><body>'
            f'<script type="application/ld+json">{jsonld}</script>'
            f'<script type="application/ld+json">'
            f'{{"@type":"BreadcrumbList","itemListElement":[]}}</script>'
            f'</body></html>')
    uit = s.kaarten_uit_jsonld(BeautifulSoup(html, "html.parser"))

    ok = True
    goed = len(uit) == 3
    print(f"  {'OK  ' if goed else 'FOUT'} drie spelers uit de structured data "
          f"({len(uit)}); de BreadcrumbList telt niet mee")
    ok = ok and goed

    goed = uit.get((s.norm("Shiloh 't Zand"), s.norm("Fortuna Sittard"))) == 3
    print(f"  {'OK  ' if goed else 'FOUT'} een naam met een apostrof uit \\u0027 "
          f"wordt gelezen")
    ok = ok and goed

    gevallen = [
        ("staat in de zichtbare lijst", "ayoub-oufkir", "Ayoub Oufkir", "AZ",
         {"ayoub-oufkir": ("Ayoub Oufkir", "AZ", 4)}, 4),
        ("alleen in de JSON-LD (uit de top-40 gevallen)", "youri-baas",
         "Youri Baas", "Ajax", {}, 2),
        ("in geen van beide: LEEG, niet nul", "niemand", "Niemand", "Ajax", {}, ""),
    ]
    for wat, slug, naam, club, op_slug, verwacht in gevallen:
        w = s.kaarten_van(slug, naam, club, op_slug, uit)
        goed = w == verwacht and type(w) is type(verwacht)
        print(f"  {'OK  ' if goed else 'FOUT'} {wat}: {w!r} (verwacht {verwacht!r})")
        ok = ok and goed
    return ok


def main():
    print("splits_status()\n")
    ok1 = test_splits_status()
    print("\nnaam-restcontrole (draait na elke scrape)\n")
    ok3 = test_status_restant()
    print("\nvind_bijna_match()\n")
    ok2 = test_vind_bijna_match()

    print("\nvermoedelijke basiself (opstellingspagina)\n")
    ok4 = test_vermoedelijke_elf()

    print("\nkolomformaat van spelers.csv\n")
    ok5 = test_spelers_formaat()

    print("\nterugkeerdatum per ronde\n")
    ok6 = test_terugkeerdatum()

    print("\nseizoensstand als terugval voor assists en kaarten\n")
    ok7 = test_stats_uit_seizoen()

    print("\nbetaalde kolommen blijven ongelezen\n")
    ok8 = test_premiumkolommen_worden_niet_gelezen()

    print("\nreddingspunten voor keepers\n")
    ok9 = test_reddingspunten()

    print("\nde elf blijft schoon bij 'Eerste wissels'\n")
    ok10 = test_eerste_wissels_vervuilt_de_elf_niet()

    print("\nkaartenlijst is een top-N, geen volledige lijst\n")
    ok11 = test_kaarten_top40()

    print()
    if all([ok1, ok2, ok3, ok4, ok5, ok6, ok7, ok8, ok9, ok10, ok11]):
        print("OK: splits_status(), vind_bijna_match(), de opstellingsparser, het\n"
              "    kolomformaat van spelers.csv en de betaalmuurgrens gedragen zich\n"
              "    zoals verwacht.")
    else:
        sys.exit("MISLUKT: zie hierboven.")


if __name__ == "__main__":
    main()
