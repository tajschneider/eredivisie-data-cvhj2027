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

    # --- opstellingspagina van een club
    slug, club = next(iter(s.CLUB_SLUG.items()))
    try:
        elf, afw = s.parse_opstelling(s.get(s.OPSTELLING_URL.format(slug=slug)),
                                     club)
    except Exception as e:
        r.fout("opstelling", "pagina niet te lezen", f"{type(e).__name__}: {e}")
        elf, afw = [], []
    r.meet("bron_basis", len(elf))
    r.meet("bron_afwezig", len(afw))
    r.eis(len(elf) == BASIS_PER_CLUB, "opstelling",
          f"{club}: {len(elf)} spelers in de vermoedelijke basiself",
          f"verwacht {BASIS_PER_CLUB}; de spelerslinks of het afwezigenblok "
          f"worden niet goed afgebakend")
    met_kans = [e for e in elf if e["kans_basis"] != ""]
    r.eis(len(met_kans) >= BASIS_PER_CLUB - 2, "opstelling",
          f"{len(met_kans)} van {len(elf)} met een basiskans",
          "het percentage naast de speler is niet meer te vinden")
    # Zowel een onder- als een bovengrens. Alleen "minstens een" eisen was te
    # zwak: PSV kwam op 15 afwezigen omdat het blok doorliep in de FAQ, die
    # dezelfde spelers nog eens in gewone tekst noemt. Een speler die onterecht
    # als afwezig wordt gemerkt valt volledig uit de pool, dus dit moet opvallen.
    r.eis(1 <= len(afw) <= 12, "opstelling",
          f"{len(afw)} afwezigen met reden",
          "'Niet beschikbaar' of de namen eronder zijn niet gevonden"
          if not afw else
          f"{len(afw)} is te veel voor een selectie — het afwezigenblok loopt "
          f"waarschijnlijk door in de rest van de pagina")
    if afw:
        r.eis(all(a["reden"] in REDENEN - {""} for a in afw), "opstelling",
              "elke afwezige heeft een bekende reden",
              f"zonder of met onbekende reden: "
              f"{[a['speler_id'] for a in afw if a['reden'] not in REDENEN - {''}][:5]}")
        overlap = {a["speler_id"] for a in afw} & {e["speler_id"] for e in elf}
        r.eis(not overlap, "opstelling",
              "geen speler zowel afwezig als in de basis",
              f"beide: {sorted(overlap)[:5]}")

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

    # --- kaartenranglijsten
    for naam, url, kolom in (("geel", s.GEEL_URL, "gele kaarten"),
                             ("rood", s.ROOD_URL, "rode kaarten")):
        try:
            kk = s.parse_kaartenlijst(s.get(url), kolom)
        except Exception as e:
            r.fout("kaarten", f"{naam} niet te lezen", f"{type(e).__name__}: {e}")
            continue
        r.meet(f"bron_kaarten_{naam}", len(kk))
        r.eis(len(kk) >= 5, "kaarten", f"{naam}: {len(kk)} spelers",
              f"de tabel met kop '{kolom}' is niet gevonden of leeg")
        if kk:
            r.eis(all(c for _, c, _ in kk.values()), "kaarten",
                  f"{naam}: club bij elke speler",
                  "de clublink in de rij is gewijzigd")


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

    met_kans = [x for x in rijen if str(x.get("kans_winst", "")).strip() != ""]
    met_xg = [x for x in rijen if str(x.get("xg_voor", "")).strip() != ""]
    r.meet("clubs_met_kansen", len(met_kans))
    r.meet("clubs_met_xg", len(met_xg))
    if met_kans:
        aandeel = len(met_xg) / len(met_kans)
        r.eis(aandeel >= 0.9, "clubs.csv",
              f"{len(met_xg)} van {len(met_kans)} rijen met kansen heeft ook "
              f"verwachte goals",
              "de verwachte goals worden op veel pagina's niet gevonden")


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


def controleer_rondes(r):
    rijen = _lees("spelers.csv", r, verplicht=False)
    if not rijen:
        r.waarschuw("spelers.csv", "nog geen ronderijen",
                    "normaal na de eerste run; het verschil tussen twee "
                    "seizoensstanden bestaat dan nog niet")
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
        controleer_rondes(r)
        controleer_afwezigen(r)
        controleer_opstellingen(r)
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
