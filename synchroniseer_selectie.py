#!/usr/bin/env python3
"""
Haalt je ECHTE vijftien op van coachvanhetjaar.nl en vergelijkt die met selectie.csv.

WAAROM DIT BESTAAT
------------------
`selectie.csv` was het enige bestand dat met de hand bijgehouden moest worden,
en dat ging in september 2026 twee keer mis:

  - Na de transfer Flamingo -> Geertruida bleef de oude regel staan, waardoor
    het model een week lang met een speler rekende die niet meer in de ploeg
    zat.
  - De keer erna werd de wijziging in `spelers.csv` gezet (de wedstrijddata
    van de scraper) in plaats van in `selectie.csv` (de ploeg). Ook dat gaf
    geen foutmelding: beide bestanden bleven geldig, ze waren alleen niet
    meer waar.

Dat is het vervelendste soort fout in deze keten -- niets crasht, het model
rekent met volle overtuiging door op een ploeg die je niet meer hebt. De site
zelf weet altijd wel wie je hebt. Dus vragen we het gewoon aan de site.

WAT HET DOET
------------
Standaard alleen CONTROLEREN: het meldt de verschillen en eindigt met een
foutcode als er iets afwijkt. Met `--schrijf` werkt het `selectie.csv` bij
naar wat de site zegt.

Herkomst van de API-kennis: ongewijzigd overgenomen uit inleggen.py, dat is
opgebouwd uit een HAR-export van een echte sessie. Dit script importeert die
functies rechtstreeks in plaats van ze te kopieren, zodat er maar EEN plek is
die weet hoe het inloggen en `/api/team/preparation/` werken -- verandert de
site, dan hoeft dat op een plek gerepareerd te worden.

VEILIGHEIDSONTWERP -- "hard falen boven half werk", net als de scrapers
----------------------------------------------------------------------
`selectie.csv` wordt ALLEEN overschreven als alles klopt:
  - precies 15 spelers uit de site,
  - elke speler met een naam, een herkenbare club en een geldige positie,
  - elke clubnaam herleidbaar via de clublijst van de site.
Klopt er iets niet, dan wordt er NIETS geschreven en eindigt het script met
een duidelijke melding. Een half overschreven selectie.csv zou stilzwijgend
tot verkeerde adviezen leiden, en dat is precies wat dit script moet
voorkomen.

Gebruik:
    python synchroniseer_selectie.py                 # alleen controleren
    python synchroniseer_selectie.py --schrijf       # selectie.csv bijwerken
    python synchroniseer_selectie.py --ronde 7       # ronde forceren

Vereiste env-variabelen: CVHJ_GEBRUIKER, CVHJ_WACHTWOORD (dezelfde GitHub
Secrets die inleggen.py gebruikt).
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import requests

from inleggen import haal_clubs, haal_preparation, inloggen, laad_cvhj_model

HIER = Path(__file__).parent
VELDEN = ["speler", "club", "positie", "prijs"]


def schrijf_output(sleutel, waarde):
    """Zelfde patroon als deadline.py/auto_kalibreer.py: naar $GITHUB_OUTPUT
    binnen Actions, anders niets -- zodat een workflow erop kan sturen."""
    pad = os.environ.get("GITHUB_OUTPUT")
    if pad:
        with open(pad, "a", encoding="utf-8") as f:
            f.write(f"{sleutel}={waarde}\n")


def bepaal_ronde(opgegeven, programma="programma.csv"):
    """De ronde waarvoor we de opstelling opvragen.

    Zelfde bron als wekelijks.yml gebruikt: de eerste regel van programma.csv
    is de eerstvolgende ronde.
    """
    if opgegeven:
        return opgegeven
    pad = Path(programma)
    if not pad.exists():
        raise SystemExit(
            f"{programma} niet gevonden en geen --ronde opgegeven. Draai eerst "
            f"scrape_programma.py, of geef de ronde expliciet mee.")
    with pad.open(encoding="utf-8") as f:
        eerste = next(csv.DictReader(f), None)
    if not eerste or "ronde" not in eerste:
        raise SystemExit(f"kon geen ronde uit {programma} lezen -- geef --ronde mee.")
    return int(eerste["ronde"])


def selectie_van_site(m, sessie, ronde):
    """De vijftien zoals de site ze kent -> lijst van dicts in selectie.csv-vorm.

    Gooit RuntimeError zodra er iets niet klopt; de aanroeper schrijft dan
    niets weg (zie het veiligheidsontwerp in de moduledocstring).
    """
    clubs = haal_clubs(sessie)
    prep = haal_preparation(sessie, ronde)

    spelers = prep.get("players")
    if not isinstance(spelers, list):
        raise RuntimeError(
            "de site gaf geen spelerslijst terug in /api/team/preparation/ "
            "(veld 'players' ontbreekt of heeft een ander type) -- de interne "
            "API is waarschijnlijk gewijzigd.")

    rijen, ontbreekt = [], []
    for entry in spelers:
        p = entry.get("player") or {}
        naam = p.get("name")
        club_id = p.get("club_id")
        positie = p.get("position")
        waarde = p.get("value")

        if not naam:
            ontbreekt.append("een speler zonder 'name'")
            continue
        if club_id not in clubs:
            ontbreekt.append(f"{naam}: club_id {club_id!r} staat niet in de clublijst van de site")
            continue
        if positie not in m.KORT:
            ontbreekt.append(f"{naam}: onbekende positie {positie!r} "
                             f"(verwacht een van {sorted(m.KORT)})")
            continue
        if not isinstance(waarde, (int, float)):
            ontbreekt.append(f"{naam}: geen bruikbare 'value' ({waarde!r})")
            continue

        rijen.append({
            "speler": naam,
            "club": m.norm_club(clubs[club_id]),
            "positie": positie,
            "prijs": f"{waarde / 1_000_000:.2f}",
        })

    if ontbreekt:
        raise RuntimeError(
            "de opstelling van de site is niet volledig te lezen:\n  - "
            + "\n  - ".join(ontbreekt)
            + "\nEr wordt niets weggeschreven.")

    if len(rijen) != 15:
        raise RuntimeError(
            f"de site gaf {len(rijen)} spelers terug in plaats van 15. Dat kan "
            f"betekenen dat je ploeg nog niet compleet is, of dat de API is "
            f"gewijzigd. Er wordt niets weggeschreven.")

    return rijen, prep


def lees_bestand(pad):
    if not Path(pad).exists():
        return []
    with open(pad, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def vergelijk(m, site_rijen, bestand_rijen):
    """(alleen_op_site, alleen_in_bestand, prijsverschillen).

    Vergelijking op genormaliseerde naam + club, dezelfde sleutel die
    bouw_pool() en koppel_selectie() gebruiken -- zo betekent "gelijk" hier
    hetzelfde als "het model vindt deze speler straks terug".
    """
    def sleutel(r):
        return f"{m.norm(r['speler'])}|{m.norm(m.norm_club(r['club']))}"

    site = {sleutel(r): r for r in site_rijen}
    bestand = {sleutel(r): r for r in bestand_rijen}

    alleen_site = [site[k] for k in site.keys() - bestand.keys()]
    alleen_bestand = [bestand[k] for k in bestand.keys() - site.keys()]

    prijsverschil = []
    for k in site.keys() & bestand.keys():
        try:
            a, b = float(site[k]["prijs"]), float(bestand[k]["prijs"])
        except (TypeError, ValueError):
            continue
        if abs(a - b) > 0.005:
            prijsverschil.append((site[k]["speler"], b, a))

    return alleen_site, alleen_bestand, prijsverschil


def schrijf_selectie(pad, rijen):
    with open(pad, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=VELDEN)
        w.writeheader()
        w.writerows(rijen)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--selectie", default="selectie.csv")
    p.add_argument("--programma", default="programma.csv")
    p.add_argument("--ronde", type=int, default=None,
                   help="standaard de eerstvolgende ronde uit programma.csv")
    p.add_argument("--schrijf", action="store_true",
                   help="selectie.csv daadwerkelijk bijwerken naar wat de site zegt")
    a = p.parse_args()

    gebruiker = os.environ.get("CVHJ_GEBRUIKER")
    wachtwoord = os.environ.get("CVHJ_WACHTWOORD")
    if not gebruiker or not wachtwoord:
        sys.exit("CVHJ_GEBRUIKER en/of CVHJ_WACHTWOORD ontbreken "
                 "(env-variabelen / GitHub Secrets).")

    m = laad_cvhj_model()
    ronde = bepaal_ronde(a.ronde, a.programma)

    sessie = requests.Session()
    print(f"Inloggen op coachvanhetjaar.nl (ronde {ronde})...")
    inloggen(sessie, gebruiker, wachtwoord)

    try:
        site_rijen, prep = selectie_van_site(m, sessie, ronde)
    except RuntimeError as e:
        schrijf_output("verschil", "onbekend")
        sys.exit(f"FOUT: {e}")

    print(f"  team {prep.get('team_name', '?')!r}: 15 spelers opgehaald  "
          f"(transfers over: {prep.get('num_transfers_left', '?')})")

    bestand_rijen = lees_bestand(a.selectie)
    alleen_site, alleen_bestand, prijsverschil = vergelijk(m, site_rijen, bestand_rijen)

    if not bestand_rijen:
        print(f"\n{a.selectie} bestaat nog niet of is leeg.")
    elif not alleen_site and not alleen_bestand:
        print(f"\n{a.selectie} komt overeen met de site: dezelfde 15 spelers.")
    else:
        print(f"\nVERSCHIL tussen {a.selectie} en je ploeg op de site:")
        for r in sorted(alleen_bestand, key=lambda r: r["speler"]):
            print(f"    staat in {a.selectie}, maar NIET in je ploeg:  "
                  f"{r['speler']} ({r['club']})")
        for r in sorted(alleen_site, key=lambda r: r["speler"]):
            print(f"    staat in je ploeg, maar NIET in {a.selectie}:  "
                  f"{r['speler']} ({r['club']}, {r['positie']}, EUR {r['prijs']})")

    # Prijzen bewegen elke week; dat is geen fout, maar wel het vermelden waard
    # omdat de budgetcontrole ermee rekent.
    if prijsverschil:
        print(f"\nPrijsverschillen (site is leidend):")
        for naam, oud, nieuw in sorted(prijsverschil):
            print(f"    {naam}: {oud:.2f} -> {nieuw:.2f}")

    afwijkend = bool(alleen_site or alleen_bestand)
    schrijf_output("verschil", "ja" if afwijkend else "nee")
    schrijf_output("aantal_verschillen", len(alleen_site) + len(alleen_bestand))

    if a.schrijf:
        veranderd = afwijkend or prijsverschil or not bestand_rijen
        if veranderd:
            schrijf_selectie(a.selectie, site_rijen)
            print(f"\n{a.selectie} bijgewerkt naar de ploeg van de site.")
            schrijf_output("bijgewerkt", "ja")
        else:
            print(f"\n{a.selectie} was al actueel -- niets gewijzigd.")
            schrijf_output("bijgewerkt", "nee")
        return

    if afwijkend:
        sys.exit(
            f"\n{a.selectie} loopt niet gelijk met je echte ploeg. Het model zou "
            f"hiermee een verkeerd advies geven.\nDraai dit script opnieuw met "
            f"--schrijf om {a.selectie} bij te werken.")


if __name__ == "__main__":
    main()
