# Validatie ronde 13 (2026-11-22)

Periode 4; ronde 13 IS een periodestart. Dit is meting 9.

## Testsuites

8 van de 8 geslaagd.

- OK `test_workflows.py` — OK: elke workflow installeert wat zijn scripts nodig hebben.
- OK `test_multi_periode.py` — OK: horizon=1 komt in elk geval overeen met de brute-force zoeker.
- OK `test_scrape_prijzen.py` —     zoals verwacht.
- OK `test_statistieken.py` — OK: scrape_statistieken.py levert data die het model ongewijzigd kan lezen.
- OK `test_synchroniseer.py` — OK: synchroniseer_selectie.py herkent afwijkingen en weigert half werk.
- OK `test_notify.py` — OK: alles wat het model weet over onbetrouwbare invoer, bereikt de mail.
- OK `test_valideer.py` — OK: de poortwachter kiest de juiste weken en het rapport oordeelt niet op ruis.
- OK `test_grenzen.py` — OK: de grenzen keuren af wat ze horen af te keuren, en laten de rest door.

## Modelkwaliteit

Gemeten over 11 evalueerbare ronde(n).

- **top15_gevangen**: 0.227 (-0.005 sinds vorige meting, slechter)
- **rho**: 0.331 (+0.002 sinds vorige meting, beter)
- **rmse**: 3.424 (+0.005 sinds vorige meting, slechter)

`top15_gevangen` is de beslissingsmaat: welk deel van het gat tussen willekeurig en perfect kiezen vangt de top-15 van het model. Dat is wat je in punten merkt; RMSE staat erbij voor de vergelijkbaarheid met eerdere metingen.

## Datadrift

- **markt_grootte**: 508 (ongewijzigd sinds vorige meting)
- **koppelgraad**: 0.915 (ongewijzigd sinds vorige meting)
- **geblesseerd**: 43 (-1 sinds vorige meting, beter)

Een sprong in deze drie is meestal geen echte verandering in de competitie maar een scraper die stil iets anders is gaan lezen.

## Wat dit rapport NIET zegt

- De waarheid in de backtest komt uit `spelers.csv` en mist assists, kaarten en keepersreddingen. Elke maat hierboven is dus een ondergrens.
- Met 11 ronde(n) is de onzekerheid groot; een verschil tussen twee metingen is pas een signaal als het zich herhaalt.
- Groene testsuites zeggen dat de code consistent is, niet dat de voorspellingen goed zijn.

