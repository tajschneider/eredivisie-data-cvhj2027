# Controle scrape — MET WAARSCHUWINGEN

Uitgevoerd 2026-10-19. 0 fout(en), 3 waarschuwing(en), 21 controles.

## Waarschuwingen

- **clubs.csv** — verwachte goals bij 0 van de 18 rijen verder vooruit dan ronde 10  
  normaal: de bron vult ze per wedstrijd aan naarmate de ronde nadert
- **spelers.csv** — bestand ontbreekt
- **spelers.csv** — nog geen ronderijen  
  normaal na de eerste run; het verschil tussen twee seizoensstanden bestaat dan nog niet

## Metingen

| Meting | Waarde |
|---|---|
| afwezigen_clubs | 15 |
| afwezigen_laatste | 50 |
| clubs_eerstvolgende_met_xg | 18 van 18 |
| clubs_eerstvolgende_ronde | 10 |
| clubs_gespeeld_met_xg | 0 van 162 |
| clubs_komend_met_xg | 18 van 36 |
| clubs_met_kansen | 198 |
| clubs_met_xg | 18 |
| clubs_rijen_met_uitslag | 162 |
| clubs_verder_vooruit_met_xg | 0 van 18 |
| clubs_verschillend | 18 |
| clubs_volledige_ronden | 9 |
| dagen_oud | 0 |
| nieuwste_ophaaldatum | 2026-10-19 |
| opstellingen_clubs | 18 |
| rijen_afwezigen.csv | 50 |
| rijen_clubs.csv | 612 |
| rijen_opstellingen.csv | 198 |
| rijen_spelers_seizoen.csv | 504 |
| seizoen_momentopnamen | 1 |
| seizoen_spelers_laatste | 504 |

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
| WAARSCHUWING | clubs.csv | verwachte goals bij 0 van de 18 rijen verder vooruit dan ronde 10 |
| OK | spelers_seizoen.csv | 504 spelers in de stand van 2026-10-19 |
| OK | spelers_seizoen.csv | 18 clubs |
| OK | spelers_seizoen.csv | tellers intern consistent |
| WAARSCHUWING | spelers.csv | bestand ontbreekt |
| WAARSCHUWING | spelers.csv | nog geen ronderijen |
| OK | afwezigen.csv | alle redenen bekend |
| OK | afwezigen.csv | terugkeerdatums in ISO-vorm |
| OK | opstellingen.csv | 18 clubs |
| OK | opstellingen.csv | elke club 11 basisspelers |
| OK | opstellingen.csv | basiskansen tussen 0 en 100 |
| OK | versheid | nieuwste gegevens zijn 0 dag(en) oud |
