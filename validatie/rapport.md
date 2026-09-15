# Validatie ronde 7 (2026-09-15)

Periode 2; volgende periodestart pas over 2 ronden (venster 1). Dit is meting 1.

## Testsuites

6 van de 6 geslaagd.

- OK `test_workflows.py` — OK: elke workflow installeert wat zijn scripts nodig hebben.
- OK `test_multi_periode.py` — OK: horizon=1 komt in elk geval overeen met de brute-force zoeker.
- OK `test_scrape_prijzen.py` — OK: splits_status() en vind_bijna_match() gedragen zich zoals verwacht.
- OK `test_statistieken.py` — OK: scrape_statistieken.py levert data die het model ongewijzigd kan lezen.
- OK `test_synchroniseer.py` — OK: synchroniseer_selectie.py herkent afwijkingen en weigert half werk.
- OK `test_notify.py` — OK: alles wat het model weet over onbetrouwbare invoer, bereikt de mail.

## Modelkwaliteit

Gemeten over 5 evalueerbare ronde(n).

- **top15_gevangen**: 0.181 (eerste meting)
- **rho**: 0.410 (eerste meting)
- **rmse**: 3.401 (eerste meting)

`top15_gevangen` is de beslissingsmaat: welk deel van het gat tussen willekeurig en perfect kiezen vangt de top-15 van het model. Dat is wat je in punten merkt; RMSE staat erbij voor de vergelijkbaarheid met eerdere metingen.

## Datadrift

- **markt_grootte**: 511 (eerste meting)
- **koppelgraad**: 0.886 (eerste meting)
- **geblesseerd**: 40 (eerste meting)

Een sprong in deze drie is meestal geen echte verandering in de competitie maar een scraper die stil iets anders is gaan lezen.

## Wat dit rapport NIET zegt

- De waarheid in de backtest komt uit `spelers.csv` en mist assists, kaarten en keepersreddingen. Elke maat hierboven is dus een ondergrens.
- Met 5 ronde(n) is de onzekerheid groot; een verschil tussen twee metingen is pas een signaal als het zich herhaalt.
- Groene testsuites zeggen dat de code consistent is, niet dat de voorspellingen goed zijn.

