#!/usr/bin/env python3
"""
Transfers uit besluit.json daadwerkelijk doorvoeren op coachvanhetjaar.nl.

Herkomst van deze kennis: coachvanhetjaar.nl is een Vite/React-app (SPA) op
een Django-backend. Er bestaat geen publieke documentatie van de interne API
-- alles hieronder komt uit een HAR-export (Network-tab) van Thomas' eigen
browser tijdens een echte, bewuste transfer, dus GEVERIFIEERD gedrag op het
moment van schrijven, geen giswerk. Wat WEL giswerk is, staat expliciet
gemarkeerd. Verandert de site haar interne API, dan breekt dit script met een
duidelijke foutmelding (nooit stil verkeerd inleggen) -- zie de aparte
paragraaf hieronder.

De API in het kort (basis https://www.coachvanhetjaar.nl):
    GET  /accounts/login/                     inlogformulier (Django/allauth)
    GET  /api/teams/all/                      clublijst: id -> naam
    GET  /api/team/preparation/?round_seq=N   je huidige 15, budget, transfers
    GET  /api/players/search_all/N/?page=..&page_size=..&sort=-total_points
                                               de hele markt, gepagineerd
    POST /api/transfer/N/sell/<uit>/buy/<in>/?auto_change_formation=true&sub=false
                                               voert EEN transfer door
                                               body: {}  (Content-Type: application/json)
                                               vereist header X-CSRFToken

Authenticatie loopt via de gewone Django-sessie (cookie `sessionid`, gezet
door in te loggen op /accounts/login/); de SPA praat met dezelfde sessie. De
POST hierboven vereist daarnaast Django's csrf-cookie (`csrftoken`) terug als
`X-CSRFToken`-header -- standaard Django-gedrag, niets CVHJ-specifieks.

Wat NIET geverifieerd is (er was geen voorbeeld van in de HAR-export):
- Het inlogformulier zelf: welke velden het exact heeft, is nooit gezien
  (de HAR begon met een al ingelogde sessie). Dit script ontleedt het
  formulier daarom LIVE (net als de scrapers): het veld met type=password
  is het wachtwoord, het veld met type=email (of anders het enige overige
  tekstveld) is de gebruikersnaam -- niet gebaseerd op geraden veldnamen.
  Gaat dit mis, dan meldt dit script dat expliciet in plaats van te gokken.
- Alleen-bank-wisselen binnen je eigen 15 (de `sub=true`-variant van de
  transfer-URL) -- nooit geobserveerd. `auto_change_formation=true` laat de
  site na een markttransfer zelf de beste opstelling/bank kiezen; dat kan op
  de bankkeuze een ander resultaat geven dan cvhj_model.py's eigen keuze,
  maar raakt niet WELKE 15 spelers je hebt. Controleer dit zelf in de app
  als de bankkeuze je opvalt.
- Live vanuit GitHub Actions: elke scraper in dit project moest voor het
  eerst handmatig gedraaid worden voordat 'ie vertrouwd werd; hetzelfde
  geldt hier. Draai dit ALTIJD eerst met DRY_RUN=ja (de standaard) en
  controleer de uitvoer, voor je 'm ooit live laat draaien.

Veiligheidsontwerp:
- DRY_RUN staat standaard AAN (via de env var DRY_RUN, 'ja' tenzij expliciet
  'nee'). In dry-run wordt alles opgezocht en gecontroleerd, maar wordt er
  geen enkele POST naar /api/transfer/ gedaan.
- De site zelf is de bron van waarheid voor transfers_left en budget -- niet
  perioden.csv of prijzen.csv, die kunnen achterlopen. Vraagt besluit.json om
  meer transfers dan de site nu toestaat, of kost het meer dan rest_budget,
  dan stopt dit script VOOR er iets wordt aangeraakt.
- Elke transfer wordt individueel bevestigd door de site (result.error moet
  false zijn); bij een fout stopt het script direct met de overige transfers
  ongedaan (niet geprobeerd), zodat er nooit een half doorgevoerde ronde
  achterblijft zonder duidelijke melding.

Gebruik:
    python inleggen.py besluit.json                # DRY_RUN staat aan by default
    DRY_RUN=nee python inleggen.py besluit.json     # daadwerkelijk inleggen

Vereiste env-variabelen: CVHJ_GEBRUIKER, CVHJ_WACHTWOORD (GitHub Secrets in
wekelijks.yml). DRY_RUN volgt de GitHub variable met dezelfde naam.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASIS = "https://www.coachvanhetjaar.nl"
LOGIN_URL = BASIS + "/accounts/login/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}
HIER = Path(__file__).parent


def laad_cvhj_model():
    """Voor norm()/norm_club() -- consistente naamnormalisatie met de rest
    van het project, in plaats van een eigen (mogelijk afwijkende) variant."""
    spec = importlib.util.spec_from_file_location("cvhj_model", HIER / "cvhj_model.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def inloggen(sessie, gebruiker, wachtwoord):
    """Logt in op /accounts/login/ door het formulier LIVE te ontleden --
    geen geraden veldnamen (zie moduledocstring). Retourneert niets; gooit
    RuntimeError met een duidelijke reden als het niet lukt.
    """
    r = sessie.get(LOGIN_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    form = None
    for f in soup.find_all("form"):
        if f.find("input", {"type": "password"}):
            form = f
            break
    if form is None:
        raise RuntimeError(
            f"geen inlogformulier met een wachtwoordveld gevonden op {LOGIN_URL} -- "
            f"de site heeft mogelijk de inlogpagina gewijzigd (bijvoorbeeld naar "
            f"alleen-OAuth). Controleer dit handmatig in de browser.")

    velden = {}
    wachtwoord_naam = None
    gebruiker_naam = None
    for inp in form.find_all("input"):
        naam = inp.get("name")
        if not naam:
            continue
        typ = (inp.get("type") or "text").lower()
        velden[naam] = inp.get("value", "")
        if typ == "password" and wachtwoord_naam is None:
            wachtwoord_naam = naam
        elif typ in ("email", "text") and gebruiker_naam is None and typ != "hidden":
            gebruiker_naam = naam
    if wachtwoord_naam is None or gebruiker_naam is None:
        raise RuntimeError(
            f"kon het gebruikers- of wachtwoordveld niet herkennen in het formulier "
            f"op {LOGIN_URL} (gevonden velden: {sorted(velden)}). Handmatig checken.")

    velden[gebruiker_naam] = gebruiker
    velden[wachtwoord_naam] = wachtwoord

    actie = form.get("action") or LOGIN_URL
    actie = urljoin(LOGIN_URL, actie)
    resp = sessie.post(actie, data=velden, headers={**HEADERS, "Referer": LOGIN_URL},
                       timeout=30)
    resp.raise_for_status()

    if "sessionid" not in sessie.cookies.get_dict() and "/accounts/login" in resp.url:
        raise RuntimeError(
            "inloggen lijkt mislukt: geen sessionid-cookie na de POST, en de site "
            "stuurde niet door weg van de inlogpagina. Meestal: verkeerd wachtwoord "
            "of de site vraagt onverwacht om een tweede stap (2FA/captcha) -- dat "
            "kan dit script niet automatisch afhandelen.")


def csrf_header(sessie):
    token = sessie.cookies.get("csrftoken")
    if not token:
        # Nog niet gezet door de login-POST zelf: een gewone GET forceert het.
        sessie.get(BASIS + "/api/teams/all/", headers=HEADERS, timeout=30)
        token = sessie.cookies.get("csrftoken")
    if not token:
        raise RuntimeError(
            "geen csrftoken-cookie gevonden na inloggen -- zonder dat token "
            "weigert de site elke wijzigende aanroep. Mogelijk is de "
            "cookienaam gewijzigd; controleer dit handmatig in de browser "
            "(Application-tab, Cookies).")
    return {"X-CSRFToken": token}


def haal_clubs(sessie):
    r = sessie.get(BASIS + "/api/teams/all/", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return {t["id"]: t["full_name"] for t in r.json()["teams"]}


def haal_preparation(sessie, ronde):
    r = sessie.get(BASIS + f"/api/team/preparation/?round_seq={ronde}",
                   headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def haal_hele_markt(sessie, ronde, pagina_grootte_probeer=1000):
    """Alle spelers uit /api/players/search_all/, gepagineerd. Probeert eerst
    een grote page_size in één keer; valt terug op de daadwerkelijke paginering
    die de site teruggeeft als die groter blijkt te zijn afgedwongen."""
    spelers = []
    pagina = 1
    page_size = pagina_grootte_probeer
    while True:
        r = sessie.get(
            BASIS + f"/api/players/search_all/{ronde}/",
            params={"page": pagina, "page_size": page_size, "sort": "-total_points"},
            headers=HEADERS, timeout=30)
        r.raise_for_status()
        d = r.json()
        spelers.extend(d["players"])
        pag = d.get("pagination", {})
        totaal_paginas = pag.get("total_pages", 1)
        try:
            page_size = int(pag.get("per_page", page_size))
        except (TypeError, ValueError):
            pass
        if pagina >= totaal_paginas:
            break
        pagina += 1
    return spelers


def norm_sleutel(m, naam, club_naam):
    return f"{m.norm(naam)}|{m.norm(m.norm_club(club_naam))}"


def zoek_speler(m, kaart, naam, club):
    return kaart.get(norm_sleutel(m, naam, club))


def main():
    m = laad_cvhj_model()

    if len(sys.argv) < 2:
        sys.exit("gebruik: python inleggen.py besluit.json")
    besluit = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

    ronde = besluit["ronde"]
    advies = besluit.get("advies")
    if not advies or not (advies.get("uit") or advies.get("in")):
        print("Geen transfer geadviseerd deze ronde -- niets om in te leggen.")
        return

    droog = os.environ.get("DRY_RUN", "ja").strip().lower() not in ("nee", "no", "false", "0")
    gebruiker = os.environ.get("CVHJ_GEBRUIKER")
    wachtwoord = os.environ.get("CVHJ_WACHTWOORD")
    if not gebruiker or not wachtwoord:
        sys.exit("CVHJ_GEBRUIKER en/of CVHJ_WACHTWOORD ontbreken (env-variabelen / GitHub Secrets).")

    print(f"Ronde {ronde}: {len(advies['uit'])} transfer(s) uit besluit.json "
          f"({'DRY RUN -- er wordt niets ingelegd' if droog else 'LIVE'})")

    sessie = requests.Session()
    print("Inloggen...")
    inloggen(sessie, gebruiker, wachtwoord)
    print("  ingelogd.")

    clubs = haal_clubs(sessie)
    prep = haal_preparation(sessie, ronde)
    print(f"Huidig team: {prep['team_name']!r}  "
          f"transfers over: {prep['num_transfers_left']}  "
          f"restbudget: EUR {prep['rest_budget']/1_000_000:.2f}")
    if not prep["is_valid"]:
        print(f"  LET OP van de site zelf: {prep['valid_msg']}")

    huidige_kaart = {}
    for entry in prep["players"]:
        p = entry["player"]
        huidige_kaart[norm_sleutel(m, p["name"], clubs[p["club_id"]])] = p

    print("Hele markt ophalen voor de 'IN'-spelers...")
    markt = haal_hele_markt(sessie, ronde)
    print(f"  {len(markt)} spelers in de markt.")
    markt_kaart = {norm_sleutel(m, p["name"], clubs[p["club_id"]]): p for p in markt}

    paren = []
    fouten = []
    for x in advies["uit"]:
        p = zoek_speler(m, huidige_kaart, x["speler"], x["club"])
        if p is None:
            fouten.append(f"UIT-speler niet gevonden in je huidige team op de site: "
                          f"{x['speler']} ({x['club']})")
        paren.append(("uit", x, p))
    for x in advies["in"]:
        p = zoek_speler(m, markt_kaart, x["speler"], x["club"])
        if p is None:
            fouten.append(f"IN-speler niet gevonden in de markt op de site: "
                          f"{x['speler']} ({x['club']})")
        paren.append(("in", x, p))

    if fouten:
        for f in fouten:
            print(f"  FOUT: {f}")
        sys.exit("Kan niet veilig doorgaan: niet alle spelers zijn eenduidig "
                 "gekoppeld aan spelers op de site. Er is niets ingelegd.")

    uit_lijst = [(x, p) for kant, x, p in paren if kant == "uit"]
    in_lijst = [(x, p) for kant, x, p in paren if kant == "in"]

    if len(uit_lijst) != len(in_lijst):
        sys.exit(f"besluit.json heeft een ongelijk aantal UIT ({len(uit_lijst)}) en "
                 f"IN ({len(in_lijst)}) spelers -- dat zou nooit mogen. Niets ingelegd.")

    aantal = len(uit_lijst)
    if aantal > prep["num_transfers_left"]:
        sys.exit(f"besluit.json wil {aantal} transfer(s), maar de site staat er nu nog "
                 f"maar {prep['num_transfers_left']} toe. Niets ingelegd -- controleer "
                 f"of er al handmatig een transfer is gedaan deze ronde.")

    netto_kosten = (sum(p["value"] for _, p in in_lijst) -
                    sum(p["value"] for _, p in uit_lijst))
    if netto_kosten > prep["rest_budget"]:
        sys.exit(f"Netto kosten (EUR {netto_kosten/1_000_000:.2f}) overschrijden het "
                 f"restbudget (EUR {prep['rest_budget']/1_000_000:.2f}) volgens de site "
                 f"zelf. Niets ingelegd.")

    print(f"\nGeplande transfer(s) (ronde {ronde}):")
    for (x_uit, p_uit), (x_in, p_in) in zip(uit_lijst, in_lijst):
        verschil = p_uit["value"] - x_uit["prijs"] * 1_000_000
        if abs(verschil) > 10_000:  # meer dan 1 cent verschil -- prijzen.csv loopt achter
            print(f"    (LET OP: prijs van {x_uit['speler']} op de site wijkt af van "
                  f"besluit.json: EUR {p_uit['value']/1_000_000:.2f} vs {x_uit['prijs']:.2f})")
        print(f"    UIT  {x_uit['speler']:26s} (id {p_uit['fantasyplayer_id']})  "
              f"-> IN  {x_in['speler']:26s} (id {p_in['fantasyplayer_id']})")

    if droog:
        print("\nDRY RUN: er is niets naar coachvanhetjaar.nl gestuurd. Zet "
              "DRY_RUN=nee om dit daadwerkelijk in te leggen.")
        return

    print()
    for (x_uit, p_uit), (x_in, p_in) in zip(uit_lijst, in_lijst):
        url = (BASIS + f"/api/transfer/{ronde}/sell/{p_uit['fantasyplayer_id']}"
               f"/buy/{p_in['fantasyplayer_id']}/?auto_change_formation=true&sub=false")
        r = sessie.post(url, json={}, headers={**HEADERS, **csrf_header(sessie),
                                               "Referer": f"{BASIS}/app/{ronde}",
                                               "Origin": BASIS})
        try:
            d = r.json()
        except ValueError:
            d = {}
        ok = r.status_code == 200 and not d.get("result", {}).get("error", True)
        if not ok:
            melding = d.get("result", {}).get("msg", f"HTTP {r.status_code}")
            sys.exit(f"Transfer UIT {x_uit['speler']} / IN {x_in['speler']} is MISLUKT "
                     f"op de site: {melding}. Gestopt -- controleer handmatig welke "
                     f"transfers al wel zijn doorgevoerd voor dit punt.")
        print(f"  OK: UIT {x_uit['speler']} / IN {x_in['speler']} -- "
              f"{d.get('result', {}).get('msg', 'gelukt')}")

    prep_na = haal_preparation(sessie, ronde)
    print(f"\nKlaar. Transfers over: {prep_na['num_transfers_left']}  "
          f"restbudget: EUR {prep_na['rest_budget']/1_000_000:.2f}  "
          f"team geldig: {prep_na['is_valid']} ({prep_na['valid_msg']})")


if __name__ == "__main__":
    main()
