#!/usr/bin/env python3
"""
Bepaalt of de CVHJ-deadline binnen handbereik is.

De deadline is de aftrap van de eerste wedstrijd van de ronde. Inhaalduels
tellen niet mee: die horen bij een eerdere ronde.

Gebruik:
    python deadline.py data/programma.csv --uren 6
    python deadline.py data/programma.csv --uren 6 --nu 2026-09-11T14:00

Schrijft binnen GitHub Actions `binnen_venster=ja|nee` en `deadline=<iso>`
naar $GITHUB_OUTPUT; buiten Actions gewoon naar stdout. Exitcode is altijd 0 --
"nog te vroeg" is geen fout.
"""
import argparse
import csv
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

MAANDEN = {"januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5,
           "juni": 6, "juli": 7, "augustus": 8, "september": 9,
           "oktober": 10, "november": 11, "december": 12}


def parse_datum(tekst):
    """'zaterdag 12 september 2026, 18:45' -> datetime, of None."""
    m = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})(?:,\s*(\d{1,2}):(\d{2}))?",
                  (tekst or "").lower())
    if not m or m.group(2) not in MAANDEN:
        return None
    return datetime(int(m.group(3)), MAANDEN[m.group(2)], int(m.group(1)),
                    int(m.group(4) or 0), int(m.group(5) or 0))


def schrijf(sleutel, waarde):
    pad = os.environ.get("GITHUB_OUTPUT")
    if pad:
        with open(pad, "a", encoding="utf-8") as f:
            f.write(f"{sleutel}={waarde}\n")
    print(f"{sleutel}={waarde}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("programma", help="pad naar programma.csv")
    p.add_argument("--uren", type=float, default=6.0,
                   help="hoeveel uur voor de deadline het venster opengaat")
    p.add_argument("--nu", help="ISO-tijdstip om mee te rekenen (voor tests)")
    args = p.parse_args()

    pad = Path(args.programma)
    if not pad.exists():
        schrijf("binnen_venster", "nee")
        sys.exit(0)

    tijden = []
    with pad.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("soort", "regulier") == "inhaal":
                continue
            dt = parse_datum(r.get("datum", ""))
            if dt:
                tijden.append(dt)

    if not tijden:
        # Geen bruikbare datum: niet gokken, niet inleggen.
        print("geen leesbare wedstrijddatums in programma.csv")
        schrijf("binnen_venster", "nee")
        sys.exit(0)

    deadline = min(tijden)
    nu = datetime.fromisoformat(args.nu) if args.nu else datetime.now()
    opent = deadline - timedelta(hours=args.uren)
    binnen = opent <= nu < deadline

    resterend = (deadline - nu).total_seconds() / 3600
    print(f"deadline   {deadline:%a %d-%m-%Y %H:%M}")
    print(f"nu         {nu:%a %d-%m-%Y %H:%M}  ({resterend:+.1f} uur)")
    print(f"venster    vanaf {opent:%H:%M} tot deadline")
    if nu >= deadline:
        print("-> deadline verstreken; niet meer inleggen")
    elif not binnen:
        print(f"-> nog te vroeg; venster opent over {(opent - nu).total_seconds()/3600:.1f} uur")
    else:
        print("-> binnen het venster")

    schrijf("binnen_venster", "ja" if binnen else "nee")
    schrijf("deadline", deadline.isoformat())


if __name__ == "__main__":
    main()
