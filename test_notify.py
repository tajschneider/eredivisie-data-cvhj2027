#!/usr/bin/env python3
"""
Regressietest voor notify.py -- zonder netwerk, zonder SMTP.

Waarom dit bestand er is. notify.py bepaalt als enige wat je werkelijk ziet:
je leest de mail, niet het Actions-log. Toch was dit het enige script zonder
een enkele test, en de validatie van 13 september liet zien wat dat kost --
vier gevallen waarin een stap omviel, het model doordraaide op oudere data,
en de mail er volstrekt normaal uitzag:

  - de selectie-synchronisatie mislukte (dat gebeurde live op 12 september);
  - selectie.csv of programma.csv ontbrak en er is teruggevallen op de
    hardgecodeerde waarden uit september;
  - spelerstats.csv was weken oud of kwam uit het dode xg.csv;
  - de regressietest faalde, dus het advies kwam uit de eenronde-zoeker.

Plus een vijfde: blessures in je eigen ploeg stonden wél in besluit.json en
werden nergens gerenderd.

Deze test toetst precies één ding, maar dan voor al die gevallen: wat in de
JSON staat, moet in de tekst terechtkomen. Een waarschuwing die het model
netjes uitrekent en die jou niet bereikt, is geen waarschuwing.

    python test_notify.py
"""
import sys

import notify

# Een normaal besluit, zoals multi_periode.py het schrijft. Bewust compleet:
# elke test hieronder verandert er één ding aan, zodat een verschil in de
# uitvoer alleen door dát ene ding kan komen.
GOED = {
    "ronde": 6,
    "gegenereerd": "2026-09-13T07:00:00",
    "model": "multi_periode",
    "bron_programma": "bestand",
    "bron_selectie": "bestand",
    "stats_bron": {"bestand": "spelerstats.csv", "leeftijd_dagen": 0.4},
    "transfers_toegestaan": 1,
    "pool_grootte": 247,
    "programma": [{"thuis": "Ajax", "uit": "PSV"}] * 9,
    "huidig": {
        "verwacht": 47.8, "kosten": 29.85,
        "basis": [{"pos": "V", "speler": "Jeff Hardeveld", "club": "Telstar", "E": 3.1}],
        "bank": [{"pos": "A", "speler": "David Min", "club": "FC Utrecht", "E": 0.0}],
    },
    "advies": {
        "verwacht": 50.7, "winst": 2.9, "formatie": "4-3-3",
        "uit": [{"speler": "Oscar Gloukh", "club": "Ajax", "pos": "M",
                 "prijs": 2.8, "E": 2.96}],
        "in": [{"speler": "Abdellah Ouazane", "club": "Ajax", "pos": "M",
                "prijs": 1.5, "E": 4.35}],
    },
}


def met(**wijziging):
    d = {k: (dict(v) if isinstance(v, dict) else v) for k, v in GOED.items()}
    d.update(wijziging)
    return d


def toont(d, fragment):
    return fragment.lower() in notify.bouw_tekst(d).lower()


def test_normaal_geen_valse_alarmen():
    """Het gewone geval mag geen enkele waarschuwing opleveren.

    Dit staat er eerst en met opzet: een controle die bij normale invoer al
    piept, leer je binnen twee weken negeren, en dan vangt hij de echte
    gevallen ook niet meer.
    """
    w = notify.blokkerende_waarschuwingen(GOED)
    goed = w == []
    print(f"  {'OK  ' if goed else 'FOUT'} normaal besluit -> geen waarschuwingen "
          f"({w if w else 'leeg'})")
    return goed


def test_waarschuwingen_bereiken_de_tekst():
    gevallen = [
        ("terugval naar de eenronde-zoeker",
         met(model="cvhj_model (eenronde-terugval)"), "terugval"),
        ("selectie.csv ontbrak",
         met(bron_selectie="hardgecodeerd"), "selectie.csv ontbrak"),
        ("programma.csv ontbrak",
         met(bron_programma="hardgecodeerd"), "programma.csv ontbrak"),
        ("synchronisatie mislukt",
         met(sync_gelukt=False), "niet gecontroleerd"),
        ("statistieken uit een dode bron",
         met(stats_bron={"bestand": "xg.csv", "leeftijd_dagen": 1.0}), "xg.csv"),
        ("statistieken te oud",
         met(stats_bron={"bestand": "spelerstats.csv", "leeftijd_dagen": 21.0}), "21"),
    ]
    ok = True
    for wat, d, fragment in gevallen:
        goed = toont(d, fragment)
        print(f"  {'OK  ' if goed else 'FOUT'} {wat}: {fragment!r} staat in de mail")
        ok = ok and goed
    return ok


def test_waarschuwing_staat_voor_het_advies():
    """Een waarschuwing ná het advies lees je pas als je je mening al hebt."""
    tekst = notify.bouw_tekst(met(sync_gelukt=False))
    plek_waarschuwing = tekst.lower().find("niet gecontroleerd")
    plek_advies = tekst.find("ADVIES")
    goed = 0 <= plek_waarschuwing < plek_advies
    print(f"  {'OK  ' if goed else 'FOUT'} waarschuwing op positie {plek_waarschuwing}, "
          f"advies op {plek_advies}")
    return goed


def test_blessures_in_de_mail():
    """geblesseerd_in_selectie stond in besluit.json en werd nergens gerenderd.

    Je las alleen "Zonder recente speeltijd (E=0)", wat als vormprobleem oogt,
    terwijl het model de blessure gewoon kende.
    """
    d = met(geblesseerd_in_selectie=[{"speler": "Deveron Fonville", "duur": "tot januari"}])
    tekst = notify.bouw_tekst(d)
    goed = "Fonville" in tekst and "tot januari" in tekst and "GEBLESSEERD" in tekst
    print(f"  {'OK  ' if goed else 'FOUT'} blessure met duur staat in de AANDACHT-lijst")
    return goed


def test_onderwerp_vlagt_de_terugval():
    """Het onderwerp is het enige dat je zeker ziet, ook op je telefoon."""
    schoon = notify.blokkerende_waarschuwingen(GOED)
    vies = notify.blokkerende_waarschuwingen(met(bron_selectie="hardgecodeerd"))
    goed = not schoon and bool(vies)
    print(f"  {'OK  ' if goed else 'FOUT'} de vlag voor het onderwerp staat aan bij "
          f"terugval en uit bij een normaal besluit")
    return goed


def test_zonder_advies():
    """Een besluit zonder transfer mag niet crashen op ontbrekende velden."""
    d = met(advies=None)
    try:
        tekst = notify.bouw_tekst(d)
    except Exception as e:                                   # noqa: BLE001
        print(f"  FOUT bouw_tekst() valt om zonder advies: {type(e).__name__}: {e}")
        return False
    goed = "Geen transfer geadviseerd" in tekst
    print(f"  {'OK  ' if goed else 'FOUT'} besluit zonder transfer levert leesbare tekst")
    return goed


def main():
    print("geen vals alarm bij normale invoer\n")
    ok1 = test_normaal_geen_valse_alarmen()

    print("\nwaarschuwingen uit besluit.json halen de mail\n")
    ok2 = test_waarschuwingen_bereiken_de_tekst()
    ok3 = test_waarschuwing_staat_voor_het_advies()
    ok4 = test_onderwerp_vlagt_de_terugval()

    print("\nblessures en randgevallen\n")
    ok5 = test_blessures_in_de_mail()
    ok6 = test_zonder_advies()

    print()
    if all([ok1, ok2, ok3, ok4, ok5, ok6]):
        print("OK: alles wat het model weet over onbetrouwbare invoer, bereikt de mail.")
    else:
        sys.exit("MISLUKT: zie hierboven -- een waarschuwing die jou niet bereikt, "
                 "is geen waarschuwing.")


if __name__ == "__main__":
    main()
