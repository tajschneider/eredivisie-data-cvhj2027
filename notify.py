#!/usr/bin/env python3
"""
besluit.json -> e-mail met het transferadvies van de week.

Gebruik:
    python notify.py besluit.json                 # verstuurt
    python notify.py besluit.json --toon          # alleen afdrukken, niets sturen

Secrets (GitHub Actions -> Settings -> Secrets and variables -> Actions):
    SMTP_HOST      bv. smtp.gmail.com
    SMTP_POORT     bv. 587
    SMTP_USER      afzenderadres
    SMTP_WACHTWOORD  app-wachtwoord (NIET je gewone wachtwoord)
    MAIL_NAAR      ontvanger

De mail is bewust kort: het besluit, de winst, en waar het model onzeker is.
De onderbouwing staat in de JSON die als bijlage meegaat.
"""
import argparse
import json
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path


def regel(x):
    return f"{x['speler']} ({x['club']}, {x['pos']}) EUR {x['prijs']:.2f}"


def opstellingsblok(kop, basis, bank, bank_kop="Bank (50%)"):
    """Eén opstelling onder een kop die zegt WELKE ploeg je ziet.

    Dit is een eigen functie geworden omdat de mail twee opstellingen moet
    kunnen tonen -- die van je huidige ploeg en die van de ploeg na de
    geadviseerde transfers -- en ze alleen te onderscheiden zijn aan hun kop.
    Zolang er één blok was met de vaste kop "OPSTELLING (basis)", gevuld uit
    besluit["huidig"], kon de mail je drie spelers laten verkopen en ze twintig
    regels lager doodgemoedereerd opstellen (gemeld 16 oktober 2026).

    De regelopmaak is ongewijzigd, zodat bestaande mails er hetzelfde uitzien.
    """
    r = ["", kop]
    for x in sorted(basis, key=lambda x: -x["E"]):
        r.append(f"  {x['pos']}  {x['speler']:26s} {x['club']:18s} E {x['E']:.2f}")
    r += ["", bank_kop]
    for x in sorted(bank, key=lambda x: -x["E"]):
        r.append(f"  {x['pos']}  {x['speler']:26s} {x['club']:18s} E {x['E']:.2f}")
    return r


def transferblok(d):
    """Wat er met je transfertegoed is gebeurd, en wat elke stap opleverde.

    multi_periode.py schrijft `transfers_beschikbaar`, `transfer_drempel` en de
    volledige `transferladder` naar besluit.json, maar de mail gebruikte daar
    niets van: je zag alleen `transfers_toegestaan`, en dat staat in die JSON
    al op het aantal DAADWERKELIJK gebruikte transfers. Werd er een transfer
    bewaard omdat de volgende te weinig opleverde, dan was dat in je inbox niet
    te zien. De informatie bestond, kwam alleen niet aan -- dezelfde blinde
    vlek als de opstelling die je verkochte spelers toonde.

    cvhj_model.py's besluit.json heeft deze velden niet. Dan geeft deze functie
    een lege lijst terug en blijft de mail precies zoals hij was.
    """
    gebruikt = d.get("transfers_toegestaan")
    beschikbaar = d.get("transfers_beschikbaar")
    ladder = d.get("transferladder") or []
    if beschikbaar is None and not ladder:
        return []

    r = []
    if beschikbaar is not None and gebruikt is not None and beschikbaar > gebruikt:
        drempel = d.get("transfer_drempel")
        reden = (f", want de volgende leverde minder dan de drempel van "
                 f"{drempel:.2f} punt op") if drempel else ""
        r.append(f"  TEGOED: {gebruikt} van je {beschikbaar} transfer(s) gebruikt, "
                 f"{beschikbaar - gebruikt} bewaard{reden}.")

    if ladder:
        # De laddergetallen staan in de GEDECAYDE HORIZON-SOM, niet in de punten
        # voor de eerstvolgende ronde waar "verwacht" en "winst" hierboven over
        # gaan. Die eenheid hier benoemen: twee grootheden op elkaar laten
        # lijken is precies waar multi_periode.py's eigen docstring voor
        # waarschuwt (waardeer_horizon), en dat is hier een reeks naast elkaar.
        r += ["", "  WAT ELKE TRANSFER OPLEVERT (gedecayde som over de horizon,",
              "   niet de punten van de komende ronde)"]
        for stap in ladder:
            k, score = stap.get("transfers"), stap.get("score")
            if k is None or score is None:
                continue
            marge = stap.get("marginale_winst") or 0.0
            merk = "" if not k else f"   {marge:+.2f} t.o.v. {k - 1}"
            keuze = "   <- gekozen" if k == gebruikt else ""
            r.append(f"    {k} transfer(s): {score:7.2f}{merk}{keuze}")

        # Alle transfers gebruikt, maar een van de stappen was mager: dan is er
        # iets te kiezen dat je anders niet ziet. multi_periode.py meldt dit op
        # de terminal; die melding hoort ook in de mail.
        mager = [s["transfers"] for s in ladder[1:]
                 if s.get("transfers") is not None
                 and gebruikt is not None and s["transfers"] <= gebruikt
                 and (s.get("marginale_winst") or 0.0) < 0.5]
        if mager:
            r.append(f"    LET OP: transfer {', '.join(str(k) for k in mager)} "
                     f"levert minder dan 0,5 punt op. Met een hogere "
                     f"--transfer-drempel zou je die bewaren.")
    return r


def blokkerende_waarschuwingen(d):
    """Alles wat het advies onbetrouwbaar maakt, bovenaan de mail.

    Dit bestand bepaalt als enige wat jij werkelijk ziet: je leest het advies,
    niet het Actions-log. Alles wat alleen in dat log stond, bestond dus in de
    praktijk niet. Uit de validatie van 13 september kwamen vier van die
    gevallen, allemaal met dezelfde vorm -- een stap valt om, het model draait
    door op oudere data, en de mail ziet er volkomen normaal uit:

      - de selectie-synchronisatie mislukte (login om, secrets verlopen), dus
        het advies rust op de selectie.csv van vorige week -- en adviseert je
        mogelijk een speler te verkopen die je al niet meer hebt;
      - selectie.csv of programma.csv ontbrak en er is teruggevallen op de
        hardgecodeerde ploeg/fixtures uit september;
      - spelerstats.csv was oud, of kwam uit xg.csv/fbref.csv -- bronnen die
        sinds januari 2026 dood zijn;
      - de regressietest faalde, dus het advies komt uit de eenronde-zoeker en
        niet uit het multi-ronde-model.

    Alles wat hier terechtkomt, komt vóór het advies te staan. Niet in de
    AANDACHT-lijst onderaan: die lees je nadat je je mening al gevormd hebt.
    """
    w = []
    if d.get("model") and d["model"] != "multi_periode":
        w.append(f"### TERUGVAL: dit advies komt uit {d['model']}, niet uit het "
                 f"multi-ronde-model ###")
    for veld, wat in (("bron_selectie", "selectie.csv"), ("bron_programma", "programma.csv")):
        if d.get(veld) == "hardgecodeerd":
            w.append(f"### {wat.upper()} ONTBRAK -- gerekend met de hardgecodeerde "
                     f"noodwaarden uit september. Dit advies is niet bruikbaar. ###")
    if d.get("sync_gelukt") is False:
        w.append("### SELECTIE NIET GECONTROLEERD tegen coachvanhetjaar.nl "
                 "(synchronisatie mislukt) -- het advies gebruikt selectie.csv "
                 "zoals die in de repo staat. Controleer of dat nog jouw ploeg is. ###")
    # Afwezigen: dezelfde vorm als de vier gevallen hierboven. De scrape van de
    # opstellingspagina's valt om, het model rekent door met alleen de
    # blessurevlag uit prijzen.csv, en de mail ziet er normaal uit -- terwijl
    # het advies je een geschorste speler kan laten kopen. Een ONTBREKEND veld
    # is hier bewust geen waarschuwing: een besluit.json van voor deze
    # toevoeging weet niets van afwezigen, en dat is iets anders dan een
    # mislukte scrape. Alleen wat het veld werkelijk zegt, telt.
    afw = d.get("bron_afwezigen") or {}
    if afw.get("status") == "ontbreekt":
        w.append("### AFWEZIGEN NIET GESCRAPET -- alleen de blessurevlag uit "
                 "prijzen.csv sluit nog spelers uit, en schorsingen staan daar "
                 "niet in. Controleer de IN-namen zelf voordat je ze inlegt. ###")
    elif afw.get("status") == "verouderd":
        w.append(f"### AFWEZIGENLIJST IS VAN {afw.get('opgehaald') or 'onbekende datum'} "
                 f"-- spelers die sindsdien hersteld zijn, zijn nu onterecht uit de "
                 f"pool gehouden. Het advies kan daardoor een betere transfer missen. ###")
    stats = d.get("stats_bron") or {}
    if stats.get("bestand") and stats["bestand"] != "spelerstats.csv":
        w.append(f"### STATISTIEKEN uit {stats['bestand']} -- een oude bestandsnaam "
                 f"van een bron die niet meer bestaat. Assists en kaarten zijn verouderd. ###")
    elif stats.get("leeftijd_dagen") is not None and stats["leeftijd_dagen"] > 8:
        w.append(f"### STATISTIEKEN zijn {stats['leeftijd_dagen']} dagen oud "
                 f"(scrape waarschijnlijk mislukt). ###")
    return w


def bouw_tekst(d):
    r = [f"CVHJ ronde {d['ronde']} - gegenereerd {d['gegenereerd']}", ""]

    # Een periodestart is de enige week waarin je drie transfers hebt. Die
    # bovenaan zetten, niet onderin bij de voetnoten.
    if d.get("periodestart"):
        r += [f"### PERIODE {d['periode']} BEGINT - JE MAG 3 TRANSFERS DOEN ###",
              "Deze ronde is de enige in deze periode met drie wissels.", ""]
    elif d.get("ronden_tot_volgende_periode") == 1:
        r += ["### VOLGENDE RONDE BEGINT EEN NIEUWE PERIODE (3 transfers) ###",
              "Een transfer deze week bewaren kan lonen: volgende week heb je er drie.", ""]

    # Vermoedelijke naam-vervuiling in prijzen.csv (zie cvhj_model.vind_bijna_match) is
    # automatisch gerepareerd, maar hoort bovenaan te staan -- dit wijst op een
    # scraper-bug die de moeite waard is om na te kijken, ook al is het advies
    # hieronder er niet meer door verstoord.
    if d.get("bijna_match"):
        r += ["### LET OP: MOGELIJKE NAAM-BUG IN prijzen.csv (automatisch gerepareerd) ###"]
        for x in d["bijna_match"]:
            r.append(f"  '{x['selectie']}' (jouw selectie) <-> '{x['marktdata']}' (marktdata, zelfde club)")
        r += ["  Dit advies is hierop gecorrigeerd, maar controleer de brondata."]
        r.append("")

    for regel_tekst in blokkerende_waarschuwingen(d):
        r.append(regel_tekst)
    if blokkerende_waarschuwingen(d):
        r.append("")

    h = d["huidig"]
    r.append(f"Huidig team: {h['verwacht']:.1f} verwachte punten, kosten EUR {h['kosten']:.2f}")

    a = d.get("advies")
    if not a:
        r += ["", "Geen transfer geadviseerd (of --transfers 0 gedraaid)."]
    else:
        r += ["", f"ADVIES ({d['transfers_toegestaan']} transfer(s)) "
                  f"-> {a['verwacht']:.1f} punten, winst {a['winst']:+.1f}, formatie {a['formatie']}", ""]
        for x in a["uit"]:
            r.append(f"  UIT  {regel(x)}  E {x['E']:.2f}")
        for x in a["in"]:
            r.append(f"  IN   {regel(x)}  E {x['E']:.2f}")

        # Een winst onder ~1 punt valt weg tegen de modelonzekerheid; dan is
        # niets doen verdedigbaar. Expliciet melden, niet stilzwijgend adviseren.
        if a["winst"] < 1.0:
            r += ["", "  LET OP: winst < 1,0 punt. Dat is binnen de ruis van het "
                      "model; niets doen is hier even verdedigbaar."]

    # multi_periode.py schrijft dezelfde besluit.json-vorm, met een paar extra
    # velden. "verwacht"/"winst" hierboven blijven altijd de eerstvolgende
    # ronde -- dit meldt er alleen bij hoeveel verder vooruit is gekeken.
    if d.get("multi_ronde") and d.get("horizon", 1) > 1:
        r += ["", f"  (gekozen met een horizon van {d['horizon']} ronden "
                  f"{d.get('horizon_rondes', '')}, decay {d.get('decay')}; "
                  f"gedecayde som over die ronden: {d.get('verwacht_horizon')})"]

    # Hoeveel van je tegoed is gebruikt, en wat elke transfer opleverde. Staat
    # hier en niet in AANDACHT onderaan: een bewaarde transfer is onderdeel van
    # het besluit, geen voetnoot erbij.
    transfers = transferblok(d)
    if transfers:
        r += [""] + transfers

    # DE OPSTELLING WAAR JE NAAR HANDELT.
    #
    # Hier stond onvoorwaardelijk de opstelling van je HUIDIGE ploeg
    # (besluit["huidig"]), onder de kop "OPSTELLING (basis)" -- ook als het
    # advies een paar regels hoger net drie van die spelers had verkocht. Dat
    # leverde een mail op die zichzelf tegensprak: "UIT Jeff Hardeveld", en
    # verderop Hardeveld in de basis, met de formatie van NA de transfers
    # erboven. De juiste opstelling werd wel berekend, maar stond niet in
    # besluit.json; sinds multi_periode.py/cvhj_model.py `advies.basis` en
    # `advies.bank` meeschrijven, staat hij er wel en leest deze functie hem.
    #
    # De terugval is met opzet luid. Een oudere besluit.json (uit historie/, of
    # uit een versie van voor die wijziging) heeft die velden niet. Dan is het
    # eerlijker om te zeggen dat je naar de ploeg VOOR de transfers kijkt dan om
    # hem stilzwijgend als "de opstelling" te presenteren -- dat stilzwijgen was
    # precies de fout.
    advies_basis = (a or {}).get("basis")
    advies_bank = (a or {}).get("bank")
    if a and advies_basis is not None and advies_bank is not None:
        r += opstellingsblok(
            f"OPSTELLING NA DE GEADVISEERDE TRANSFERS (dit opstellen) - "
            f"{a['formatie']}, verwacht {a['verwacht']:.1f}",
            advies_basis, advies_bank, bank_kop="Bank na de transfers (50%)")
        r += opstellingsblok(
            f"Je ploeg NU, zonder transfers - verwacht {h['verwacht']:.1f}",
            h["basis"], h["bank"], bank_kop="Bank nu (50%)")
    elif a:
        r += opstellingsblok(
            "OPSTELLING VAN JE PLOEG VOOR DE TRANSFERS -- LET OP: dit is NIET de "
            "ploeg die het advies hierboven oplevert",
            h["basis"], h["bank"])
        r += ["", "  (besluit.json bevat geen advies.basis/advies.bank; draai het "
                  "advies opnieuw met de huidige multi_periode.py of cvhj_model.py "
                  "om hier de juiste opstelling te krijgen.)"]
    else:
        # Geen transferadvies: je huidige ploeg IS de ploeg die je opstelt.
        r += opstellingsblok("OPSTELLING (basis)", h["basis"], h["bank"])

    aandacht = []
    # Blessures eerst. Het model kent ze (beide zoekers zetten
    # geblesseerd_in_selectie in besluit.json en filteren geblesseerden uit de
    # markt), maar dit bestand gebruikte dat veld niet -- je las alleen
    # "Zonder recente speeltijd (E=0)", wat als vormprobleem oogt. De vaste
    # regel over blessurenieuws versterkte de indruk dat er niets bekend was.
    for x in d.get("geblesseerd_in_selectie", []):
        duur = f" ({x['duur']})" if x.get("duur") else ""
        aandacht.append(f"GEBLESSEERD in je ploeg: {x['speler']}{duur}")
    for x in d.get("afwezig_in_selectie", []):
        terug = f", terug {x['terug']}" if x.get("terug") else ""
        aandacht.append(f"AFWEZIG in je ploeg: {x['speler']} ({x.get('reden') or 'reden onbekend'}"
                        f"{terug}) -- hij staat op E=0, dus de zoeker wil hem eruit.")
    # Wie zijn basisplaats lijkt te zijn verloren. Dit is het ENIGE wat de
    # opstellingsbron doet: de verwachte punten rekenen er niet mee, omdat het
    # percentage van die bron geen kans is (zie cvhj_model.lees_opstellingen()).
    # Juist daarom moet het hier staan -- een signaal dat niet in een getal zit,
    # bestaat alleen als jij het leest.
    for x in d.get("buiten_vermoedelijke_elf", []):
        aandacht.append(f"NIET IN DE VERMOEDELIJKE ELF: {x['speler']} ({x.get('club', '?')}) "
                        f"begon {x.get('basis', '?')}/{x.get('duels', '?')} recent. "
                        f"De verwachting rekent hier NIET mee.")
    # Geen statistiekenbestand is geen storing (het model draait dan zoals vóór
    # stap 5), maar je hoort te weten dat assists en kaarten ontbreken -- niet
    # alleen in het log.
    if (d.get("stats_bron") or {}).get("bestand") is None:
        aandacht.append("Geen spelerstats.csv: assists en kaarten zitten NIET in deze "
                        "schatting.")
    if d.get("zonder_speeltijd"):
        aandacht.append(f"Zonder recente speeltijd (E=0): {', '.join(d['zonder_speeltijd'])}")
    if d.get("inhaal"):
        aandacht.append(f"Inhaalduels meegerekend voor: {', '.join(d['inhaal'])}")
    if len(d.get("programma", [])) != 9:
        aandacht.append(f"Programma bevat {len(d.get('programma', []))} wedstrijden, verwacht 9")
    aandacht.append("Blessurenieuws van vandaag zit NIET in het model - "
                    "loop de basisopstelling na voor de deadline.")
    if d.get("periode") and not d.get("periodestart"):
        n = d.get("ronden_tot_volgende_periode")
        if n:
            aandacht.append(f"Periode {d['periode']}; volgende periodestart over {n} ronden.")
    r += ["", "AANDACHT"] + [f"  - {x}" for x in aandacht]
    r += ["", f"Pool: {d['pool_grootte']} spelers met voldoende speeltijd."]
    return "\n".join(r)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("besluit", help="pad naar besluit.json")
    p.add_argument("--toon", action="store_true", help="alleen afdrukken")
    args = p.parse_args()

    d = json.loads(Path(args.besluit).read_text(encoding="utf-8"))
    # Of de selectie-synchronisatie lukte weet alleen de workflow (die stap
    # draait met continue-on-error). Hij geeft het door als env-variabele,
    # zodat het besluit.json-formaat niet van de workflow hoeft te weten.
    if os.environ.get("SYNC_GELUKT"):
        d["sync_gelukt"] = os.environ["SYNC_GELUKT"].strip().lower() in ("ja", "yes", "true", "1")
    tekst = bouw_tekst(d)

    if args.toon:
        print(tekst)
        return

    ontbreekt = [k for k in ("SMTP_HOST", "SMTP_USER", "SMTP_WACHTWOORD", "MAIL_NAAR")
                 if not os.environ.get(k)]
    if ontbreekt:
        print(tekst)
        sys.exit(f"\nFOUT: ontbrekende secrets: {', '.join(ontbreekt)}")

    a = d.get("advies")
    # Een bewaarde transfer hoort in het onderwerp: dat is het enige dat je op
    # je telefoon zeker ziet, en "2 van 3" is een ander bericht dan "2".
    if a:
        _gebruikt = len(a["uit"])
        _besch = d.get("transfers_beschikbaar")
        _van = f" van {_besch}" if _besch is not None and _besch > _gebruikt else ""
        kern = f"{_gebruikt}{_van} transfer(s), {a['winst']:+.1f} punt"
    else:
        kern = "alleen opstelling"
    # Het onderwerp is het enige dat je zeker ziet, ook op je telefoon. Staat er
    # iets fundamenteels mis met de invoer, dan hoort dat daar en niet pas
    # halverwege de tekst.
    vlag = "LET OP - " if blokkerende_waarschuwingen(d) else ""
    if d.get("periodestart"):
        kop = f"{vlag}CVHJ ronde {d['ronde']} - PERIODE {d['periode']} START, 3 transfers: {kern}"
    elif d.get("ronden_tot_volgende_periode") == 1:
        kop = f"{vlag}CVHJ ronde {d['ronde']} (volgende week 3 transfers): {kern}"
    else:
        kop = f"{vlag}CVHJ ronde {d['ronde']}: {kern}"

    msg = EmailMessage()
    msg["Subject"] = kop
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = os.environ["MAIL_NAAR"]
    msg.set_content(tekst)
    msg.add_attachment(Path(args.besluit).read_bytes(), maintype="application",
                       subtype="json", filename="besluit.json")

    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_POORT", 587))) as s:
        s.starttls()
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_WACHTWOORD"])
        s.send_message(msg)
    print(f"mail verstuurd naar {os.environ['MAIL_NAAR']}: {kop}")


if __name__ == "__main__":
    main()
