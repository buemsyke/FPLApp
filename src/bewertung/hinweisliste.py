#!/usr/bin/env python3
"""
Hinweisliste im Format der Fachberatung (XLSX und CSV).

Die Hinweise an die Schule stehen nicht im Gutachten (DOCX), sondern in einer
eigenen Tabelle – so, wie die Fachberatung sie bisher verschickt:

    ;;;;;Gewählt:
    Vorschlag A;;Schülermaterial;Lehrermaterial;Hinweise;Überarbeitet am;Herkunft
    1.3.;Skizzieren ist Anforderungsbereich 2;;S. 2;;;Regel [X.5b]
    3;Bitte prüfen, ob die Vorgabe 4.2 (…) erfüllt ist.;S. 7;;…;;Regel [4.2]
    Allgemein;Im Schülermaterial bitte „BE“ statt „Punkte“ verwenden.;S. 2, 3;;;;Regel [X.3]

    Vorschlag B;Keine Anmerkungen

Die Spalte „Überarbeitet am“ füllt die Schule aus. Die Spalte „Herkunft“ ist
intern: Sie zeigt, ob ein Hinweis aus einer festen Regel stammt oder von einem
Sprachmodell (mit Modellname und Konfidenz). KI-Hinweise schwanken stark mit
dem Modell – sie sind in der XLSX gelb hinterlegt und vor dem Versand zu
prüfen; die Spalte wird vor dem Versand gelöscht.

Die Gutachtenliste (Raster im DOCX) wird weiterhin vollständig abgearbeitet:
✔ / ✘ / ? je Kriterium. Was dort „?“ ist, prüft die Fachberatung selbst.
"""

from __future__ import annotations

import contextlib
import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.bewertung.regelbasiert import (
    ABITUR_BEARBEITUNGSZEIT_MIN,
    _KRITERIUM_MATERIAL,
    _formuliere_hoeflich,
    _ordne_ergebnis_aufgaben_zu,
    _seite_fuer_aufgabe,
    begutachte,
    erstelle_aufgabenbezogene_befunde,
)

KONFIDENZ_SCHWELLE = 75

VORGABE_4_2 = ("Bitte prüfen, ob die Vorgabe 4.2 (Jede Teilaufgabe kann, "
               "unabhängig von Fehlleistungen in anderen Aufgaben, gelöst "
               "werden.) erfüllt ist.")

SPALTE_HERKUNFT = "Herkunft (intern – vor Versand löschen)"


# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------

@dataclass
class Hinweis:
    """Eine Zeile der Hinweisliste."""
    aufgabe: str            # "1.3", "2.1a", "3" oder "Allgemein"
    text: str               # Spalte „Hinweis“
    sm_seite: str = ""      # „S. 4“
    lm_seite: str = ""
    zusatz: str = ""        # Spalte „Hinweise“, z. B. „Zur Information.“
    herkunft: str = ""      # „Regel [X.4]“ / „KI [3.3] gemma-4-12b · 85 %“
    ki: bool = False        # True → vor Versand prüfen (gelb)


@dataclass
class HinweisBlock:
    """Alle Hinweise zu einem Vorschlag (eine Überschrift „Vorschlag A“)."""
    titel: str
    hinweise: list[Hinweis] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

_MARKER = ("ABWEICHUNG:", "MANUELL PRÜFEN:", "KI PRÜFT QUALITÄT:", "Vorabcheck:",
           "Bitte manuell prüfen.", "Bitte manuell prüfen,", "Bitte manuell prüfen",
           "Bitte zwingend manuell prüfen!", ">>>")


def _kurz(kommentar: str, max_len: int = 220) -> str:
    """Erste Zeile des Kommentars ohne interne Marker, gekürzt."""
    k = kommentar
    for marker in _MARKER:
        k = k.replace(marker, "")
    k = k.split("\n")[0].strip(" -–.")
    if len(k) > max_len:
        k = k[:max_len].rstrip(" ,;") + " …"
    return k


def _saetze(text: str, anzahl: int = 2, max_len: int = 300) -> str:
    """Die ersten Sätze eines Textes, höchstens max_len Zeichen."""
    teile = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    kurz = " ".join(teile[:anzahl]).strip()
    if len(kurz) > max_len:
        kurz = kurz[:max_len].rstrip(" ,;") + " …"
    return kurz


def _anfz(woerter: list[str]) -> str:
    """„A“, „B“ und „C“"""
    q = [f"„{w}“" for w in woerter]
    return q[0] if len(q) == 1 else ", ".join(q[:-1]) + " und " + q[-1]


def aufgabe_anzeige(nr: str) -> str:
    """Schreibweise wie in den versendeten Listen: „1.3.“ statt „1.3“.

    Der Schlusspunkt verhindert außerdem, dass Excel „1.3“ beim Öffnen
    der CSV in ein Datum umwandelt."""
    return nr + "." if re.fullmatch(r"\d+\.\d+", nr) else nr


def _sortierschluessel(h: Hinweis) -> tuple:
    if h.aufgabe == "Allgemein":
        return (1, ())
    zahlen = tuple(int(z) for z in re.findall(r"\d+", h.aufgabe))
    return (0, zahlen, h.aufgabe)


def _aufgabe_aus_text(text: str) -> str | None:
    m = re.search(r"(?:Teil)?[Aa]ufgabe\s+(\d+(?:\.\d+)*[a-z]?)", text or "")
    return m.group(1) if m else None


def _seite(nr: str, seiten: dict[str, int]) -> str:
    """Seitenangabe für eine (Teil-)Aufgabe; fällt auf die Hauptaufgabe zurück."""
    s = _seite_fuer_aufgabe(nr, seiten)
    if not s:
        basis = re.match(r"\d+(?:\.\d+)?", nr or "")
        if basis:
            s = _seite_fuer_aufgabe(basis.group(0), seiten)
    return s


def erkenne_vorschlag(schueler_text: str = "", dateiname: str = "") -> str:
    """„Vorschlag A“ aus dem Kopf des Schülermaterials oder dem Dateinamen."""
    m = re.search(r"Vorschlag\s+([A-D])\b", (schueler_text or "")[:4000])
    if m:
        return f"Vorschlag {m.group(1)}"
    stem = Path(dateiname).stem if dateiname else ""
    m = re.search(r"(?:Vorschlag|Aufg(?:abe)?)[\s_-]*([A-D])(?![A-Za-z])", stem, re.I)
    if m:
        return f"Vorschlag {m.group(1).upper()}"
    return f"Vorschlag ({stem})" if stem else "Vorschlag"


# ---------------------------------------------------------------------------
# Hinweise aus der regelbasierten Prüfung
# ---------------------------------------------------------------------------

# Kurze Formulierungen im Stil der versendeten Hinweise.
# Wert: (Text mit {k} = gekürzter Kommentar, Zusatz für Spalte „Hinweise“)
_KURZ: dict[str, tuple[str, str]] = {
    "1.1":  ("Bitte das Layout prüfen: {k}.", "Zur Information."),
    "2.5":  ("Das Lehrermaterial enthält keine vollständige Lösung.", ""),
    "4.6":  ("Die Verteilung der Anforderungsbereiche weicht vom Richtwert "
             "(ca. 30 % / 40 % / 30 %) ab: {k}.", ""),
    "X.1":  ("Die erste Teilaufgabe ist Anforderungsbereich 3. Bitte prüfen, ob "
             "ein Einstieg über Anforderungsbereich 1 oder 2 möglich ist.", ""),
    "X.6":  ("Der Schwerpunkt „Informationstechnik“ fehlt im Kopfbereich.", ""),
    "X.7":  ("Verhältnis BE zu Bearbeitungszeit: {k}. Bitte prüfen, ob gemäß der "
             "Vorgabe 4.3 die Bearbeitungszeit angemessen ist.", ""),
    "X.8":  ("Keine Operatoren nach EPA im Erwartungshorizont.", ""),
    "X.10": ("Verteilung der BE auf Operatoren ist nicht nachvollziehbar.", ""),
    "X.13": ("Die Summe der BE im Schülermaterial stimmt nicht mit dem "
             "Erwartungshorizont überein: {k}.", ""),
    "X.15": ("Platzhalter sind noch nicht ausgefüllt: {k}.", ""),
    "X.18": ("Bitte die Nummerierung der Teilaufgaben prüfen: {k}.", ""),
}

# Kriterien mit „?“, die trotzdem einen konkreten Befund enthalten.
# Alle anderen „?“ sind Prüffragen – sie bleiben im Gutachten-Raster.
_OFFEN_MIT_BEFUND = {"4.2", "4.3", "X.3", "X.5b", "X.15", "X.16", "X.17", "X.18"}
_OHNE_BEFUND = ("nicht valide", "übersprungen", "keine eindeutigen",
                "konnte nicht", "nicht prüfbar")

# Kriterien, die erstelle_aufgabenbezogene_befunde() je Aufgabe aufschlüsselt
_JE_AUFGABE = {"X.3", "X.4", "X.9", "X.11", "4.7"}


def _hinweis_allgemein(e) -> Hinweis:
    k = _kurz(e.kommentar)
    nr = e.kriterium_nr
    zusatz = ""
    sm_seite = ""
    if nr == "1.1" and (seiten := re.findall(r"S\.\s*(\d+):", e.kommentar)):
        text = "Lange Zeilen – möglicherweise ist das Layout an diesen Stellen verrutscht."
        sm_seite = "S. " + ", ".join(dict.fromkeys(seiten))
        zusatz = "Zur Information."
    elif nr == "4.3" and (m := re.search(r"Angegebene Bearbeitungszeit:\s*(\d+)", e.kommentar)):
        text = (f"Die Bearbeitungszeit beträgt {m.group(1)} Minuten (Vorgabe: "
                f"{ABITUR_BEARBEITUNGSZEIT_MIN} Minuten). Bitte prüfen, ob gemäß der "
                f"Vorgabe 4.3 die Anforderungen in dieser Zeit angemessen sind.")
    elif nr == "X.13" and (m := re.search(r"SM:\s*(\d+)\s*BE.*?EWH:\s*(\d+)\s*BE", e.kommentar)):
        text = (f"Die Summe der BE stimmt nicht überein: Schülermaterial {m.group(1)} BE, "
                f"Erwartungshorizont {m.group(2)} BE.")
    elif nr == "X.15":
        text = "Platzhalter sind noch nicht ausgefüllt: " + k.replace("Platzhalter gefunden:", "").strip() + "."
    elif nr == "4.5" and (m := re.search(r"Nicht-EPA-Phrasen:\s*(.+)", e.kommentar)):
        phrasen = [p.strip(" .") for p in m.group(1).split(",") if p.strip(" .")]
        verb = "ist kein Operator" if len(phrasen) == 1 else "sind keine Operatoren"
        text = f"{_anfz(phrasen)} {verb} nach EPA."
    elif nr == "X.17" and (m := re.search(r":\s*(.+?)\.\s+[A-ZÄÖÜ]", e.kommentar + ". X")):
        text = f"Folgende Dateien liegen mir nicht vor: {m.group(1)}."
    elif nr == "X.3":
        text = "Im Schülermaterial bitte durchgängig „BE“ statt „Punkte“ verwenden."
    elif nr in _KURZ:
        vorlage, zusatz = _KURZ[nr]
        text = vorlage.format(k=k)
    else:
        text = _formuliere_hoeflich(e)
    return Hinweis("Allgemein", text, sm_seite, zusatz=zusatz, herkunft=f"Regel [{nr}]")


def _teilaufgabe_an_stelle(seite: int, pos: int, aufgaben, sm_seiten, sm_pages) -> str | None:
    """Letzte (Teil-)Aufgabe, die vor Seite/Position beginnt."""
    reihenfolge = [nr for a in aufgaben
                   for nr in [str(a.nummer)] + [t.nummer for t in a.teilaufgaben]]
    treffer = None
    for nr in reihenfolge:
        s_nr = sm_seiten.get(nr)
        if s_nr is None or s_nr > seite:
            continue
        if s_nr == seite:
            anfang = re.search(rf"(?m)^\s*{re.escape(nr)}(?!\d|\.\d)", sm_pages[s_nr - 1])
            if anfang is None or anfang.start() > pos:
                continue
        treffer = nr
    return treffer


def _verorte(muster: re.Pattern, sm_pages, aufgaben, sm_seiten,
             nur_seite: int | None = None) -> tuple[int, str | None] | None:
    """(Seite, Teilaufgabe) der ersten Fundstelle eines Musters."""
    for idx, text in enumerate(sm_pages):
        if nur_seite and idx + 1 != nur_seite:
            continue
        if m := muster.search(text):
            return idx + 1, _teilaufgabe_an_stelle(idx + 1, m.start(), aufgaben, sm_seiten, sm_pages)
    return None


def _hinweise_abhaengigkeit(e, aufgaben, sm_pages, sm_seiten) -> list[Hinweis]:
    """Vorgabe 4.2: Fundstellen aus dem Kommentar einer Teilaufgabe zuordnen."""
    schnipsel = re.findall(r'„(.+?)"(?=\s*\||\s*$)', e.kommentar)
    ergebnis: list[Hinweis] = []
    gesehen: set[tuple] = set()
    for s in schnipsel:
        woerter = s.split()[:5]
        if not woerter:
            continue
        muster = re.compile(r"\s+".join(re.escape(w) for w in woerter))
        fund = _verorte(muster, sm_pages, aufgaben, sm_seiten)
        aufgabe = (fund[1] if fund else None) or "Allgemein"
        bezug = re.search(r"(?:Aufgabe|Teilaufgabe|TA\.?)\s*(\d+(?:[.,]\d+)*)", s)
        schluessel = (aufgabe, bezug.group(1) if bezug else s)
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        text = (f"Die Aufgabe baut auf Aufgabe {bezug.group(1)} auf. " if bezug else "") + VORGABE_4_2
        ergebnis.append(Hinweis(
            aufgabe, text,
            sm_seite=f"S. {fund[0]}" if fund else "",
            zusatz=f"„{s.strip()} …“",
            herkunft="Regel [4.2]",
        ))
    if not ergebnis:
        ergebnis.append(Hinweis("Allgemein", VORGABE_4_2, herkunft="Regel [4.2]"))
    return ergebnis


_ROEMISCH = {"I": "1", "II": "2", "III": "3"}


def _hinweise_afb_zeilen(e, lm_seiten) -> list[Hinweis]:
    """X.5b: „Teilaufgabe 1.2: Operator 'begründen' (korrekt: AFB II)“."""
    hinweise = []
    for m in re.finditer(r"Teilaufgabe\s+(\S+?):\s+Operator\s+'(\w+)'\s+"
                         r"\(korrekt:\s+AFB\s+([IV]+)\)", e.kommentar):
        nr, op, afb = m.groups()
        hinweise.append(Hinweis(
            nr, f"{op.capitalize()} ist Anforderungsbereich {_ROEMISCH.get(afb, afb)}",
            lm_seite=_seite(nr, lm_seiten), herkunft="Regel [X.5b]"))
    for m in re.finditer(r"Teilaufgabe\s+(\S+?):\s+'(\w+)'", e.kommentar):
        nr, op = m.groups()
        hinweise.append(Hinweis(
            nr, f"{op.capitalize()} ist nicht Anforderungsbereich 1. Bitte die "
                f"Zuordnung im Erwartungshorizont prüfen.",
            lm_seite=_seite(nr, lm_seiten), herkunft="Regel [X.5b]"))
    return hinweise


def _hinweise_je_aufgabe(befunde: list[dict], aufgaben=(), sm_seiten=None,
                         sm_pages=()) -> tuple[list[Hinweis], set[str]]:
    """Wandelt erstelle_aufgabenbezogene_befunde() in kurze Hinweise um.

    Die Befunde nennen die erste Aufgabe ihrer Seite; hier wird die Fundstelle
    im Seitentext gesucht und der richtigen Teilaufgabe zugeordnet.
    Gibt (Hinweise, Kriterien mit Befunden je Aufgabe) zurück."""
    sm_seiten = sm_seiten or {}
    hinweise: list[Hinweis] = []
    abgedeckt: set[str] = set()
    punkte_seiten: list[str] = []
    nicht_epa: dict[str, list] = {}

    def genauer(b: dict, muster: str) -> str:
        seite = re.search(r"\d+", b["sm_seite"] or "")
        if not (seite and sm_pages):
            return b["aufgabe"]
        fund = _verorte(re.compile(muster, re.I), sm_pages, aufgaben, sm_seiten,
                        nur_seite=int(seite.group(0)))
        return (fund[1] if fund else None) or b["aufgabe"]

    for b in befunde:
        m = re.match(r"\[([^\]]+)\]", b["kriterium"])
        nr = m.group(1) if m else ""
        abgedeckt.add(nr)
        if nr == "X.3":
            punkte_seiten.append(b["sm_seite"].replace("S. ", ""))
        elif nr == "X.9":
            op = re.search(r"'(\w+)'", b["kriterium"])
            if not op:
                continue
            aufgabe = genauer(b, rf"\b{re.escape(op.group(1))}\w*\s+Sie\b")
            eintrag = nicht_epa.setdefault(aufgabe, [[], b["sm_seite"]])
            eintrag[0].append(op.group(1))
        elif nr == "X.4":
            ops = [o.strip() for o in b["kommentar"].split(":", 1)[-1].split(",") if o.strip()]
            verb = "fehlt" if len(ops) == 1 else "fehlen"
            wort = "Operator" if len(ops) == 1 else "Operatoren"
            aufgabe = genauer(b, rf"\b{re.escape(ops[0][:-1])}\w*\s+Sie\b") if ops else b["aufgabe"]
            hinweise.append(Hinweis(
                aufgabe, f"{wort} {_anfz(ops)} {verb} im Erwartungshorizont.",
                b["sm_seite"], b["lm_seite"], herkunft="Regel [X.4]"))
        elif nr == "X.11":
            hinweise.append(Hinweis(
                b["aufgabe"], b["kommentar"].replace("Mögliche Wiederholungen", "Doppeltes Wort") + ".",
                b["sm_seite"], zusatz="Zur Information.", herkunft="Regel [X.11]"))
        elif nr == "4.7":
            hinweise.append(Hinweis(b["aufgabe"], "Keine BE angegeben.",
                                    b["sm_seite"], herkunft="Regel [4.7]"))

    for aufgabe, (ops, seite) in nicht_epa.items():
        verb = "ist kein Operator" if len(ops) == 1 else "sind keine Operatoren"
        hinweise.append(Hinweis(
            aufgabe, f"{_anfz(ops)} {verb} nach EPA. Bitte ersetzen oder im "
                     f"Lehrermaterial als erweiterten Operator mit "
                     f"Anforderungsbereich aufführen.",
            seite, herkunft="Regel [X.9]"))
    if punkte_seiten:
        hinweise.append(Hinweis(
            "Allgemein", "Im Schülermaterial bitte durchgängig „BE“ statt „Punkte“ verwenden.",
            "S. " + ", ".join(dict.fromkeys(punkte_seiten)), herkunft="Regel [X.3]"))
    return hinweise, abgedeckt


def hinweise_aus_regelpruefung(
    ergebnisse: list,
    aufgaben: list,
    sm_seiten: dict[str, int],
    lm_seiten: dict[str, int],
    sm_pages: list[str] | None = None,
    lm_pages: list[str] | None = None,
) -> list[Hinweis]:
    """Hinweise aus den Ergebnissen von regelbasiert.begutachte()."""
    sm_pages = sm_pages or []
    lm_pages = lm_pages or []
    status = {e.kriterium_nr: e.erfuellt for e in ergebnisse}

    def kriterium(b: dict) -> str:
        m = re.match(r"\[([^\]]+)\]", b["kriterium"])
        return m.group(1) if m else ""

    befunde = []
    if sm_pages or lm_pages:
        # Befund je Aufgabe nur, wenn das Kriterium geprüft und insgesamt
        # nicht erfüllt ist (fehlt es in den Ergebnissen → kein Befund)
        befunde = [
            b for b in erstelle_aufgabenbezogene_befunde(
                aufgaben, sm_pages, lm_pages, sm_seiten, lm_seiten)
            if status.get(kriterium(b), True) is not True
        ]
    hinweise, abgedeckt = _hinweise_je_aufgabe(befunde, aufgaben, sm_seiten, sm_pages)

    for e in ergebnisse:
        nr = e.kriterium_nr
        if e.erfuellt is True:
            continue
        if nr in _JE_AUFGABE and nr in abgedeckt:
            continue
        if e.erfuellt is None:
            k = e.kommentar.lower()
            if nr not in _OFFEN_MIT_BEFUND or any(w in k for w in _OHNE_BEFUND):
                continue
            if nr == "4.3" and "achtung" not in k:
                continue
        if nr == "4.2":
            hinweise.extend(_hinweise_abhaengigkeit(e, aufgaben, sm_pages, sm_seiten))
            continue
        if nr == "X.5b":
            hinweise.extend(_hinweise_afb_zeilen(e, lm_seiten))
            continue

        aufg_nummern = _ordne_ergebnis_aufgaben_zu(e, aufgaben)
        material = _KRITERIUM_MATERIAL.get(nr, "SM")
        vorlage = _hinweis_allgemein(e)
        for aufg in aufg_nummern:
            hinweise.append(Hinweis(
                aufg, vorlage.text,
                vorlage.sm_seite if aufg == "Allgemein" else
                _seite(aufg, sm_seiten) if material in ("SM", "BEIDE") else "",
                _seite(aufg, lm_seiten) if material in ("LM", "BEIDE") and aufg != "Allgemein" else "",
                vorlage.zusatz, vorlage.herkunft))
    return _eindeutig(hinweise)


# ---------------------------------------------------------------------------
# Hinweise aus KI-Prüfung und Lösbarkeit (modellabhängig → gelb, prüfen)
# ---------------------------------------------------------------------------

def hinweise_aus_ki(ki_ergebnisse: list, modell: str = "",
                    schwelle: int = KONFIDENZ_SCHWELLE,
                    sm_seiten: dict[str, int] | None = None) -> list[Hinweis]:
    """Nur Beanstandungen ab der Konfidenzschwelle."""
    sm_seiten = sm_seiten or {}
    hinweise = []
    for e in ki_ergebnisse or []:
        if e.ki_ergebnis != "beanstandung" or (e.konfidenz or 0) < schwelle:
            continue
        fund = " ".join(str(f) for f in (e.fundstellen or []))
        aufgabe = _aufgabe_aus_text(fund) or _aufgabe_aus_text(e.begruendung) or "Allgemein"
        hinweise.append(Hinweis(
            aufgabe, f"{e.kriterium_text}: {_saetze(e.begruendung)}",
            _seite(aufgabe, sm_seiten) if aufgabe != "Allgemein" else "",
            zusatz=_saetze(fund, 1, 160) if fund else "",
            herkunft=f"KI [{e.kriterium_nr}] {modell} · {e.konfidenz} %".replace("  ", " "),
            ki=True))
    return hinweise


def hinweise_aus_loesbarkeit(ergebnisse: list, modell: str = "",
                             sm_seiten: dict[str, int] | None = None,
                             lm_seiten: dict[str, int] | None = None,
                             schwelle: int = KONFIDENZ_SCHWELLE) -> list[Hinweis]:
    """Nicht lösbare Teilaufgaben und fehlerhafte Musterlösungen."""
    sm_seiten = sm_seiten or {}
    lm_seiten = lm_seiten or {}
    hinweise = []
    for e in ergebnisse or []:
        nr = e.teilaufgabe
        if e.loesbarkeit == "nein" and (e.loesbarkeit_konfidenz or 0) >= schwelle:
            fehlt = "; ".join(str(f) for f in e.fehlende_information or [])
            text = "Bitte prüfen, ob alle zur Bearbeitung nötigen Informationen vorliegen."
            if fehlt:
                text += f" Möglicherweise fehlt: {fehlt}."
            hinweise.append(Hinweis(
                nr, text, _seite(nr, sm_seiten),
                zusatz=_saetze(e.loesbarkeit_begruendung, 1, 200),
                herkunft=f"KI-Lösbarkeit {modell} · {e.loesbarkeit_konfidenz} %".replace("  ", " "),
                ki=True))
        if e.richtigkeit == "nein" and (e.richtigkeit_konfidenz or 0) >= schwelle:
            fehler = "; ".join(str(f) for f in e.fehler_in_loesung or [])
            hinweise.append(Hinweis(
                nr, "Bitte die Musterlösung prüfen" + (f": {fehler}." if fehler else "."),
                lm_seite=_seite(nr, lm_seiten),
                zusatz=_saetze(e.richtigkeit_begruendung, 1, 200),
                herkunft=f"KI-Lösbarkeit {modell} · {e.richtigkeit_konfidenz} %".replace("  ", " "),
                ki=True))
    return hinweise


def _eindeutig(hinweise: list[Hinweis]) -> list[Hinweis]:
    gesehen = set()
    ergebnis = []
    for h in hinweise:
        schluessel = (h.aufgabe, h.text)
        if schluessel not in gesehen:
            gesehen.add(schluessel)
            ergebnis.append(h)
    return ergebnis


# ---------------------------------------------------------------------------
# Komfortfunktion: alles für einen Vorschlag
# ---------------------------------------------------------------------------

def regelpruefung_still(schueler_pfad: str, lehrer_pfad: str) -> tuple:
    """begutachte() ohne Konsolenausgabe."""
    with contextlib.redirect_stdout(io.StringIO()):
        return begutachte(schueler_pfad, lehrer_pfad)


def baue_hinweisblock(
    titel: str,
    regel: tuple | None = None,
    ki_ergebnisse: list | None = None,
    loesbarkeit: list | None = None,
    modell: str = "",
) -> HinweisBlock:
    """Fasst alle Quellen zu einem Block „Vorschlag X“ zusammen.

    regel = Rückgabe von begutachte():
            (ergebnisse, analyse, aufgaben, sm_seiten, lm_seiten, sm_pages, lm_pages)
    """
    hinweise: list[Hinweis] = []
    sm_seiten: dict[str, int] = {}
    lm_seiten: dict[str, int] = {}
    if regel is not None:
        ergebnisse, _analyse, aufgaben, sm_seiten, lm_seiten, sm_pages, lm_pages = regel
        hinweise += hinweise_aus_regelpruefung(
            ergebnisse, aufgaben, sm_seiten, lm_seiten, sm_pages, lm_pages)
    hinweise += hinweise_aus_ki(ki_ergebnisse or [], modell, sm_seiten=sm_seiten)
    hinweise += hinweise_aus_loesbarkeit(loesbarkeit or [], modell, sm_seiten, lm_seiten)
    hinweise = _eindeutig(hinweise)
    hinweise.sort(key=_sortierschluessel)
    return HinweisBlock(titel, hinweise)


def hinweisblock_fuer_vorschlag(
    schueler_pfad: str,
    lehrer_pfad: str,
    ki_ergebnisse: list | None = None,
    loesbarkeit: list | None = None,
    modell: str = "",
    regel: tuple | None = None,
    dateiname: str | None = None,
) -> HinweisBlock:
    """Regelprüfung (falls nicht übergeben) + Titel „Vorschlag X“ + Block.

    dateiname: ursprünglicher Name des Schülermaterials (z. B. beim Upload),
    falls der Pfad nur „schueler.pdf“ heißt."""
    if regel is None:
        regel = regelpruefung_still(schueler_pfad, lehrer_pfad)
    sm_pages = regel[5] if len(regel) > 5 else []
    titel = erkenne_vorschlag("\n".join(sm_pages[:2]), dateiname or schueler_pfad)
    return baue_hinweisblock(titel, regel, ki_ergebnisse, loesbarkeit, modell)


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------

def _tabellenzeilen(bloecke: list[HinweisBlock]) -> list[tuple[list[str], str]]:
    """Zeilen der Liste mit Zeilenart: kopf, block, hinweis, ki, leer."""
    n = 7
    zeilen: list[tuple[list[str], str]] = [(["", "", "", "", "", "Gewählt:", ""], "kopf")]
    for i, b in enumerate(bloecke):
        if i:
            zeilen.append(([""] * n, "leer"))
        if not b.hinweise:
            zeilen.append(([b.titel, "Keine Anmerkungen", "", "", "", "", ""], "block"))
            continue
        zeilen.append(([b.titel, "", "Schülermaterial", "Lehrermaterial", "Hinweise",
                        "Überarbeitet am", SPALTE_HERKUNFT], "block"))
        for h in sorted(b.hinweise, key=_sortierschluessel):
            zeilen.append(([aufgabe_anzeige(h.aufgabe), h.text, h.sm_seite, h.lm_seite,
                            h.zusatz, "", h.herkunft], "ki" if h.ki else "hinweis"))
    return zeilen


def schreibe_hinweisliste_csv(bloecke: list[HinweisBlock], pfad: str | Path) -> Path:
    """CSV wie die versendeten Listen: Semikolon, UTF-8 mit BOM (Excel), CRLF."""
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with pfad.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\r\n")
        for zeile, _art in _tabellenzeilen(bloecke):
            w.writerow(zeile)
    return pfad


def schreibe_hinweisliste_xlsx(bloecke: list[HinweisBlock], pfad: str | Path) -> Path:
    """Gleiche Liste als XLSX; KI-Hinweise gelb, Herkunft grau."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Hinweise"

    breiten = {"A": 12, "B": 70, "C": 16, "D": 16, "E": 34, "F": 16, "G": 30}
    for spalte, breite in breiten.items():
        ws.column_dimensions[spalte].width = breite

    duenn = Side(style="thin", color="BFBFBF")
    rahmen = Border(left=duenn, right=duenn, top=duenn, bottom=duenn)
    grau = PatternFill("solid", start_color="D9D9D9", end_color="D9D9D9")
    gelb = PatternFill("solid", start_color="FFF2CC", end_color="FFF2CC")
    oben = Alignment(vertical="top", wrap_text=True)
    herkunft_font = Font(italic=True, size=9, color="7F7F7F")

    for r, (zeile, art) in enumerate(_tabellenzeilen(bloecke), start=1):
        for c, wert in enumerate(zeile, start=1):
            zelle = ws.cell(row=r, column=c, value=wert)
            zelle.number_format = "@"
            zelle.alignment = oben
            if art in ("block", "hinweis", "ki") and (wert or art != "block"):
                zelle.border = rahmen
            if art == "block":
                zelle.font = Font(bold=True)
                if wert:
                    zelle.fill = grau
            elif art == "ki":
                zelle.fill = gelb
            if c == 7 and art in ("hinweis", "ki"):
                zelle.font = herkunft_font

    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    wb.save(pfad)
    return pfad


def schreibe_hinweisliste(bloecke: list[HinweisBlock], basis: str | Path) -> tuple[Path, Path]:
    """Schreibt <basis>.xlsx und <basis>.csv. Gibt beide Pfade zurück."""
    basis = Path(basis)
    if basis.suffix.lower() in (".xlsx", ".csv"):
        basis = basis.with_suffix("")
    return (schreibe_hinweisliste_xlsx(bloecke, basis.with_suffix(".xlsx")),
            schreibe_hinweisliste_csv(bloecke, basis.with_suffix(".csv")))


def zaehle(bloecke: list[HinweisBlock]) -> tuple[int, int]:
    """(Hinweise gesamt, davon KI)."""
    alle = [h for b in bloecke for h in b.hinweise]
    return len(alle), sum(1 for h in alle if h.ki)
