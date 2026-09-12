#!/usr/bin/env python3
"""
Regressietest voor synchroniseer_selectie.py -- zonder netwerk en zonder inloggen.

De fixture is Thomas' echte vijftien uit besluit.json van ronde 6, met een
verschil dat precies de fout van september 2026 naspeelt: de SITE kent
Geertruida, terwijl selectie.csv nog Flamingo bevat. Die situatie moet dit
script herkennen en kunnen repareren.

Getest wordt vooral het gedrag dat MISGAAT als het misgaat:
  - wordt het verschil gevonden,
  - en, belangrijker, wordt er NIETS geschreven zodra de site iets teruggeeft
    dat niet volledig klopt (14 spelers, onbekende club, onbekende positie,
    ontbrekende prijs). Een half overschreven selectie.csv zou stilzwijgend
    verkeerde adviezen opleveren.

    python test_synchroniseer.py
"""
import csv
import sys
import tempfile
from pathlib import Path

import synchroniseer_selectie as s

# id -> full_name, zoals /api/teams/all/ het teruggeeft. "N.E.C." staat er
# bewust in met puntjes: norm_club() hoort daar "NEC" van te maken, net als
# overal elders in het project.
CLUBS = {
    1: "Go Ahead Eagles", 2: "Excelsior", 3: "PSV", 4: "Telstar", 5: "N.E.C.",
    6: "FC Twente", 7: "ADO Den Haag", 8: "Ajax", 9: "Sparta Rotterdam",
    10: "Feyenoord", 11: "Fortuna Sittard", 12: "AZ", 13: "FC Utrecht",
    14: "FC Groningen", 15: "sc Heerenveen",
}

# Zoals /api/team/preparation/ het teruggeeft: {"players": [{"player": {...}}]}
PLOEG = [
    ("Kjetil Haug", 1, "Goalkeeper", 1_500_000),
    ("Stijn van Gassel", 2, "Goalkeeper", 1_750_000),
    ("Lutsharel Geertruida", 3, "Defender", 3_000_000),   # de site weet het al
    ("Jeff Hardeveld", 4, "Defender", 2_000_000),
    ("Deveron Fonville", 5, "Defender", 2_000_000),
    ("Aske Adelgaard", 6, "Defender", 1_500_000),
    ("Sekou Sylla", 7, "Defender", 1_500_000),
    ("Oscar Gloukh", 8, "Midfielder", 2_800_000),
    ("Shunsuke Mito", 9, "Midfielder", 2_000_000),
    ("Gjivai Zechiël", 10, "Midfielder", 2_000_000),
    ("Mohamed Ihattaren", 11, "Midfielder", 2_000_000),
    ("Mexx Meerdink", 12, "Forward", 2_500_000),
    ("David Min", 13, "Forward", 1_750_000),
    ("Brynjólfur Willumsson", 14, "Forward", 1_800_000),
    ("Jacob Trenskow", 15, "Forward", 2_200_000),
]


def prep(ploeg=None):
    return {
        "team_name": "Testploeg",
        "num_transfers_left": 1,
        "players": [{"player": {"name": n, "club_id": c, "position": p, "value": v}}
                    for n, c, p, v in (ploeg if ploeg is not None else PLOEG)],
    }


def zet_nep(monkey_prep):
    s.haal_clubs = lambda sessie: CLUBS
    s.haal_preparation = lambda sessie, ronde: monkey_prep


def selectie_met_flamingo():
    """selectie.csv zoals het WAS: nog met Flamingo in plaats van Geertruida."""
    rijen = []
    for naam, club_id, positie, waarde in PLOEG:
        if naam == "Lutsharel Geertruida":
            naam, positie, waarde = "Ryan Flamingo", "Defender", 3_000_000
        rijen.append({"speler": naam, "club": CLUBS[club_id], "positie": positie,
                      "prijs": f"{waarde / 1_000_000:.2f}"})
    return rijen


def test_verschil_gevonden(m):
    zet_nep(prep())
    site_rijen, _ = s.selectie_van_site(m, None, 7)
    alleen_site, alleen_bestand, _ = s.vergelijk(m, site_rijen, selectie_met_flamingo())

    goed = (len(alleen_site) == 1 and alleen_site[0]["speler"] == "Lutsharel Geertruida"
            and len(alleen_bestand) == 1 and alleen_bestand[0]["speler"] == "Ryan Flamingo")
    print(f"  {'OK  ' if goed else 'FOUT'} verschil herkend: in je ploeg "
          f"{[r['speler'] for r in alleen_site]}, in selectie.csv "
          f"{[r['speler'] for r in alleen_bestand]}")
    return goed


def test_geen_verschil(m):
    zet_nep(prep())
    site_rijen, _ = s.selectie_van_site(m, None, 7)
    alleen_site, alleen_bestand, prijs = s.vergelijk(m, site_rijen, site_rijen)
    goed = not alleen_site and not alleen_bestand and not prijs
    print(f"  {'OK  ' if goed else 'FOUT'} identieke ploeg geeft geen verschil")
    return goed


def test_prijsverschil(m):
    zet_nep(prep())
    site_rijen, _ = s.selectie_van_site(m, None, 7)
    aangepast = [dict(r) for r in site_rijen]
    aangepast[0]["prijs"] = "1.20"
    _, _, prijs = s.vergelijk(m, site_rijen, aangepast)
    goed = len(prijs) == 1 and abs(prijs[0][2] - 1.50) < 0.001
    print(f"  {'OK  ' if goed else 'FOUT'} prijsverschil gezien: {prijs}")
    return goed


def test_clubnaam_genormaliseerd(m):
    """'N.E.C.' van de site moet 'NEC' worden -- anders matcht Fonville nooit."""
    zet_nep(prep())
    site_rijen, _ = s.selectie_van_site(m, None, 7)
    fonville = next((r for r in site_rijen if r["speler"] == "Deveron Fonville"), None)
    goed = fonville is not None and fonville["club"] == "NEC"
    print(f"  {'OK  ' if goed else 'FOUT'} 'N.E.C.' -> {fonville['club']!r} (verwacht 'NEC')")
    return goed


def test_weigert_onvolledige_data(m):
    """Het hart van het veiligheidsontwerp: bij twijfel niets schrijven."""
    gevallen = [
        ("14 spelers", PLOEG[:-1]),
        ("onbekende positie", [(n, c, "Sweeper" if i == 0 else p, v)
                               for i, (n, c, p, v) in enumerate(PLOEG)]),
        ("onbekende club", [(n, 99 if i == 0 else c, p, v)
                            for i, (n, c, p, v) in enumerate(PLOEG)]),
        ("ontbrekende prijs", [(n, c, p, None if i == 0 else v)
                               for i, (n, c, p, v) in enumerate(PLOEG)]),
        ("lege naam", [("" if i == 0 else n, c, p, v)
                       for i, (n, c, p, v) in enumerate(PLOEG)]),
    ]
    ok = True
    for beschrijving, ploeg in gevallen:
        zet_nep(prep(ploeg))
        try:
            s.selectie_van_site(m, None, 7)
            print(f"  FOUT {beschrijving}: geaccepteerd, had geweigerd moeten worden")
            ok = False
        except RuntimeError:
            print(f"  OK   {beschrijving}: geweigerd, er wordt niets geschreven")

    # En als de site iets heel anders teruggeeft dan een spelerslijst.
    zet_nep({"team_name": "x"})
    try:
        s.selectie_van_site(m, None, 7)
        print("  FOUT ontbrekend 'players'-veld: geaccepteerd")
        ok = False
    except RuntimeError:
        print("  OK   ontbrekend 'players'-veld: geweigerd")
    return ok


def test_schrijft_leesbaar_bestand(m):
    """Het weggeschreven selectie.csv moet door het model gelezen kunnen worden."""
    zet_nep(prep())
    site_rijen, _ = s.selectie_van_site(m, None, 7)
    ok = True
    with tempfile.TemporaryDirectory() as d:
        pad = Path(d) / "selectie.csv"
        s.schrijf_selectie(pad, site_rijen)

        geladen = m.lees_selectie(str(pad))
        goed = geladen is not None and len(geladen) == 15
        print(f"  {'OK  ' if goed else 'FOUT'} lees_selectie() leest {len(geladen or [])} "
              f"spelers terug uit het geschreven bestand")
        ok = ok and goed

        club, pos, prijs = geladen.get("Lutsharel Geertruida", (None, None, None))
        goed = club == "PSV" and pos == "V" and abs(prijs - 3.00) < 0.001
        print(f"  {'OK  ' if goed else 'FOUT'} Geertruida komt terug als "
              f"({club!r}, {pos!r}, {prijs}) -- verwacht ('PSV', 'V', 3.0)")
        ok = ok and goed

        kop = next(csv.reader(pad.open(encoding="utf-8")))
        goed = kop == s.VELDEN
        print(f"  {'OK  ' if goed else 'FOUT'} kolomkoppen {kop} (verwacht {s.VELDEN})")
        ok = ok and goed
    return ok


# --------------------------------------------------------------- omleidingen
# De login zelf is niet te testen zonder echte gegevens, maar het AFHANDELEN
# van de omleidingen erna wel -- en dat is precies waar het op 12 september
# 2026 op stukliep (`TooManyRedirects: Exceeded 30 redirects`, zonder verdere
# informatie). Hieronder een nepsessie: geen netwerk, geen wachtwoorden.
import inleggen


class NepAntwoord:
    def __init__(self, code, url, locatie=None):
        self.status_code, self.url = code, url
        self.headers = {"Location": locatie} if locatie else {}

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307, 308) and "Location" in self.headers


class NepSessie:
    """Beantwoordt elke GET volgens `plan`, en zet het sessionid-koekje pas na
    `sessie_na` hops (None = nooit, oftewel de lus)."""

    def __init__(self, plan, sessie_na=None):
        self.plan, self.sessie_na, self.hops = plan, sessie_na, 0
        self._koekjes = {}
        self.cookies = self

    def get_dict(self):
        return dict(self._koekjes)

    def get(self, url, **_kw):
        self.hops += 1
        if self.sessie_na is not None and self.hops >= self.sessie_na:
            self._koekjes["sessionid"] = "nep"
        return self.plan(url, self.hops)


def test_omleidingslus():
    """Een eindeloze lus moet netjes stoppen, niet na 30 hops crashen."""
    lus = lambda url, n: NepAntwoord(302, url, "/accounts/login/")
    sessie = NepSessie(lus)
    spoor = []
    start = NepAntwoord(302, "https://x/accounts/login/", "/accounts/login/")
    _resp, ingelogd = inleggen._volg_omleidingen(sessie, start, spoor)
    goed = not ingelogd and len(spoor) <= inleggen.MAX_HOPS + 1 and sessie.hops < 30
    print(f"  {'OK  ' if goed else 'FOUT'} lus gestopt na {len(spoor)} stappen "
          f"(niet ingelogd), i.p.v. TooManyRedirects na 30")
    return goed


def test_stopt_zodra_sessie_er_is():
    """Zodra sessionid er staat zijn we klaar -- ook al blijft de site omleiden.

    Dit is de kern van de reparatie: de functie moet een INGELOGDE SESSIE
    opleveren, niet een bepaalde eindpagina. Blijft de site daarna rondjes
    draaien, dan raakt ons dat niet meer.
    """
    eeuwig = lambda url, n: NepAntwoord(302, url, "/app/6")
    sessie = NepSessie(eeuwig, sessie_na=2)
    spoor = []
    start = NepAntwoord(302, "https://x/accounts/login/", "/app/6")
    _resp, ingelogd = inleggen._volg_omleidingen(sessie, start, spoor)
    goed = ingelogd and len(spoor) < inleggen.MAX_HOPS
    print(f"  {'OK  ' if goed else 'FOUT'} gestopt zodra sessionid er was "
          f"({len(spoor)} stappen, ingelogd={ingelogd})")
    return goed


def test_weigert_307():
    """307/308 zou de POST -- met wachtwoord -- naar een andere URL sturen."""
    sessie = NepSessie(lambda url, n: NepAntwoord(200, url))
    start = NepAntwoord(307, "https://x/accounts/login/", "https://elders/login")
    try:
        inleggen._volg_omleidingen(sessie, start, [])
    except RuntimeError as e:
        goed = "elders" in str(e)
        print(f"  {'OK  ' if goed else 'FOUT'} 307 geweigerd: {str(e)[:60]}...")
        return goed
    print("  FOUT 307 werd gevolgd -- dat stuurt inloggegevens door")
    return False


def main():
    m = s.laad_cvhj_model()

    print("verschil met de site herkennen\n")
    ok1 = test_verschil_gevonden(m)
    ok2 = test_geen_verschil(m)
    ok3 = test_prijsverschil(m)
    ok4 = test_clubnaam_genormaliseerd(m)

    print("\nweigeren bij onvolledige data (hard falen boven half werk)\n")
    ok5 = test_weigert_onvolledige_data(m)

    print("\nhet geschreven selectie.csv\n")
    ok6 = test_schrijft_leesbaar_bestand(m)

    print("\nomleidingen na de login-POST\n")
    ok7 = test_omleidingslus()
    ok8 = test_stopt_zodra_sessie_er_is()
    ok9 = test_weigert_307()

    print()
    if all([ok1, ok2, ok3, ok4, ok5, ok6, ok7, ok8, ok9]):
        print("OK: synchroniseer_selectie.py herkent afwijkingen en weigert half werk.")
    else:
        sys.exit("MISLUKT: zie hierboven.")


if __name__ == "__main__":
    main()
