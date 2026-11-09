# Hoe historie.csv te lezen

Onderzocht 2026-11-09, naar aanleiding van de val van `rho` tussen meting 5 en
meting 6 (0,3982 -> 0,3252). Deze notitie legt vast wat die val was, zodat
niemand -- mens of verbeterlus -- er nog een keer weken aan besteedt.

## Conclusie

Er was GEEN meetlatwijziging, geen modelverslechtering en geen scraperfout.

`rho` en `top15_gevangen` zijn ONGEWOGEN gemiddelden over ronden (`gem()` in
`meet_model`). Bij zeven tot tien ronden verschuift een enkele slechte ronde het
totaal fors. Tussen meting 5 en meting 6 kwamen ronde 9 (rho 0,037) en ronde 10
(rho 0,166) de reeks binnen. Dat is de hele val.

`rmse` is wel n-gewogen (`wortel(fout2)` over losse spelerfouten) en beweegt
daarom veel minder: 3,3124 -> 3,3634.

## Het bewijs

Ongewogen gemiddelde van de rho per ronde, met de huidige code en data:

| ronden in de reeks | ongewogen gem. rho | opgeslagen in historie.csv |
|---|---|---|
| 2 t/m 8  (7 ronden)  | 0,3783 | meting 5: 0,3982 (7 ronden) |
| 2 t/m 9  (8 ronden)  | 0,3356 | -- |
| 2 t/m 10 (9 ronden)  | 0,3168 | meting 6: 0,3252 (9 ronden) |
| 2 t/m 11 (10 ronden) | 0,3218 | meting 7: 0,3277 (10 ronden) |

De rondeaantallen kloppen exact en de vorm is identiek: scherpe val bij ronde 9
en 10, licht herstel bij ronde 11. De restafwijking van ~0,02 komt uit de
datavintage (`eigen_elf.csv` mengt sinds 2026-11-01 echte punten mee).

rho per ronde: 2: 0,571 | 3: 0,496 | 4: 0,304 | 5: 0,163 | 6: 0,420 |
7: 0,383 | 8: 0,311 | **9: 0,037** | **10: 0,166** | 11: 0,367

## Code of data? Een 2x2 op dezelfde ronderange (`--tot 9`)

| cel | code | data | n | rmse | rho |
|---|---|---|---|---|---|
| A | 9f6a18d (meting 5) | 9f6a18d | 1381 | 3,31 | 0,398 |
| C | HEAD | 9f6a18d | 1381 | 3,32 | 0,392 |
| B | HEAD | HEAD | 1604 | 3,39 | 0,336 |

Cel A reproduceert meting 5 exact (opgeslagen: 3,3124 / 0,3982), dus de opzet is
geldig.

- A -> C (alleen de CODE verandert): rho -0,006. Verwaarloosbaar.
- C -> B (alleen de DATA verandert): rho -0,056. Vrijwel de hele val.

De datawijziging is niet het kolomformaat: voor ronde 2 t/m 8 is het aantal
spelers met minuten identiek tussen oud en nieuw (278/283/277/274/276/276/271).
Het verschil is dat ronde 9 bij meting 5 nog NIET in `spelers.csv` stond --
nul rijen -- en bij meting 6 wel, met 274 speelbare spelers.

## Wat hiermee is uitgesloten

Alle vier eerder vermoede oorzaken zijn weerlegd, met datum:

- **Het nieuwe kolomformaat van `spelers.csv`** (13d8ba4, 2026-10-26 20:21).
  Herschreef het hele bestand (8458 regels, 4107 -> 4351), maar liet de
  evalueerbare samenstelling van ronde 2 t/m 8 ongemoeid.
- **`eigen_elf.csv`** (145a13c, 2026-11-01 21:32:43, 39 seconden voor meting 6).
  Bevatte toen 15 rijen, alleen ronde 11. Ronde 1 t/m 9 kwam er pas op
  2026-11-02 bij, NA meting 6.
- **De assist/kaart-terugval** (8ea08fc, 2026-10-23). Raakt `cvhj_model.py`,
  `multi_periode.py` en `notify.py` -- niet `backtest.py`. Zie de open punten.
- **De verdwenen `status`-kolom.** De check `(r.get("status") or "") == "afwezig"`
  is sindsdien dood, maar `evalueer_ronde` en `basislijn` filteren verderop op
  `minuten == 0`, wat afwezigen alsnog buitenhoudt. Eén plek was niet gedekt;
  die is nu gerepareerd (zie onder).

## Wat wel kapot was, en nu gerepareerd is

In `basislijn()` stond de dode `status`-check in het vormvenster ZONDER
minutenfilter erachter, waardoor `v["duels"] += 1` ook voor afwezige rijen liep.
Dat verhoogde de noemer van `gem_goals` en drukte de naïeve voorspelling -- de
referentie waartegen het model wordt afgemeten.

Gemeten effect van de reparatie: de modelkolommen zijn ONGEWIJZIGD (TOTAAL
3,37 / 2,35 / +0,18 / 0,322 voor en na), `rmse_naief` stijgt 0,01 tot 0,08 per
ronde. Klein, en in de richting van een iets grotere modelmarge. Het is dus geen
verklaring voor de val, wel een echte fout.

## Twee nieuwe kolommen

`ronden` en `rho_min` zijn aan `VELDEN` toegevoegd. De bestaande zeven regels
hebben ze LEEG: voor meting 1 t/m 4 is niet vast te stellen welke ronden
meededen, en een kolom met wisselende betrouwbaarheid is erger dan een lege.

Lees ze zo: staat `rho_min` ver onder `rho`, dan wordt het totaal door een
uitbijterronde bepaald en niet door een trend. Bij de proefrun van 2026-11-09
was dat `rho` 0,3219 tegen `rho_min` 0,0366 -- precies het geval dat deze
notitie beschrijft.

Vergelijk `ronden` tussen twee metingen voordat je een verschil een signaal
noemt. Verandert de rondeverzameling, dan is het verschil in `rho` en
`top15_gevangen` niet zonder meer een modelverschil.

## De vier open punten, afgehandeld 2026-11-09

### 1. De ijking meette een ander model dan het advies draait -- GEREPAREERD

`spelerstats.csv` heeft nooit in de repo bestaan, dus `fbref` was in
`backtest.main()` en in `meet_model()` altijd leeg. De terugval
`stats_uit_seizoen()` (8ea08fc, 2026-10-23) was alleen in `cvhj_model.py`,
`multi_periode.py` en `notify.py` gezet, niet in de ijking. `KRIMP_SPELER` en
`KRIMP_CLUB` zijn dus gekalibreerd op een variant die niemand draaide.

Beide plekken vallen nu terug op `spelers_seizoen.csv`, net als productie. De
run meldt sindsdien `spelerstats: 422 spelers uit seizoen`.

### 2. De waarheid kon assists en kaarten niet scoren -- GEREPAREERD, per ronde

`punten_met_positie()` telt nu assists, gele en rode kaarten en reddingen mee,
met de waarden uit `CVHJ_modelverantwoording.md` r.101 (assist 5/4/3/2 naar
positie, geel -3, rood -8, 1 punt per 5 reddingen).

De moeilijkheid was dat die velden voor ronde 1 t/m 9 LEEG zijn (geverifieerd:
418 tot 458 lege velden per ronde, geen enkele "0") en vanaf ronde 10 gevuld.
Zomaar uitbreiden zou de waarheid per ronde verschillend maken binnen hetzelfde
ongewogen gemiddelde. Daarom is `evalueer_ronde()` nu PER RONDE SYMMETRISCH: de
seizoensstatistieken gaan alleen naar `bouw_pool` voor ronden waarvan de
waarheid de volle spelregels kan toepassen. Ronde 1 t/m 9 voorspelt en scoort
zonder assists en kaarten, aan beide kanten hetzelfde.

Gemeten effect, hele reeks:

| ronde | rmse voor -> na | rho voor -> na |
|---|---|---|
| 2 t/m 9 | ongewijzigd | ongewijzigd |
| 10 | 3,12 -> 3,28 | 0,166 -> 0,243 |
| 11 | 3,43 -> 3,62 | 0,367 -> 0,393 |
| TOTAAL | 3,37 -> 3,41 | 0,322 -> 0,332 |

Ronde 2 t/m 9 is bit-voor-bit identiek: de historische reeks krijgt geen nieuwe
breuk. De rangorde verbetert waar de meting symmetrisch werd, de absolute fout
stijgt doordat de waarheid meer echte punten bevat, en de bias zakt van +0,18
naar +0,15 -- het model overschatte minder dan het leek.

Proefrun van `valideer.py --ronde 12` met alle vier punten erin, tegenover de
opgeslagen meting 7 op dezelfde data:

| maat | meting 7 (asymmetrisch) | met deze patch |
|---|---|---|
| rmse | 3,3822 | 3,4067 |
| rho | 0,3277 | 0,3322 |
| top15_gevangen | 0,1858 | **0,2083** |

Eén keuze die niet uit de spelregels volgt: de reddingen gaan met vloerdeling
(`//`), want "1 punt per 5 reddingen" leest als een heel punt per vijf. Keert
CVHJ naar rato uit, dan is dat één teken wijzigen in `punten_met_positie()`.

### 3. De halve-rondeoverslag van PR #33 -- NIET DOORGEVOERD, en dat is juist

Ik had dit fout. `clubs.csv` heeft voor ELKE ronde 9 wedstrijden, ronde 6
inbegrepen. Alleen `historie/ronde-6.json` zag er 5 -- dat is een artefact van
het ADVIES dat midden in de ronde draaide, niet van de data waarop de backtest
rekent. `evalueer_ronde()` voorspelt ronde 6 opnieuw uit het volledige
programma, en die ronde scoort met rho 0,420 juist bovengemiddeld.

De overslag hoort dus precies waar hij staat: in `meet_eigen_ploeg()`, dat het
ADVIES tegen de werkelijke ploeg meet. Hem naar `meet_model()` verplaatsen zou
een goede ronde weggooien.

### 4. De validator testte zichzelf niet -- GEREPAREERD

`test_valideer.py` en `test_grenzen.py` stonden niet in `SUITES`. `suites_totaal`
gaat daarmee van 6 naar 8. Dat is een zichtbare verandering in de reeks, want
beide kolommen staan er al in. Alle acht zijn groen.
