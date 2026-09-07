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
  scrape_prijzen.py             -> prijzen.csv           |
  scrape_programma.py --horizon -> programma.csv (N rondes)
                               |               |
                               +-------+-------+
                                       v
                        test_multi_periode.py  (regressie-waarborg)
                                       v
                    multi_periode.py --horizon auto  -> besluit.json
              (bij falen: cvhj_model.py, één ronde, zelfde besluit.json-vorm)
                                       v
                                  notify.py  -> e-mail
                                       v
                          deadline.py -> inleggen.py  (uit tenzij INLEGGEN=ja)
                                       v
                              historie/ronde-N.json

kalibratie.yml (nieuw, di 08:00 UTC, onafhankelijk van bovenstaande)
  auto_kalibreer.py  -> (evt.) KRIMP_SPELER/KRIMP_CLUB in cvhj_model.py
                      -> kalibratie/status.json (altijd)
                      -> e-mail (alleen bij een daadwerkelijke aanpassing)

xg.yml (ma 05:00 en do 08:00 UTC -- telkens vóór wekelijks.yml; zie
        "xG, assists en kaarten")
  scrape_sofascore.py -> xg.csv
                     (pikt wekelijks.yml automatisch op; ontbreekt het,
                      dan draait het advies zonder stap 5 -- een mindere
                      schatting, geen storing)
```

Alle workflows die naar `main` pushen (`wekelijks.yml`, `data.yml`,
`kalibratie.yml`, `xg.yml`) staan in dezelfde concurrency-groep en doen
`git pull --rebase` voor de push, zodat ze elkaar niet omverduwen.
`wekelijks.yml` draait een uur na `scrape.yml`.

| Nodig | Stond er | Nu |
|---|---|---|
| `clubs.csv`, `spelers.csv` | scraper | ongewijzigd |
| `prijzen.csv` | handmatig | `scrape_prijzen.py` |
| `PROGRAMMA` | hardgecodeerd | `scrape_programma.py` |
| `INHAAL` | hardgecodeerd | `scrape_programma.py` (detectie) |
| `SELECTIE` | hardgecodeerd | `selectie.csv` |
| inleggen | handmatig | `inleggen.py` (uit, met `INLEGGEN`/`DRY_RUN`) |

## Gebruik

Alles draait vanuit de hoofdmap van de repo; de standaardpaden kloppen al.

```bash
pip install requests beautifulsoup4 numpy
pip install scipy                # alleen nodig voor multi_periode.py

python scrape_prijzen.py        # -> prijzen.csv
python scrape_programma.py      # -> programma.csv
python scrape_sofascore.py      # -> xg.csv (optioneel, zie "xG" hieronder)

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
(standaard `ja`), `DEADLINE_UREN` (standaard 6); voor de automatische
kalibratie `KALIBREER_ELKE` (standaard 4), `MIN_RONDES_KALIBRATIE` (standaard
8), `MIN_VERBETERING_KALIBRATIE` (standaard 0.03) en `MAX_STAP_KALIBRATIE`
(standaard 2.0) -- zie "Backtest en kalibratie"; en voor de multi-ronde-zoeker
`HORIZON_SCRAPE` (standaard 6) en `DECAY` (standaard 0.84) -- zie "Meerdere
ronden vooruit kijken". Alle standaardwaarden zijn bewust conservatief; er is
geen reden om ze aan te passen totdat er meer dan een paar rondes aan data
staan.

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

## Vangnet tegen vervuilde namen ("transfer X voor X")

Op 6 september 2026 kreeg Thomas een advies om Gjivai Zechiël te
transfereren voor Gjivai Zechiël: een zinloze zelf-transfer. Oorzaak:
`prijzen.csv` bevatte voor die speler `"Gjivai Zechiël basis"` in plaats van
`"Gjivai Zechiël"` — de naamkolom op pouletips.nl bevat naast de naam ook
statuswoorden ("basis"/"bank"/"nieuw"), die `scrape_prijzen.py`'s
`splits_status()` hoort te strippen. Dat matchte niet meer met
`selectie.csv`'s schone naam, dus kreeg de "echte" Zechiël een dood slot
(E=0, "verkoop") terwijl de vervuilde marktdata-naam als aparte, nieuwe
aankoop verscheen (E=7,60, "koop") — twee losse regels voor dezelfde speler.

Twee lagen tegen dit soort fouten:

1. **Hoofdlettergevoeligheid gefixt.** `STATUS_RE` in `scrape_prijzen.py` was
   hoofdlettergevoelig; een statuswoord met een andere hoofdletter ("Basis"
   i.p.v. "basis") liep er ongestript doorheen. Dit is een reproduceerbaar
   gat dat nu gedicht is (`re.IGNORECASE`), maar niet met zekerheid
   vastgesteld als DE live oorzaak — de site-HTML zelf is niet ingezien.
2. **Vangnet, voor onbekende toekomstige gevallen.** `cvhj_model.vind_bijna_match()`
   zoekt, als de exacte naam niet matcht, naar een kandidaat bij dezelfde
   club wiens naam-woorden een deelverzameling zijn van elkaar (of
   omgekeerd). Vindt hij er precies één, dan wordt die automatisch gebruikt
   in plaats van een dood slot — en wordt dit LUID gemeld (console, `advies.txt`,
   `besluit.json`'s `bijna_match`-veld, en bovenaan de e-mail), zodat een
   scraper-bug die de eerste laag niet vangt niet meer stilzwijgend een
   onzinnig advies oplevert, en toch opgemerkt wordt om alsnog te fixen.
   Bij meer dan één kandidaat (bv. twee bankspelers met overlappende namen)
   valt het terug op het oude, veilige dode-slot-gedrag — gokken is hier
   erger dan een gemiste repair.

Regressietest: `test_scrape_prijzen.py` (splits_status-edge cases inclusief
deze exacte casus, en vind_bijna_match's matching/niet-matching-gevallen).

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

## Rol en speeltijd (stap 1+2)

Twee samenhangende tekortkomingen uit het oorspronkelijke plan, in één keer
opgelost: het model reageerde traag op een rolwijziging (een speler die net
basisspeler wordt, of hem juist verliest), en gebruikte speeltijd alleen
indirect (via de krimpformule), niet als een eigen voorspellende factor voor
HOEVEEL van een wedstrijd iemand waarschijnlijk meemaakt.

**Het probleem met het oude vlakke gemiddelde.** `bouw_pool()` schatte de
kans op een basisplaats (`p_basis`) als het aandeel basisplaatsen over de
laatste `--venster` (standaard 6) ronden, allemaal even zwaar meegewogen. Een
speler die twee ronden geleden net doorbrak, sleepte dan nog 4 oude
bankronden mee die niet meer representatief zijn -- en omgekeerd voor een
speler die zijn plek net kwijtraakte.

**De oplossing: recency-weging in plaats van een vlak gemiddelde.**
`rol_kenmerken()` weegt elke ronde in het venster met `ROL_DECAY` tot de
macht "hoeveel ronden geleden" (dezelfde soort weging als de decay in
`multi_periode.py`, hier toegepast op het VERLEDEN in plaats van de
toekomst). Daarmee vervangt één vlakke `p_basis` drie aparte, gerichtere
signalen:

- **p_speelt** -- kans dat de speler aan het spel komt (elke minuut telt).
  Stuurt de ploegpunten, die je krijgt zodra je meedoet.
- **p_60plus** -- kans dat hij minstens `CLEANSHEET_MINUTEN_DREMPEL` (60)
  minuten speelt. Stuurt de clean-sheet-bonus. **Aanname:** CVHJ hanteert,
  net als de meeste fantasy-competities (waaronder de officiële Premier
  League-competitie), een minutendrempel voor clean sheets -- dit is niet
  bij CVHJ zelf geverifieerd. Pas `CLEANSHEET_MINUTEN_DREMPEL` aan als dat
  niet klopt.
- **speelfractie** -- verwacht aandeel van de wedstrijd dat hij speelt
  (gewogen minuten/90). Zet de per-90-productieschatting (doelpunten,
  assists, kaarten) om in een verwachting voor DEZE wedstrijd: een speler
  die vaak na 60 minuten wordt gewisseld, krijgt nu minder toegerekend dan
  iemand die altijd de volle wedstrijd speelt, ook al starten ze even vaak.

Dezelfde recency-weging geldt voor de doelpuntenschatting zelf (`ind90`):
niet langer een plat seizoensgemiddelde, maar een gewogen gemiddelde dat
recente vorm zwaarder laat wegen -- vooral relevant vlak na een rolwijziging.

**Validatie en de grens daarvan.** `backtest.py` (voor/na dezelfde ronden,
zie "Backtest en kalibratie") laat een kleine, consistente verbetering zien:
RMSE 3.27 -> 3.25, rho (rangcorrelatie, belangrijker dan RMSE voor de
opstellingskeuze) 0.44 -> 0.46. Eerlijk gezegd: dat is op een dataset van
maar 3 evalueerbare ronden vroeg in het seizoen, en de uitkomst bleek in die
test nauwelijks gevoelig voor de precieze `ROL_DECAY`-waarde (0.2 tot 1.0
gaven bijna hetzelfde resultaat) -- simpelweg omdat er nog geen 6 ronden
geschiedenis is om verschil in te laten zien. Het is dus een reële, maar
zwak geteste verbetering. Draai `backtest.py` opnieuw zodra er meer ronden
data zijn (het venster van 6 ronden is dan pas volledig gevuld) en stel
`ROL_DECAY` bij als dat een duidelijkere winnaar aanwijst.

Geen nieuwe bestanden, secrets of variabelen: dit verandert alleen de
puntenformule in `cvhj_model.py`, gebruikt door zowel `cvhj_model.py` als
`multi_periode.py`.

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

### Automatisering in wekelijks.yml

`multi_periode.py` is nu de standaardzoeker in `wekelijks.yml` -- `cvhj_model.py`
blijft bestaan (en blijft de referentie waartegen `test_multi_periode.py`
toetst), maar de wekelijkse mail komt uit de multi-ronde-zoeker.

**Horizon en transfers volgen de periode, automatisch.** `--horizon auto` en
`--transfers auto` gebruiken hetzelfde `perioden.csv` als cvhj_model.py: de
horizon loopt tot de volgende periodestart (daarna is de keuze toch weer vrij
met 3 transfers, dus verder vooruitkijken heeft geen zin), met een vaste
bovengrens van 6 ronden zonder periode-informatie. `scrape_programma.py` haalt
in de workflow steeds `HORIZON_SCRAPE` ronden op (standaard 6, ruim boven de
langste periode van 5) -- ronden die de auto-horizon niet nodig heeft, worden
door `multi_periode.py` gewoon genegeerd.

**Waarborg vóór vertrouwen, niet erna.** Elke run voert eerst
`test_multi_periode.py` uit -- dezelfde regressietest die hierboven liet zien
dat de MILP bij horizon 1 exact overeenkomt met de brute-force zoeker. Faalt
die test (een toekomstige wijziging heeft iets gebroken), dan valt de workflow
terug op `cvhj_model.py` voor die week en verschijnt er een `::error::`-melding
in de run -- de mail blijft dus komen, maar het is zichtbaar dat er iets te
repareren is. Faalt `multi_periode.py` zelf (bijvoorbeeld een MILP die
onverwacht geen oplossing vindt), dan geldt dezelfde terugval, maar dan als
`::warning::` in plaats van `::error::` -- de zoeker zelf werkt, alleen deze
ene ronde niet.

**Nieuwe GitHub-variabelen** (naast de bestaande, zie "Instellen in GitHub"):
`HORIZON_SCRAPE` (standaard 6) en `DECAY` (standaard 0,84). Geen nieuwe
secrets -- multi_periode.py mailt via dezelfde `notify.py` en dezelfde
besluit.json-vorm als cvhj_model.py (met een paar extra velden die notify.py
gebruikt om de gekozen horizon en decay in de mail te vermelden zodra die
horizon groter is dan 1).

## xG, assists en kaarten (Sofascore)

Stap 5 uit het optimalisatieplan. Pouletips (de bron van `clubs.csv` en
`spelers.csv`) levert geen assists en geen kaarten, en de doelpuntenschatting
draaide tot nu toe op RUWE doelpunten uit een venster van een paar recente
duels -- ruizig, vooral vroeg in het seizoen. `scrape_sofascore.py` haalt xG,
xAG (verwachte assists), en gele/rode kaarten per speler op, in `xg.csv`.

### Waarom niet meer FBref

Dit draaide oorspronkelijk op FBref. Die bron is om twee onafhankelijke
redenen vervallen, beide bevestigd:

1. **De data is er niet meer.** Sports Reference (moederbedrijf van FBref)
   raakte op 23 januari 2026 zijn Opta-licentie kwijt na een geschil over de
   overeenkomst. De xG/xAG-data is daar weg; alleen basisstatistiek blijft.
   Aangekondigd als permanent.
2. **De pagina is niet bereikbaar vanaf GitHub Actions.** FBref geeft HTTP 403
   op scripted requests vanaf datacenter-IP's. De oude `fbref.yml` liep daar in
   de praktijk ook op stuk.

Sofascore heeft beide problemen niet, en geeft bovendien exacte gespeelde
minuten waar FBref afgeronde "90s" gaf -- de per-90-omrekening is daardoor
iets nauwkeuriger dan voorheen.

### Wat er wél en niet geverifieerd is

**Wel** (met echte, live respons van `api.sofascore.com`):

- Toernooi-id 37 = Eredivisie; `/seasons` geeft het nieuwste seizoen vooraan.
- `/statistics` levert per speler exact de benodigde velden: `goals`,
  `assists`, `expectedGoals`, `expectedAssists`, `yellowCards`, `redCards`,
  `minutesPlayed`, `appearances`. Voorbeeld uit de echte respons: Gjivai
  Zechiel (Feyenoord) -- 4 goals, 3 assists, xG 1.83, xAG 1.71, 1 gele kaart,
  440 minuten, 5 wedstrijden.
- Paginering met `limit`/`offset` werkt (~4-5 verzoeken voor de hele competitie).
- Alle 18 clubnamen zoals Sofascore ze schrijft -- `CLUB_ALIAS_SOFASCORE` is
  dus nagelopen, geen gok.
- De `robots.txt` van sofascore.com noemt `/api/` niet en verbiedt het dus niet.
  Dat is niet hetzelfde als expliciete toestemming in de gebruiksvoorwaarden;
  bij één ophaalactie per paar dagen is dit een hobbygebruik-afweging die je
  zelf moet maken. De gelicentieerde route is Sportmonks (betaald, ~€48/mnd).

**Niet**: het script als geheel is nooit live gedraaid -- de bouwomgeving kon
`api.sofascore.com` niet met een eigen HTTP-verzoek bereiken. De parsing is
getest tegen een synthetische respons met exact de echte veldnamen en waarden
(`test_sofascore.py`). **Draai `xg.yml` dus één keer handmatig** en controleer
het aantal spelers en de 18 clubnamen in de samenvatting.

### Terugval en menging

**Volledig optioneel, met een geverifieerde terugval.** Ontbreekt `xg.csv`,
dan draaien `cvhj_model.py` en `multi_periode.py` WISKUNDIG IDENTIEK aan vóór
deze stap (enige verschil: een `LET OP`-regel dat het bestand ontbreekt).
Staat een speler er niet in (transfer, geen speelminuten, naam/club niet
gematcht), dan geldt voor hem hetzelfde: 0-bijdrage.

**De schatting is een gewogen menging, geen vervanging.** Doelpunten worden
een drieweg-menging van het lokale venster, de xG-per-90 over het hele
seizoen, en de bestaande positieprior -- elk gewogen naar hoeveel data
erachter zit (`XG_GEWICHT` dempt hoeveel een seizoens-90-tal weegt t.o.v. een
lokaal 90-tal, want xG is niet gecorrigeerd voor de specifieke tegenstanders
die het model elders al verrekent). Assists en kaarten hebben geen lokale
bron, dus daar is het een tweeweg-menging met een positieprior
(`KRIMP_ASSIST`/`KRIMP_KAART`, `PRIOR_ASSIST_RATE`/`PRIOR_GEEL_RATE`/
`PRIOR_ROOD_RATE` in `cvhj_model.py`).

De prior-constanten zijn schattingen op basis van algemene kennis van
posities, niet gekalibreerd op jouw data -- `spelers.csv` houdt geen assists
of kaarten bij, dus `backtest.py` kan dat deel niet toetsen (het RMSE-getal
daar blijft een ondergrens die alleen doelpunten/ploegpunten/clean sheets
meet). De richting klopt (hoge xG/xAG stijgt, veel kaarten daalt), de precieze
grootte is niet gevalideerd.

**Geen nieuwe secrets of variabelen.** `xg.yml` draait maandag 05:00 en
donderdag 08:00 UTC -- telkens vóór `wekelijks.yml` -- en commit alleen
`xg.csv`. Bewust een APARTE workflow: loopt het ophalen stuk, dan blijft het
wekelijkse advies gewoon draaien (zonder stap 5). Naamcompatibiliteit: het
bestandsformaat is identiek aan het oude `fbref.csv`, de vlag `--fbref` werkt
nog als alias voor `--xg`, en staat er nog een oud `fbref.csv` in de repo dan
wordt dat als terugval gelezen als `xg.csv` ontbreekt.

## Inleggen op coachvanhetjaar.nl

`inleggen.py` voert de transfer(s) uit `besluit.json` daadwerkelijk door op
coachvanhetjaar.nl. coachvanhetjaar.nl heeft geen publieke API-documentatie --
het is een React/Vite-app op een Django-backend die intern met een eigen,
ongedocumenteerde JSON-API praat. Die API is hier ontdekt via een HAR-export
(Network-tab van de browser) van een echte, bewust door Thomas uitgevoerde
transfer, dus GEVERIFIEERD gedrag, geen giswerk over hoe de site werkt.

**Wat de API doet** (basis `https://www.coachvanhetjaar.nl`):

- `GET /api/team/preparation/?round_seq=N` — je huidige 15, budget, aantal
  transfers dat nog mag, en of je team geldig is (allemaal door de site zelf
  berekend, dus de bron van waarheid — niet `perioden.csv` of `prijzen.csv`,
  die kunnen achterlopen).
- `GET /api/players/search_all/N/?page=..` — de hele markt, gepagineerd.
- `GET /api/teams/all/` — clublijst (dezelfde schrijfwijze als in dit
  project, inclusief `N.E.C.` dat `norm_club()` al naar `NEC` omzet).
- `POST /api/transfer/N/sell/<uit>/buy/<in>/?auto_change_formation=true` —
  voert één transfer door. Vereist Django's csrf-cookie terug als
  `X-CSRFToken`-header; verder een gewone sessie-cookie na inloggen.

**Wat NIET geverifieerd is** (er was geen voorbeeld van in de HAR-export,
zie de docstring van `inleggen.py` voor het volledige verhaal):

- Het inlogformulier zelf (de HAR begon met een al ingelogde sessie).
  `inleggen.py` ontleedt het daarom LIVE — het veld met `type=password` is
  het wachtwoord, ongeacht hoe het heet — in plaats van geraden veldnamen te
  gebruiken.
- Live draaien vanuit GitHub Actions.
- Het los wisselen van basis/bank binnen je eigen 15 (`sub=true` in de
  transfer-URL) — nooit geobserveerd, dus niet gebouwd. `auto_change_formation=true`
  laat de site na elke transfer zelf de beste opstelling kiezen, wat een
  andere bankspeler kan opleveren dan `cvhj_model.py`'s eigen keuze; dat
  raakt niet WELKE 15 spelers je hebt, alleen wie er zit.

**Veiligheidsontwerp, in aflopende volgorde:**

1. `DRY_RUN` staat standaard op `ja` (GitHub variable): alles wordt
   opgezocht, gematcht en gecontroleerd, maar er gaat geen enkele POST naar
   de site.
2. De site zelf is de bron van waarheid voor het aantal transfers dat nog
   mag en het resterende budget — vraagt `besluit.json` om meer of duurdere
   transfers dan de site nu toestaat, dan stopt het script VOOR er iets
   wordt aangeraakt.
3. Spelers uit `besluit.json` worden op naam + club gematcht tegen de
   site's eigen spelerslijst (accent-/spelling-ongevoelig, zelfde `norm()`
   als de rest van het project). Lukt dat niet eenduidig voor een speler,
   dan wordt er NIETS ingelegd — nooit een gok wagen over welke speler-ID
   bedoeld is.
4. Elke transfer wordt individueel door de site bevestigd; bij een
   afwijzing stopt het script direct, met de melding van de site erbij, en
   worden latere transfers uit dezelfde ronde niet meer geprobeerd.

Getest (met de echte JSON-vormen uit de HAR-export, maar gemockte
netwerkoproepen): het matchen van spelers inclusief accentverschillen, de
budget- en transfers-check (zowel de doorlaat- als de stopconditie), het
dry-run-pad, het live-transferpad bij succes, en het afbreken bij een
mislukte transfer of een niet-gevonden speler. Niet getest: een echte
netwerkoproep naar coachvanhetjaar.nl, want dat zou een echte transfer
kosten (Thomas had er deze ronde nog maar één, en die is al gebruikt).

**Voor je dit aanzet:** draai `python inleggen.py besluit.json` een paar keer
handmatig met `DRY_RUN=ja` (de standaard) zodra er weer een transfer gepland
staat, en controleer dat de UIT/IN-namen en de budgetcontrole kloppen. Zet
pas daarna `INLEGGEN=ja` (GitHub variable, standaard uit) om de job in
`wekelijks.yml` mee te laten draaien, en zet `DRY_RUN=nee` pas als je dat
vertrouwt. Geen nieuwe secrets nodig: `CVHJ_GEBRUIKER`/`CVHJ_WACHTWOORD`
stonden al klaar in de workflow.

## Bekende beperkingen

Onveranderd uit het model: maximaliseert de verwachting en niet de
klassering (per ronde; over de horizon wordt nu wel meerdere ronden
vooruitgekeken, zie hierboven), en geen blessurenieuws van vandaag. De mail
herhaalt dat laatste elke week als expliciete controlestap. Assists en
kaarten kunnen worden meegewogen via `xg.csv`, zie "xG, assists en kaarten"
hierboven voor wat daar nog niet geverifieerd is.

Nieuw:

- `scrape_sofascore.py` is niet live gedraaid in de bouwomgeving (wel getest
  tegen de echte veldnamen). Draai `xg.yml` één keer handmatig en controleer
  het aantal spelers en de 18 clubnamen voordat je erop vertrouwt. Sofascore's
  `/api/` is een niet-gedocumenteerde interne API: geen SLA, kan zonder
  aankondiging wijzigen -- hetzelfde risicoprofiel als de pouletips-scrapers.
- `ROL_DECAY` en `CLEANSHEET_MINUTEN_DREMPEL` (zie "Rol en speeltijd") zijn
  slechts op 3 ronden getest en de minutendrempel is een aanname, niet
  bevestigd bij CVHJ. Draai `backtest.py` opnieuw zodra er meer data is.
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
  het ophalen van echte verre ronden nog niet. `wekelijks.yml` draait dit nu
  wel automatisch; controleer daarom vóór de eerste live run zelf even of
  `scrape_programma.py --horizon 6` een programma oplevert dat klopt (via
  `data.yml`, met `horizon: 6` als input -- die workflow commit't
  `programma.csv` zodat je het kunt inzien zonder dat er iets gemaild wordt).
  Mocht er toch iets misgaan, valt de workflow terug op `cvhj_model.py` (zie
  "Meerdere ronden vooruit kijken"), dus een mail blijft komen -- maar een
  fout in de horizon-fixtures zelf (bijvoorbeeld een club-slug die verkeerd
  wordt gesplitst) zou wel een verkeerde E per ronde kunnen opleveren zonder
  dat de regressietest dat vangt, want die test alleen de horizon-1-situatie.
- `inleggen.py` bestaat, maar het inlogformulier en een live run vanuit
  GitHub Actions zijn niet geverifieerd (zie "Inleggen op coachvanhetjaar.nl").
  Staat uit totdat `INLEGGEN=ja` én `DRY_RUN=nee` bewust zijn gezet.
- `vind_bijna_match()` (zie "Vangnet tegen vervuilde namen") is een vangnet,
  geen garantie: het lost alleen het geval op waarbij precies één kandidaat
  bij dezelfde club een deelverzameling-naam heeft. Een fout die de naam
  ONHERKENBAAR verandert (i.p.v. een extra woord toevoegt), of een fout die
  de CLUB verkeerd zet, glipt er nog steeds doorheen als een dood slot
  (E=0, met een melding) — controleer bij zo'n melding altijd `prijzen.csv`
  zelf voor je een geadviseerde transfer volgt.
