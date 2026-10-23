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

def main():
    print("splits_status()\n")
    ok1 = test_splits_status()
    print("\nnaam-restcontrole (draait na elke scrape)\n")
    ok3 = test_status_restant()
    print("\nvind_bijna_match()\n")
    ok2 = test_vind_bijna_match()

    print("\nvermoedelijke basiself (opstellingspagina)\n")
    ok4 = test_vermoedelijke_elf()

    print()
    if ok1 and ok2 and ok3 and ok4:
        print("OK: splits_status(), vind_bijna_match() en de opstellingsparser\n"
              "    gedragen zich zoals verwacht.")
    else:
        sys.exit("MISLUKT: zie hierboven.")


if __name__ == "__main__":
    main()
