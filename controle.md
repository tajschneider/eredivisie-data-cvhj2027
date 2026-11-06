# Controle scrape — GOED

Uitgevoerd 2026-11-06. 0 fout(en), 0 waarschuwing(en), 30 controles.

## Metingen

| Meting | Waarde |
|---|---|
| afwezigen_clubs | 15 |
| afwezigen_laatste | 53 |
| clubs_eerstvolgende_met_xg | 18 van 18 |
| clubs_eerstvolgende_ronde | 12 |
| clubs_gespeeld_met_xg | 36 van 198 |
| clubs_komend_met_xg | 36 van 36 |
| clubs_met_kansen | 234 |
| clubs_met_xg | 72 |
| clubs_rijen_met_uitslag | 198 |
| clubs_verder_vooruit_met_xg | 18 van 18 |
| clubs_verschillend | 18 |
| clubs_volledige_ronden | 11 |
| dagen_oud | 0 |
| minuten_onzichtbaar_voor_model | 0 |
| nieuwste_ophaaldatum | 2026-11-06 |
| opstellingen_clubs | 18 |
| opstellingen_kansen_verschillend | 0 |
| prijzen_clubs | 18 |
| prijzen_goedkoopste15 | 15.0 |
| prijzen_koppelgraad | 480 van 508 (94%) |
| prijzen_spelers | 508 |
| rijen_afwezigen.csv | 374 |
| rijen_clubs.csv | 612 |
| rijen_opstellingen.csv | 1386 |
| rijen_prijzen.csv | 508 |
| rijen_spelers.csv | 4572 |
| rijen_spelers_seizoen.csv | 3037 |
| ronderijen_ronden | 11 |
| seizoen_dalende_tellers | 0 |
| seizoen_minuten_revisies | 0 |
| seizoen_momentopnamen | 6 |
| seizoen_spelers_laatste | 512 |
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
| OK | clubs.csv | verwachte goals bij 18 van de 18 rijen van ronde 12, de eerstvolgende |
| OK | spelers_seizoen.csv | 512 spelers in de stand van 2026-11-06 |
| OK | spelers_seizoen.csv | 18 clubs |
| OK | spelers_seizoen.csv | tellers intern consistent |
| OK | spelers_seizoen.csv | geen dalende seizoenstotalen tussen 2026-11-02 en 2026-11-06 |
| OK | spelers.csv | geen dubbele ronde/speler/club |
| OK | spelers.csv | geen speeltijd onder een onbekende slug |
| OK | spelers.csv | elke rij heeft een ronde |
| OK | spelers.csv | minuten en productie per ronde plausibel |
| OK | afwezigen.csv | alle redenen bekend |
| OK | afwezigen.csv | terugkeerdatums in ISO-vorm |
| OK | opstellingen.csv | 18 clubs |
| OK | opstellingen.csv | elke club 11 basisspelers |
| OK | opstellingen.csv | basiskansen tussen 0 en 100 |
| OK | opstellingen.csv | basiskansen varieren (0 verschillende waarden over 0 spelers) |
| OK | prijzen.csv | 18 clubs |
| OK | prijzen.csv | vier posities in het Engels |
| OK | prijzen.csv | prijzen in een plausibel bereik |
| OK | prijzen.csv | geen dubbele speler_id |
| OK | prijzen.csv | vijftien goedkoopste spelers kosten 15.00 |
| OK | prijzen.csv | 480 van de 508 prijsrijen koppelt aan een gescrapete speler (94%) |
| OK | versheid | nieuwste gegevens zijn 0 dag(en) oud |
