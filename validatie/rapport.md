# Validatie ronde 8 (2026-10-04)

Periode 2; periodestart over 1 ronde(n) (venster 1). Dit is meting 2.

## Testsuites

6 van de 6 geslaagd.

- OK `test_workflows.py` — OK: elke workflow installeert wat zijn scripts nodig hebben.
- OK `test_multi_periode.py` — OK: horizon=1 komt in elk geval overeen met de brute-force zoeker.
- OK `test_scrape_prijzen.py` — OK: splits_status() en vind_bijna_match() gedragen zich zoals verwacht.
- OK `test_statistieken.py` — OK: scrape_statistieken.py levert data die het model ongewijzigd kan lezen.
- OK `test_synchroniseer.py` — OK: synchroniseer_selectie.py herkent afwijkingen en weigert half werk.
- OK `test_notify.py` — OK: alles wat het model weet over onbetrouwbare invoer, bereikt de mail.

## Modelkwaliteit

Gemeten over 6 evalueerbare ronde(n).

- **top15_gevangen**: 0.197 (+0.016 sinds vorige meting, beter)
- **rho**: 0.409 (-0.001 sinds vorige meting, slechter)
- **rmse**: 3.304 (-0.097 sinds vorige meting, beter)

`top15_gevangen` is de beslissingsmaat: welk deel van het gat tussen willekeurig en perfect kiezen vangt de top-15 van het model. Dat is wat je in punten merkt; RMSE staat erbij voor de vergelijkbaarheid met eerdere metingen.

## Datadrift

- **markt_grootte**: 509 (-2 sinds vorige meting, slechter)
- **koppelgraad**: 0.898 (+0.011 sinds vorige meting, beter)
- **geblesseerd**: 47 (+7 sinds vorige meting, slechter)

Een sprong in deze drie is meestal geen echte verandering in de competitie maar een scraper die stil iets anders is gaan lezen.

## Wat dit rapport NIET zegt

- De waarheid in de backtest komt uit `spelers.csv` en mist assists, kaarten en keepersreddingen. Elke maat hierboven is dus een ondergrens.
- Met 6 ronde(n) is de onzekerheid groot; een verschil tussen twee metingen is pas een signaal als het zich herhaalt.
- Groene testsuites zeggen dat de code consistent is, niet dat de voorspellingen goed zijn.

