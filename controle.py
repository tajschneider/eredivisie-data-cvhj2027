#!/usr/bin/env python3
"""
Controleren of de scrape nog klopt.

Twee soorten controle, met een verschillende vraag:

  --bron   Werkt de scraper nog op de pagina's zoals ze NU zijn? Elke parser
           wordt op een echte pagina gezet en de uitkomst moet plausibel zijn.
           Dit is de kanarie: toen pouletips in oktober de wedstrijdpagina's
           ombouwde, liep de scraper weken leeg zonder een enkele foutmelding,
           omdat 'geen uitslag gevonden' net zo stil is als 'nog niet
           gespeeld'. Deze controle had dat de eerste maandag gemeld.

  --data   Is wat er in de CSV's staat intern consistent? Spiegeling tussen
           de twee rijen van een wedstrijd, kansen die optellen tot 100,
           seizoenstotalen die nooit dalen, minuten die niet boven de 90 per
           ronde komen, en hoe oud de nieuwste gegevens zijn.

Gebruik:
    python controle.py                 # beide
    python controle.py --bron
    python controle.py --data
    python controle.py --data --soft    # altijd exitcode 0

Afloop: exitcode 1 bij een FOUT, 0 bij alleen WAARSCHUWING. Er komt een
controle.md (om te lezen) en een controle.json (om te meten) naast te staan.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import scrape_eredivisie as s

HIER = Path(__file__).parent
VANDAAG = time.strftime("%Y-%m-%d")

# verwachtingen die uit de spelregels en de competitie volgen
DUELS_PER_RONDE = 9
CLUBS = 18
BASIS_PER_CLUB = 11
MIN_SPELERS = 400          # de index telde 504 op 19-10-2026
MAX_DAGEN_OUD = 8
REDENEN = {"blessure", "schorsing", "vertrokken", "ziek", "twijfel",
           "persoonlijk", "transfer", ""}


class Rapport:
    def __init__(self):
        self.regels = []
        self.meting = {}

    def _voeg(self, niveau, groep, tekst, detail=""):
        self.regels.append((niveau, groep, tekst, detail))
        vlag = {"OK": "ok  ", "WAARSCHUWING": "waarsch", "FOUT": "FOUT"}[niveau]
        # Het detail is de uitleg bij een FOUT. Dat ook onder een geslaagde
        # controle afdrukken leverde regels op als "ok ... minder dan 400",
        # wat zichzelf tegenspreekt en het logboek onleesbaar maakt.
        toon = detail if niveau != "OK" else ""
        print(f"  {vlag:8s} {groep}: {tekst}"
              + (f"\n           {toon}" if toon else ""))

    def ok(self, groep, tekst, detail=""):
        self._voeg("OK", groep, tekst, detail)

    def waarschuw(self, groep, tekst, detail=""):
        self._voeg("WAARSCHUWING", groep, tekst, detail)

    def fout(self, groep, tekst, detail=""):
        self._voeg("FOUT", groep, tekst, detail)

    def eis(self, goed, groep, tekst, detail=""):
        (self.ok if goed else self.fout)(groep, tekst, detail)
        return goed

    def meet(self, naam, waarde):
        self.meting[naam] = waarde

    @property
    def fouten(self):
        return [r for r in self.regels if r[0] == "FOUT"]

    @property
    def waarschuwingen(self):
        return [r for r in self.regels if r[0] == "WAARSCHUWING"]

    def schrijf(self, pad_md, pad_json):
        n_f, n_w = len(self.fouten), len(self.waarschuwingen)
        kop = ("GEFAALD" if n_f else ("MET WAARSCHUWINGEN" if n_w else "GOED"))
        uit = [f"# Controle scrape — {kop}", "",
               f"Uitgevoerd {VANDAAG}. {n_f} fout(en), {n_w} waarschuwing(en), "
               f"{len(self.regels)} controles.", ""]
        if n_f:
            uit += ["## Fouten", ""]
            for _, g, t, d in self.fouten:
                uit.append(f"- **{g}** — {t}" + (f"  \n  {d}" if d else ""))
            uit.append("")
        if n_w:
            uit += ["## Waarschuwingen", ""]
            for _, g, t, d in self.waarschuwingen:
                uit.append(f"- **{g}** — {t}" + (f"  \n  {d}" if d else ""))
            uit.append("")
        uit += ["## Metingen", "", "| Meting | Waarde |", "|---|---|"]
        for k, v in sorted(self.meting.items()):
            uit.append(f"| {k} | {v} |")
        uit += ["", "## Alle controles", "", "| Uitkomst | Groep | Controle |",
                "|---|---|---|"]
        for n, g, t, _ in self.regels:
            uit.append(f"| {n} | {g} | {t} |")
        Path(pad_md).write_text("\n".join(uit) + "\n", encoding="utf-8")
        Path(pad_json).write_text(json.dumps(
            {"datum": VANDAAG, "fouten": n_f, "waarschuwingen": n_w,
             "controles": len(self.regels), "uitkomst": kop,
             "metingen": self.meting,
             "fout_details": [{"groep": g, "tekst": t, "detail": d}
                              for _, g, t, d in self.fouten]},
            indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# =========================================================== bron (de kanarie)
def controleer_bron(r):
    """Elke parser op een echte pagina zetten en de uitkomst beoordelen.

    Met opzet via de parsers zelf en niet via losse regexjes: zo kan de
    controle niet uit de pas gaan lopen met wat de scraper werkelijk doet.
    """
    # --- uitslagen
    try:
        duels = s.parse_uitslagen(s.get(s.UITSLAGEN_URL))
    except Exception as e:
        r.fout("uitslagen", "pagina niet te lezen", f"{type(e).__name__}: {e}")
        return
    r.meet("bron_duels", len(duels))
    gespeeld = [d for d in duels if d["thuis_goals"] is not None]
    r.meet("bron_duels_gespeeld", len(gespeeld))
    r.eis(len(duels) >= DUELS_PER_RONDE, "uitslagen",
          f"{len(duels)} wedstrijden gevonden",
          "minder dan een hele ronde: de rijen worden niet meer herkend")
    r.eis(bool(gespeeld), "uitslagen",
          f"{len(gespeeld)} wedstrijden met uitslag",
          "geen enkele uitslag herkend — het scorepatroon is veranderd")
    clubs = {d["thuis"] for d in duels} | {d["uit"] for d in duels}
    onbekend = clubs - set(s.CLUB_SLUG.values())
    # ook eisen dat er clubs ZIJN: op een leeg resultaat was "0 clubnamen
    # allemaal bekend" eerder vacuüm waar en dus misleidend groen
    r.eis(clubs and not onbekend, "uitslagen",
          f"{len(clubs)} clubnamen allemaal bekend",
          f"onbekend: {sorted(onbekend)} — vul CLUB_ALIAS aan" if onbekend
          else "geen enkele club herkend")
    rondes = {d["ronde"] for d in duels}
    r.eis(len(rondes) >= 1, "uitslagen", f"ronden gevonden: {min(rondes)}-{max(rondes)}"
          if rondes else "geen ronden", "geen ronde uit de rijen of de koppen te halen")

    # --- wedstrijdpagina: liefst een nog niet gespeeld duel, want daar moeten
    #     de kansen en de verwachte goals in staan
    open_ = [d for d in duels if d["thuis_goals"] is None] or duels
    w, d0 = {}, None
    if not open_:
        # Geen enkel duel herkend. Niet afbreken: de spelersindex, de
        # opstellingen en de kaarten staan op andere pagina's en kunnen nog
        # wel gecontroleerd worden. Dat maakt het rapport bruikbaar in plaats
        # van alleen "stuk".
        r.fout("wedstrijd", "geen wedstrijd-URL om te controleren",
               "de uitslagenpagina leverde geen duel op; de overige "
               "controles zijn wel gedaan")
    else:
        d0 = open_[0]
        try:
            w = s.parse_wedstrijd(s.get(d0["url"]), d0["thuis"], d0["uit"])
        except Exception as e:
            r.fout("wedstrijd", "pagina niet te lezen",
                   f"{type(e).__name__}: {e}")
    if w and d0:
        wie = f"{d0['thuis']} - {d0['uit']}"
        xg_v, xg_t = w.get("xg_thuis", ""), w.get("xg_uit", "")
        r.eis(xg_v != "" and xg_t != "", "wedstrijd",
              f"verwachte goals gelezen ({wie}: {xg_v} / {xg_t})",
              "'Verwachte goals <club> <getal>' niet gevonden")
        if xg_v != "" and xg_t != "":
            r.meet("bron_xg_thuis", xg_v)
            r.eis(0.2 <= float(xg_v) <= 5.0 and 0.2 <= float(xg_t) <= 5.0,
                  "wedstrijd", "verwachte goals in een plausibel bereik",
                  f"{xg_v} / {xg_t} valt buiten 0,2-5,0")
        kw, kg, ku = (w.get("kans_thuis", ""), w.get("kans_gelijk", ""),
                      w.get("kans_uit", ""))
        if r.eis(kw != "" and kg != "" and ku != "", "wedstrijd",
                 f"kansen gelezen ({kw}/{kg}/{ku})",
                 "de drie percentages met hun labels zijn niet gevonden"):
            som = int(kw) + int(kg) + int(ku)
            r.meet("bron_kansen_som", som)
            r.eis(99 <= som <= 101, "wedstrijd", f"kansen tellen op tot {som}",
                  "dit is geen kansendrieling meer")
        r.eis(w.get("beide_scoren") != "", "wedstrijd",
              f"beide ploegen scoren {w.get('beide_scoren')}%",
              "'Beide ploegen scoren' niet gevonden")
        r.eis(w.get("over_25") != "", "wedstrijd",
              f"meer dan 2,5 goals {w.get('over_25')}%",
              "'Meer dan 2,5 goals' niet gevonden")

    # --- opstellingspagina's van ALLE clubs
    #
    # Eerst stond hier een steekproef van een: next(iter(CLUB_SLUG)). Dat is
    # te weinig voor deze pagina. De opstellingsparser is drie keer omgevallen
    # op een gewijzigde bron, en een steekproef van een club zegt niets over de
    # andere zeventien -- een club die als enige afwijkt, levert geen
    # opstelling op en dat zie je dan nergens. Achttien pagina's kosten met de
    # verplichte pauze van 1,2 seconde ongeveer 22 seconden extra, drie keer
    # per week. Dat is de prijs van weten.
    #
    # Gerapporteerd wordt een SAMENVATTING en niet achttien keer hetzelfde
    # blok. Vier eisen over achttien clubs, met per eis alleen de clubs die
    # afwijken erbij. Negentig regels waarvan er tweeentachtig "ok" zeggen is
    # geen rapport maar ruis, en dan lees je ook de acht die ertoe doen niet.
    per_club, stuk = {}, {}
    for slug, club in s.CLUB_SLUG.items():
        try:
            per_club[club] = s.parse_opstelling(
                s.get(s.OPSTELLING_URL.format(slug=slug)), club)
        except Exception as e:
            stuk[club] = f"{type(e).__name__}: {e}"
            per_club[club] = ([], [])
    r.meet("bron_clubs_bekeken", len(per_club))

    # Een onbereikbare pagina is iets anders dan een pagina die anders is
    # geworden: de eerste kan aan het netwerk liggen, de tweede is werk.
    r.eis(not stuk, "opstelling",
          f"alle {len(per_club)} opstellingspagina's opgehaald",
          f"niet te lezen: {', '.join(f'{c} ({f})' for c, f in list(stuk.items())[:4])}")

    goed_elf = [c for c, (elf, _) in per_club.items() if len(elf) == BASIS_PER_CLUB]
    mis_elf = {c: len(elf) for c, (elf, _) in per_club.items()
               if len(elf) != BASIS_PER_CLUB}
    r.meet("bron_basis_clubs", len(goed_elf))
    eerste = next(iter(s.CLUB_SLUG))
    r.eis(not mis_elf, "opstelling",
          f"{len(goed_elf)} van {len(per_club)} clubs met {BASIS_PER_CLUB} spelers "
          f"in de vermoedelijke basiself",
          f"afwijkend: {', '.join(f'{c} ({n})' for c, n in sorted(mis_elf.items()))}. "
          f"De scraper levert voor zo'n club NIETS af, dus opstellingen.csv blijft "
          f"er leeg voor. Draai de debug op "
          f"{s.OPSTELLING_URL.format(slug=eerste)} (of op de club hierboven) en "
          f"kijk naar KOPPEN (staat 'Verwachte opstelling' er nog?) en "
          f"SPELERSLINKS (hoeveel uniek?). Bij 0: de kop is weg of de namen zijn "
          f"geen links meer. Bij meer dan {BASIS_PER_CLUB}: het blok loopt door "
          f"in een ander deel van de pagina")

    # De basiskans is een METING en geen eis. Op 23-10-2026 heeft de bron de
    # percentages per speler van de opstellingspagina gehaald: de elf staat er
    # nog, als veldopstelling met avatars, maar zonder enig getal per speler.
    # Dit als fout blijven melden zou een controle opleveren die nooit meer
    # groen kan worden, en zo'n controle leert je het hele rapport te negeren --
    # dezelfde fout als de twee permanent brandende waarschuwingen van vorige
    # week.
    #
    # Dat dit niets blokkeert, is geen berusting maar het gevolg van een keuze:
    # het model gebruikt het percentage niet als kans. Het bleek er geen te
    # zijn (129 spelers die alle zes ronden begonnen kregen gemiddeld 0,83 en
    # maximaal 0,92), dus alleen het LIDMAATSCHAP van de elf weegt mee, en dat
    # staat er nog. Zet de bron de percentages terug, dan ziet deze meting dat
    # en pakt de scraper ze weer op.
    #
    # Een GEDEELTELIJKE vulling blijft wel een fout, en per club: de ene helft
    # met en de andere zonder percentage betekent dat je niet weet welke helft
    # je ziet.
    met_kans = {c: len([e for e in elf if e["kans_basis"] != ""])
                for c, (elf, _) in per_club.items() if elf}
    r.meet("bron_basiskans_clubs", sum(1 for n in met_kans.values() if n))
    half = {c: n for c, n in met_kans.items()
            if 0 < n < BASIS_PER_CLUB - 2}
    if met_kans and not any(met_kans.values()):
        r.ok("opstelling",
             f"geen basiskans per speler, bij alle {len(met_kans)} clubs",
             "de bron publiceert het percentage niet meer; het model rekent er niet "
             "mee, alleen met wie er in de elf staat")
    else:
        # De kopregel moet zelf zeggen wat er mis is. "basiskans aanwezig bij
        # 18 van 18 clubs" naast een FOUT leest als een geslaagde controle, en
        # dan sla je het detail over waar het probleem in staat.
        r.eis(not half, "opstelling",
              (f"basiskans bij {len(half)} club(s) maar gedeeltelijk gevuld"
               if half else
               f"basiskans aanwezig bij {sum(1 for n in met_kans.values() if n)} van "
               f"{len(met_kans)} clubs"),
              f"gedeeltelijk gevuld: {', '.join(f'{c} ({n})' for c, n in sorted(half.items()))}"
              f" -- dan is onduidelijk welke helft je ziet")

    # Zowel een onder- als een bovengrens, en per club. Alleen "minstens een"
    # eisen was te zwak: PSV kwam op 15 afwezigen omdat het blok doorliep in de
    # FAQ, die dezelfde spelers nog eens in gewone tekst noemt. Een speler die
    # onterecht als afwezig wordt gemerkt valt volledig uit de pool, dus dit
    # moet opvallen. Een club ZONDER afwezigen is overigens niet vreemd -- een
    # fitte selectie bestaat -- dus de ondergrens geldt over het geheel en niet
    # per club.
    tel_afw = {c: len(afw) for c, (_, afw) in per_club.items()}
    teveel = {c: n for c, n in tel_afw.items() if n > 12}
    r.meet("bron_afwezig_totaal", sum(tel_afw.values()))
    r.eis(sum(tel_afw.values()) > 0 and not teveel, "opstelling",
          f"{sum(tel_afw.values())} afwezigen met reden over {len(tel_afw)} clubs "
          f"({sum(1 for n in tel_afw.values() if n)} clubs met minstens een)",
          f"meer dan 12 bij: {', '.join(f'{c} ({n})' for c, n in sorted(teveel.items()))}"
          f" -- het afwezigenblok loopt daar door in de rest van de pagina"
          if teveel else
          f"nul afwezigen over alle {len(tel_afw)} clubs. Een naam telt alleen als "
          f"er een reden achter staat ({', '.join(s.REDEN_WOORDEN[:3])}, ...). Draai "
          f"de debug op {s.OPSTELLING_URL.format(slug=eerste)} en kijk onder welke "
          f"kop de blessures nu staan")

    vreemd = {c: sorted({a["reden"] for a in afw} - REDENEN)
              for c, (_, afw) in per_club.items()
              if {a["reden"] for a in afw} - REDENEN}
    r.eis(not vreemd, "opstelling", "elke afwezige heeft een bekende reden",
          f"onbekende reden bij: {', '.join(f'{c} {v}' for c, v in sorted(vreemd.items())[:4])}")

    dubbel = {c: sorted({a["speler_id"] for a in afw} & {e["speler_id"] for e in elf})
              for c, (elf, afw) in per_club.items()
              if {a["speler_id"] for a in afw} & {e["speler_id"] for e in elf}}
    r.eis(not dubbel, "opstelling", "geen speler zowel afwezig als in de basis",
          f"beide bij: {', '.join(f'{c} {v[:3]}' for c, v in sorted(dubbel.items())[:4])}")

    # --- spelersindex
    try:
        index = s.parse_spelersindex(s.get(s.SPELERS_URL))
    except Exception as e:
        r.fout("spelersindex", "pagina niet te lezen", f"{type(e).__name__}: {e}")
        index = []
    r.meet("bron_spelers", len(index))
    r.eis(len(index) >= MIN_SPELERS, "spelersindex",
          f"{len(index)} spelers gevonden",
          f"minder dan {MIN_SPELERS}: de index is niet volledig gelezen")
    r.eis(len({c for _, _, c, _ in index}) == CLUBS, "spelersindex",
          f"{len({c for _, _, c, _ in index})} clubs",
          "niet alle achttien clubs herkend")
    r.eis(len({p for _, _, _, p in index}) == 4, "spelersindex",
          "vier posities herkend",
          "de kopjes Keepers/Verdedigers/Middenvelders/Aanvallers zijn gewijzigd")

    # --- spelerspagina, een veldspeler en een keeper
    for positie, verwacht in (("Forward", "assists"), ("Goalkeeper", "reddingen")):
        kand = [x for x in index if x[3] == positie]
        if not kand:
            continue
        slug2, naam = kand[0][0], kand[0][1]
        try:
            v = s.parse_speler(s.get(s.SPELER_URL.format(slug=slug2),
                                     toestaan_404=True))
        except Exception as e:
            r.fout("speler", f"{naam} niet te lezen", f"{type(e).__name__}: {e}")
            continue
        gevonden = set(v.get("_gevonden", "").split(","))
        r.eis("minuten" in gevonden and "duels" in gevonden, "speler",
              f"{naam}: {v['duels']} duels, {v['minuten']} minuten",
              "de seizoenstabel of de losse labels zijn gewijzigd")
        # Op de kolom zelf toetsen, niet op de waarde: een lege teller wordt
        # in de scraper op nul gezet, en dan lijkt een verdwenen kolom precies
        # op een speler zonder assists.
        r.eis(verwacht in gevonden, "speler",
              f"{naam}: {verwacht} gelezen ({v[verwacht]})",
              f"de kolom '{verwacht}' staat niet meer op de pagina van een "
              f"{positie} — hij zou stil op nul worden gezet")

    # --- CVHJ-spelerslijst met prijzen
    try:
        soup_p = s.get(s.PRIJZEN_URL)
        pr = s.parse_poule_prijzen(soup_p)
    except Exception as e:
        r.fout("prijslijst", "pagina niet te lezen", f"{type(e).__name__}: {e}")
        pr = []
    gm = re.search(r"Alle\s+(\d{2,4})\s+spelers",
                   re.sub(r"\s+", " ", s.vlak(soup_p)) if pr else "")
    r.meet("bron_prijzen", len(pr))
    if gm:
        verwacht = int(gm.group(1))
        r.meet("bron_prijzen_gemeld", verwacht)
        r.eis(len(pr) >= verwacht * 0.95, "prijslijst",
              f"{len(pr)} van de {verwacht} aangekondigde spelers gelezen",
              "de rijen van de CVHJ-spelerslijst worden niet meer herkend")
    else:
        r.eis(len(pr) >= 400, "prijslijst", f"{len(pr)} spelers gelezen",
              "minder dan 400 en de pagina zegt niet hoeveel er horen te staan")
    if pr:
        r.eis(len({c for _, _, c, _, _ in pr}) == CLUBS, "prijslijst",
              f"{len({c for _, _, c, _, _ in pr})} clubs",
              f"verwacht {CLUBS}")
        r.eis(len({p for _, _, _, p, _ in pr}) == 4, "prijslijst",
              "vier posities herkend",
              f"gevonden: {sorted({p for _, _, _, p, _ in pr})}")
        r.eis(all(sid for sid, _, _, _, _ in pr), "prijslijst",
              "elke rij heeft een speler_id",
              "zonder id moet de koppeling op naam en dat is foutgevoelig")
        # Of dat id uit een link komt of uit de naam is geraden, staat in het
        # logboek van de scraper. Wat het werkelijk waard is, meet de
        # datacontrole: die zet prijzen.csv naast de gescrapete spelers en
        # rapporteert de koppelgraad. Daar hoort dit thuis, niet hier.
        r.eis(all(p in ("Goalkeeper", "Defender", "Midfielder", "Forward")
                  for _, _, _, p, _ in pr), "prijslijst",
              "posities omgezet naar het Engels",
              "de Nederlandse positienamen worden niet meer herkend")

    # --- kaartenranglijsten
    for naam, url, kolom in (("geel", s.GEEL_URL, "gele kaarten"),
                             ("rood", s.ROOD_URL, "rode kaarten")):
        try:
            soup = s.get(url)
            kk = s.parse_kaartenlijst(soup, kolom)
        except Exception as e:
            r.fout("kaarten", f"{naam} niet te lezen", f"{type(e).__name__}: {e}")
            continue
        r.meet(f"bron_kaarten_{naam}", len(kk))

        # Tegen wat de pagina zelf aankondigt afzetten in plaats van tegen een
        # verzonnen drempel. Rode kaarten zijn na negen ronden intrinsiek
        # zeldzaam (4 van 4); een vaste ondergrens verklaarde die lijst
        # onterecht stuk en zou '12 van de 40 gelezen' juist doorlaten.
        toon, totaal = s.gemeld_aantal(soup)
        if toon:
            r.meet(f"bron_kaarten_{naam}_gemeld", f"{toon} van {totaal}")
            r.eis(len(kk) >= max(1, int(toon * 0.9)), "kaarten",
                  f"{naam}: {len(kk)} rijen gelezen van de {toon} "
                  f"aangekondigde (lijst telt {totaal} spelers)",
                  f"de pagina kondigt {toon} rijen aan maar er zijn er "
                  f"{len(kk)} gelezen — de afstand tussen naam en aantal klopt "
                  f"niet meer")
        else:
            r.eis(len(kk) >= 1, "kaarten", f"{naam}: {len(kk)} spelers",
                  f"geen rijen gevonden op {url} en de pagina zegt ook niet "
                  f"hoeveel er horen te staan. Draai de debug erop: staat er "
                  f"'GEEN spelerslink in de ruwe HTML', dan wordt de lijst in "
                  f"de browser ingeladen en is hij met requests niet te halen")
        if kk:
            met_club = sum(1 for _, c, _ in kk.values() if c)
            if met_club < len(kk) * 0.8:
                # Geen fout: deze clubnaam wordt nergens gebruikt. Het model
                # haalt de club van een speler uit de spelersindex, en uit deze
                # lijst alleen het aantal kaarten. Blokkeren op een veld dat
                # niemand leest hield de hele run tegen.
                r.waarschuw("kaarten",
                            f"{naam}: club bij {met_club} van {len(kk)} spelers",
                            "deze clubnaam wordt niet gebruikt — het model haalt "
                            "de club uit de spelersindex — dus dit blokkeert niets")


# ================================================================ data in csv
def _f(x):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _lees(naam, r, verplicht=True):
    pad = HIER / naam
    if not pad.exists():
        (r.fout if verplicht else r.waarschuw)(naam, "bestand ontbreekt")
        return []
    rijen = s.lees(pad)
    r.meet(f"rijen_{naam}", len(rijen))
    if not rijen and verplicht:
        r.fout(naam, "bestand is leeg")
    return rijen


def controleer_clubs(r):
    rijen = _lees("clubs.csv", r)
    if not rijen:
        return
    sleutels = [(x["ronde"], x["club"]) for x in rijen]
    dubbel = {k for k in sleutels if sleutels.count(k) > 1}
    r.eis(not dubbel, "clubs.csv", "geen dubbele ronde/club",
          f"dubbel: {sorted(dubbel)[:6]}")

    per_ronde = {}
    for x in rijen:
        per_ronde.setdefault(x["ronde"], []).append(x)

    # Volume eerst. Alle controles hieronder zijn relationeel en blijven groen
    # op twee rijen; juist een scrape die bijna niets oplevert moet opvallen.
    # De competitie heeft achttien clubs en dus negen duels per ronde, en de
    # scraper schrijft een rij per club per duel, ook zonder uitslag.
    alle_clubs = {x["club"] for x in rijen}
    r.meet("clubs_verschillend", len(alle_clubs))
    r.eis(len(alle_clubs) == CLUBS, "clubs.csv",
          f"{len(alle_clubs)} verschillende clubs in het bestand",
          f"verwacht {CLUBS}; mist {sorted(set(s.CLUB_SLUG.values()) - alle_clubs)}")
    te_klein = {k: len(v) for k, v in per_ronde.items()
                if not 16 <= len(v) <= 20}
    r.eis(not te_klein, "clubs.csv",
          f"elke ronde ongeveer {CLUBS} rijen ({len(per_ronde)} ronden)",
          f"afwijkend aantal rijen per ronde: {te_klein} — verwacht "
          f"{DUELS_PER_RONDE} duels x 2")
    scheef = {k: len(v) for k, v in per_ronde.items() if len(v) != CLUBS
              and 16 <= len(v) <= 20}
    if scheef:
        r.waarschuw("clubs.csv", f"ronden met net niet {CLUBS} rijen: {scheef}",
                    "een verplaatst duel kan dit geven")

    spiegelfout, kansfout, logicafout, xgfout = [], [], [], []
    volledig = 0
    for ronde, groep in sorted(per_ronde.items(), key=lambda t: int(t[0] or 0)):
        gespeeld = [x for x in groep if str(x.get("voor", "")).strip() != ""]
        if gespeeld:
            if len(gespeeld) == CLUBS:
                volledig += 1
            else:
                r.waarschuw("clubs.csv", f"ronde {ronde}: {len(gespeeld)}/{CLUBS} "
                            f"clubs met uitslag", "uitgesteld duel of een gemiste wedstrijd")
        op_club = {x["club"]: x for x in groep}
        for x in groep:
            tegen = op_club.get(x["tegenstander"])
            if tegen is None:
                spiegelfout.append(f"r{ronde} {x['club']}: tegenstander "
                                   f"{x['tegenstander']} ontbreekt")
                continue
            # spiegeling: wat voor de een 'voor' is, is voor de ander 'tegen'
            for a, b in (("voor", "tegen"), ("kans_winst", "kans_verlies"),
                         ("xg_voor", "xg_tegen"), ("verwacht_voor", "verwacht_tegen")):
                p, q = _f(x.get(a)), _f(tegen.get(b))
                if p is not None and q is not None and abs(p - q) > 0.011:
                    spiegelfout.append(f"r{ronde} {x['club']}: {a}={p} maar "
                                       f"{x['tegenstander']}.{b}={q}")
            kg1, kg2 = _f(x.get("kans_gelijk")), _f(tegen.get("kans_gelijk"))
            if kg1 is not None and kg2 is not None and abs(kg1 - kg2) > 1.01:
                spiegelfout.append(f"r{ronde} {x['club']}: gelijkspelkans "
                                   f"{kg1} vs {kg2}")
            # kansen tellen op tot 100
            k = [_f(x.get(c)) for c in ("kans_winst", "kans_gelijk", "kans_verlies")]
            if all(v is not None for v in k) and not 99 <= sum(k) <= 101:
                kansfout.append(f"r{ronde} {x['club']}: som {sum(k):.0f}")
            # verwachte goals plausibel
            for c in ("xg_voor", "xg_tegen"):
                v = _f(x.get(c))
                if v is not None and not 0.15 <= v <= 5.5:
                    xgfout.append(f"r{ronde} {x['club']}: {c}={v}")
            # uitslag, resultaat, ploegpunten en clean sheet moeten rijmen
            gf, gc = _f(x.get("voor")), _f(x.get("tegen"))
            if gf is not None and gc is not None:
                res = "W" if gf > gc else ("G" if gf == gc else "V")
                ppt = 3 if res == "W" else (1 if res == "G" else 0)
                if x.get("resultaat") != res:
                    logicafout.append(f"r{ronde} {x['club']}: {gf:.0f}-{gc:.0f} "
                                      f"maar resultaat {x.get('resultaat')}")
                if _f(x.get("ploegpunten")) not in (None, ppt):
                    logicafout.append(f"r{ronde} {x['club']}: {res} maar "
                                      f"{x.get('ploegpunten')} ploegpunten")
                if _f(x.get("clean_sheet")) not in (None, float(gc == 0)):
                    logicafout.append(f"r{ronde} {x['club']}: {gc:.0f} tegen maar "
                                      f"clean_sheet {x.get('clean_sheet')}")

    r.meet("clubs_volledige_ronden", volledig)
    r.eis(not spiegelfout, "clubs.csv", "thuis- en uitrij spiegelen",
          "; ".join(spiegelfout[:5]))
    r.eis(not kansfout, "clubs.csv", "kansen tellen op tot 100",
          "; ".join(kansfout[:5]))
    r.eis(not xgfout, "clubs.csv", "verwachte goals plausibel",
          "; ".join(xgfout[:5]))
    r.eis(not logicafout, "clubs.csv",
          "uitslag, resultaat, ploegpunten en clean sheet rijmen",
          "; ".join(logicafout[:5]))

    # Een wedstrijd die nog niet is gespeeld kan geen uitslag hebben. Deze
    # controle ontbrak, en dat heeft 225 voorspelde uitslagen als echte
    # uitslagen in het bestand laten belanden: de bron zet bij een komend duel
    # een voorspelde stand in dezelfde rij.
    gespeeld = [x for x in rijen if str(x.get("voor", "")).strip() != ""]
    onspeeld = [x for x in rijen if str(x.get("voor", "")).strip() == ""]
    r.meet("clubs_rijen_met_uitslag", len(gespeeld))
    vroeg = [f"r{x['ronde']} {x['club']} ({x.get('datum')})" for x in gespeeld
             if x.get("datum", "") > VANDAAG]
    r.eis(not vroeg, "clubs.csv",
          "geen uitslag bij een wedstrijd in de toekomst",
          f"{len(vroeg)} rijen met een uitslag terwijl de datum nog moet "
          f"komen: {vroeg[:5]} — mogelijk wordt een voorspelde stand als "
          f"uitslag gelezen")

    # Verwachte goals zijn een vooruitblik: ze staan op de pagina van een
    # KOMEND duel. Na de wedstrijd verdwijnen ze, en dan valt het model terug
    # op het terugrekenen uit de kansen. De eis geldt dus alleen voor duels
    # die nog gespeeld moeten worden; eerder toetste ik het over alle rijen en
    # dat verklaarde een normale situatie onterecht stuk.
    met_kans = [x for x in rijen if str(x.get("kans_winst", "")).strip() != ""]
    met_xg = [x for x in rijen if str(x.get("xg_voor", "")).strip() != ""]
    r.meet("clubs_met_kansen", len(met_kans))
    r.meet("clubs_met_xg", len(met_xg))
    komend_kans = [x for x in onspeeld
                   if str(x.get("kans_winst", "")).strip() != ""]
    komend_xg = [x for x in komend_kans
                 if str(x.get("xg_voor", "")).strip() != ""]
    r.meet("clubs_komend_met_xg", f"{len(komend_xg)} van {len(komend_kans)}")
    # De bron vult de verwachte goals per WEDSTRIJD aan naarmate de ronde
    # nadert, en haalt ze na afloop weg. Gemeten op 19-10-2026: 0 van 162
    # gespeelde rijen, 18 van 18 bij de eerstvolgende ronde, 0 van 18 bij de
    # ronde daarna (PSV - Willem II had kansen maar geen verwachte goals,
    # Ajax - AZ wel). Het model rekent met de eerstvolgende ronde, dus daar is
    # de eis hard; verder vooruit is het nieuws en geen gebrek.
    ronden_open = sorted({int(x["ronde"]) for x in onspeeld
                          if str(x.get("ronde", "")).isdigit()})
    if ronden_open:
        eerste = ronden_open[0]
        r.meet("clubs_eerstvolgende_ronde", eerste)
        nu_rijen = [x for x in komend_kans if str(x.get("ronde")) == str(eerste)]
        nu_xg = [x for x in nu_rijen if str(x.get("xg_voor", "")).strip() != ""]
        r.meet("clubs_eerstvolgende_met_xg", f"{len(nu_xg)} van {len(nu_rijen)}")
        if nu_rijen:
            zonder = sorted(x["club"] for x in nu_rijen
                            if str(x.get("xg_voor", "")).strip() == "")
            r.eis(len(nu_xg) >= len(nu_rijen) * 0.9, "clubs.csv",
                  f"verwachte goals bij {len(nu_xg)} van de {len(nu_rijen)} "
                  f"rijen van ronde {eerste}, de eerstvolgende",
                  f"zonder verwachte goals: {zonder[:6]}"
                  f"{', ...' if len(zonder) > 6 else ''} — dit is de ronde "
                  f"waarmee het model rekent, dus hier moeten ze staan")
        else:
            r.waarschuw("clubs.csv",
                        f"ronde {eerste} heeft nog geen kansen",
                        "de wedstrijdpagina's van de eerstvolgende ronde zijn "
                        "nog niet opgehaald")

        later = [x for x in komend_kans if str(x.get("ronde")) != str(eerste)]
        later_xg = [x for x in later if str(x.get("xg_voor", "")).strip() != ""]
        if later:
            # Alleen als meting, niet als waarschuwing. De bron heeft ze daar
            # per definitie nog niet, dus deze melding zou elke run afgaan —
            # en een waarschuwing die altijd aanstaat leert je het rapport
            # niet meer te lezen. Dat ondermijnt de hele controle.
            r.meet("clubs_verder_vooruit_met_xg",
                   f"{len(later_xg)} van {len(later)}")
    gespeeld_xg = sum(1 for x in gespeeld
                      if str(x.get("xg_voor", "")).strip() != "")
    r.meet("clubs_gespeeld_met_xg", f"{gespeeld_xg} van {len(gespeeld)}")


def controleer_seizoen(r):
    rijen = _lees("spelers_seizoen.csv", r)
    if not rijen:
        return None
    standen = sorted({x.get("opgehaald", "") for x in rijen})
    r.meet("seizoen_momentopnamen", len(standen))
    laatste = standen[-1]
    nu = [x for x in rijen if x.get("opgehaald") == laatste]
    r.meet("seizoen_spelers_laatste", len(nu))
    r.eis(len(nu) >= MIN_SPELERS, "spelers_seizoen.csv",
          f"{len(nu)} spelers in de stand van {laatste}",
          f"minder dan {MIN_SPELERS}")
    r.eis(len({x["club"] for x in nu}) == CLUBS, "spelers_seizoen.csv",
          f"{len({x['club'] for x in nu})} clubs",
          "niet alle achttien clubs")

    onzin = []
    for x in nu:
        d, m, b = _f(x.get("duels")), _f(x.get("minuten")), _f(x.get("basisplaatsen"))
        if d is None or m is None:
            continue
        if m > d * 100 + 10:
            onzin.append(f"{x['speler_id']}: {m:.0f}' in {d:.0f} duels")
        if b is not None and b > d:
            onzin.append(f"{x['speler_id']}: {b:.0f} basis in {d:.0f} duels")
        for c in ("goals", "assists", "geel", "rood"):
            v = _f(x.get(c))
            if v is not None and v < 0:
                onzin.append(f"{x['speler_id']}: {c}={v}")
    r.eis(not onzin, "spelers_seizoen.csv", "tellers intern consistent",
          "; ".join(onzin[:5]))

    # Seizoenstotalen kunnen niet dalen. Dit is de scherpste regressietest die
    # er is: gaat de parser ergens de mist in, dan zakt een teller.
    if len(standen) >= 2:
        vorige, dalers = standen[-2], []
        oud = {x["speler_id"]: x for x in rijen if x.get("opgehaald") == vorige}
        for x in nu:
            v = oud.get(x["speler_id"])
            if not v:
                continue
            for c in ("duels", "minuten", "goals", "assists", "geel", "rood",
                      "basisplaatsen", "reddingen"):
                a, b = _f(x.get(c)), _f(v.get(c))
                if a is not None and b is not None and a < b:
                    dalers.append(f"{x['speler_id']}.{c}: {b:.0f} -> {a:.0f}")
        r.meet("seizoen_dalende_tellers", len(dalers))
        r.eis(not dalers, "spelers_seizoen.csv",
              f"geen dalende seizoenstotalen tussen {vorige} en {laatste}",
              "; ".join(dalers[:6]) + " — een teller kan niet omlaag; "
              "waarschijnlijk is er een parser stuk of een speler van club gewisseld")
    return laatste


def controleer_rondes(r, momentopnamen=1):
    # Zonder waarschuwing lezen: hieronder volgt één melding in plaats van
    # twee over dezelfde situatie ("bestand ontbreekt" plus "nog geen
    # ronderijen").
    pad = HIER / "spelers.csv"
    rijen = s.lees(pad) if pad.exists() else []
    r.meet("rijen_spelers.csv", len(rijen))
    if not rijen:
        if momentopnamen and momentopnamen < 2:
            # Dit hóórt zo na de eerste run: productie per ronde is het
            # verschil tussen twee seizoensstanden, en die tweede komt pas
            # volgende week. Geen waarschuwing, anders staat ze er altijd.
            r.ok("spelers.csv", "nog geen ronderijen, en dat hoort zo",
                 "")
        else:
            # FOUT en geen waarschuwing. Zonder dit bestand bouwt bouw_pool()
            # een LEGE pool -- geen enkele speler haalt de speeltijddrempel --
            # en dan is er geen advies, alleen een nette lege uitvoer. Op
            # 23-10-2026 stond hier een waarschuwing, en de scrape legde
            # vrolijk vast terwijl het bestand van de runner verdwenen was.
            # Een waarschuwing laat de run doorgaan; dat hoort hier niet.
            #
            # Twee momentopnamen zonder ronde ertussen is een geldige reden dat
            # het verschil niets oplevert -- maar dan hoort het BESTAAND
            # bestand te blijven staan, niet te verdwijnen. Dat het er niet is
            # terwijl er twee standen zijn, betekent dat er iets is weggehaald.
            r.fout("spelers.csv", "geen ronderijen terwijl er wel twee "
                   "seizoensstanden zijn",
                   "zonder dit bestand is de pool leeg en is er geen advies. "
                   "Het verschil tussen de twee standen leverde niets op, of het "
                   "bestand is tijdens de run verplaatst of verwijderd. Kijk in "
                   "de scrape-uitvoer bij 'venster ... -> ...' of er een ronde "
                   "tussen de twee standen gespeeld is, en of spelers.csv nog "
                   "in de repo staat")
        return
    # Eerst het kolomformaat. Een bestand uit de vorige opzet levert anders een
    # onbegrijpelijke lijst dubbelen op, terwijl het echte probleem is dat het
    # bestand van vóór de ombouw is.
    nodig = {"ronde", "speler_id", "club", "minuten", "goals", "assists",
             "geel", "venster"}
    mist = nodig - set(rijen[0])
    if mist:
        r.fout("spelers.csv", "oud kolomformaat",
               f"deze kolommen missen: {sorted(mist)}. Dit bestand komt uit de "
               f"vorige opzet; de scraper zet het bij de volgende volledige run "
               f"apart als spelers_vorig_formaat.csv. De ronderijen beginnen "
               f"opnieuw bij de tweede momentopname.")
        return

    sleutels = [(x.get("ronde"), x.get("speler_id"), x.get("club")) for x in rijen]
    dubbel = {k for k in sleutels if sleutels.count(k) > 1}
    r.eis(not dubbel, "spelers.csv", "geen dubbele ronde/speler/club",
          f"dubbel: {sorted(dubbel)[:4]}")

    per_ronde = {}
    for x in rijen:
        per_ronde.setdefault(x.get("ronde"), []).append(x)
    r.meet("ronderijen_ronden", len(per_ronde))
    leeg = [x for x in rijen if str(x.get("ronde", "")).strip() == ""]
    r.eis(not leeg, "spelers.csv", "elke rij heeft een ronde",
          f"{len(leeg)} rijen zonder ronde")

    onzin = []
    for x in rijen:
        n_rondes = max(1, len([v for v in str(x.get("venster", "")).split(",") if v]))
        grens = 95 * n_rondes
        m = _f(x.get("minuten"))
        if m is not None and m > grens:
            onzin.append(f"r{x.get('ronde')} {x.get('speler_id')}: {m:.0f}' "
                         f"over {n_rondes} ronde(n)")
        for c, max_ in (("goals", 5), ("assists", 5), ("geel", 2), ("rood", 1)):
            v = _f(x.get(c))
            if v is not None and v > max_ * n_rondes:
                onzin.append(f"r{x.get('ronde')} {x.get('speler_id')}: {c}={v:.0f}")
            if v is not None and v < 0:
                onzin.append(f"r{x.get('ronde')} {x.get('speler_id')}: {c}={v:.0f}")
    r.eis(not onzin, "spelers.csv", "minuten en productie per ronde plausibel",
          "; ".join(onzin[:5]))

    for ronde, groep in sorted(per_ronde.items(), key=lambda t: int(t[0] or 0)):
        spelers = len([x for x in groep if (_f(x.get("minuten")) or 0) > 0])
        if spelers < CLUBS * BASIS_PER_CLUB * 0.7:
            r.waarschuw("spelers.csv", f"ronde {ronde}: {spelers} spelers met "
                        f"speeltijd", f"verwacht rond {CLUBS * BASIS_PER_CLUB} "
                        f"basisspelers plus invallers")
    breed = [v for v in per_ronde.values()
             if len({str(x.get("venster", "")) for x in v}) and
             any("," in str(x.get("venster", "")) for x in v)]
    if breed:
        r.waarschuw("spelers.csv", f"{len(breed)} ronde(n) met meer dan een "
                    "ronde in het venster",
                    "productie is dan niet exact aan een ronde toe te rekenen")


def controleer_afwezigen(r):
    rijen = _lees("afwezigen.csv", r, verplicht=False)
    if not rijen:
        return
    laatste = max(x.get("opgehaald", "") for x in rijen)
    nu = [x for x in rijen if x.get("opgehaald") == laatste]
    r.meet("afwezigen_laatste", len(nu))
    r.meet("afwezigen_clubs", len({x["club"] for x in nu}))
    onbekend = {x.get("reden", "") for x in nu} - REDENEN
    r.eis(not onbekend, "afwezigen.csv", "alle redenen bekend",
          f"onbekend: {sorted(onbekend)}")
    zonder = CLUBS - len({x["club"] for x in nu})
    if zonder > 3:
        r.waarschuw("afwezigen.csv", f"{zonder} clubs zonder afwezigen",
                    "mogelijk worden de blessureblokken niet meer gevonden")
    slecht = [x["speler_id"] for x in nu
              if x.get("verwacht_terug") and
              not re.fullmatch(r"\d{4}-\d{2}-\d{2}", x["verwacht_terug"])]
    r.eis(not slecht, "afwezigen.csv", "terugkeerdatums in ISO-vorm",
          f"afwijkend: {slecht[:5]}")


def controleer_opstellingen(r):
    rijen = _lees("opstellingen.csv", r, verplicht=False)
    if not rijen:
        return
    laatste = max(x.get("opgehaald", "") for x in rijen)
    nu = [x for x in rijen if x.get("opgehaald") == laatste]
    per_club = {}
    for x in nu:
        per_club.setdefault(x["club"], []).append(x)
    r.meet("opstellingen_clubs", len(per_club))
    r.eis(len(per_club) == CLUBS, "opstellingen.csv", f"{len(per_club)} clubs",
          "niet alle achttien clubs")
    mis = {c: len(v) for c, v in per_club.items() if len(v) != BASIS_PER_CLUB}
    r.eis(not mis, "opstellingen.csv", f"elke club {BASIS_PER_CLUB} basisspelers",
          f"afwijkend: {mis}")
    buiten = [x["speler_id"] for x in nu
              if (_f(x.get("kans_basis")) or 0) > 100 or
              (x.get("kans_basis") != "" and (_f(x.get("kans_basis")) or 0) < 0)]
    r.eis(not buiten, "opstellingen.csv", "basiskansen tussen 0 en 100",
          f"afwijkend: {buiten[:5]}")


def controleer_prijzen(r):
    """prijzen.csv, en vooral: koppelt het aan de gescrapete spelers?

    Een speler die niet koppelt kan het model niet kopen, hoe goed hij ook
    speelt. Met de CVHJ-lijst uit de bron staat het speler_id erin en hoort de
    koppeling vrijwel volledig te zijn; met de oude bevroren sheet lag die op
    tweederde.
    """
    rijen = _lees("prijzen.csv", r, verplicht=False)
    if not rijen:
        r.waarschuw("prijzen.csv", "ontbreekt",
                    "zonder prijslijst kan het model niet rekenen; draai "
                    "scrape_eredivisie.py --prijzen")
        return
    r.meet("prijzen_spelers", len(rijen))
    r.meet("prijzen_clubs", len({x["team"] for x in rijen}))
    r.eis(len({x["team"] for x in rijen}) == CLUBS, "prijzen.csv",
          f"{len({x['team'] for x in rijen})} clubs",
          f"verwacht {CLUBS}")
    posities = {x["positie"] for x in rijen}
    r.eis(posities == {"Goalkeeper", "Defender", "Midfielder", "Forward"},
          "prijzen.csv", "vier posities in het Engels",
          f"gevonden: {sorted(posities)}")
    slecht = [x.get("speler") for x in rijen
              if (_f(x.get("prijs")) or 0) < 0.5 or (_f(x.get("prijs")) or 0) > 10]
    r.eis(not slecht, "prijzen.csv", "prijzen in een plausibel bereik",
          f"afwijkend: {slecht[:5]}")
    ids = [x.get("speler_id") or "" for x in rijen]
    dubbel = {i for i in ids if i and ids.count(i) > 1}
    r.eis(not dubbel, "prijzen.csv", "geen dubbele speler_id",
          f"dubbel: {sorted(dubbel)[:5]}")

    # een geldige selectie moet binnen het budget kunnen
    goedkoop = sorted(_f(x.get("prijs")) or 99 for x in rijen)[:15]
    r.meet("prijzen_goedkoopste15", round(sum(goedkoop), 2))
    r.eis(sum(goedkoop) <= 32.0, "prijzen.csv",
          f"vijftien goedkoopste spelers kosten {sum(goedkoop):.2f}",
          "boven het budget van 32,00: dan bestaat er geen geldige selectie")

    # de koppeling
    seizoen = _lees("spelers_seizoen.csv", r, verplicht=False)
    if not seizoen:
        return
    laatste = max(x.get("opgehaald", "") for x in seizoen)
    bron = {(x["speler_id"], x["club"]) for x in seizoen
            if x.get("opgehaald") == laatste}
    met_id = [x for x in rijen if x.get("speler_id")]
    raak = [x for x in met_id if (x["speler_id"], x["team"]) in bron]
    if met_id:
        aandeel = len(raak) / len(met_id)
        r.meet("prijzen_koppelgraad",
               f"{len(raak)} van {len(met_id)} ({round(100 * aandeel)}%)")
        r.eis(aandeel >= 0.9, "prijzen.csv",
              f"{len(raak)} van de {len(met_id)} prijsrijen koppelt aan een "
              f"gescrapete speler ({round(100 * aandeel)}%)",
              "wie niet koppelt kan het model niet kopen. Komt de prijslijst "
              "uit de CVHJ-sheet in plaats van uit de bron, dan is dit "
              "normaal; draai scrape_eredivisie.py --prijzen voor de actuele "
              "lijst met speler_id erin")
    else:
        r.waarschuw("prijzen.csv", "geen speler_id in het bestand",
                    "de koppeling gaat dan op naam en dat is foutgevoelig; "
                    "draai scrape_eredivisie.py --prijzen")


def controleer_versheid(r):
    data = []
    for naam in ("clubs.csv", "spelers_seizoen.csv", "afwezigen.csv",
                 "opstellingen.csv"):
        pad = HIER / naam
        if not pad.exists():
            continue
        d = max((x.get("opgehaald", "") for x in s.lees(pad)), default="")
        if d:
            data.append((naam, d))
    if not data:
        r.fout("versheid", "geen enkele ophaaldatum gevonden")
        return
    nieuwste = max(d for _, d in data)
    r.meet("nieuwste_ophaaldatum", nieuwste)
    try:
        oud = (time.mktime(time.strptime(VANDAAG, "%Y-%m-%d"))
               - time.mktime(time.strptime(nieuwste, "%Y-%m-%d"))) / 86400
    except ValueError:
        r.fout("versheid", f"ophaaldatum onleesbaar: {nieuwste}")
        return
    r.meet("dagen_oud", int(oud))
    r.eis(oud <= MAX_DAGEN_OUD, "versheid",
          f"nieuwste gegevens zijn {int(oud)} dag(en) oud",
          f"ouder dan {MAX_DAGEN_OUD} dagen: de scrape levert niets meer op "
          f"terwijl hij wel groen afsluit")
    for naam, d in sorted(data):
        if d != nieuwste:
            r.waarschuw("versheid", f"{naam} loopt achter ({d} tegen {nieuwste})",
                        "normaal bij een lichte run, verdacht na een volledige")


# ======================================================================= main
def main():
    global HIER
    p = argparse.ArgumentParser()
    p.add_argument("--bron", action="store_true", help="de live pagina's")
    p.add_argument("--data", action="store_true", help="de CSV's")
    p.add_argument("--soft", action="store_true", help="altijd exitcode 0")
    p.add_argument("--map", help="map met de CSV's (standaard: naast dit script)")
    a = p.parse_args()
    if a.map:
        HIER = Path(a.map)
    doe_bron = a.bron or not (a.bron or a.data)
    doe_data = a.data or not (a.bron or a.data)

    r = Rapport()
    if doe_bron:
        print("BRON — werken de parsers nog op de pagina's van vandaag?")
        controleer_bron(r)
    if doe_data:
        print("\nDATA — is wat er in de CSV's staat consistent?")
        controleer_clubs(r)
        controleer_seizoen(r)
        # het aantal momentopnamen bepaalt of ontbrekende ronderijen normaal
        # zijn: het verschil bestaat pas vanaf de tweede stand
        controleer_rondes(r, r.meting.get("seizoen_momentopnamen", 1))
        controleer_afwezigen(r)
        controleer_opstellingen(r)
        controleer_prijzen(r)
        controleer_versheid(r)

    r.schrijf(HIER / "controle.md", HIER / "controle.json")
    n_f, n_w = len(r.fouten), len(r.waarschuwingen)
    print(f"\n{'=' * 66}\n{len(r.regels)} controles: {n_f} fout, "
          f"{n_w} waarschuwing")
    if n_f:
        print("\nWat er stuk is:")
        for _, g, t, d in r.fouten:
            print(f"  - {g}: {t}")
            if d:
                print(f"      {d}")
        print("\nDraai `python scrape_eredivisie.py --debug <url>` op de pagina "
              "die hierboven wordt genoemd; dan hoeft er niet geraden te worden.")
    sys.exit(1 if (n_f and not a.soft) else 0)


if __name__ == "__main__":
    main()
