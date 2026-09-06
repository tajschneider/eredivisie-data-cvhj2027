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

    r += ["", "OPSTELLING (basis)"]
    for x in sorted(h["basis"], key=lambda x: (-x["E"])):
        r.append(f"  {x['pos']}  {x['speler']:26s} {x['club']:18s} E {x['E']:.2f}")
    r += ["", "Bank (50%)"]
    for x in sorted(h["bank"], key=lambda x: -x["E"]):
        r.append(f"  {x['pos']}  {x['speler']:26s} {x['club']:18s} E {x['E']:.2f}")

    aandacht = []
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
    kern = f"{len(a['uit'])} transfer(s), {a['winst']:+.1f} punt" if a else "alleen opstelling"
    if d.get("periodestart"):
        kop = f"CVHJ ronde {d['ronde']} - PERIODE {d['periode']} START, 3 transfers: {kern}"
    elif d.get("ronden_tot_volgende_periode") == 1:
        kop = f"CVHJ ronde {d['ronde']} (volgende week 3 transfers): {kern}"
    else:
        kop = f"CVHJ ronde {d['ronde']}: {kern}"

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
