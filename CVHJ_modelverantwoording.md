# Modelverantwoording — Coach van het Jaar 2026/27

Versie 19 oktober 2026. Vervangt de versie van 7 augustus. Doel: per speelronde de selectie en opstelling met de hoogste verwachte puntenopbrengst, binnen de spelregels.

Elke claim is gelabeld **Feit** (verifieerbaar), **Aanname** (mijn schatting) of **Interpretatie** (modeluitkomst). Waar ik iets niet hard kon verifiëren staat dat erbij.

## Samenvatting voor wie alleen dit leest

Het model is sinds augustus op drie punten wezenlijk veranderd. Handmatig ingeschatte clubsterktes zijn vervangen door marktnoteringen; het terugrekenen van individuele productie uit vorig seizoen is vervangen door werkelijk gescrapete doelpunten, assists en kaarten per ronde; en de statustabel voor speeltijd is vervangen door de basiskans die de bron zelf publiceert. Daarmee zijn drie van de vier verbeterpunten uit de vorige versie afgehandeld.

Er is één nieuwe beperking bij gekomen, en die is ernstig: **de officiële opstelling is niet meer te scrapen.** Pouletips laadt die pas ongeveer een uur voor de aftrap in de browser. Het model werkt daarom met de vermoedelijke opstelling. Het wekelijks zelf nalopen van de opgegeven opstellingen is daarmee niet langer een goedkope verbetering maar een noodzakelijke stap.

**Belangrijkste risico's**
- De bron kan stil veranderen. Dat is in oktober gebeurd en het heeft weken onopgemerkt data gekost. Hiervoor is nu een controle ingebouwd (§2.2).
- De vermoedelijke opstelling is geen opstelling. Van vier handmatig gecontroleerde namen bleken er in augustus twee onjuist ingeschat.
- Het model maximaliseert de verwachting, niet de klassering. Bij duizenden deelnemers beslist de staart.

---

## 1. Architectuur in vijf lagen

```
[0] Datapijplijn        wat weten we, hoe vers is het, en klopt het nog
      ↓
[A] Spelerspool         wie is koopbaar, tegen welke prijs
      ↓
[B] Puntenmodel         wat levert een speler op per wedstrijd
      ↓
[C] Spreiding           hoeveel ruis zit op die verwachting
      ↓
[D] Optimalisatie       welke 15 maximaliseren dat, binnen de spelregels
```

Laag 0 is nieuw en bepaalt in de praktijk de kwaliteit van alles erboven. Laag B bepaalt de uitkomst, laag C relativeert die, laag D rekent uit.

---

## 2. Laag 0 — Databron en controle

### 2.1 Vijf pagina's in plaats van één

**Feit, geverifieerd 19 oktober 2026.** Pouletips heeft de wedstrijdpagina's omgebouwd. De titel luidt nu *"FC Groningen - Ajax: opstellingen en voorspelling"* zonder uitslag, en de tekst *"De officiële opstelling van …"* bestaat niet meer; er staat *"Zodra de clubs de officiële opstelling bekendmaken, ongeveer een uur voor de aftrap"*. Uitslag, basiself, bank, wissels en doelpuntenmakers zitten in een blok dat pas in de browser wordt geladen.

De data staat er nog wel, verspreid over vijf pagina's:

| Bron | Wat eruit komt | Volume |
|---|---|---|
| `/eredivisie/uitslagen/` | uitslagen van alle speelronden, met ronde en datum | 1 pagina |
| `/eredivisie/wedstrijd/<slug>/` | kansen, **verwachte goals**, beide-ploegen-scoren, over 2,5 | 1 per duel, eenmalig |
| `/eredivisie/<club>/opstelling/` | **afwezigen** met reden en terugkeerdatum, vermoedelijke basiself met basiskans | 18 per run |
| `/eredivisie/speler/<slug>/` | duels, basisplaatsen, minuten, goals, **assists**, overtredingen, reddingen | 504 per week |
| `/eredivisie/statistieken/gele-kaarten/` en `/rode-kaarten/` | **kaarten** per speler | 2 per run |

**Feit:** de spelersindex telde 504 spelers over 18 clubs; 139 spelers hebben minstens één assist, 160 minstens één gele kaart. **Beperking:** de kaartenranglijsten tonen de top 40, dus wie minder dan ongeveer twee kaarten heeft is onzichtbaar.

Productie per ronde komt niet uit een wedstrijdverslag maar uit het **verschil tussen twee seizoensstanden**. Elke maandag wordt de stand per speler bevroren; het verschil met vorige maandag is de productie van de tussenliggende ronde. De kolom `venster` legt vast welke ronden in dat verschil zaten (**Interpretatie**: bij inhaalduels of een midweekse ronde is de toerekening aan één ronde niet exact).

### 2.2 De controle — waarom die er moest komen

**Feit:** toen de bron in oktober veranderde, sloot de scrape af met exitcode 0 en legde niets vast. De melding was "geen uitslag gevonden", wat niet te onderscheiden is van "nog niet gespeeld". Er is weken niets binnengekomen zonder dat iets of iemand alarm sloeg.

Daarom nu twee controles, elke run, met een verschillende vraag:

**Broncontrole** (`controle.py --bron`) zet elke parser op een echte pagina en beoordeelt de uitkomst: zijn er elf basisspelers, staan er afwezigen met een bekende reden, zijn de verwachte goals gelezen en liggen ze tussen 0,2 en 5, tellen de drie kansen op tot 100, zijn er ten minste 400 spelers in de index over 18 clubs, en bestaat de assistkolom nog. Met opzet via de parsers zelf, niet via losse patronen: zo kan de controle niet uit de pas lopen met wat de scraper werkelijk doet.

**Datacontrole** (`controle.py --data`) toetst de CSV's op interne consistentie: spiegeling tussen de thuis- en uitrij van hetzelfde duel, kansen die optellen tot 100, uitslag die rijmt met resultaat en ploegpunten, ongeveer 18 rijen per ronde, geen dubbele sleutels, minuten die niet boven 90 per ronde komen, en hoe oud de nieuwste gegevens zijn.

De scherpste van allemaal is de **monotonietoets**: seizoenstotalen kunnen niet dalen. Zakt een teller tussen twee weken, dan is er een parser stuk of is een speler van club gewisseld. Dat is een regressietest die geen enkele layoutwijziging overleeft.

Valt een van de twee controles om, dan legt de workflow **niets** vast. Stale data is hinderlijk, foute data is schadelijk.

**Aanname, nog te verifiëren:** de controle is getoetst op nagebouwde HTML en op veertien soorten moedwillig bedorven data — alle veertien worden betrapt. Ik heb de scraper niet live kunnen draaien; de eerste echte maandagrun moet je nalopen.

---

## 3. Laag A — De spelerspool

**504 spelers, 18 clubs** (**Feit**, 19 oktober). Twee bronnen:

| Bron | Wat | Status |
|---|---|---|
| Spelersindex pouletips | alle spelers per club, met positie uit de kopjes Keepers/Verdedigers/Middenvelders/Aanvallers | **Feit**, wekelijks vernieuwd |
| CVHJ-spelerslijst | prijs per speler | **Feit**, en bevroren: CVHJ wijzigt prijzen niet tijdens het seizoen |

De positie komt nu uit de bron en niet meer uit de prijslijst. Dat betekent dat een speler die van positie wisselt automatisch meegaat.

Spelers op de afwezigenlijst vallen uit de pool, waarbij alleen de laatste stand telt — wie in september geblesseerd was, doet in oktober weer mee. Spelers onder de minutendrempel (standaard 60 in het venster) vallen af als dood slot met E = 0.

**Beperking:** de koppeling tussen de CVHJ-naam en de bronnaam loopt via een genormaliseerde naamvorm. Dat werkt voor accenten en Noordse tekens, maar niet voor afwijkende schrijfwijzen of bijnamen. Het model benoemt welke namen het niet kon koppelen; die lijst hoort elke ronde leeg te zijn.

---

## 4. Laag B — Het puntenmodel

De CVHJ-score van een speler in één wedstrijd valt uiteen in drie delen:

```
punten = ploegresultaat + clean sheet + individuele productie
```

Waarden volgens de spelregels (**Feit**): winst 3, gelijkspel 1; doelpunt 12/10/8/6 naar positie; assist 5/4/3/2; clean sheet 5 voor een keeper en 3 voor een verdediger; gele kaart −3, rode kaart −8; 1 punt per 5 reddingen; strafschop 4; een niet-ingevallen reserve scoort 50%.

### 4.1 Ploegresultaat en clean sheet

**Dit is het grootste verschil met de augustusversie.** De handmatig ingeschatte aanval- en verdedigingswaarden per club zijn verdwenen. In plaats daarvan:

1. **Verwachte goals rechtstreeks uit de bron.** De wedstrijdpagina noemt ze expliciet: *"Verwachte goals FC Groningen 1.51"*, *"Verwachte goals Ajax 2.17"* (**Feit**, ronde 9; de wedstrijd eindigde 2-5). Deze getallen zijn marktnoteringen waaruit de bookmakersmarge is gehaald.
2. **Ridge-regressie op logschaal** schat daaruit per club een aanval- en verdedigingswaarde, gekrompen naar de doelpunten voor en tegen per duel van seizoen 25/26 (**Aanname** in de krimpsterkte, **Feit** in de prior).
3. **Poisson** levert uit het lambdapaar de winst-, gelijkspel- en clean-sheetkans.

Tot vandaag werden die lambda's teruggerekend uit de winstkansen met een raster van 170×170 Poisson-evaluaties per wedstrijd. Dat was duur en principieel onnauwkeurig, want twee verschillende lambdaparen kunnen dezelfde winstkans opleveren. **Interpretatie, gemeten op tien ronden testdata:** het rechtstreeks lezen brengt de rekentijd van 22 seconden naar 0,15 seconde en haalt de benaderingsfout eruit. Staan de verwachte goals niet op de pagina, dan valt het model terug op het terugrekenen en meldt dat.

### 4.2 Individuele productie

In augustus moest ik dit terugrekenen uit de totaalpunten van vorig seizoen, omdat het CVHJ-bestand geen goals, assists of kaarten gaf. Dat is niet meer nodig: de scraper levert ze per speler.

```
aanvallend = (goals × goalwaarde + assists × assistwaarde + prior × 8) / (n90 + 8)
discipline = (geel × −3 + rood × −8 + kaartprior × 8) / (n90 + 8)
```

met `n90` = minuten / 90. Het gewicht van acht wedstrijden betekent: bij acht gespeelde wedstrijden telt de eigen prestatie voor 50%. Zonder die krimp schiet het model door op spelers die toevallig twee keer scoorden.

Priors in punten per 90 (**Aanname**):

| Positie | Doelpunten | Assists | Kaarten |
|---|---|---|---|
| Keeper | 0,30 | 0,05 | −0,06 |
| Verdediger | 0,85 | 0,32 | −0,42 |
| Middenvelder | 1,25 | 0,45 | −0,48 |
| Aanvaller | 1,75 | 0,25 | −0,30 |

**Tegenstandercorrectie, gedempt.** Aanvallende productie schaalt mee met de verwachte goals van de eigen ploeg, maar met de wortel in plaats van lineair; discipline schaalt niet mee, want een gele kaart hangt niet af van de verdediging van de tegenstander. **Interpretatie:** de volle correctie zette in augustus Ihattaren op de bank op grond van de tegenstander, terwijl hij scoorde en de wel opgestelde Willumsson niets maakte. De tegenstander doet voor individuele productie aantoonbaar minder dan voor ploegpunten en clean sheets.

### 4.3 Speeltijd

De statustabel uit augustus (`vast` 0,92 / `basis` 0,78 / `rot` 0,50 / `bank` 0,15 / `out` 0,00) is vervallen. Die was mijn interpretatie van losse waarnemingen uit voorrondes en opgegeven basiselftallen, en dekte 101 van de 493 spelers.

In plaats daarvan publiceert de bron per speler een **basiskans**: het aandeel wedstrijden waarin hij dit seizoen begon (**Feit**, bijvoorbeeld *"Mika Mármol 90%"*). Dat is dezelfde grootheid, voor alle spelers, uit de bron. Ontbreekt het bestand, dan valt het model terug op een schatting uit de minuten in het venster, en meldt dat.

Hiermee is ook jouw vraag van augustus opgelost — of Baas werkelijk de basisspeler was en niet Blind of Bouwman. Die vraag is nu een kolom in plaats van een inschatting.

---

## 5. Laag C — Spreiding

**Eerlijk over wat hier staat:** de Monte Carlo-simulatie is in augustus en september uitgevoerd in de analyse, maar zit **niet** in het geëxporteerde model. `cvhj_model.py` rekent met puntverwachtingen.

De uitkomst van toen (**Interpretatie**, 20.000 simulaties over ronde 1 t/m 4): gemiddeld 198,9 punten, p10 161, p90 238. De standaardafwijking van ongeveer 30 punten per periode is het getal dat blijft staan, ook al zijn de niveaus achterhaald.

Dat getal is de reden voor terughoudendheid over de hele exercitie. **Feit:** het geoptimaliseerde account uit het infotopics-artikel eindigde 14.646e van 28.301. **Feit:** jouw eigen eerste ronden leverden 45 en 50 punten. Verschillen van enkele punten tussen alternatieve selecties liggen binnen de ruis; tien minuten de opgegeven opstellingen nalopen levert meer op dan welke verdere modelverfijning ook.

---

## 6. Laag D — Optimalisatie

**Wat in het geëxporteerde model zit:** een uitputtende zoektocht. De opstelling zet per linie de zwakste speler op de bank, die voor 50% meetelt. De transferzoeker probeert alle combinaties van verkopen en kopen binnen budget, één speler per club en een geldige samenstelling, en rapporteert de vijf beste.

**Wat in de analyse van augustus zat:** één binair lineair programma (MILP, HiGHS) over ronde 1 t/m 4 tegelijk, met ongeveer 1.700 binaire variabelen na pruning. Dat is gebruikt voor de opbouw van periode 1 en zit niet in de export.

**Randvoorwaarden, allemaal uit de spelregels (Feit):**
- 15 spelers, 11 basis, exact 1 reserve per linie
- lijngroottes per formatie: 3-4-3, 4-3-3, 4-4-2, 3-5-2, 5-3-2
- maximaal 1 speler per club
- selectiewaarde ≤ €32,00
- 1 transfer per ronde, niet op te sparen; 3 vóór een nieuwe periode, in plaats van de rondewissel

De selectiesamenstelling legt de formatie vast, omdat de bank verplicht één speler per linie telt. Van formatie wisselen kan dus alleen via een transfer. Basis en bank onderling wisselen is vrij en onbeperkt.

Het programma van de komende ronde komt nu uit `clubs.csv` in plaats van met de hand in het script te staan — de scraper schrijft het hele speelschema weg.

---

## 7. Wat het model niet kan

| Beperking | Gevolg |
|---|---|
| **De officiële opstelling is niet te scrapen** | Werkt met de vermoedelijke opstelling. Dit is nu de grootste blinde vlek. |
| Kaarten alleen voor de top 40 van de ranglijst | Wie minder dan ongeveer twee kaarten heeft krijgt de positieprior |
| Productie per ronde komt uit een verschil tussen weken | Bij een midweekse of uitgestelde ronde niet exact aan één ronde toe te rekenen |
| Optimaliseert één ronde vooruit | De transferbeslissing geldt voor een hele periode |
| Maximaliseert de verwachting, niet de klassering | Bij duizenden deelnemers wint de staart, niet het gemiddelde |
| Geen blessurenieuws van dezelfde dag | De afwezigenlijst is zo vers als de laatste run: donderdag en vrijdag |
| Naamkoppeling CVHJ ↔ bron is tekstueel | Een afwijkende schrijfwijze levert een dood slot met E = 0 |

---

## 8. Waar dit het model zou verbeteren

Stand van de vier punten uit de augustusversie:

1. ~~Slotnoteringen van bookmakers in plaats van handmatige clubsterkte~~ — **afgehandeld** (§4.1).
2. **Een rangorde-doelfunctie**: maximaliseer de kans op een top-1%-klassering in plaats van het gemiddelde. **Nog open, en het grootste resterende punt.** Dit verandert de selectie richting differentials en is precies wat de 30 punten spreiding uit §5 relevant maakt.
3. ~~Werkelijke minuten in plaats van basis-of-bank~~ — **afgehandeld** (§4.3).
4. **Wekelijkse verificatie van de opstellingen** — **nog nodig, en nu noodzakelijk in plaats van optioneel**, omdat de officiële opstelling niet meer te scrapen is.

Nieuw op de lijst:

5. **Kaarten ijken op overtredingen.** `overtredingen` staat per speler in `spelers_seizoen.csv`, voor alle 504. De verhouding kaarten per overtreding is op de zichtbare top 40 te ijken en daarna op iedereen toe te passen. Dat dicht het gat uit §7 zonder extra bron.
6. **Periodeoptimalisatie in de export.** De MILP uit augustus optimaliseerde vier ronden tegelijk; de export doet één ronde. De transferbeslissing geldt voor een periode, dus hier zit nog winst.
7. **Monte Carlo in de export** in plaats van alleen in de analyse, zodat elke weekuitkomst een spreiding meekrijgt en niet alleen een puntschatting.
