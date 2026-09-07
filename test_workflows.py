#!/usr/bin/env python3
"""
Controleert of elke workflow installeert en meebrengt wat zijn scripts nodig hebben.

Waarom dit bestaat: in één week liepen drie workflows stuk op precies dezelfde
soort fout -- de omgeving kwam niet overeen met wat de code nodig had, en dat
bleek pas als het ding al draaide:

  - kalibratie.yml: `backtest.py` stond niet in de repo
        -> ModuleNotFoundError: No module named 'backtest'
  - kalibratie.yml: de fout werd verstopt door een pipe zonder `set -o pipefail`
        -> fatal: pathspec 'kalibratie/status.json' did not match any files
  - xg.yml: `pip install requests` miste numpy, dat test_sofascore.py via
    cvhj_model.py nodig heeft
        -> ModuleNotFoundError: No module named 'numpy'

Alle drie zijn statisch te zien, zonder iets te draaien. Dit script doet dat:
voor elke workflow zoekt het op welke scripts hij start, welke lokale bestanden
die (direct en indirect) importeren, en welke externe pakketten daarvoor nodig
zijn -- en vergelijkt dat met de `pip install`-regel van diezelfde workflow.

Draai dit na elke wijziging aan een workflow of aan de imports van een script:

    python test_workflows.py

Bewust zonder afhankelijkheden (geen PyYAML): het parsen gaat met reguliere
expressies, wat voor deze paar patronen ruim voldoende is en betekent dat dit
overal draait waar Python staat.
"""
import re
import sys
from pathlib import Path

HIER = Path(__file__).parent
WORKFLOWS = HIER / ".github" / "workflows"

# importnaam -> pakketnaam zoals pip hem kent
EXTERN = {
    "numpy": "numpy",
    "scipy": "scipy",
    "requests": "requests",
    "bs4": "beautifulsoup4",
}

# Scripts die cvhj_model.py niet importeren maar dynamisch inladen via
# laad_model() (importlib). Statisch zoeken naar `import cvhj_model` mist dat,
# dus die koppeling staat hier expliciet.
DYNAMISCH = {"laad_model": "cvhj_model"}


def lokale_modules():
    return {p.stem: p for p in HIER.glob("*.py")}


def imports_van(pad, modules):
    """(lokale modules, externe pakketten) die dit bestand direct nodig heeft."""
    tekst = pad.read_text(encoding="utf-8")
    # Alleen echte importregels, geen woorden in commentaar of docstrings.
    namen = set(re.findall(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)",
                           tekst, re.MULTILINE))
    lokaal = {n for n in namen if n in modules}
    extern = {EXTERN[n] for n in namen if n in EXTERN}
    for aanroep, module in DYNAMISCH.items():
        if re.search(r"\b" + aanroep + r"\s*\(", tekst) and module in modules:
            lokaal.add(module)
    return lokaal, extern


def sluit_af(start, modules):
    """Alles wat `start` direct of indirect nodig heeft."""
    te_doen, gezien, extern = [start], set(), set()
    while te_doen:
        naam = te_doen.pop()
        if naam in gezien or naam not in modules:
            continue
        gezien.add(naam)
        lok, ext = imports_van(modules[naam], modules)
        extern |= ext
        te_doen.extend(lok - gezien)
    return gezien, extern


def controleer(pad_workflow, modules):
    tekst = pad_workflow.read_text(encoding="utf-8")
    naam = pad_workflow.name

    geinstalleerd = set()
    for regel in re.findall(r"pip install ([^\n|&]+)", tekst):
        geinstalleerd |= {w.strip() for w in regel.split() if not w.startswith("-")}

    gestart = sorted(set(re.findall(r"python\s+([A-Za-z0-9_]+)\.py", tekst)))
    if not gestart:
        print(f"  {naam}: geen scripts gestart, niets te controleren")
        return True

    ok = True
    for script in gestart:
        if script not in modules:
            print(f"  FOUT {naam}: start {script}.py, maar dat bestand bestaat niet")
            ok = False
            continue
        nodig_lokaal, nodig_extern = sluit_af(script, modules)
        ontbreekt = sorted(nodig_extern - geinstalleerd)
        if ontbreekt:
            via = ", ".join(sorted(nodig_lokaal - {script})) or "direct"
            print(f"  FOUT {naam}: {script}.py heeft {', '.join(ontbreekt)} nodig "
                  f"(via {via}), maar de workflow installeert dat niet")
            ok = False

    if ok:
        alles = set()
        for script in gestart:
            alles |= sluit_af(script, modules)[1]
        overbodig = sorted(geinstalleerd - alles)
        extra = f"  (installeert ook {', '.join(overbodig)})" if overbodig else ""
        print(f"  OK   {naam}: {len(gestart)} script(s), afhankelijkheden compleet{extra}")
    return ok


def main():
    if not WORKFLOWS.is_dir():
        sys.exit(f"geen workflows gevonden in {WORKFLOWS}")

    modules = lokale_modules()
    print(f"Workflows controleren ({len(modules)} lokale scripts gevonden)\n")

    alles_ok = True
    for pad in sorted(WORKFLOWS.glob("*.yml")):
        if not controleer(pad, modules):
            alles_ok = False

    # Losse controle: elk lokaal script moet importeren wat het bestaat.
    print()
    kapot = []
    for naam, pad in sorted(modules.items()):
        lok, _ = imports_van(pad, modules)
        for m in lok:
            if m not in modules:
                kapot.append(f"{naam}.py importeert {m}, dat bestaat niet")
    if kapot:
        alles_ok = False
        for regel in kapot:
            print(f"  FOUT {regel}")
    else:
        print(f"  OK   alle onderlinge imports tussen de {len(modules)} scripts kloppen")

    print()
    if alles_ok:
        print("OK: elke workflow installeert wat zijn scripts nodig hebben.")
    else:
        sys.exit("MISLUKT: zie hierboven -- dit zou live een ModuleNotFoundError geven.")


if __name__ == "__main__":
    main()
