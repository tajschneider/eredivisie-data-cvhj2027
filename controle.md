# Controle scrape — MET WAARSCHUWINGEN

Uitgevoerd 2026-11-27. 0 fout(en), 2 waarschuwing(en), 33 controles.

## Waarschuwingen

- **spelers_seizoen.csv** — 2 herziene feiten sinds 2026-11-16  
  jan-burger.assists: 1 -> 0; evan-rottier.assists: 5 -> 4 — een enkele herzienbare teller een stap omlaag, zonder dat duels, basisplaatsen of minuten zakken. Dat is de bron die een beoordeling terugdraait: een assist wordt na de wedstrijd toegekend en soms anders toegekend. Blokkeert niet, want onze cijfers volgen de bron en die noemt deze waarde nu zelf. Kijk wel op de spelerspagina als het dezelfde speler blijft of als er meer bijkomen.
- **opstellingen.csv** — geen basiskansen (0 van 198 rijen gevuld)  
  de bron publiceert ze met tussenpozen, dus dit kan volgende run weer goed zijn. Blokkeert niet, maar het model rekent dan zonder speeltijdkans: draai scrape_eredivisie.py --debug op een opstellingspagina als het blijft staan

## Metingen

| Meting | Waarde |
|---|---|
| afwezigen_clubs | 18 |
| afwezigen_laatste | 63 |
| clubs_eerstvolgende_met_xg | 18 van 18 |
| clubs_eerstvolgende_ronde | 14 |
| clubs_gespeeld_met_xg | 72 van 234 |
| clubs_komend_met_xg | 36 van 36 |
| clubs_met_kansen | 270 |
| clubs_met_xg | 108 |
| clubs_rijen_met_uitslag | 234 |
| clubs_verder_vooruit_met_xg | 18 van 18 |
| clubs_verschillend | 18 |
| clubs_volledige_ronden | 13 |
| dagen_oud | 0 |
| minuten_onzichtbaar_voor_model | 0 |
| nieuwste_ophaaldatum | 2026-11-27 |
| opstellingen_clubs | 18 |
| opstellingen_kansen_gevuld | 0 |
| opstellingen_kansen_verschillend | 0 |
| prijzen_clubs | 18 |
| prijzen_goedkoopste15 | 15.0 |
| prijzen_koppelgraad | 478 van 508 (94%) |
| prijzen_spelers | 508 |
| rijen_afwezigen.csv | 741 |
| rijen_clubs.csv | 612 |
| rijen_opstellingen.csv | 2574 |
| rijen_prijzen.csv | 508 |
| rijen_spelers.csv | 5142 |
| rijen_spelers_seizoen.csv | 5080 |
| ronderijen_ronden | 13 |
| seizoen_dalende_tellers | 0 |
| seizoen_feitcorrecties | 2 |
| seizoen_minuten_revisies | 0 |
| seizoen_momentopnamen | 10 |
| seizoen_spelers_laatste | 510 |
| spelers_met_twee_slugs | 18 |

## Alle controles

| Uitkomst | Groep | Controle |
|---|---|---|
| OK | clubs.csv | geen dubbele ronde/club |
| OK | clubs.csv | 18 verschillende clubs in het bestand |
| OK | clubs.csv | elke ronde ongeveer 18 rijen (34 ronden) |
| OK | clubs.csv | thuis- en uitrij spiegelen |
| OK | clubs.csv | kansen tellen op tot 100 |
| OK | clubs.csv | verwachte goals plausibel |
| OK | clubs.csv | uitslag, resultaat, ploegpunten en clean sheet rijmen |
| OK | clubs.csv | geen uitslag bij een wedstrijd in de toekomst |
| OK | clubs.csv | verwachte goals bij 18 van de 18 rijen van ronde 14, de eerstvolgende |
| OK | spelers_seizoen.csv | 510 spelers in de stand van 2026-11-27 |
| OK | spelers_seizoen.csv | 18 clubs |
| OK | spelers_seizoen.csv | tellers intern consistent |
| OK | spelers_seizoen.csv | geen dalende seizoenstotalen tussen 2026-11-16 en 2026-11-27 |
| WAARSCHUWING | spelers_seizoen.csv | 2 herziene feiten sinds 2026-11-16 |
| OK | spelers.csv | geen dubbele ronde/speler/club |
| OK | spelers.csv | geen speeltijd onder een onbekende slug |
| OK | spelers.csv | elke rij heeft een ronde |
| OK | spelers.csv | minuten en productie per ronde plausibel |
| OK | afwezigen.csv | alle redenen bekend |
| OK | afwezigen.csv | terugkeerdatums in ISO-vorm |
| OK | opstellingen.csv | 18 clubs |
| OK | opstellingen.csv | elke club 11 basisspelers |
| OK | opstellingen.csv | basiskansen tussen 0 en 100 |
| WAARSCHUWING | opstellingen.csv | geen basiskansen (0 van 198 rijen gevuld) |
| OK | opstellingen.csv | basiskansen varieren: niet gemeten bij 0 gevulde kans(en), deze toets heeft er 50 nodig |
| OK | prijzen.csv | 508 spelers in de lijst |
| OK | prijzen.csv | 18 clubs |
| OK | prijzen.csv | vier posities in het Engels |
| OK | prijzen.csv | prijzen in een plausibel bereik |
| OK | prijzen.csv | geen dubbele speler_id |
| OK | prijzen.csv | vijftien goedkoopste spelers kosten 15.00 |
| OK | prijzen.csv | 478 van de 508 prijsrijen koppelt aan een gescrapete speler (94%) |
| OK | versheid | nieuwste gegevens zijn 0 dag(en) oud |
