# CVHJ-model 2026/27

Twee onderdelen: een scraper die wekelijks data van pouletips.nl ophaalt, en
een model dat per speelronde de beste opstelling en de beste transfers
berekent binnen de spelregels.

## Wat er in oktober veranderde

Pouletips heeft de wedstrijdpagina's omgebouwd. De uitslag staat niet meer in
de titel (`FC Groningen - Ajax: opstellingen en voorspelling`, geen
`uitslag: 2-1`), en de officiële basiself, de bank, de wissels en de
doelpuntenmakers worden pas in de browser ingeladen — met `requests` zijn die
niet te zien. De oude scraper liep daarom leeg.

De data staat er nog wel, maar verspreid over vijf pagina's:

| Wat | Waar | Hoe vaak |
|---|---|---|
| Uitslagen, alle ronden | `/eredivisie/uitslagen/` | 1 pagina |
| Kansen, **verwachte goals**, over/under | `/eredivisie/wedstrijd/<slug>/` | 1 per duel, eenmalig |
| **Afwezigen** met reden en terugkeerdatum, vermoedelijke basiself met basiskans | `/eredivisie/<club>/opstelling/` | 18 per run |
| Minuten, basisplaatsen, goals, **assists**, overtredingen | `/eredivisie/speler/<slug>/` | 504 per week |
| **Gele en rode kaarten** | `/eredivisie/statistieken/gele-kaarten/`, `/rode-kaarten/` | 2 per run |

## Bestanden die de scraper maakt

| Bestand | Inhoud |
|---|---|
| `clubs.csv` | per club per ronde: uitslag, ploegpunten, clean sheet, kansen, `xg_voor`, `xg_tegen`, `beide_scoren`, `over_25`. Bevat het hele speelschema, dus ook nog niet gespeelde ronden. |
| `spelers_seizoen.csv` | seizoenstotalen per speler, één bevroren stand per ophaaldatum |
| `spelers.csv` | productie per ronde, als verschil tussen twee opeenvolgende standen: minuten, basis, goals, assists, geel, rood, reddingen, clean sheet |
| `afwezigen.csv` | wie geblesseerd, geschorst of vertrokken is, met reden en verwachte terugkeerdatum |
| `opstellingen.csv` | vermoedelijke basiself per club met de basiskans per speler |
| `prijzen.csv` | de CVHJ-spelerslijst: team, speler, positie, prijs **en speler_id** |

`prijzen.csv` komt uit `/eredivisie/poule/coach-van-het-jaar/spelers/`, de
pagina met alle spelers die je in CVHJ kunt kopen. Omdat de naam daar een link
naar de spelerspagina is, staat het `speler_id` in het bestand en is de
koppeling met de gescrapete spelers exact. Dat vervangt de bevroren
CVHJ-sheet, waarin aanwinsten geen prijs hadden (bij PSV koppelde maar 21 van
de 31 spelers) en waarin namen afwijkend geschreven stonden.

Van die pagina worden alleen naam, club, positie en waarde gelezen. De
kolommen *Verwachte punten*, *Per miljoen* en de basiskans staan er volgens de
pagina zelf "voor leden" bij — dat is Pouletips Premium en dat blijft eraf.

Productie per ronde komt dus uit een verschil, niet uit een wedstrijdverslag.
De kolom `venster` zegt welke ronden in dat verschil zaten. Staat er meer dan
één ronde in, dan is de toerekening aan een ronde niet exact — dat gebeurt bij
inhaalduels en midweekse ronden.

## Scraper draaien

```bash
python scrape_eredivisie.py --alles                  # alles
python scrape_eredivisie.py --clubs --afwezigen      # licht, voor de deadline
python scrape_eredivisie.py --prijzen                # alleen de CVHJ-prijslijst
python scrape_eredivisie.py --clubs --ronde 10       # één ronde opnieuw
python scrape_eredivisie.py --spelers --max-spelers 20   # proefrun
python scrape_eredivisie.py --debug <url>            # wat staat er echt?
```

`--debug` drukt de koppen, de tabellen, de spelerslinks en de omgeving van elk
zoekwoord af. Gebruik hem zodra een club `0 basis` oplevert of een kolom leeg
blijft; dan hoeft er niet geraden te worden. Dat raden heeft eerder drie
rondes aan onzin opgeleverd.

De volledige run doet ruim 500 pagina's met 1,2 seconde pauze: ongeveer een
kwartier. Bij een 429 of een 5xx wordt steeds langer gewacht.

**Let op bij de uitslagenpagina:** een nog niet gespeeld duel krijgt daar een
*voorspelde* stand mee, in dezelfde rij en in dezelfde vorm als een echte
uitslag — `za 23 jan, 16:30 Ajax 2-1 voorspelling Telstar`. Het woord
`voorspelling` is het enige verschil. Zonder die uitzondering belanden 225 van
de 306 duels met een verzonnen uitslag, resultaat, ploegpunten en clean sheet
in `clubs.csv`, en worden de clubratings daarop gefit. De datacontrole toetst
nu ook dat geen enkele wedstrijd in de toekomst een uitslag heeft.

Staat er nog een `spelers.csv` uit de vorige opzet, dan zet de eerste volledige
run die apart als `spelers_vorig_formaat.csv`. De ronderijen beginnen opnieuw
bij de tweede momentopname.

De uitslagenpagina noemt alle 34 ronden, ruim driehonderd duels. Het hele
speelschema gaat in `clubs.csv` — daar haalt het model zijn programma uit —
maar wedstrijdpagina's worden alleen opgehaald voor gespeelde ronden waarvan
de kansen nog missen, plus de komende twee ronden (`VOORUIT_RONDEN`). Die
laatste elke run opnieuw, want de odds scherpen naar de aftrap toe aan. Odds
van ronde 30 in oktober zijn zinloos en zouden verouderd zijn voordat die
ronde wordt gespeeld.

### Schema in GitHub Actions

| Moment | Taken | Waarom |
|---|---|---|
| maandag 08:00 | `--alles` | de ronde is gespeeld; seizoensstand bevriezen zodat het verschil één ronde is |
| donderdag 18:00 | `--clubs --afwezigen` | kansen en blessures voor de komende ronde |
| vrijdag 09:00 | `--clubs --afwezigen` | laatste keer voor de deadline; odds scherpen aan en blessures komen laat |

De lichte runs schrijven géén ronderijen weg: zonder gespeelde ronde in het
venster zou een verschil van nul aan de vorige ronde worden toegerekend.

## Controleren of de scrape nog klopt

```bash
python controle.py              # beide controles
python controle.py --bron       # werken de parsers nog op de pagina's van nu?
python controle.py --data       # is wat er in de CSV's staat consistent?
python controle.py --data --soft   # rapporteren, maar exitcode altijd 0
```

Exitcode 1 bij een fout, 0 bij alleen waarschuwingen. Er komt een `controle.md`
(om te lezen) en een `controle.json` (om te meten) naast te staan.

**De broncontrole is de kanarie.** Elke parser wordt op een echte pagina gezet
en de uitkomst moet plausibel zijn: elf basisspelers per club, afwezigen met
een bekende reden, verwachte goals tussen 0,2 en 5, drie kansen die optellen
tot 100, minstens 400 spelers over 18 clubs, en een assistkolom die nog
bestaat. Dat gaat met opzet via de parsers zelf en niet via losse patronen, zo
kan de controle niet uit de pas lopen met wat de scraper werkelijk doet.

**De datacontrole** toetst de CSV's: spiegeling tussen de thuis- en uitrij van
hetzelfde duel, kansen die optellen tot 100, uitslag die rijmt met resultaat en
ploegpunten, ongeveer 18 rijen per ronde, geen dubbele sleutels, minuten die
niet boven 90 per ronde komen, en de leeftijd van de nieuwste gegevens. De
scherpste toets is dat **seizoenstotalen niet kunnen dalen**: zakt een teller
tussen twee weken, dan is er iets stuk.

In de workflow draait de broncontrole vóór het scrapen en de datacontrole
erna. Valt een van de twee om, dan wordt er **niets** vastgelegd — stale data
is hinderlijk, foute data is schadelijk. Met de hand starten en `negeer_controle`
aanzetten gaat alsnog door.

## Model draaien

`prijzen.csv` komt nu uit de scraper (zie boven), dus je hoeft niets met de
hand bij te houden. Het model koppelt op `speler_id` als dat erin staat, en
anders op naam — dan met een voorvoegselmatch binnen dezelfde club voor
gevallen als `Yarek Gasiorowski` tegen `Yarek Gąsiorowski Hernandis`, maar
alleen als die precies één kandidaat oplevert. Het model meldt per run hoeveel
prijsrijen koppelen en welke niet.

```bash
python cvhj_model.py --ronde 10                  # opstelling + 3 transfers
python cvhj_model.py --ronde 10 --transfers 1    # de gewone rondewissel
python cvhj_model.py --ronde 10 --transfers 0    # alleen de opstelling
python cvhj_model.py --ronde 10 --toon-pool 30   # beste 30 van de hele markt
```

Het programma van de komende ronde komt nu uit `clubs.csv`; dat hoeft niet
meer met de hand in het script. `INHAAL` en `SELECTIE` onderin wel. Knoppen:
`--venster` (hoeveel ronden vorm meetellen, standaard 6), `--min-minuten`
(drempel voor de pool, standaard 60), `--negeer-afwezigen`.

## Hoe het rekent

1. **Clubsterkte uit de markt.** De verwachte goals per wedstrijd komen uit de
   bron waar ze er staan. Dat is alleen rond de eerstvolgende ronde: na een
   wedstrijd haalt de bron ze weg, en verder vooruit vult ze ze per wedstrijd
   aan naarmate de ronde nadert. Gemeten op 19-10-2026: nul van de 162
   gespeelde rijen, alle achttien van de eerstvolgende ronde, geen van de
   ronde daarna. Voor de historie wordt dus altijd uit de winstkansen
   teruggerekend met een Poisson-zoektocht (grof naar fijn, met cache: 0,5
   seconde voor 81 wedstrijden). Dat blijft een benadering, want twee
   lambdaparen kunnen dezelfde winstkans geven. Daarna schat een
   ridge-regressie per club een aanval- en verdedigingswaarde, gekrompen naar
   de cijfers van vorig seizoen. Het model meldt per run hoeveel verwachte
   goals uit de bron komen en hoeveel zijn teruggerekend.

2. **Individuele productie.** Doelpunten, assists en kaarten per 90 minuten,
   omgerekend naar CVHJ-punten (goal 12/10/8/6, assist 5/4/3/2 naar positie,
   geel −3, rood −8) en gekrompen naar een positiegemiddelde met een gewicht
   van acht wedstrijden. Zonder die krimp schiet het model door op spelers die
   toevallig twee keer scoorden.

3. **Kans op een basisplaats** uit `opstellingen.csv`: het percentage dat de
   bron geeft, namelijk hoe vaak de speler dit seizoen begon. Ontbreekt dat
   bestand, dan wordt het uit de minuten in het venster geschat.

4. **Afwezigen** vallen uit de pool. Alleen de laatste stand telt, zodat wie in
   september geblesseerd was in oktober weer meedoet.

5. **Verwachte punten** = ploegpunten + clean sheet + individuele productie.
   Aanvallende productie wordt gedempt met de wortel van de verwachte goals
   van de ploeg; discipline niet. De tegenstander doet voor individuele
   productie veel minder dan voor ploegpunten en clean sheets. Zonder die
   demping zette het model in augustus Ihattaren op de bank op grond van de
   tegenstander, terwijl hij scoorde.

6. **Optimalisatie.** De opstelling zet per linie de zwakste op de bank (die
   telt voor 50%). De transferzoeker probeert alle combinaties van verkopen en
   kopen, binnen budget, één speler per club, en een geldige samenstelling.

De selectiesamenstelling legt de formatie vast, omdat de bank verplicht één
speler per linie telt. Van formatie wisselen kan dus alleen via een transfer.

## Wat het model niet weet

- **De officiële opstelling.** Die staat pas ongeveer een uur voor de aftrap
  op de pagina, en dan alleen in de browser. Het model gebruikt de
  vermoedelijke opstelling. Dit is nu de grootste blinde vlek: loop de echte
  opstellingen elke ronde zelf na. Van vier handmatig gecontroleerde spelers
  bleken er in augustus twee onjuist ingeschat.
- **Kaarten voor wie buiten de top 40 valt.** De ranglijst toont 40 van de 160
  spelers met minstens één gele kaart. Wie daaronder zit, krijgt de
  positieprior. `overtredingen` staat wel per speler in
  `spelers_seizoen.csv` en is een bruikbare proxy om dat later te ijken.
- **Eén ronde vooruit.** De transferbeslissing geldt voor een hele periode,
  maar wordt op één ronde geoptimaliseerd.
- **Verwachting, geen klassering.** Bij duizenden deelnemers wint niet het
  hoogste gemiddelde maar de beste staart. Monte Carlo liet ongeveer 30 punten
  standaardafwijking per periode zien.

## Onderhoud

De clubnamen moeten in alle bestanden gelijk zijn. De scraper brengt elke
schrijfwijze terug naar de korte vorm (`PSV Eindhoven` → `PSV`, `AFC Ajax` →
`Ajax`, `N.E.C.` → `NEC`) via `CLUB_SLUG` en `CLUB_ALIAS` bovenin.
Spelersnamen worden genormaliseerd naar de vorm van de link-slug; de tabel
`TRANS` is nodig omdat ø, æ en å geen ontbinding in NFKD hebben en er zonder
die tabel stilletjes uitvallen (`søren-tengstedt` werd `sren-tengstedt`).

Verandert het kolomformaat van een CSV, dan begint de scraper dat bestand
opnieuw op in plaats van een mengsel te maken.

Nieuw seizoen of een gepromoveerde club: pas `CLUB_SLUG` in de scraper aan en
`PRIOR_AANVAL` / `PRIOR_TEGEN` in het model, met de doelpunten voor en tegen
per duel van het vorige seizoen.
