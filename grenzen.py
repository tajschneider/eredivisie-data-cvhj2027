#!/usr/bin/env python3
"""
De grenzen waarbinnen een automatisch voorstel mag blijven.

Deze controle draait op elke pull request en is bewust DETERMINISTISCH. Een
prompt kan zeggen "raak inleggen.py niet aan"; dat is een verzoek, geen grens.
Dit bestand is de grens: het leest welke bestanden een PR verandert en keurt
hem af als hij buiten de lijnen komt. Een model dat de instructie verkeerd
begrijpt, of een PR die van elders komt, loopt hier hoe dan ook tegenaan.

Drie regels, elk met een eigen reden.

1. WELKE BESTANDEN. `inleggen.py` legt daadwerkelijk transfers in op
   coachvanhetjaar.nl -- dat is het enige script dat iets onomkeerbaars doet
   in de echte wereld, en het hoort niet automatisch gewijzigd te worden. De
   workflows staan er ook buiten: een workflow kan zichzelf meer rechten
   geven, en een automatisch voorstel dat zijn eigen rechten uitbreidt is
   precies wat je niet wilt. Dit bestand en zijn test staan op de lijst omdat
   een hek dat zichzelf kan verzetten geen hek is. CSV's evenmin: data komt
   van de scrapers, niet uit een voorstel.

2. TESTS MOGEN NIET KRIMPEN. De klassieke manier waarop een automatische
   wijziging "slaagt" is door de test te verzwakken die hem tegenhield. Het
   aantal testfuncties per bestand mag daarom niet dalen. Toevoegen mag
   altijd.

3. OMVANG. Een voorstel van driehonderd regels is geen voorstel meer maar een
   herschrijving, en die beoordeel je niet meer serieus in een PR-weergave.
   Boven de grens wordt hij afgekeurd met het verzoek hem op te splitsen.

Gebruik (in de PR-workflow):

    git diff --name-only origin/main...HEAD > gewijzigd.txt
    python grenzen.py --gewijzigd gewijzigd.txt --basis origin/main

Zonder --basis worden alleen de padregels gecontroleerd, niet het krimpen.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

# Nooit automatisch wijzigen. Volgorde = volgorde van uitleg in de melding.
VERBODEN = [
    ("inleggen.py",
     "legt echte transfers in op coachvanhetjaar.nl -- het enige script met een "
     "onomkeerbaar gevolg buiten de repo"),
    (".github/workflows/",
     "een workflow kan zichzelf meer rechten geven; een voorstel dat zijn eigen "
     "rechten uitbreidt hoort niet automatisch te kunnen"),
    ("grenzen.py",
     "dit is het hek zelf -- een hek dat zichzelf kan verzetten is geen hek"),
    ("test_grenzen.py",
     "de test die het hek bewaakt, om dezelfde reden"),
]

# Data komt uit de scrapers, niet uit een voorstel.
VERBODEN_PATRONEN = [
    (r"\.csv$", "data hoort uit de scrapers te komen, niet uit een codevoorstel"),
    (r"^validatie/", "meetreeks: die schrijft valideer.py, en alleen die"),
    (r"^historie/", "vastgelegde adviezen blijven zoals ze waren"),
    (r"^kalibratie/", "kalibratiegeschiedenis blijft zoals hij was"),
]

MAX_REGELS = 400


def is_verboden(pad):
    """(verboden?, reden). Eén plek, zodat de melding en de regel niet uiteenlopen."""
    for verboden, reden in VERBODEN:
        if pad == verboden or pad.startswith(verboden):
            return True, reden
    for patroon, reden in VERBODEN_PATRONEN:
        if re.search(patroon, pad):
            return True, reden
    return False, ""


def tel_tests(tekst):
    """Aantal testfuncties in een bestand."""
    return len(re.findall(r"^\s*def\s+test_\w+", tekst, re.MULTILINE))


def bestand_bij_basis(pad, basis):
    """De inhoud van dit bestand op de basisbranch, of None als het nieuw is."""
    try:
        r = subprocess.run(["git", "show", f"{basis}:{pad}"],
                           capture_output=True, text=True, check=True)
        return r.stdout
    except subprocess.CalledProcessError:
        return None


def regels_gewijzigd(basis):
    """Aantal toegevoegde plus verwijderde regels ten opzichte van de basis."""
    try:
        r = subprocess.run(["git", "diff", "--numstat", f"{basis}...HEAD"],
                           capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError:
        return None
    totaal = 0
    for regel in r.stdout.splitlines():
        delen = regel.split("\t")
        if len(delen) >= 2:
            for n in delen[:2]:
                if n.isdigit():
                    totaal += int(n)
    return totaal


def controleer(paden, basis=None, max_regels=MAX_REGELS):
    """(fouten, opmerkingen). Fouten keuren de PR af, opmerkingen niet."""
    fouten, opmerkingen = [], []

    for pad in paden:
        verboden, reden = is_verboden(pad)
        if verboden:
            fouten.append(f"{pad} mag niet automatisch gewijzigd worden: {reden}")

    if basis:
        for pad in paden:
            if not Path(pad).name.startswith("test_") or not pad.endswith(".py"):
                continue
            oud = bestand_bij_basis(pad, basis)
            if oud is None:
                opmerkingen.append(f"{pad} is nieuw ({tel_tests(Path(pad).read_text(encoding='utf-8')) if Path(pad).exists() else 0} tests)")
                continue
            if not Path(pad).exists():
                fouten.append(f"{pad} is VERWIJDERD -- een testbestand weghalen is geen verbetering")
                continue
            voor, na = tel_tests(oud), tel_tests(Path(pad).read_text(encoding="utf-8"))
            if na < voor:
                fouten.append(
                    f"{pad} verliest testfuncties ({voor} -> {na}). Een wijziging die "
                    f"slaagt door de test te verzwakken die hem tegenhield, is geen "
                    f"verbetering. Toevoegen mag altijd.")
            elif na > voor:
                opmerkingen.append(f"{pad}: {voor} -> {na} tests")

        n = regels_gewijzigd(basis)
        if n is not None:
            if n > max_regels:
                fouten.append(
                    f"{n} gewijzigde regels, grens is {max_regels}. Dit is geen voorstel "
                    f"meer maar een herschrijving; splits het op in stappen die los te "
                    f"beoordelen zijn.")
            else:
                opmerkingen.append(f"{n} gewijzigde regels (grens {max_regels})")

    return fouten, opmerkingen


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--gewijzigd", required=True,
                   help="bestand met de gewijzigde paden, een per regel")
    p.add_argument("--basis", default=None, help="basisbranch, bv. origin/main")
    p.add_argument("--max-regels", type=int, default=MAX_REGELS)
    a = p.parse_args()

    paden = [r.strip() for r in Path(a.gewijzigd).read_text(encoding="utf-8").splitlines()
             if r.strip()]
    if not paden:
        print("Geen gewijzigde bestanden.")
        return

    print(f"{len(paden)} gewijzigd bestand(en):")
    for pad in paden:
        print(f"  {pad}")

    fouten, opmerkingen = controleer(paden, a.basis, a.max_regels)

    print()
    for o in opmerkingen:
        print(f"  {o}")
    if fouten:
        print()
        for f in fouten:
            print(f"  BUITEN DE GRENZEN: {f}")
        sys.exit("\nAfgekeurd. Deze grenzen staan in grenzen.py en zijn er om een "
                 "automatisch voorstel beoordeelbaar en omkeerbaar te houden. Wil je "
                 "toch iets wijzigen wat hier verboden is, doe dat dan met de hand -- "
                 "dan lees je het zelf.")
    print("\nOK: het voorstel blijft binnen de grenzen.")


if __name__ == "__main__":
    main()
