# Controle scrape — MET WAARSCHUWINGEN

Uitgevoerd 2026-11-19. 0 fout(en), 2 waarschuwing(en), 32 controles.

## Waarschuwingen

- **opstellingen.csv** — geen basiskansen (0 van 198 rijen gevuld)  
  de bron publiceert ze met tussenpozen, dus dit kan volgende run weer goed zijn. Blokkeert niet, maar het model rekent dan zonder speeltijdkans: draai scrape_eredivisie.py --debug op een opstellingspagina als het blijft staan
- **versheid** — spelers_seizoen.csv loopt achter (2026-11-16 tegen 2026-11-19)  
  normaal bij een lichte run, verdacht na een volledige

## Metingen

| Meting | Waarde |
|---|---|
| afwezigen_clubs | 17 |
| afwezigen_laatste | 62 |
| clubs_eerstvolgende_met_xg | 18 van 18 |
| clubs_eerstvolgende_ronde | 13 |
| clubs_gespeeld_met_xg | 54 van 216 |
| clubs_komend_met_xg | 36 van 36 |
| clubs_met_kansen | 252 |
| clubs_met_xg | 90 |
| clubs_rijen_met_uitslag | 216 |
| clubs_verder_vooruit_met_xg | 18 van 18 |
| clubs_verschillend | 18 |
| clubs_volledige_ronden | 12 |
| dagen_oud | 0 |
| minuten_onzichtbaar_voor_model | 0 |
| nieuwste_ophaaldatum | 2026-11-19 |
| opstellingen_clubs | 18 |
| opstellingen_kansen_gevuld | 0 |
| opstellingen_kansen_verschillend | 0 |
| prijzen_clubs | 18 |
| prijzen_goedkoopste15 | 15.0 |
| prijzen_koppelgraad | 479 van 508 (94%) |
| prijzen_spelers | 508 |
| rijen_afwezigen.csv | 619 |
| rijen_clubs.csv | 612 |
| rijen_opstellingen.csv | 2178 |
| rijen_prijzen.csv | 508 |
| rijen_spelers.csv | 4859 |
| rijen_spelers_seizoen.csv | 4570 |
| ronderijen_ronden | 12 |
| seizoen_dalende_tellers | 0 |
| seizoen_feitcorrecties | 0 |
| seizoen_minuten_revisies | 0 |
| seizoen_momentopnamen | 9 |
| seizoen_spelers_laatste | 511 |
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
| OK | clubs.csv | verwachte goals bij 18 van de 18 rijen van ronde 13, de eerstvolgende |
| OK | spelers_seizoen.csv | 511 spelers in de stand van 2026-11-16 |
| OK | spelers_seizoen.csv | 18 clubs |
| OK | spelers_seizoen.csv | tellers intern consistent |
| OK | spelers_seizoen.csv | geen dalende seizoenstotalen tussen 2026-11-14 en 2026-11-16 |
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
| OK | prijzen.csv | 18 clubs |
| OK | prijzen.csv | vier posities in het Engels |
| OK | prijzen.csv | prijzen in een plausibel bereik |
| OK | prijzen.csv | geen dubbele speler_id |
| OK | prijzen.csv | vijftien goedkoopste spelers kosten 15.00 |
| OK | prijzen.csv | 479 van de 508 prijsrijen koppelt aan een gescrapete speler (94%) |
| OK | versheid | nieuwste gegevens zijn 0 dag(en) oud |
| WAARSCHUWING | versheid | spelers_seizoen.csv loopt achter (2026-11-16 tegen 2026-11-19) |
