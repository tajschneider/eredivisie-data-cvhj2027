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

kalibratie.yml (nieuw, di 08:00 UTC, onafhankelijk van bovenstaande)
  auto_kalibreer.py  -> (evt.) KRIMP_SPELER/KRIMP_CLUB in cvhj_model.py
                      -> kalibratie/status.json (altijd)
                      -> e-mail (alleen bij een daadwerkelijke aanpassing)
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
pip install scipy                # alleen nodig voor multi_periode.py

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
(standaard `ja`), `DEADLINE_UREN` (standaard 6), en voor de automatische
kalibratie `KALIBREER_ELKE` (standaard 4), `MIN_RONDES_KALIBRATIE` (standaard
8), `MIN_VERBETERING_KALIBRATIE` (standaard 0.03) en `MAX_STAP_KALIBRATIE`
(standaard 2.0) -- zie "Backtest en kalibratie" voor wat elke waarde
tegenhoudt. De standaardwaarden zijn bewust conservatief; er is geen reden om
ze aan te passen totdat er meer dan een paar rondes aan data staan.

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

## Backtest en kalibratie

`backtest.py` voorspelt ronde *r* met uitsluitend data uit ronden < *r* en
vergelijkt met wat er werkelijk gebeurde. Zonder dit is geen enkele wijziging
aan het model beoordeelbaar -- je weet dat de uitvoer anders is, niet of hij
beter is.

```bash
python backtest.py                        # RMSE, MAE, rangcorrelatie per ronde
python backtest.py --per-speler ruw.csv   # voorspelling vs. werkelijkheid, per speler
python calibrate.py                       # doorzoekt KRIMP_SPELER x KRIMP_CLUB
```

Belangrijke beperking: de "werkelijke punten" in de backtest zijn een
reconstructie uit `ploegpunten + clean_sheet-bonus + goals x doelpuntwaarde` --
dezelfde termen die het model kent. Assists, kaarten en keeper-reddingen
ontbreken aan beide kanten. Dit meet dus niet je echte CVHJ-score, maar wel
eerlijk of een wijziging het voorspelbare deel beter voorspelt.

Op ronde 2-4 (de enige nu evalueerbare rondes) is `calibrate.py` gedraaid over
een raster van KRIMP_SPELER (1-30) en KRIMP_CLUB (0,25-8). Resultaat: de
huidige waarden (8 en 1,0) presteren al dicht bij het beste punt in het raster
(RMSE 3,27 tegen een raster-minimum van 3,25) -- het verschil ligt binnen de
ruis van drie rondes en is per ronde niet overal in dezelfde richting (ronde 2
werd er licht slechter van, ronde 3-4 licht beter). Wel eenduidig: nauwelijks
krimp (KRIMP_SPELER=1) is op alle drie de rondes merkbaar slechter (RMSE
2,87/3,70/3,76 tegen 2,75/3,56/3,44). De krimpconstanten zijn dus niet
aangepast -- er is onvoldoende bewijs om van de huidige waarden af te wijken,
wel bewijs dat ze niet te laag staan.

### Automatische herkalibratie

Dit handmatig herhalen is precies het risico dat het hierboven al bijna fout
liet gaan: het is verleidelijk om de rastere winnaar over te nemen omdat de
totaal-RMSE net iets beter is, terwijl dat verschil op drie rondes ruis bleek
te zijn. `auto_kalibreer.py` (workflow `kalibratie.yml`, dinsdag 08:00 UTC)
stelt elke week dezelfde vraag die hierboven met de hand is beantwoord, maar
dan met vier waarborgen die harde stopcondities zijn, geen aanbevelingen:

1. **Minimaal aantal rondes** (`MIN_RONDES_KALIBRATIE`, standaard 8) -- met
   minder rondes wordt er sowieso niets aangepast.
2. **Minimumverbetering** (`MIN_VERBETERING_KALIBRATIE`, standaard 3%
   relatief) -- een winnaar die de RMSE met 0,6% verslaat, zoals hierboven,
   haalt deze drempel niet.
3. **Consistentie per ronde** -- de kandidaat moet de huidige instelling
   verslaan in een meerderheid van de individuele backtestrondes, niet alleen
   in het gewogen gemiddelde. Dit is de check die hierboven aan het licht
   bracht dat ronde 2 juist slechter werd.
4. **Maximale stapgrootte** (`MAX_STAP_KALIBRATIE`, standaard factor 2) --
   zelfs als de eerste drie waarborgen een aanpassing toestaan, mag
   KRIMP_SPELER of KRIMP_CLUB niet in één keer meer dan een factor 2
   veranderen.

Getest tegen de echte data (ronde 2-4, dus met slechts 3 evalueerbare rondes):
het script wijst een aanpassing correct af op waarborg 1 (te weinig rondes) --
dezelfde conclusie als de handmatige kalibratie hierboven, nu automatisch
afgedwongen in plaats van op gevoel beoordeeld.

Elke controle -- ook een afwijzing -- wordt gelogd in `kalibratie/status.json`
(gecommit, dus de geschiedenis van beslissingen en de reden erachter is
achteraf te controleren). Alleen als er daadwerkelijk iets is aangepast, gaat
er een aparte e-mail uit: dit verandert het model zelf, niet het
rondeadvies, en verdient dus een eigen melding los van de wekelijkse mail.

```bash
python auto_kalibreer.py                          # met de standaardwaarborgen
python auto_kalibreer.py --forceer --droog         # negeer de "elke N ronden"-gate,
                                                    # reken wel door, schrijf niets
```

`--elke` (standaard 4 ronden, ongeveer een periode) bepaalt hoe vaak de
kalibratie een nieuwe poging waard vindt; de workflow draait wekelijks maar
het script beslist zelf of dat te vroeg is. Herhaal deze kalibratie zodra er
meer rondes zijn; drie rondes is genoeg om een grove misser te detecteren
(KRIMP_SPELER=1), niet genoeg om een fijnere waarde te kiezen -- vandaar
waarborg 1.

## Meerdere ronden vooruit kijken

`cvhj_model.py` optimaliseert altijd precies de eerstvolgende ronde. Dat is
een bekende tekortkoming: een speler met een zware tegenstander deze week
maar een makkelijke serie daarna wordt te laag gewaardeerd, en andersom.
`multi_periode.py` telt in plaats daarvan de verwachte punten van de komende
`--horizon` ronden mee, met een aftakelende weging per ronde verder weg
(`--decay`, standaard 0,84 -- dezelfde waarde die in de FPL-literatuur
gebruikelijk is voor dit soort meerperiode-optimalisatie).

Twee dingen maken dit haalbaar zonder de rest van het model te raken:

- **Geen marktkansen nodig voor toekomstige ronden.** `bouw_pool` gebruikt per
  wedstrijd alleen de twee clubs (via de al gefitte clubratings), niet de
  kans_thuis/kans_gelijk/kans_uit van die specifieke wedstrijd -- die kansen
  worden alleen gebruikt om de clubratings zelf te *trainen* op AFGELOPEN
  wedstrijden. Een ronde ver vooruit, waarvoor de bookmaker nog geen kansen
  heeft gepubliceerd, is dus even bruikbaar als de eerstvolgende: er hoeft
  alleen bekend te zijn wie tegen wie speelt.
- **Een echte oplosser in plaats van brute force.** De bestaande zoeker
  (`beste_transfers`) somt combinaties op -- prima voor 1 ronde, maar dat
  schaalt niet naar een horizon van meerdere ronden. `multi_periode.py`
  formuleert dezelfde keuze (welke 15 spelers, met welke bankplek per linie,
  binnen budget/club/formatie/transferregels) als een lineair 0/1-probleem en
  lost het op met `scipy.optimize.milp` (HiGHS als solver) -- geen nieuwe
  dependency, scipy is al gangbaar.

**Validatie:** met `--horizon 1` (dus zonder dat de decay ertoe doet) moet de
MILP exact dezelfde spelersgroep en score vinden als de bestaande brute-force
zoeker, voor zowel 1 als 3 transfers -- het zijn twee algoritmes voor precies
dezelfde vraag. `test_multi_periode.py` controleert dit automatisch en is op
de echte data gedraaid: score en spelersgroep kwamen in beide gevallen exact
overeen (54,12 bij 1 transfer, 59,42 bij 3). Draai deze test opnieuw na elke
wijziging aan `multi_periode.py`.

Met een (voor de test verzonnen) programma over 4 ronden koos de 3-transfer-
zoeker een ANDER drietal dan de eenronde-zoeker -- die verving Oscar Gloukh,
de eenronde-zoeker koos daar niet voor zodra de rest van de horizon meetelde.
Dat is precies het punt van dit script: het laat zien WANNEER de twee
adviezen uiteenlopen, niet alleen dat ze dat theoretisch zouden kunnen.
Gebruik `--vergelijk` om dat verschil (of de afwezigheid ervan) elke ronde te
zien.

**Vereenvoudiging, met opzet:** de bankplek-korting (zwakste per linie telt
50%) wordt toegepast op de opgetelde, gedecayde punten per speler over de hele
horizon, niet per ronde apart opnieuw bepaald. Wie er in ronde 3 van de
horizon op de bank zou moeten staan simuleren zou het aantal variabelen met
een factor `horizon` vermenigvuldigen voor weinig extra scherpte, en de
daadwerkelijke opstelling blijft toch elke week een losse beslissing --
cvhj_model.py's advies VOOR DIE RONDE gebruikt gewoon zijn eigen E,
ongewijzigd. Inhaalduels tellen om dezelfde reden alleen mee voor de
eerstvolgende ronde.

```bash
python scrape_programma.py --horizon 4              # programma.csv t/m 3 ronden verder
python multi_periode.py --ronde 6 --transfers 1 --horizon 4 --vergelijk
python test_multi_periode.py                        # regressietest tegen de brute-force zoeker
```

Dit is nog een los te draaien script, geen onderdeel van `wekelijks.yml` --
bewust, om dezelfde reden als bij de kalibratie: eerst een paar keer met de
hand bekijken of de adviezen kloppen en zinnig aanvoelen, dan pas automatiseren.
Zodra dat vertrouwen er is, is het een kleine stap om `scrape_programma.py
--horizon` en `multi_periode.py` aan `wekelijks.yml` toe te voegen naast (niet
in plaats van) de bestaande eenronde-zoeker.

## Bekende beperkingen

Onveranderd uit het model: geen assists, geen kaarten, maximaliseert de
verwachting en niet de klassering, en geen blessurenieuws van vandaag. De mail
herhaalt dat laatste elke week als expliciete controlestap. De eenronde-
beperking is met `multi_periode.py` te omzeilen (zie hierboven), maar dat
script draait nog los van de wekelijkse mail.

Nieuw:

- De volgende deadline wordt op zeven dagen na de huidige geschat (zie
  "Uitgestelde duels"). Bij een interlandperiode of bekerweek klopt dat niet;
  corrigeer dan met `--venster-dagen`.
- De live HTML-structuur van pouletips is niet geverifieerd tegen de parsers
  (de bouwomgeving kon die host niet bereiken). Draai beide scrapers één keer
  handmatig voordat je de workflow aanzet.
- `multi_periode.py`'s horizon-fixtures (ronde 2+) zijn in deze omgeving
  getest met een VERZONNEN programma (de bouwomgeving kon pouletips niet
  bereiken) -- de wedstrijdlogica zelf (budget/club/formatie/transfers, en de
  exacte match met de brute-force zoeker bij horizon 1) is dus geverifieerd,
  de scraper voor echte verre ronden nog niet. Draai `scrape_programma.py
  --horizon` handmatig en controleer de uitvoer voordat je op het advies
  vertrouwt.
- `inleggen.py` bestaat nog niet.
