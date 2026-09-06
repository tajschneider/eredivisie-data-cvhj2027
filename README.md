# CVHJ — automatiseringslaag

Draait het CVHJ-model wekelijks vanzelf: data ophalen, optimaliseren, advies
mailen. Leeft in dezelfde repo als de scraper, dus `clubs.csv` en `spelers.csv`
staan er al; alle scripts vinden ze op hun standaardpaden in de hoofdmap.

## Wat er veranderd is aan het model

`cvhj_model.py` is op twee punten aangepast; de uitkomsten zijn **bit-identiek**
aan de oorspronkelijke versie (geverifieerd door beide te draaien en te diffen).

**1. Het lambda-raster wordt één keer voorgerekend.** `lambdas_uit_kansen` deed
per wedstrijd een zoektocht over 172×172 kandidaat-lambdas, met een verse
Poisson-berekening per punt. Het raster is echter altijd hetzelfde; alleen de
marktnotering verschuift. Nu wordt het raster bij import één keer als
numpy-matrix opgebouwd en is elke aanroep een `argmin`.

| | origineel | nu |
|---|---|---|
| `lambdas_uit_kansen`, 30 noteringen | 7,5 s | 0,006 s |
| volledige draai, ronde 6, 3 transfers | 19,9 s | 10,9 s |

Na 4 ronden scheelt dat 9 seconden; na 34 ronden loopt het oude raster richting
een minuut of vijf, en dat wil je niet vlak voor een deadline.

**2. `PROGRAMMA`, `INHAAL` en `SELECTIE` komen uit bestanden.** Ze stonden
hardgecodeerd onderin het script. Nu leest het model `programma.csv` en
`selectie.csv`, met terugval op de blokken onderin als die bestanden ontbreken —
je bestaande werkwijze blijft dus werken.

Nieuw: `--json besluit.json` schrijft het besluit machineleesbaar weg.

## De keten

```
scrape.yml (bestaand, ma 06:00 UTC)
  scrape_eredivisie.py -> clubs.csv, spelers.csv
                               |
wekelijks.yml (nieuw, ma 07:00 + do 09:00 UTC)
  scrape_prijzen.py    -> prijzen.csv          |
  scrape_programma.py  -> programma.csv        |
                               |               |
                               +-------+-------+
                                       v
                              cvhj_model.py  -> besluit.json
                                       v
                                  notify.py  -> e-mail
                                       v
                          deadline.py -> inleggen.py  (nog niet ingevuld)
                                       v
                              historie/ronde-N.json
```

Beide workflows pushen naar `main`. `wekelijks.yml` draait een uur na
`scrape.yml`, staat in dezelfde concurrency-groep en doet `git pull --rebase`
voor de push, zodat ze elkaar niet omverduwen.

| Nodig | Stond er | Nu |
|---|---|---|
| `clubs.csv`, `spelers.csv` | scraper | ongewijzigd |
| `prijzen.csv` | handmatig | `scrape_prijzen.py` |
| `PROGRAMMA` | hardgecodeerd | `scrape_programma.py` |
| `INHAAL` | hardgecodeerd | `scrape_programma.py` (detectie) |
| `SELECTIE` | hardgecodeerd | `selectie.csv` |
| inleggen | handmatig | **nog open — vereist de CVHJ-request** |

## Gebruik

Alles draait vanuit de hoofdmap van de repo; de standaardpaden kloppen al.

```bash
pip install requests beautifulsoup4 numpy

python scrape_prijzen.py        # -> prijzen.csv
python scrape_programma.py      # -> programma.csv

python cvhj_model.py --ronde 6 --transfers 1 --json besluit.json
python notify.py besluit.json --toon      # advies afdrukken zonder te mailen
```

`selectie.csv` heeft de kolommen `speler, club, positie, prijs`; positie mag
Engels zijn of `K/V/M/A`. Dit bestand is de toestand van je ploeg — werk het bij
zodra een transfer is doorgevoerd.

**Let op:** deze repo is publiek. `selectie.csv` en `historie/` zijn dus voor
iedereen leesbaar. Je secrets niet — die staan in GitHub Secrets en komen niet
in de repo of in de logs.

## Instellen in GitHub

Secrets: `SMTP_HOST`, `SMTP_POORT`, `SMTP_USER`, `SMTP_WACHTWOORD`, `MAIL_NAAR`.
Voor Gmail een app-wachtwoord, niet je gewone wachtwoord.

Variables: `INLEGGEN` (`ja` zet de inlegjob aan, standaard uit), `DRY_RUN`
(standaard `ja`), `DEADLINE_UREN` (standaard 6).

De workflow draait maandag 07:00 UTC (een uur na `scrape.yml`) en
donderdag 09:00 UTC. Inleggen zit in een aparte job die pas binnen
`DEADLINE_UREN` van de aftrap iets doet, zodat je na de maandagmail dagen hebt
om in te grijpen.

## Ontwerpkeuzes in de scrapers

**Kolomnaam-gebaseerd, niet class-gebaseerd.** De spelerstabel wordt herkend aan
de kopteksten Speler/Club/Positie/Waarde. Classes veranderen bij elke redesign,
kopteksten zelden.

**Join op slug.** De spelerslinks op de prijzenpagina gebruiken dezelfde slug als
`speler_id` in `spelers.csv`. Omdat `prijzen.csv` nu uit dezelfde bron komt als
`spelers.csv`, matchen namen exact — het onderhoudspunt uit je oude README
(naamconsistentie) vervalt daarmee voor spelers.

**Clubnamen komen uit `clubs.csv`.** Slugs terug naar namen raden loopt stuk op
`sc Heerenveen` en `Go Ahead Eagles`. Nu wordt de splitsing gezocht waarbij beide
helften een bekende club zijn; getest op alle 306 thuis-uitcombinaties.

**Hard falen boven half werk.** `scrape_prijzen.py` schrijft niets onder 400
spelers. Een half gevuld `prijzen.csv` laat het model doorrekenen op een
onvolledige markt, en dat merk je pas aan de uitslag.

## Perioden en drie transfers

CVHJ deelt het seizoen in acht perioden van 4 of 5 ronden. Voorafgaand aan elke
periode mag je drie transfers doen in plaats van één. Die grenzen staan vast in
de spelregels en dus in `perioden.csv`:

| Periode | Startronde | | Periode | Startronde |
|---|---|---|---|---|
| 1 | 1 | | 5 | 18 |
| 2 | 5 | | 6 | 22 |
| 3 | 9 | | 7 | 26 |
| 4 | 13 | | 8 | 30 |

`--transfers auto` (de stand in de workflow) leest dat bestand en kiest zelf: 3
bij een periodestart, anders 1. De mail meldt het op drie manieren, zodat je het
niet mist:

- **onderwerpregel** — `PERIODE 3 START, 3 transfers`
- **bovenaan de mail** — een blok boven het advies, niet onderin bij de voetnoten
- **de week ervoor** — "volgende ronde begint een nieuwe periode; een transfer
  deze week bewaren kan lonen"

Die laatste is het punt van de hele exercitie: als je weet dat er volgende week
drie wissels aankomen, is een marginale transfer deze week zonde.

## Uitgestelde duels

Twee dingen gaan hier makkelijk mis, dus ze zitten expliciet in de code.

**Detectie gaat op onvolledige rondes, niet op verstreken datums.** Zodra een
uitgesteld duel een nieuwe speeldatum krijgt, ligt die in de *toekomst* — precies
het geval dat je wilt vinden. Het signaal is dat een eerdere ronde geen negen
uitslagen heeft. Dat leest `scrape_programma.py` uit `clubs.csv`, en het haalt
alleen de ontbrekende duels op in plaats van alle rondepagina's.

**Wat telt is welk elftal er staat, niet welke ronde het duel heet.** Het team
dat je vastzet bij de deadline blijft staan tot de volgende deadline; alles
daartussen speel je met dat elftal. Een uitgesteld duel uit ronde 3 op dinsdag 15
september valt ná de laatste wedstrijd van ronde 6, maar ruim vóór de deadline
van ronde 7 — dus het telt mee voor je beslissing van ronde 6, en die spelers
moet je nu al bezitten. Duels buiten dat venster krijgen `soort=inhaal_later` en
worden door het model genegeerd.

**Welke ronde is "de volgende"?** De eerste ronde waarvan de *deadline* nog niet
verstreken is — niet de eerste met een onspeelde wedstrijd. Op zondagmiddag loopt
de huidige ronde nog, maar daar viel vrijdag bij de aftrap het doek over.

## Bekende beperkingen

Onveranderd uit het model: geen assists, geen kaarten, één ronde vooruit,
maximaliseert de verwachting en niet de klassering, en geen blessurenieuws van
vandaag. De mail herhaalt dat laatste elke week als expliciete controlestap.

Nieuw:

- De volgende deadline wordt op zeven dagen na de huidige geschat (zie
  "Uitgestelde duels"). Bij een interlandperiode of bekerweek klopt dat niet;
  corrigeer dan met `--venster-dagen`.
- De live HTML-structuur van pouletips is niet geverifieerd tegen de parsers
  (de bouwomgeving kon die host niet bereiken). Draai beide scrapers één keer
  handmatig voordat je de workflow aanzet.
- `inleggen.py` bestaat nog niet.
