# Controle scrape — MET WAARSCHUWINGEN

Uitgevoerd 2026-10-23. 0 fout(en), 1 waarschuwing(en), 26 controles.

## Waarschuwingen

- **spelers.csv** — geen ronderijen terwijl er wel twee seizoensstanden zijn  
  het verschil tussen de twee standen leverde niets op

## Metingen

| Meting | Waarde |
|---|---|
| afwezigen_clubs | 16 |
| afwezigen_laatste | 59 |
| clubs_eerstvolgende_met_xg | 18 van 18 |
| clubs_eerstvolgende_ronde | 10 |
| clubs_gespeeld_met_xg | 0 van 162 |
| clubs_komend_met_xg | 36 van 36 |
| clubs_met_kansen | 198 |
| clubs_met_xg | 36 |
| clubs_rijen_met_uitslag | 162 |
| clubs_verder_vooruit_met_xg | 18 van 18 |
| clubs_verschillend | 18 |
| clubs_volledige_ronden | 9 |
| dagen_oud | 0 |
| nieuwste_ophaaldatum | 2026-10-23 |
| opstellingen_clubs | 18 |
| prijzen_clubs | 18 |
| prijzen_goedkoopste15 | 15.0 |
| prijzen_koppelgraad | 477 van 507 (94%) |
| prijzen_spelers | 507 |
| rijen_afwezigen.csv | 109 |
| rijen_clubs.csv | 612 |
| rijen_opstellingen.csv | 396 |
| rijen_prijzen.csv | 507 |
| rijen_spelers.csv | 0 |
| rijen_spelers_seizoen.csv | 1009 |
| seizoen_dalende_tellers | 0 |
| seizoen_momentopnamen | 2 |
| seizoen_spelers_laatste | 505 |

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
| OK | clubs.csv | verwachte goals bij 18 van de 18 rijen van ronde 10, de eerstvolgende |
| OK | spelers_seizoen.csv | 505 spelers in de stand van 2026-10-23 |
| OK | spelers_seizoen.csv | 18 clubs |
| OK | spelers_seizoen.csv | tellers intern consistent |
| OK | spelers_seizoen.csv | geen dalende seizoenstotalen tussen 2026-10-19 en 2026-10-23 |
| WAARSCHUWING | spelers.csv | geen ronderijen terwijl er wel twee seizoensstanden zijn |
| OK | afwezigen.csv | alle redenen bekend |
| OK | afwezigen.csv | terugkeerdatums in ISO-vorm |
| OK | opstellingen.csv | 18 clubs |
| OK | opstellingen.csv | elke club 11 basisspelers |
| OK | opstellingen.csv | basiskansen tussen 0 en 100 |
| OK | prijzen.csv | 18 clubs |
| OK | prijzen.csv | vier posities in het Engels |
| OK | prijzen.csv | prijzen in een plausibel bereik |
| OK | prijzen.csv | geen dubbele speler_id |
| OK | prijzen.csv | vijftien goedkoopste spelers kosten 15.00 |
| OK | prijzen.csv | 477 van de 507 prijsrijen koppelt aan een gescrapete speler (94%) |
| OK | versheid | nieuwste gegevens zijn 0 dag(en) oud |
