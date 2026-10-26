# Controle scrape — GEFAALD

Uitgevoerd 2026-10-26. 1 fout(en), 0 waarschuwing(en), 28 controles.

## Fouten

- **spelers_seizoen.csv** — geen dalende seizoenstotalen tussen 2026-10-23 en 2026-10-26  
  lasse-wilhelm.minuten: 63 -> 62; jan-zamburek.minuten: 219 -> 218; matej-sin.goals: 1 -> 0 — een teller kan niet omlaag; waarschijnlijk is er een parser stuk of een speler van club gewisseld

## Metingen

| Meting | Waarde |
|---|---|
| afwezigen_clubs | 16 |
| afwezigen_laatste | 56 |
| clubs_eerstvolgende_met_xg | 18 van 18 |
| clubs_eerstvolgende_ronde | 11 |
| clubs_gespeeld_met_xg | 18 van 180 |
| clubs_komend_met_xg | 36 van 36 |
| clubs_met_kansen | 216 |
| clubs_met_xg | 54 |
| clubs_rijen_met_uitslag | 180 |
| clubs_verder_vooruit_met_xg | 18 van 18 |
| clubs_verschillend | 18 |
| clubs_volledige_ronden | 10 |
| dagen_oud | 0 |
| nieuwste_ophaaldatum | 2026-10-26 |
| opstellingen_clubs | 18 |
| prijzen_clubs | 18 |
| prijzen_goedkoopste15 | 15.0 |
| prijzen_koppelgraad | 476 van 507 (94%) |
| prijzen_spelers | 507 |
| rijen_afwezigen.csv | 165 |
| rijen_clubs.csv | 612 |
| rijen_opstellingen.csv | 594 |
| rijen_prijzen.csv | 507 |
| rijen_spelers.csv | 4350 |
| rijen_spelers_seizoen.csv | 1515 |
| ronderijen_ronden | 10 |
| seizoen_dalende_tellers | 3 |
| seizoen_momentopnamen | 3 |
| seizoen_spelers_laatste | 506 |

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
| OK | clubs.csv | verwachte goals bij 18 van de 18 rijen van ronde 11, de eerstvolgende |
| OK | spelers_seizoen.csv | 506 spelers in de stand van 2026-10-26 |
| OK | spelers_seizoen.csv | 18 clubs |
| OK | spelers_seizoen.csv | tellers intern consistent |
| FOUT | spelers_seizoen.csv | geen dalende seizoenstotalen tussen 2026-10-23 en 2026-10-26 |
| OK | spelers.csv | geen dubbele ronde/speler/club |
| OK | spelers.csv | elke rij heeft een ronde |
| OK | spelers.csv | minuten en productie per ronde plausibel |
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
| OK | prijzen.csv | 476 van de 507 prijsrijen koppelt aan een gescrapete speler (94%) |
| OK | versheid | nieuwste gegevens zijn 0 dag(en) oud |
