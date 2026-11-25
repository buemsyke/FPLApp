#!/usr/bin/env python3
"""
Automatische Begutachtung von Abiturklausur-Vorschlägen
für das Berufliche Gymnasium - Technik - Informationstechnik.

Prüft Schüler- und Lehrermaterial gegen die Kriterien der Gutachtenvorlage,
die Operatorentabelle und die Hinweise aus Beachte.pdf.

Erzeugt ein ausgefülltes Gutachten als DOCX-Datei.
"""

from __future__ import annotations

import argparse
import copy
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor

# ---------------------------------------------------------------------------
# Operatorentabelle (aus operatoren_tabelle_geprueft.odt)
# ---------------------------------------------------------------------------
OPERATOREN = {
    "beschreiben":          {"afb": ["I"],        "desc": "Sachverhalte oder Zusammenhänge strukturiert und fachsprachlich richtig mit eigenen Worten wiedergeben"},
    "nennen":               {"afb": ["I"],        "desc": "Elemente, Sachverhalte, Begriffe, Daten ohne Erläuterungen aufzählen"},
    "berechnen":            {"afb": ["I", "II"],  "desc": "Ergebnisse von einem bekannten Ansatz ausgehend durch Rechenoperationen oder grafische Lösungsmethoden gewinnen"},
    "bestimmen":            {"afb": ["I", "II"],  "desc": "Ergebnisse von einem bekannten Ansatz ausgehend durch Rechenoperationen oder grafische Lösungsmethoden gewinnen"},
    "darstellen":           {"afb": ["I", "II"],  "desc": "Sachverhalte, Zusammenhänge, Methoden usw. strukturiert darstellen"},
    "erläutern":            {"afb": ["I", "II"],  "desc": "Einen technischen Sachverhalt in einen Zusammenhang einordnen sowie ihn nachvollziehbar und verständlich machen"},
    "erklären":             {"afb": ["I", "II"],  "desc": "Einen technischen Sachverhalt in einen Zusammenhang einordnen sowie ihn nachvollziehbar und verständlich machen"},
    "vergleichen":          {"afb": ["I", "II"],  "desc": "Gemeinsamkeiten, Ähnlichkeiten und Unterschiede ermitteln"},
    "zeichnen":             {"afb": ["I", "II"],  "desc": "Einen technischen Sachverhalt mit zeichnerischen Mitteln unter Einhaltung der genormten Symbole darstellen"},
    "ableiten":             {"afb": ["II"],       "desc": "Auf der Grundlage wesentlicher Merkmale sachgerechte Schlüsse ziehen"},
    "abschätzen":           {"afb": ["II"],       "desc": "Eine technische Einrichtung grob dimensionieren ohne genaue Berechnungen"},
    "auswerten":            {"afb": ["II"],       "desc": "Daten, Einzelergebnisse oder andere Elemente in einen Zusammenhang stellen"},
    "begründen":            {"afb": ["II"],       "desc": "Sachverhalte auf Regeln und Gesetzmäßigkeiten zurückführen"},
    "durchführen":          {"afb": ["II"],       "desc": "Eine vorgegebene oder eigene Anleitung umsetzen"},
    "ermitteln":            {"afb": ["II"],       "desc": "Einen Zusammenhang oder eine Lösung finden und das Ergebnis formulieren"},
    "konstruieren":         {"afb": ["II"],       "desc": "Form und Bau eines technischen Objektes maßgebend gestalten"},
    "optimieren":           {"afb": ["II"],       "desc": "Einen gegebenen technischen Sachverhalt so verändern, dass geforderte Kriterien erfüllt werden"},
    "skizzieren":           {"afb": ["II"],       "desc": "Sachverhalte auf das Wesentliche reduzieren und grafisch oder als Text übersichtlich darstellen"},
    "strukturieren":        {"afb": ["II"],       "desc": "Vorliegende Objekte oder Sachverhalte kategorisieren und hierarchisieren"},
    "ordnen":               {"afb": ["II"],       "desc": "Vorliegende Objekte oder Sachverhalte kategorisieren und hierarchisieren"},
    "analysieren":          {"afb": ["II", "III"], "desc": "Wichtige Bestandteile oder Eigenschaften auf eine bestimmte Fragestellung hin herausarbeiten"},
    "untersuchen":          {"afb": ["II", "III"], "desc": "Wichtige Bestandteile oder Eigenschaften herausarbeiten, ggf. mit praktischen Anteilen"},
    "beurteilen":           {"afb": ["II", "III"], "desc": "Zu einem Sachverhalt ein selbstständiges Urteil formulieren und begründen"},
    "bewerten":             {"afb": ["II", "III"], "desc": "Eine eigene Position nach ausgewiesenen Kriterien vertreten"},
    "stellung nehmen":      {"afb": ["II", "III"], "desc": "Eine eigene Position nach ausgewiesenen Kriterien vertreten"},
    "dimensionieren":       {"afb": ["II", "III"], "desc": "Eine technische Einrichtung bestimmen"},
    "entwickeln":           {"afb": ["II", "III"], "desc": "Lösungen für komplexe Probleme erarbeiten"},
    "entwerfen":            {"afb": ["II", "III"], "desc": "Lösungen für komplexe Probleme erarbeiten"},
    "überprüfen":           {"afb": ["II", "III"], "desc": "Sachverhalte oder Aussagen an Fakten oder innerer Logik messen"},
    "nachweisen":           {"afb": ["II", "III"], "desc": "Sachverhalte oder Aussagen an Fakten oder innerer Logik messen"},
    "übertragen":           {"afb": ["II", "III"], "desc": "Einen bekannten Sachverhalt oder eine bekannte Methode auf etwas Neues beziehen"},
    "dokumentieren":        {"afb": ["III"],       "desc": "Entscheidende Erklärungen, Herleitungen und Skizzen darstellen"},
}

# Alle Operator-Wörter für die Regex-Erkennung (sortiert nach Länge absteigend,
# damit z.B. "stellung nehmen" vor "nehmen" erkannt wird)
OPERATOR_NAMES = sorted(OPERATOREN.keys(), key=len, reverse=True)

# ---------------------------------------------------------------------------
# Lerngebiete Informationstechnik (aus bgtechnik2016.pdf)
# ---------------------------------------------------------------------------
IT_LERNGEBIETE = {
    "IT1": "Technische Prozesse steuern",
    "IT2": "Netzwerke analysieren, planen und konfigurieren",
    "IT3": "Software zur Prozessdatenverarbeitung entwickeln",
    "IT4": "Messwerte erfassen und verarbeiten",
    "IT5": "Software zur grafischen Darstellung technischer Prozesse entwickeln",
}

# Verbindliche Lerngebiete IT (Qualifikationsphase)
IT_VERBINDLICH = {"IT1", "IT2"}
# Optionale Lerngebiete IT (eins aus drei)
IT_OPTIONAL = {"IT3", "IT4", "IT5"}

# Übergeordnete Kompetenzen Fach Technik (RRL bgtechnik2016.pdf, Abschnitt 1.3)
RRL_KOMPETENZEN = [
    "Technische Probleme analysieren, Wirkungszusammenhänge ermitteln, Lösungen entwickeln und deren Wirksamkeit beurteilen",
    "Technische Aufgabenstellungen und Lösungen unter den Aspekten ihrer Zweckbestimmung, Funktionalität und Übertragbarkeit analysieren",
    "Optimieren von Lösungen für technische Aufgabenstellungen",
    "Theorien und Gesetzmäßigkeiten sowie mögliche Analyse- und Syntheseverfahren anwenden",
    "Erkenntnismethoden der Technik beschreiben und situationsgerecht nutzen",
    "Mit technischen Geräten, Maschinen und Anlagen umgehen",
    "Informationen selbstständig beschaffen, verarbeiten und präsentieren",
    "Fachbezogene Kommunikationstechniken anwenden sowie technische Komponenten planen und konstruieren",
    "Typische Lösungsverfahren erfassen, auswählen, anwenden und bewerten",
    "Ergebnisse in Form von Tabellen, Grafiken, Diagrammen und Abbildungen darstellen",
    "Hypothesen formulieren und überprüfen",
    "Modellvorstellungen entwickeln, simulieren, darstellen und gegebenenfalls modifizieren",
]

# Bearbeitungszeit einer Abiturklausur (eA) in Minuten
ABITUR_BEARBEITUNGSZEIT_MIN = 300


# ---------------------------------------------------------------------------
# Hilfsfunktionen zum Textextrahieren
# ---------------------------------------------------------------------------

def extract_text_pdf(filepath: str, layout: bool = False) -> str:
    """Extrahiert Text aus einer PDF-Datei.

    Versucht zuerst pdftotext (poppler), dann pypdf als plattformunabhängigen
    Fallback.  Gibt leeren String zurück, wenn beide Methoden scheitern.

    Args:
        filepath: Pfad zur PDF-Datei.
        layout: Wenn True, wird ``-layout`` verwendet (nur pdftotext).
    """
    # Versuch 1: pdftotext (höhere Qualität, besonders für Layout/Tabellen)
    try:
        cmd = ["pdftotext"]
        if layout:
            cmd.append("-layout")
        cmd.extend([filepath, "-"])
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass  # pdftotext nicht installiert (z.B. Windows ohne poppler)

    # Fallback: pypdf (plattformunabhängig, kein poppler nötig)
    try:
        import pypdf  # pip install pypdf
        reader = pypdf.PdfReader(filepath)
        seiten = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                seiten.append(text)
        if seiten:
            return "\f".join(seiten)  # \f = Seitentrennzeichen wie pdftotext
    except ImportError:
        pass  # pypdf nicht installiert
    except Exception:
        pass  # beschädigte oder verschlüsselte PDF

    print(f"WARNUNG: PDF-Text konnte nicht extrahiert werden: "
          f"{os.path.basename(filepath)}")
    print("  Tipp: 'pip install pypdf' (falls noch nicht installiert)")
    return ""


def extract_text_docx(filepath: str) -> str:
    """Extrahiert Text aus einer DOCX-Datei."""
    try:
        doc = Document(filepath)
        parts = []
        for para in doc.paragraphs:
            if para.text.strip():
                parts.append(para.text)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        parts.append(cell.text)
        return "\n".join(parts)
    except Exception as e:
        print(f"WARNUNG: DOCX-Datei konnte nicht geöffnet werden: "
              f"{os.path.basename(filepath)}: {e}")
        return ""


def extract_text(filepath: str) -> str:
    """Extrahiert Text aus PDF oder DOCX."""
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf":
        return extract_text_pdf(filepath)
    elif ext == ".docx":
        return extract_text_docx(filepath)
    else:
        raise ValueError(f"Nicht unterstütztes Dateiformat: {ext}")


def extract_pages_pdf(filepath: str) -> list[str]:
    """Extrahiert Text seitenweise aus einer PDF-Datei.
    Gibt eine Liste zurück, wobei Index 0 = Seite 1."""
    # Versuch 1: pdftotext
    try:
        result = subprocess.run(
            ["pdftotext", filepath, "-"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            pages = result.stdout.split("\x0c")
            if pages and not pages[-1].strip():
                pages = pages[:-1]
            return pages
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Fallback: pypdf
    try:
        import pypdf
        reader = pypdf.PdfReader(filepath)
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return pages
    except (ImportError, Exception):
        return []


_SEITEN_HEADER_PATTERN = re.compile(
    r"^("
    r"Zentralabitur\s+\d{4}.*"
    r"|Technik\s*-\s*(?:Mechatronik|Informationstechnik).*"
    r"|Aufgabe\s+[A-Z](?=\s|$)"
    r"|Material\s+f.r\s+Pr.flinge"
    r"|Sch.lermaterial|Lehrermaterial"
    r"|eA|gA"
    r"|Bearbeitungszeit.*"
    r"|Nieders.chsisches\s+Kultusministerium"
    r"|\d+\s+von\s+\d+"
    r"|Thema:"
    r")$",
    re.IGNORECASE | re.MULTILINE,
)

# Vorkompilierte Pattern für Aufgaben- / Teilaufgaben-Parsing
# (früher innerhalb von finde_aufgaben_seiten / parse_aufgaben jedesmal neu erstellt)
_AUFGABE_PATTERN = re.compile(r"(\d+)\.\s*Aufgabe[:\s]", re.IGNORECASE)
_AUFGABE_PATTERN_TITEL = re.compile(r"(\d+)\.\s*Aufgabe[:\s]*(.*?)$", re.IGNORECASE)
_TEIL_PATTERN = re.compile(r"^(\d+\.\d+)\s", re.MULTILINE)
_TEIL_PATTERN_TITEL = re.compile(r"^(\d+\.\d+)\s+(.*?)$", re.IGNORECASE)
_INSGESAMT_PATTERN = re.compile(r"insgesamt\s+(\d+)\s*(?:Punkte|BE|P)", re.IGNORECASE)
_NUR_PUNKTE_PATTERN = re.compile(r"^\s*(\d+)\s*(?:Punkte|BE|P)\s*$", re.IGNORECASE)
_TEIL_PUNKTE_TAIL = re.compile(r"(\d+)\s*(?:Punkte|BE|P)\s*$", re.IGNORECASE)



def _normalisiere_aufgabentext(text: str) -> str:
    """Normalisiert mehrzeilige Aufgaben-Header zu einzeiliger Form.

    Wandelt z.B. '1.\\n\\nAufgabe\\n\\n[50 BE]' in '1. Aufgabe insgesamt 50 BE'
    und '1.1\\n\\nTiteltext' in '1.1 Titeltext'.
    Entfernt wiederholte Seitenheader aus dem PDF-Text.
    """
    # Wiederholte Seitenheader entfernen (stören die Erkennung)
    text = _SEITEN_HEADER_PATTERN.sub("", text)
    # "N.\n...\nAufgabe" -> "N. Aufgabe" (Hauptaufgabe über mehrere Zeilen)
    text = re.sub(
        r'(\d+)\.\s*\n[\s\n]*Aufgabe\b',
        r'\1. Aufgabe',
        text,
    )
    # "[NN BE]" / "[NN Pkt.]" / "[NN Pkt]" -> "insgesamt NN BE"
    text = re.sub(
        r'\[(\d+)\s*(?:BE|Pkt\.?)\]',
        r'insgesamt \1 BE',
        text,
        flags=re.IGNORECASE,
    )
    # Mehrzeilige Teilaufgaben: "N.M\n...\nTitel" -> "N.M Titel"
    text = re.sub(
        r'(\d+\.\d+)\s*\n[\s\n]*(\S)',
        r'\1 \2',
        text,
    )
    return text


def finde_aufgaben_seiten(pages: list[str]) -> dict[str, int]:
    """Bestimmt, auf welcher Seite jede Aufgabe/Teilaufgabe beginnt.
    Gibt ein Dict {nummer: seite} zurück, z.B. {"1": 2, "1.1": 2, "2": 5}.
    Seitennummern sind 1-basiert."""
    ergebnis = {}
    for i, seite in enumerate(pages):
        seite_nr = i + 1
        norm = _normalisiere_aufgabentext(seite)
        for m in _AUFGABE_PATTERN.finditer(norm):
            nr = m.group(1)
            if nr not in ergebnis:
                ergebnis[nr] = seite_nr
        for m in _TEIL_PATTERN.finditer(norm):
            nr = m.group(1)
            if nr not in ergebnis:
                ergebnis[nr] = seite_nr
    return ergebnis


# ---------------------------------------------------------------------------
# Datenstrukturen
# ---------------------------------------------------------------------------

@dataclass
class Teilaufgabe:
    nummer: str          # z.B. "1.1", "2.3"
    text: str            # Aufgabentext
    punkte: int | None = None
    operatoren: list = field(default_factory=list)
    afb_zuordnung: list = field(default_factory=list)


@dataclass
class Aufgabe:
    nummer: int          # 1, 2, 3
    titel: str
    gesamtpunkte: int | None = None
    teilaufgaben: list = field(default_factory=list)


@dataclass
class PruefungsErgebnis:
    kriterium_nr: str
    kriterium_text: str
    erfuellt: bool | None  # True / False / None (nicht prüfbar)
    kommentar: str = ""


# ---------------------------------------------------------------------------
# Parser: Aufgaben und Operatoren aus Schülermaterial extrahieren
# ---------------------------------------------------------------------------

def parse_aufgaben(text: str) -> list[Aufgabe]:
    """Extrahiert Aufgaben und Teilaufgaben aus dem Schülermaterial-Text."""
    # Mehrzeilige Aufgaben-Header normalisieren (z.B. Mechatronik-PDFs)
    text = _normalisiere_aufgabentext(text)
    aufgaben = []
    lines = text.split("\n")

    current_aufgabe = None
    current_teil = None

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Hauptaufgabe erkennen
        m = _AUFGABE_PATTERN_TITEL.search(line)
        if m:
            nr = int(m.group(1))
            titel = m.group(2).strip() if m.group(2) else ""
            # Punkte auf derselben Zeile?
            pm = _INSGESAMT_PATTERN.search(line)
            punkte = int(pm.group(1)) if pm else None
            # Punkte auf den nächsten Zeilen suchen – auch über Teilaufgaben
            # und Kopfzeilen hinweg, da das PDF-Layout die Gesamtpunkte
            # oft erst nach der ersten Teilaufgabe setzt.
            if punkte is None:
                for lookahead in range(1, 15):
                    if i + lookahead >= len(lines):
                        break
                    next_line = lines[i + lookahead].strip()
                    if not next_line:
                        continue
                    pm2 = _INSGESAMT_PATTERN.search(next_line)
                    if pm2:
                        punkte = int(pm2.group(1))
                        break
                    pm3 = _NUR_PUNKTE_PATTERN.match(next_line)
                    if pm3:
                        punkte = int(pm3.group(1))
                        break
                    # Nächste Hauptaufgabe → aufhören
                    if _AUFGABE_PATTERN.match(next_line):
                        break
            current_aufgabe = Aufgabe(nummer=nr, titel=titel, gesamtpunkte=punkte)
            aufgaben.append(current_aufgabe)
            current_teil = None
            i += 1
            continue

        # Teilaufgabe erkennen
        m = _TEIL_PATTERN_TITEL.match(line)
        if m and current_aufgabe is not None:
            tnr = m.group(1)
            hauptnr = tnr.split(".")[0]
            if hauptnr == str(current_aufgabe.nummer):
                ttext = m.group(2).strip() if m.group(2) else ""
                # Punkte in derselben Zeile?
                tpunkte = None
                pm2 = _TEIL_PUNKTE_TAIL.search(line)
                if pm2:
                    tpunkte = int(pm2.group(1))
                # Punkte auf den nächsten Zeilen suchen
                if tpunkte is None:
                    for lookahead in range(1, 8):
                        if i + lookahead >= len(lines):
                            break
                        next_line = lines[i + lookahead].strip()
                        if not next_line:
                            continue
                        pm3 = _NUR_PUNKTE_PATTERN.match(next_line)
                        if pm3:
                            tpunkte = int(pm3.group(1))
                            break
                        pm4 = _INSGESAMT_PATTERN.search(next_line)
                        if pm4:
                            val = int(pm4.group(1))
                            # Gesamtpunkte der Hauptaufgabe überspringen
                            if (current_aufgabe.gesamtpunkte is not None
                                    and val == current_aufgabe.gesamtpunkte):
                                continue
                            tpunkte = val
                            break
                        # Neue Teilaufgabe oder Aufgabe → aufhören
                        if _TEIL_PATTERN.match(next_line) or _AUFGABE_PATTERN.match(next_line):
                            break
                        break  # sonstiger Inhalt → aufhören
                current_teil = Teilaufgabe(nummer=tnr, text=ttext, punkte=tpunkte)
                current_aufgabe.teilaufgaben.append(current_teil)
                i += 1
                continue

        # Teilaufgabentext sammeln
        if current_teil is not None and line:
            current_teil.text += " " + line

        i += 1

    return aufgaben


def find_operatoren_in_text(text: str) -> list[dict]:
    """
    Findet alle verwendeten Operatoren im Text.
    Gibt eine Liste von dicts mit 'operator', 'kontext' und 'position' zurück.
    """
    gefundene = []
    text_lower = text.lower()

    for op_name in OPERATOR_NAMES:
        # Suche nach dem Operator als ganzem Wort (auch konjugierte Formen)
        # Der Operator kann am Satzanfang großgeschrieben sein
        # Wir suchen sowohl nach der Grundform als auch nach Imperativ-Form
        patterns = []
        # Grundform / Infinitiv
        patterns.append(re.compile(
            r"\b" + re.escape(op_name) + r"(?:n|en|t|te|ten|)?\b",
            re.IGNORECASE
        ))
        # Spezialfall: "Stellung nehmen" → "nehmen Sie Stellung"
        if op_name == "stellung nehmen":
            patterns.append(re.compile(
                r"\bnehmen\s+Sie\s+Stellung\b", re.IGNORECASE
            ))

        for pat in patterns:
            for match in pat.finditer(text):
                # Kontext extrahieren (50 Zeichen vor und nach)
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                kontext = text[start:end].replace("\n", " ").strip()
                gefundene.append({
                    "operator": op_name,
                    "match": match.group(),
                    "kontext": kontext,
                    "position": match.start(),
                    "afb": OPERATOREN[op_name]["afb"],
                })

    # Deduplizieren (gleiche Position)
    seen_positions = set()
    unique = []
    for g in sorted(gefundene, key=lambda x: x["position"]):
        # Überlappende Treffer entfernen
        if g["position"] not in seen_positions:
            unique.append(g)
            for p in range(g["position"], g["position"] + len(g["match"])):
                seen_positions.add(p)
    return unique


def find_operatoren_in_aufgabenstellung(text: str) -> list[dict]:
    """
    Findet Operatoren speziell in der Aufgabenstellung (Imperativ-Form).
    Filtert typische Nicht-Aufgabenstellungs-Kontexte heraus.
    """
    alle = find_operatoren_in_text(text)

    # Filtere nur solche, die wirklich als Arbeitsauftrag verwendet werden
    aufgaben_ops = []
    # Muster für Imperativ-Einsatz in Aufgabenstellung:
    # - "Erläutern Sie ..."
    # - "Berechnen Sie ..."
    # - "Entwickeln Sie ..."
    # Oder am Satzanfang als Imperativ
    imperativ_pattern = re.compile(
        r"(" + "|".join(re.escape(op) for op in OPERATOR_NAMES) + r")"
        r"\s+Sie\b",
        re.IGNORECASE
    )

    for match in imperativ_pattern.finditer(text):
        op_lower = match.group(1).lower()
        # Normalisierung
        for op_name in OPERATOR_NAMES:
            if op_lower.startswith(op_name[:4]):
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 60)
                kontext = text[start:end].replace("\n", " ").strip()
                aufgaben_ops.append({
                    "operator": op_name,
                    "match": match.group(),
                    "kontext": kontext,
                    "position": match.start(),
                    "afb": OPERATOREN[op_name]["afb"],
                })
                break

    # Deduplizieren
    seen = set()
    unique = []
    for g in aufgaben_ops:
        key = (g["operator"], g["position"])
        if key not in seen:
            seen.add(key)
            unique.append(g)
    return unique


# ---------------------------------------------------------------------------
# Parser: Erwartungshorizont / AFB-Verteilung aus Lehrermaterial
# ---------------------------------------------------------------------------

def parse_erwartungshorizont_afb(text: str) -> dict:
    """
    Versucht aus dem Lehrermaterial die AFB-Verteilung (I, II, III)
    und die Gesamtpunktzahl zu extrahieren.
    """
    ergebnis = {"afb_I": 0, "afb_II": 0, "afb_III": 0, "gesamt": 0}

    # Suche nach Gesamtsummen-Zeile
    # Muster 1: "Gesamtsummen  30  42  28  100" oder "Gesamtsummen (absolut) 30 42 28 100"
    pattern_gesamt = re.compile(
        r"Gesamtsummen?\s*(?:\([^)]*\))?\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)",
        re.IGNORECASE
    )
    m = pattern_gesamt.search(text)
    if m:
        ergebnis["afb_I"] = int(m.group(1))
        ergebnis["afb_II"] = int(m.group(2))
        ergebnis["afb_III"] = int(m.group(3))
        ergebnis["gesamt"] = int(m.group(4))
        return ergebnis

    # Muster 2: "Gesamtsummen" + optional Text + Newline + Zahlen (mehrzeilig)
    pattern_gesamt2 = re.compile(
        r"Gesamtsummen?\s*(?:\([^)]*\))?\s*\n\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)",
        re.IGNORECASE
    )
    m = pattern_gesamt2.search(text)
    if m:
        ergebnis["afb_I"] = int(m.group(1))
        ergebnis["afb_II"] = int(m.group(2))
        ergebnis["afb_III"] = int(m.group(3))
        ergebnis["gesamt"] = int(m.group(4))
        return ergebnis

    # Fallback: Suche nach Prozentzeile
    pattern_pct = re.compile(
        r"%\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)",
        re.IGNORECASE
    )
    m = pattern_pct.search(text)
    if m:
        ergebnis["afb_I"] = int(m.group(1))
        ergebnis["afb_II"] = int(m.group(2))
        ergebnis["afb_III"] = int(m.group(3))
        ergebnis["gesamt"] = int(m.group(4))

    return ergebnis


def parse_erweiterte_operatoren(text: str) -> dict:
    """Extrahiert erweiterte Operatoren aus dem Lehrermaterial.

    Sucht den Block nach „Operatorenliste wurde … erweitert" und liest
    pro Tabellenzeile Operator(en) und AFB-Zuordnung. Operatoren in der
    Schreibweise „Op1/Op2" werden als zwei einzelne Einträge gespeichert.
    Header-Stichwörter (Operator, Beschreibung, Anforderungsbereich) werden
    explizit ausgeschlossen.

    Rückgabe: ``{operator: {"afb": [<röm.Zahlen>], "desc": ...}}``
    """
    erweitert: dict = {}

    block_match = re.search(
        r"Operatorenliste\s+wurde[^\n]*?erweitert.*?(?=Erwartungshorizont|Musterlösung|$)",
        text, re.IGNORECASE | re.DOTALL,
    )
    if not block_match:
        return erweitert
    block = block_match.group()

    KEINE_OPERATOREN = {
        "operator", "operatoren", "operatorenliste",
        "beschreibung", "erwarteten", "leistung",
        "anforderungsbereich", "anforderungsbereiche",
        # Römische Zahlen dürfen nicht als Operator gelesen werden
        "i", "ii", "iii",
    }
    zeile_pattern = re.compile(
        r"^\s*([A-Za-zÄÖÜäöüß]+(?:\s*/\s*[A-Za-zÄÖÜäöüß]+)?)"   # Operator(en)
        r".+?"                                                  # Beschreibung
        r"\b(I{1,3}(?:\s*(?:und|/|,|\s)\s*I{1,3})*)\s*$",       # AFB am Zeilenende
        re.MULTILINE,
    )
    for m in zeile_pattern.finditer(block):
        op_raw = m.group(1).strip().lower()
        afb_str = m.group(2)
        if op_raw in KEINE_OPERATOREN:
            continue
        afbs = re.findall(r"I{1,3}", afb_str)
        if not afbs:
            continue
        for op in re.split(r"\s*/\s*", op_raw):
            erweitert[op] = {"afb": afbs, "desc": "Erweitert (Lehrermaterial)"}

    return erweitert


# Nicht-EPA-Phrasen, die als Arbeitsauftrag verwendet werden, aber nicht zur
# EPA-Operatorenliste gehören. Werden in der Aufgabenstellung gesucht und
# führen zu einem Hinweis (kein harter Verstoß).
NICHT_EPA_PHRASEN: list[tuple[str, str]] = [
    (r"\bGeben\s+Sie\s+an\b",
     'Phrase "Geben Sie an" – durch "Nennen Sie" oder "Bestimmen Sie" ersetzen'),
    (r"\btragen\s+Sie\b[^.]{0,40}\bein\b",
     'Phrase "tragen Sie … ein" – als erweiterten Operator dokumentieren oder durch "Ergänzen" ersetzen'),
    (r"\bersetzen\s+Sie\b",
     'Phrase "ersetzen Sie" – durch "Anpassen" (erweitert) oder "Durchführen" ersetzen'),
    (r"\bfüllen\s+Sie\b[^.]{0,40}\baus\b",
     'Phrase "füllen Sie … aus" – durch "Ergänzen" ersetzen oder als erweiterten Operator dokumentieren'),
    (r"\bSchreiben\s+Sie\s+(?!ein|eine)\b",
     'Phrase "Schreiben Sie" als Arbeitsauftrag – nicht in der EPA-Liste'),
]


def finde_nicht_epa_phrasen(schueler_text: str) -> list[tuple[str, str]]:
    """Sucht in der Aufgabenstellung nach Nicht-EPA-Formulierungen.

    Rückgabe: Liste von (gefundene Stelle, Empfehlung).
    """
    treffer: list[tuple[str, str]] = []
    for pattern, empfehlung in NICHT_EPA_PHRASEN:
        for m in re.finditer(pattern, schueler_text, re.IGNORECASE):
            treffer.append((m.group(0), empfehlung))
    return treffer


# ---------------------------------------------------------------------------
# Prüfungen
# ---------------------------------------------------------------------------

def check_punkte_schueler(text: str, aufgaben: list[Aufgabe]) -> PruefungsErgebnis:
    """4.7: Punkte bei jeder Aufgabe und Teilaufgabe auf dem Aufgabenblatt."""
    fehlende = []
    for aufg in aufgaben:
        if aufg.gesamtpunkte is None:
            fehlende.append(f"Aufgabe {aufg.nummer}: keine Gesamtpunkte")
        for teil in aufg.teilaufgaben:
            if teil.punkte is None:
                fehlende.append(f"Teilaufgabe {teil.nummer}: keine Punkte")

    if not fehlende:
        return PruefungsErgebnis("4.7",
            "Angabe der zu erreichenden Punkte bei jeder Aufgabe und Teilaufgabe",
            True, "Punkte sind bei allen Aufgaben und Teilaufgaben angegeben.")
    else:
        return PruefungsErgebnis("4.7",
            "Angabe der zu erreichenden Punkte bei jeder Aufgabe und Teilaufgabe",
            False, "Fehlende Punkteangaben: " + "; ".join(fehlende))


def check_operatoren_epa(schueler_text: str, erweiterte_ops: dict) -> PruefungsErgebnis:
    """4.5: Operatoren in Anlehnung an EPA verwendet."""
    ops_in_aufgabe = find_operatoren_in_aufgabenstellung(schueler_text)

    # Alle bekannten Operatoren (Standard + erweitert)
    alle_ops = set(OPERATOREN.keys()) | set(erweiterte_ops.keys())

    unbekannte = []
    for op_info in ops_in_aufgabe:
        if op_info["operator"] not in alle_ops:
            unbekannte.append(op_info["match"])

    # Zusätzlich nach Nicht-EPA-Phrasen suchen (z. B. „Geben Sie an",
    # „tragen Sie … ein", „ersetzen Sie"). Diese werden in der reinen
    # Wortlisten-Erkennung nicht erfasst.
    phrasen_treffer = finde_nicht_epa_phrasen(schueler_text)

    gefundene_ops = sorted(set(o["operator"] for o in ops_in_aufgabe))

    if not unbekannte and not phrasen_treffer:
        return PruefungsErgebnis("4.5",
            "Operatoren in Anlehnung an EPA",
            True,
            f"Verwendete Operatoren: {', '.join(gefundene_ops)}. "
            f"Alle Operatoren sind EPA-konform.")

    teile = []
    if unbekannte:
        teile.append(f"Nicht in EPA-Liste: {', '.join(set(unbekannte))}")
    if phrasen_treffer:
        phr = ", ".join(sorted({t[0] for t in phrasen_treffer}))
        teile.append(f"Nicht-EPA-Phrasen: {phr}")
    return PruefungsErgebnis("4.5",
        "Operatoren in Anlehnung an EPA",
        False,
        f"Verwendete Operatoren: {', '.join(gefundene_ops)}. "
        + " | ".join(teile))


def check_afb_verteilung(afb_data: dict) -> PruefungsErgebnis:
    """4.6: Angemessene Berücksichtigung aller AFBs: ca. I: 30%, II: 40%, III: 30%."""
    gesamt = afb_data.get("gesamt", 0)
    if gesamt == 0:
        return PruefungsErgebnis("4.6",
            "Angemessene AFB-Verteilung",
            None,
            "Keine AFB-Verteilung im Lehrermaterial gefunden.")

    pct_I = afb_data["afb_I"] / gesamt * 100
    pct_II = afb_data["afb_II"] / gesamt * 100
    pct_III = afb_data["afb_III"] / gesamt * 100

    kommentar = (
        f"AFB I: {afb_data['afb_I']} P ({pct_I:.0f}%), "
        f"AFB II: {afb_data['afb_II']} P ({pct_II:.0f}%), "
        f"AFB III: {afb_data['afb_III']} P ({pct_III:.0f}%), "
        f"Gesamt: {gesamt} P. "
        f"Soll: ca. 30% / 40% / 30%."
    )

    # Toleranz: ±10%
    ok = (20 <= pct_I <= 40) and (30 <= pct_II <= 50) and (20 <= pct_III <= 40)

    if ok:
        kommentar += " Verteilung ist angemessen."
    else:
        kommentar += " ABWEICHUNG von der empfohlenen Verteilung!"

    return PruefungsErgebnis("4.6", "Angemessene AFB-Verteilung", ok, kommentar)


def check_erste_aufgabe_nicht_afb3(schueler_text: str) -> PruefungsErgebnis:
    """Erste Teilaufgabe soll nicht AFB III sein."""
    # Finde den ersten Operator in der Aufgabenstellung
    ops = find_operatoren_in_aufgabenstellung(schueler_text)

    if not ops:
        return PruefungsErgebnis("X.1",
            "Erste Aufgabe nicht AFB III",
            None, "Keine Operatoren in der Aufgabenstellung gefunden.")

    erster_op = ops[0]
    if "III" in erster_op["afb"] and "II" not in erster_op["afb"] and "I" not in erster_op["afb"]:
        return PruefungsErgebnis("X.1",
            "Erste Aufgabe nicht AFB III",
            False,
            f"Die erste Teilaufgabe verwendet den Operator '{erster_op['operator']}' "
            f"(AFB {'/'.join(erster_op['afb'])}). "
            f"EPA: Die erste Aufgabe soll NICHT aus AFB III stammen.")
    else:
        return PruefungsErgebnis("X.1",
            "Erste Aufgabe nicht AFB III",
            True,
            f"Erster Operator: '{erster_op['operator']}' (AFB {'/'.join(erster_op['afb'])}). OK.")


def check_hilfsmittel(schueler_text: str) -> PruefungsErgebnis:
    """2.7: Erlaubte Hilfsmittel sind angegeben."""
    keywords = ["hilfsmittel", "taschenrechner", "zeichengerät",
                "formelsammlung", "tabellenbuch", "pc-arbeitsplatz",
                "ausstattung", "zur verfügung"]
    text_low = schueler_text.lower()
    found = [kw for kw in keywords if kw in text_low]

    if found:
        return PruefungsErgebnis("2.7",
            "Erlaubte Hilfsmittel angegeben",
            True,
            f"Hilfsmittel-Hinweise gefunden (Schlüsselwörter: {', '.join(found)}).")
    else:
        return PruefungsErgebnis("2.7",
            "Erlaubte Hilfsmittel angegeben",
            False,
            "Keine Angabe zu erlaubten Hilfsmitteln gefunden.")


def check_formelsammlung(schueler_text: str) -> PruefungsErgebnis:
    """2.8: Formelsammlung vorhanden wenn als Hilfsmittel angegeben."""
    text_low = schueler_text.lower()
    if "formelsammlung" in text_low:
        return PruefungsErgebnis("2.8",
            "Formelsammlung vorhanden",
            None,
            "Formelsammlung wird erwähnt – bitte manuell prüfen, ob sie beiliegt.")
    else:
        return PruefungsErgebnis("2.8",
            "Formelsammlung vorhanden",
            True,
            "Keine Formelsammlung als Hilfsmittel angegeben, daher nicht erforderlich.")


def check_bearbeitungszeit(schueler_text: str) -> PruefungsErgebnis:
    """1.2 (Teil): Bearbeitungszeit angegeben."""
    m = re.search(r"Bearbeitungszeit[:\s]*(\d+)\s*Min", schueler_text, re.IGNORECASE)
    if m:
        return PruefungsErgebnis("1.2a",
            "Bearbeitungszeit angegeben",
            True,
            f"Bearbeitungszeit: {m.group(1)} Minuten.")
    else:
        return PruefungsErgebnis("1.2a",
            "Bearbeitungszeit angegeben",
            False,
            "Keine Bearbeitungszeit gefunden.")


def check_dokumentenvorlage(schueler_text: str) -> PruefungsErgebnis:
    """1.2: Dokumentenvorlage MK mit Jahr, Fach, Vorschlag, Seite, Bearbeitungszeit."""
    m_jahr = re.search(r"Abitur\s*(?:20\d{2}|20\s*_\s*_)", schueler_text, re.IGNORECASE)
    m_fach = re.search(r"\bTechnik\b", schueler_text, re.IGNORECASE)
    m_vorschlag = re.search(r"Vorschlag\s*[A-Z]|Aufgabe\s+[A-Z](?=\s|$)", schueler_text, re.IGNORECASE)
    m_seite = re.search(r"Seite\s*\d+|\d+\s*von\s*\d+", schueler_text, re.IGNORECASE)
    m_zeit = re.search(r"Bearbeitungszeit[:\s]*\d+\s*Min", schueler_text, re.IGNORECASE)

    gefunden = {}
    fehlend = []
    for name, m in [("Jahr/Abitur", m_jahr), ("Fach/Technik", m_fach),
                     ("Vorschlag", m_vorschlag), ("Seite", m_seite),
                     ("Bearbeitungszeit", m_zeit)]:
        if m:
            gefunden[name] = m.group().strip()
        else:
            fehlend.append(name)

    if not fehlend:
        return PruefungsErgebnis("1.2", "Dokumentenvorlage MK", True,
            "Alle Elemente vorhanden: "
            + "; ".join(f"{k}: '{v}'" for k, v in gefunden.items()))
    else:
        fund_str = "; ".join(f"{k}: '{v}'" for k, v in gefunden.items()) if gefunden else "—"
        return PruefungsErgebnis("1.2", "Dokumentenvorlage MK", False,
            f"Gefunden: {fund_str}. Fehlend: {', '.join(fehlend)}.")


def check_lerngebiete(lehrer_text: str) -> PruefungsErgebnis:
    """2.2/2.3: Aufgaben den Lerngebieten zugeordnet + Beschreibung Unterrichtszusammenhang."""
    # Suche nach Lerngebiet-Zuordnungen
    lerngebiet_matches = re.findall(
        r'Lerngebiet(?:es?)?\s*["\u201e\u201c\u201d\']*\s*(IT\d[^"\']*)',
        lehrer_text, re.IGNORECASE
    )
    # Breiter suchen
    lg_count = len(re.findall(r"Lerngebiet", lehrer_text, re.IGNORECASE))
    kurs_matches = re.findall(r"(?:12\.[12]|13\.[12])\s", lehrer_text)

    bezug = "Bezug der Aufgaben zum Unterricht" in lehrer_text or \
            "Bezug der Aufgaben" in lehrer_text or \
            "unterrichtliche Voraussetzungen" in lehrer_text.lower()

    kommentar_parts = []
    if lg_count > 0:
        kommentar_parts.append(f"{lg_count} Erwähnungen von 'Lerngebiet' gefunden.")
    if kurs_matches:
        kommentar_parts.append(f"Kursbezeichnungen: {', '.join(sorted(set(kurs_matches)))}.")
    if bezug:
        kommentar_parts.append("Bezug zum Unterricht ist beschrieben.")

    erfuellt = lg_count >= 3 and bezug

    return PruefungsErgebnis("2.2",
        "Aufgaben den Lerngebieten zugeordnet",
        erfuellt,
        " ".join(kommentar_parts) if kommentar_parts else
        "Keine Lerngebiet-Zuordnung gefunden.")


def check_erwartungshorizont(lehrer_text: str) -> PruefungsErgebnis:
    """2.4: Aussagefähiger Erwartungshorizont mit Zuordnung zu den AFBs."""
    hat_ewh = bool(re.search(r"Erwartungshorizont", lehrer_text, re.IGNORECASE))
    hat_afb = bool(re.search(r"Anforderungsbereich", lehrer_text, re.IGNORECASE))
    hat_tabelle = bool(re.search(
        r"(?:I\s+II\s+III|AFB\s*I|Anforderungsbereich\s*Bewertung)",
        lehrer_text, re.IGNORECASE
    ))

    if hat_ewh and hat_afb:
        return PruefungsErgebnis("2.4",
            "Erwartungshorizont mit AFB-Zuordnung",
            True,
            "Erwartungshorizont mit Anforderungsbereich-Zuordnung vorhanden.")
    elif hat_ewh:
        return PruefungsErgebnis("2.4",
            "Erwartungshorizont mit AFB-Zuordnung",
            False,
            "Erwartungshorizont vorhanden, aber AFB-Zuordnung nicht erkennbar.")
    else:
        return PruefungsErgebnis("2.4",
            "Erwartungshorizont mit AFB-Zuordnung",
            False,
            "Kein Erwartungshorizont gefunden.")


def check_loesung(lehrer_text: str) -> PruefungsErgebnis:
    """2.5: Komplette Lösung vorhanden."""
    keywords = ["musterlösung", "lösungsvorschlag", "lösung", "lösungshinweis"]
    text_low = lehrer_text.lower()
    found = [kw for kw in keywords if kw in text_low]
    count = sum(text_low.count(kw) for kw in keywords)

    if found and count >= 2:
        return PruefungsErgebnis("2.5",
            "Komplette Lösung",
            True,
            f"Lösungshinweise gefunden ({count} Treffer für: {', '.join(found)}).")
    elif found:
        return PruefungsErgebnis("2.5",
            "Komplette Lösung",
            None,
            f"Wenige Lösungshinweise ({count} Treffer). Bitte manuell prüfen.")
    else:
        return PruefungsErgebnis("2.5",
            "Komplette Lösung",
            False,
            "Keine Lösung/Musterlösung im Lehrermaterial gefunden.")


def check_bewertungsschema(lehrer_text: str) -> PruefungsErgebnis:
    """2.6: Bewertungsschema / Verteilung der Bewertungseinheiten."""
    hat_schema = bool(re.search(
        r"(?:Bewertungsschema|Bewertungsmaßstab|KMK.Punkte|Umrechnung|Notenschlüssel)",
        lehrer_text, re.IGNORECASE
    ))
    hat_punkte_verteilung = bool(re.search(r"\d+\s+\d+\s+\d+\s+\d+", lehrer_text))

    if hat_schema:
        return PruefungsErgebnis("2.6",
            "Bewertungsschema",
            True,
            "Bewertungsschema / KMK-Umrechnung vorhanden.")
    elif hat_punkte_verteilung:
        return PruefungsErgebnis("2.6",
            "Bewertungsschema",
            None,
            "Punkteverteilung erkennbar, aber kein explizites Bewertungsschema. Bitte prüfen.")
    else:
        return PruefungsErgebnis("2.6",
            "Bewertungsschema",
            False,
            "Kein Bewertungsschema gefunden.")


def check_operatoren_erweitert_dokumentiert(lehrer_text: str, schueler_text: str) -> PruefungsErgebnis:
    """Prüft ob erweiterte Operatoren im Lehrermaterial dokumentiert sind."""
    erweiterte = parse_erweiterte_operatoren(lehrer_text)

    # Finde alle Operatoren im Schülermaterial, die NICHT in der Standard-Liste sind
    ops_schueler = find_operatoren_in_aufgabenstellung(schueler_text)
    nicht_standard = []
    for op_info in ops_schueler:
        if op_info["operator"] not in OPERATOREN:
            nicht_standard.append(op_info["operator"])

    if not nicht_standard:
        return PruefungsErgebnis("X.2",
            "Erweiterte Operatoren dokumentiert",
            True,
            "Keine nicht-standardmäßigen Operatoren im Schülermaterial verwendet.")

    nicht_dokumentiert = [op for op in set(nicht_standard) if op not in erweiterte]
    if nicht_dokumentiert:
        return PruefungsErgebnis("X.2",
            "Erweiterte Operatoren dokumentiert",
            False,
            f"Nicht-Standard-Operatoren ohne Dokumentation: {', '.join(nicht_dokumentiert)}")
    else:
        return PruefungsErgebnis("X.2",
            "Erweiterte Operatoren dokumentiert",
            True,
            f"Erweiterte Operatoren sind dokumentiert: {', '.join(erweiterte.keys())}")


def check_aufgabe_als_arbeitsauftrag(schueler_text: str) -> PruefungsErgebnis:
    """4.4: Aufgabenstellung als Arbeitsauftrag/Handlungsanweisung."""
    # Zähle Imperative mit "Sie"
    imperativ_count = len(re.findall(
        r"\b(?:" + "|".join(re.escape(op) for op in OPERATOR_NAMES) +
        r")\w*\s+Sie\b",
        schueler_text, re.IGNORECASE
    ))

    if imperativ_count >= 3:
        return PruefungsErgebnis("4.4",
            "Aufgabenstellung als Arbeitsauftrag",
            True,
            f"{imperativ_count} Arbeitsaufträge (Imperativ + 'Sie') gefunden.")
    elif imperativ_count > 0:
        return PruefungsErgebnis("4.4",
            "Aufgabenstellung als Arbeitsauftrag",
            None,
            f"Nur {imperativ_count} Arbeitsaufträge gefunden. Bitte manuell prüfen.")
    else:
        return PruefungsErgebnis("4.4",
            "Aufgabenstellung als Arbeitsauftrag",
            False,
            "Keine Arbeitsaufträge im Imperativ gefunden.")


def check_kompetenzen_rrl(schueler_text: str, lehrer_text: str) -> PruefungsErgebnis:
    """3.1: Kompetenzen gemäß Rahmenrichtlinien (bgtechnik2016.pdf, Abschnitt 1.3).
    Manuelle Prüfung erforderlich."""
    # Schlüsselwörter aus den RRL-Kompetenzen suchen
    kompetenz_keywords = [
        "analysieren", "wirkungszusammenhänge", "lösungen entwickeln",
        "optimieren", "modellvorstellungen", "hypothesen",
        "kommunikationstechniken", "lösungsverfahren",
        "technische probleme", "zweckbestimmung", "funktionalität",
    ]
    text_low = (schueler_text + " " + lehrer_text).lower()
    gefunden = [kw for kw in kompetenz_keywords if kw in text_low]

    kommentar = (
        "MANUELL PRÜFEN: Werden die übergeordneten Kompetenzen des Fachs Technik "
        "gemäß RRL (bgtechnik2016.pdf, Abschnitt 1.3) angesprochen? "
        "Dazu gehören u.a.: Technische Probleme analysieren, Lösungen entwickeln "
        "und beurteilen; Optimieren von Lösungen; Modellvorstellungen entwickeln; "
        "Ergebnisse darstellen; Hypothesen formulieren und überprüfen."
    )
    if gefunden:
        kommentar += f" Hinweise auf Kompetenzbezug gefunden: {', '.join(gefunden)}."

    return PruefungsErgebnis("3.1",
        "Kompetenzen gemäß Rahmenrichtlinien",
        None, kommentar)


def check_aufgaben_lerngebiete_rrl(lehrer_text: str) -> PruefungsErgebnis:
    """3.2: Aufgaben aus Lerngebieten der RRL (IT1–IT5).
    Manuelle Prüfung erforderlich."""
    text_combined = lehrer_text
    gefundene_lg = []
    for lg_id, lg_titel in IT_LERNGEBIETE.items():
        if re.search(re.escape(lg_id) + r"\b", text_combined, re.IGNORECASE):
            gefundene_lg.append(lg_id)
        # Auch nach Titel-Fragmenten suchen
        titel_kurz = lg_titel.split()[0:3]
        if any(w.lower() in text_combined.lower() for w in titel_kurz if len(w) > 4):
            if lg_id not in gefundene_lg:
                gefundene_lg.append(lg_id)

    # Schulinterne Erweiterungen (IT6, IT7, …) gesondert erfassen –
    # sie sind nicht Teil der RRL, können aber als optionales schulinternes
    # Lerngebiet anerkannt werden (vgl. Mustervorschlag IT6).
    schulintern = sorted(set(re.findall(r"\bIT([6-9]|\d{2,})\b", lehrer_text)))
    schulintern_lg = [f"IT{n}" for n in schulintern]

    kommentar_parts = []
    kommentar_parts.append(
        "MANUELL PRÜFEN: Stammen die Aufgaben aus den Lerngebieten der RRL "
        "Informationstechnik (bgtechnik2016.pdf)?")
    kommentar_parts.append(
        f"Verbindlich: {', '.join(f'{k} ({v})' for k,v in IT_LERNGEBIETE.items() if k in IT_VERBINDLICH)}. "
        f"Optional (1 aus 3): {', '.join(f'{k} ({v})' for k,v in IT_LERNGEBIETE.items() if k in IT_OPTIONAL)}.")
    if gefundene_lg:
        kommentar_parts.append(
            f"Im Lehrermaterial erkannte Lerngebiete: {', '.join(sorted(gefundene_lg))}.")
    else:
        kommentar_parts.append("Keine IT-Lerngebiet-Kennungen (IT1–IT5) im Lehrermaterial erkannt.")
    if schulintern_lg:
        kommentar_parts.append(
            "Zusätzlich erkannt (nicht in RRL bgtechnik2016, ggf. schulinterne "
            "Erweiterung – Anerkennung als optionales Lerngebiet bitte in den "
            "'Unterrichtlichen Voraussetzungen' begründen): "
            + ", ".join(schulintern_lg) + ".")

    return PruefungsErgebnis("3.2",
        "Aufgaben aus Lerngebieten der RRL",
        None, " ".join(kommentar_parts))


def check_ganzheitlichkeit(schueler_text: str, aufgaben: list[Aufgabe]) -> PruefungsErgebnis:
    """3.3: Ganzheitlichkeit und Problembezug, komplexe Aufgabenstellungen.
    Manuelle Prüfung erforderlich."""
    # Prüfe ob es eine zusammenhängende Situationsbeschreibung gibt
    hat_situation = bool(re.search(
        r"Situationsbeschreibung|Ausgangssituation|Szenario",
        schueler_text, re.IGNORECASE
    ))

    # Prüfe ob mindestens 2 Aufgaben / Lerngebiete abgedeckt werden
    anzahl_aufgaben = len(aufgaben)

    kommentar_parts = []
    kommentar_parts.append(
        "MANUELL PRÜFEN: Sind die Aufgaben ganzheitlich und problembezogen? "
        "Komplexe Aufgabenstellungen mit Bezug zur beruflichen Praxis?")
    if hat_situation:
        kommentar_parts.append("Situationsbeschreibung vorhanden.")
    else:
        kommentar_parts.append("Keine explizite Situationsbeschreibung erkannt.")

    kommentar_parts.append(f"{anzahl_aufgaben} Hauptaufgabe(n) gefunden.")

    return PruefungsErgebnis("3.3",
        "Ganzheitlichkeit und Problembezug",
        None,
        " ".join(kommentar_parts))


def check_berufliche_handlungskompetenz(schueler_text: str, lehrer_text: str) -> PruefungsErgebnis:
    """3.4: Orientierung an beruflicher Handlungskompetenz.
    Manuelle Prüfung erforderlich."""
    keywords = [
        "handlungskompetenz", "berufliche", "praxisbezug", "praxisnah",
        "betrieb", "unternehmen", "firma", "kunde", "auftrag",
        "projekt", "arbeitsauftrag", "facharbeit",
    ]
    text_low = (schueler_text + " " + lehrer_text).lower()
    gefunden = [kw for kw in keywords if kw in text_low]

    kommentar = (
        "MANUELL PRÜFEN: Orientiert sich die Aufgabenstellung an beruflicher "
        "Handlungskompetenz? Werden berufstypische Problemstellungen aus der "
        "Informationstechnik behandelt?"
    )
    if gefunden:
        kommentar += f" Hinweise auf Praxisbezug: {', '.join(gefunden)}."

    return PruefungsErgebnis("3.4",
        "Orientierung an beruflicher Handlungskompetenz",
        None, kommentar)


def check_verschiedene_kompetenzen(schueler_text: str) -> PruefungsErgebnis:
    """3.5: Verschiedene Kompetenzen (Fach-, Methoden-, Sozial-, Selbstkompetenz).
    Manuelle Prüfung erforderlich."""
    ops = find_operatoren_in_aufgabenstellung(schueler_text)
    afbs_abgedeckt = set()
    for op in ops:
        afbs_abgedeckt.update(op["afb"])

    op_namen = sorted(set(o["operator"] for o in ops))

    kommentar_parts = []
    kommentar_parts.append(
        "MANUELL PRÜFEN: Werden verschiedene Kompetenzen angesprochen "
        "(Fachkompetenz, Methodenkompetenz, ggf. Sozialkompetenz, Selbstkompetenz)?")
    if op_namen:
        kommentar_parts.append(
            f"Erkannte Operatoren: {', '.join(op_namen)} "
            f"(AFB {', '.join(sorted(afbs_abgedeckt))}).")
        if len(afbs_abgedeckt) < 3:
            kommentar_parts.append(
                f"Hinweis: Nur AFB {', '.join(sorted(afbs_abgedeckt))} abgedeckt – "
                f"alle drei AFB sollten vertreten sein.")
    else:
        kommentar_parts.append("Keine Operatoren erkannt – Kompetenzspektrum nicht prüfbar.")

    return PruefungsErgebnis("3.5",
        "Verschiedene Kompetenzen",
        None, " ".join(kommentar_parts))


def check_aufgaben_klar_formuliert(schueler_text: str) -> PruefungsErgebnis:
    """4.1: Aufgaben klar formuliert, Lösungsweg nicht vorgezeichnet.
    Manuelle Prüfung erforderlich."""
    # Hinweise auf vorgezeichnete Lösungswege
    loesungsweg_patterns = [
        r"gehen Sie wie folgt vor",
        r"führen Sie folgende Schritte",
        r"Schritt\s*\d",
        r"zunächst.*dann.*abschließend",
        r"in folgender Reihenfolge",
    ]
    hinweise = []
    for pat in loesungsweg_patterns:
        if re.search(pat, schueler_text, re.IGNORECASE):
            hinweise.append(pat)

    kommentar_parts = []
    kommentar_parts.append(
        "MANUELL PRÜFEN: Sind die Aufgaben klar und verständlich formuliert? "
        "Ist der Lösungsweg NICHT vorgezeichnet (keine Schritt-für-Schritt-Anleitung)?")
    if hinweise:
        kommentar_parts.append(
            f"ACHTUNG: Mögliche Hinweise auf vorgezeichneten Lösungsweg erkannt "
            f"({len(hinweise)} Muster). "
            f"Bitte prüfen ob der Lösungsweg zu stark vorgegeben ist.")

    return PruefungsErgebnis("4.1",
        "Aufgaben klar formuliert, Lösungsweg nicht vorgezeichnet",
        None, " ".join(kommentar_parts))


def check_anforderungen_bearbeitungszeit(schueler_text: str, aufgaben: list[Aufgabe]) -> PruefungsErgebnis:
    """4.3: Anforderungen nachvollziehbar und der Bearbeitungszeit angemessen.
    Manuelle Prüfung erforderlich. Bearbeitungszeit Abitur: 300 Minuten."""
    m = re.search(r"Bearbeitungszeit[:\s]*(\d+)\s*Min", schueler_text, re.IGNORECASE)
    zeit_min = int(m.group(1)) if m else None

    gesamt_be = sum(a.gesamtpunkte for a in aufgaben if a.gesamtpunkte)
    anzahl_teilaufgaben = sum(len(a.teilaufgaben) for a in aufgaben)

    kommentar_parts = []
    kommentar_parts.append(
        "MANUELL PRÜFEN: Sind die Anforderungen nachvollziehbar und in der "
        f"Bearbeitungszeit ({ABITUR_BEARBEITUNGSZEIT_MIN} Min) angemessen zu bewältigen?")

    if zeit_min:
        kommentar_parts.append(f"Angegebene Bearbeitungszeit: {zeit_min} Minuten.")
        if zeit_min != ABITUR_BEARBEITUNGSZEIT_MIN:
            kommentar_parts.append(
                f"ACHTUNG: Erwartete Bearbeitungszeit für Abiturklausur: "
                f"{ABITUR_BEARBEITUNGSZEIT_MIN} Min, angegeben: {zeit_min} Min!")
    else:
        kommentar_parts.append("Bearbeitungszeit nicht im Schülermaterial gefunden!")

    if gesamt_be > 0:
        kommentar_parts.append(f"Gesamt-BE: {gesamt_be}, {anzahl_teilaufgaben} Teilaufgaben.")
        if zeit_min:
            min_pro_be = zeit_min / gesamt_be
            kommentar_parts.append(f"Verhältnis: {min_pro_be:.1f} Min/BE.")

    return PruefungsErgebnis("4.3",
        "Anforderungen nachvollziehbar und der Bearbeitungszeit angemessen",
        None, " ".join(kommentar_parts))


def check_unabhaengigkeit_teilaufgaben(schueler_text: str) -> PruefungsErgebnis:
    """4.2: Jede Teilaufgabe kann unabhängig gelöst werden.

    Häufigster Mangel laut Auswertung Gutachten: Teilaufgaben bauen aufeinander auf,
    ohne dass ein Alternativwert angegeben ist.
    """
    # Explizite Abhängigkeits-Signalwörter: direkte Verweise auf andere Teilaufgaben
    abhaengig_explizit = [
        # Klassisch: "Ergebnis/Lösung aus Aufgabe X"
        r"(?:Ergebnis|Lösung|Wert)\s+(?:aus|von)\s+(?:Aufgabe|Teilaufgabe|TA\.?|A\.?)\s*\d",
        r"verwenden\s+Sie\s+(?:das|die|den|Ihr|Ihre)\s+(?:Ergebnis|Lösung|Wert)\s+aus",
        # Auf vorherige Aufgabe aufbauend
        r"(?:das|die|den|Ihr|Ihre)\s+(?:in|aus|bei|von)\s+(?:Aufgabe|Teilaufgabe|TA\.?)\s*\d+[\.,\d]*\s+"
        r"(?:entwickelt|erstellt|entworfene?|erarbeitete?|hergeleitete?|berechnete?|konstruiert)",
        # Ergänzen/Erweitern eines vorherigen Ergebnisses
        r"(?:Ergänzen|Erweitern|Vervollständigen)\s+Sie\s+(?:das|die|den|Ihr|Ihre|Ihren)\s+"
        r"(?:\w+\s+){0,4}(?:aus|in)\s+(?:Aufgabe|Teilaufgabe|TA\.?|A\.?)\s*\d",
        # Schaltbild/Diagramm/Programm aus vorheriger Aufgabe
        r"(?:Schaltbild|Schaltplan|Schaltung|Programm|Code|Quellcode|Diagramm|Modell|"
        r"Tabelle|Grafcet|Zustandsdiagramm|Klassendiagramm|ER-Modell|Flussdiagramm)\s+"
        r"(?:aus|von|in)\s+(?:Aufgabe|Teilaufgabe|TA\.?)\s*\d",
        # "gemäß/laut/wie in Aufgabe X" als implizite Abhängigkeit
        r"(?:gemäß|laut|wie\s+in|entsprechend)\s+(?:Aufgabe|Teilaufgabe|TA\.?)\s+\d+[\.,\d]*",
        # Auf Basis der vorherigen Teilaufgabe
        r"auf\s+(?:der\s+)?Basis\s+(?:der|des|Ihrer|Ihres|von)\s+"
        r"(?:Ergebnisse?|Lösung|Schaltung|Tabelle)\s+(?:aus|von|in)?\s*\d",
        # "das in X.Y entworfene/erstellte ..."
        r"(?:das|die|den)\s+in\s+(?:Aufgabe|Teilaufgabe|TA\.?|A\.?)\s*\d+[\.,\d]*\s+"
        r"(?:entworfene?|erstellte?|entwickelte?|hergeleitete?|berechnete?|verwendete?)",
        # Dreistufige Abhängigkeit: "baut auf X auf"
        r"baut\s+(?:direkt\s+)?auf\s+(?:Aufgabe|Teilaufgabe)\s+\d",
        # "Ihre Lösung / Ihr Ergebnis aus"
        r"(?:Ihre?[nm]?)\s+(?:Lösung|Ergebnis|Schaltung|Programm|Diagramm)\s+aus\s+"
        r"(?:Aufgabe|Teilaufgabe|TA\.?)\s*\d",
        # "Tragen Sie in das Schaltbild aus X ein"
        r"(?:Tragen|Zeichnen|Fügen|Markieren)\s+Sie\s+.{5,60}?\s+(?:in|auf|in\s+das)\s+"
        r"(?:Schaltbild|Schaltplan|Diagramm|Vorlage|Formular)\s+(?:aus|von)?\s*(?:Aufgabe\s*)?\d",
    ]

    # Alternativwert-Muster: zeigen, dass Abhängigkeit abgefedert ist
    alternativ_patterns = [
        r"[Ss]ollten\s+Sie\s+(?:in\s+(?:Aufgabe|Teilaufgabe)\s+\d+[\.,\d]*)?\s*"
        r"(?:kein[e]?|nicht|nichts)\s+(?:Ergebnis|Lösung|Wert|Schaltung|Diagramm)?\s*"
        r"(?:erhalten|haben|ermittelt|erstellt|entwickelt|gefunden|berechnet)?",
        r"[Ff]alls\s+Sie\s+(?:in\s+(?:Aufgabe|Teilaufgabe)\s*\d+[\.,\d]*)?\s*"
        r"kein[e]?\s+(?:Ergebnis|Lösung|Wert)",
        r"[Nn]utzen?\s+Sie\s+(?:in\s+diesem\s+Fall|alternativ|stattdessen)\s+"
        r"(?:den|die|das|Wert|Ergebnis|Zahl|folgende[rn]?)",
        r"[Aa]lternativwert",
        r"[Vv]erwenden\s+Sie\s+(?:in\s+diesem\s+Fall|alternativ|stattdessen|dann)\s+"
        r"(?:den|die|das|folgende[rn]?\s+Wert|folgende\s+(?:Schaltung|Lösung)|die\s+Zahl)",
        r"[Ss]ollten.*?verwenden\s+Sie\s+(?:in\s+diesem\s+Fall|alternativ)",
        r"(?:Hilfs-?|Ersatz-?)wert",
        r"[Ff]ür\s+diese\s+(?:Aufgabe|Teilaufgabe)\s+(?:können\s+Sie\s+)?(?:alternativ\s+)?(?:den\s+Wert|die\s+Zahl)\s+\d",
    ]

    # Alle Treffer sammeln
    gefundene_abhaengigkeiten = []
    for pat in abhaengig_explizit:
        for m in re.finditer(pat, schueler_text, re.IGNORECASE):
            start = max(0, m.start() - 20)
            end = min(len(schueler_text), m.end() + 40)
            kontext = schueler_text[start:end].replace("\n", " ").strip()
            gefundene_abhaengigkeiten.append(kontext)

    hat_alternativwert = any(
        re.search(pat, schueler_text, re.IGNORECASE | re.DOTALL)
        for pat in alternativ_patterns
    )

    if not gefundene_abhaengigkeiten:
        return PruefungsErgebnis("4.2",
            "Teilaufgaben unabhängig lösbar (Vorgabe 4.2)",
            True,
            "Keine expliziten Abhängigkeiten zwischen Teilaufgaben erkannt.")

    # Abhängigkeiten gefunden – sind sie durch Alternativwerte abgesichert?
    beispiele = list(dict.fromkeys(gefundene_abhaengigkeiten[:4]))  # max. 4, dedupliziert
    beispiel_str = " | ".join(f'„{b[:60]}"' for b in beispiele)

    if hat_alternativwert:
        return PruefungsErgebnis("4.2",
            "Teilaufgaben unabhängig lösbar (Vorgabe 4.2)",
            True,
            f"Abhängigkeiten erkannt, aber Alternativwert/-hinweis vorhanden. "
            f"Fundstellen: {beispiel_str}")
    else:
        return PruefungsErgebnis("4.2",
            "Teilaufgaben unabhängig lösbar (Vorgabe 4.2)",
            None,
            f"MANUELL PRÜFEN: {len(gefundene_abhaengigkeiten)} mögliche Aufgaben-Abhängigkeit(en) "
            f"ohne erkennbaren Alternativwert erkannt. "
            f"Gemäß Vorgabe 4.2 muss jede Teilaufgabe unabhängig lösbar sein. "
            f"Falls eine Teilaufgabe auf Ergebnissen einer anderen aufbaut, "
            f"ist ein Alternativwert oder Hinweis erforderlich. "
            f"Fundstellen: {beispiel_str}")


# ---------------------------------------------------------------------------
# Zusätzliche Prüfungen (aus Auswertung Gutachten der Vorjahre)
# ---------------------------------------------------------------------------

# Bekannte Nicht-EPA-Operatoren, die häufig fälschlich verwendet werden
# Quellen: Auswertung Gutachten der Vorjahre (Hildesheim, Rotenburg, Stade u.a.)
NICHT_EPA_OPERATOREN = {
    "erstellen", "kommentieren", "implementieren", "speichern",
    "reduzieren", "programmieren", "konfigurieren", "installieren",
    "testen", "codieren", "notieren", "ergänzen", "eintragen",
    "ausfüllen", "lesen", "eingeben", "ausgeben", "anpassen",
    # Weitere häufige Nicht-EPA-Operatoren aus Gutachten-Auswertung:
    "erweitern",   # sehr häufig fälschlich verwendet (z.B. Rotenburg, Stade)
    "umsetzen",    # kein EPA-Operator
    "aufbauen",    # kein EPA-Operator
    "validieren",  # kein EPA-Operator
    "kompilieren", # kein EPA-Operator
    "abbilden",    # kein EPA-Operator
    "vervollständigen",  # kein EPA-Operator
}


def check_punkte_vs_be(schueler_text: str, lehrer_text: str) -> PruefungsErgebnis:
    """Prüft ob 'Punkte' statt 'BE' (Bewertungseinheiten) verwendet wird.
    'Punkte' ist dem KMK-Notensystem (0-15) vorbehalten."""
    # Im Schülermaterial nach "Punkte" suchen (ohne "KMK-Punkte")
    treffer_schueler = re.findall(
        r"\b\d+\s+Punkte\b", schueler_text, re.IGNORECASE
    )
    # Prüfe ob "BE" auch vorkommt
    hat_be = bool(re.search(r"\b\d+\s+BE\b", schueler_text, re.IGNORECASE))

    if treffer_schueler and not hat_be:
        return PruefungsErgebnis("X.3",
            "Bewertungseinheiten (BE) statt 'Punkte'",
            False,
            f"Im Schülermaterial wird 'Punkte' verwendet ({len(treffer_schueler)}x). "
            f"Korrekt wäre 'BE' (Bewertungseinheiten). "
            f"'Punkte' ist dem KMK-Notensystem (0–15) vorbehalten.")
    elif treffer_schueler and hat_be:
        return PruefungsErgebnis("X.3",
            "Bewertungseinheiten (BE) statt 'Punkte'",
            None,
            f"Im Schülermaterial wird sowohl 'Punkte' ({len(treffer_schueler)}x) als auch 'BE' "
            f"verwendet. Bitte einheitlich 'BE' verwenden.")
    else:
        return PruefungsErgebnis("X.3",
            "Bewertungseinheiten (BE) statt 'Punkte'",
            True,
            "Korrekt: 'Punkte' wird nicht fälschlich für Bewertungseinheiten verwendet.")


def check_operatoren_schueler_vs_ewh(schueler_text: str, lehrer_text: str) -> PruefungsErgebnis:
    """Prüft ob die Operatoren im Schülermaterial mit denen im Erwartungshorizont
    übereinstimmen (häufigster Fehler laut Auswertung)."""
    ops_schueler = find_operatoren_in_aufgabenstellung(schueler_text)
    ops_ewh = find_operatoren_in_text(lehrer_text)

    schueler_set = set(o["operator"] for o in ops_schueler)
    ewh_set = set(o["operator"] for o in ops_ewh)

    # Operatoren im Schülermaterial, die nicht im EWH auftauchen
    nur_schueler = schueler_set - ewh_set
    # Operatoren im EWH, die nicht im Schülermaterial als Auftrag erscheinen
    nur_ewh = ewh_set - schueler_set

    kommentar_parts = []
    if nur_schueler:
        kommentar_parts.append(
            f"Operatoren im Schülermaterial, aber nicht im EWH: {', '.join(sorted(nur_schueler))}")
    if nur_ewh:
        kommentar_parts.append(
            f"Operatoren im EWH, aber nicht als Arbeitsauftrag im Schülermaterial: "
            f"{', '.join(sorted(nur_ewh))}")

    if not nur_schueler:
        return PruefungsErgebnis("X.4",
            "Operatoren Schülermaterial ↔ Erwartungshorizont",
            True,
            f"Alle Operatoren aus dem Schülermaterial ({', '.join(sorted(schueler_set))}) "
            f"finden sich auch im Erwartungshorizont.")
    else:
        return PruefungsErgebnis("X.4",
            "Operatoren Schülermaterial ↔ Erwartungshorizont",
            False,
            " | ".join(kommentar_parts))


FEHLZUORDNUNG_WARNUNG = {
    # AFB-II-Operatoren, die häufig fälschlich in AFB I eingetragen werden:
    "begründen":    "NUR AFB II – niemals AFB I! (häufigster Fehler laut Gutachten)",
    "dokumentieren": "NUR AFB III – niemals AFB I oder II! (häufig falsch zugeordnet)",
    "skizzieren":   "NUR AFB II – niemals AFB I! (Gutachten: Lüchow, Hannover)",
    "ermitteln":    "NUR AFB II – niemals AFB I oder III! (Gutachten: Hannover)",
    "ableiten":     "NUR AFB II – niemals AFB I! (Gutachten: Hannover)",
    # AFB-II/III-Operatoren, die manchmal nur AFB I erhalten:
    "analysieren":  "AFB II/III – niemals allein AFB I!",
    "beurteilen":   "AFB II/III – niemals allein AFB I! (Gutachten: Hannover, Lüneburg)",
    "entwickeln":   "AFB II/III – niemals allein AFB I!",
    "entwerfen":    "AFB II/III – niemals allein AFB I!",
    "überprüfen":   "AFB II/III – niemals allein AFB I!",
    "bewerten":     "AFB II/III – niemals allein AFB I!",
    # AFB-I-Operatoren, die manchmal fälschlich höher eingetragen werden:
    "beschreiben":  "NUR AFB I – niemals AFB II oder III!",
    "nennen":       "NUR AFB I – niemals AFB II oder III!",
}


def check_afb_zuordnung_korrekt(lehrer_text: str) -> PruefungsErgebnis:
    """Prüft ob die AFB-Zuordnungen im EWH mit der Operatorentabelle übereinstimmen.
    Häufiger Fehler: Operatoren dem falschen AFB zugeordnet."""
    ops_ewh = find_operatoren_in_text(lehrer_text)

    afb_data = parse_erwartungshorizont_afb(lehrer_text)
    gesamt = afb_data.get("gesamt", 0)

    if gesamt == 0:
        return PruefungsErgebnis("X.5",
            "AFB-Zuordnung korrekt (Operatoren ↔ Tabelle)",
            None,
            "AFB-Verteilung konnte nicht extrahiert werden. "
            "Bitte manuell prüfen ob Operatoren den richtigen AFBs zugeordnet sind. "
            "Häufige Fehler: 'Begründen' ist AFB II, 'Dokumentieren' ist AFB III, "
            "'Skizzieren' ist AFB II.")

    # Referenzliste der im EWH verwendeten Operatoren
    referenz = []
    warnungen = []
    for op_info in ops_ewh:
        op = op_info["operator"]
        if op in OPERATOREN:
            korrekte_afbs = OPERATOREN[op]["afb"]
            referenz.append(f"{op.capitalize()}: AFB {'/'.join(korrekte_afbs)}")
            if op in FEHLZUORDNUNG_WARNUNG:
                warnungen.append(f"{op.capitalize()}: {FEHLZUORDNUNG_WARNUNG[op]}")

    kommentar = (
        "Referenz für im EWH verwendete Operatoren: "
        + ("; ".join(referenz[:8]) + ("..." if len(referenz) > 8 else "")
           if referenz else "keine erkannt")
    )
    if warnungen:
        kommentar += " | Zu prüfende Risiko-Operatoren: " + "; ".join(warnungen)

    return PruefungsErgebnis("X.5",
        "AFB-Zuordnung korrekt (Operatoren ↔ Tabelle)",
        None,
        kommentar)


def check_schwerpunkt_angabe(schueler_text: str) -> PruefungsErgebnis:
    """Prüft ob der Schwerpunkt 'Informationstechnik' angegeben ist."""
    if re.search(r"Schwerpunkt[:\s]*Informationstechnik",
                 schueler_text, re.IGNORECASE):
        return PruefungsErgebnis("X.6",
            "Schwerpunkt 'Informationstechnik' angegeben",
            True,
            "Schwerpunkt 'Informationstechnik' ist korrekt angegeben.")
    elif re.search(r"Informationstechnik", schueler_text, re.IGNORECASE):
        return PruefungsErgebnis("X.6",
            "Schwerpunkt 'Informationstechnik' angegeben",
            True,
            "'Informationstechnik' ist im Dokument erwähnt.")
    else:
        return PruefungsErgebnis("X.6",
            "Schwerpunkt 'Informationstechnik' angegeben",
            False,
            "Schwerpunkt 'Informationstechnik' nicht gefunden. "
            "Muss im Kopfbereich des Schülermaterials stehen.")


def check_be_zeit_verhaeltnis(schueler_text: str, aufgaben: list[Aufgabe]) -> PruefungsErgebnis:
    """X.7: Prüft ob das Verhältnis von BE zur Bearbeitungszeit angemessen ist.
    Bearbeitungszeit Abiturklausur: 300 Minuten. Richtwert: ca. 2,5–3 Minuten pro BE."""
    # Bearbeitungszeit extrahieren
    m = re.search(r"Bearbeitungszeit[:\s]*(\d+)\s*Min", schueler_text, re.IGNORECASE)
    zeit_min = int(m.group(1)) if m else ABITUR_BEARBEITUNGSZEIT_MIN

    gesamt_be = sum(a.gesamtpunkte for a in aufgaben if a.gesamtpunkte)

    if gesamt_be == 0:
        return PruefungsErgebnis("X.7",
            "Verhältnis BE / Bearbeitungszeit",
            None,
            "Keine Gesamtpunktzahl ermittelbar.")

    min_pro_be = zeit_min / gesamt_be
    kommentar = (f"Bearbeitungszeit: {zeit_min} Min "
                 f"(Abitur-Sollwert: {ABITUR_BEARBEITUNGSZEIT_MIN} Min), "
                 f"Gesamt-BE: {gesamt_be}, "
                 f"Verhältnis: {min_pro_be:.1f} Min/BE (Richtwert: 2,5–3,0 Min/BE).")

    if not m:
        kommentar += (f" Bearbeitungszeit nicht im Schülermaterial gefunden, "
                      f"Berechnung mit Sollwert {ABITUR_BEARBEITUNGSZEIT_MIN} Min.")

    if zeit_min != ABITUR_BEARBEITUNGSZEIT_MIN:
        kommentar += (f" ACHTUNG: Angegebene Bearbeitungszeit ({zeit_min} Min) weicht "
                      f"vom Abitur-Sollwert ({ABITUR_BEARBEITUNGSZEIT_MIN} Min) ab!")

    if 2.0 <= min_pro_be <= 3.5:
        return PruefungsErgebnis("X.7",
            "Verhältnis BE / Bearbeitungszeit",
            True, kommentar)
    else:
        return PruefungsErgebnis("X.7",
            "Verhältnis BE / Bearbeitungszeit",
            False,
            kommentar + " ABWEICHUNG vom Richtwert!")


def check_operatoren_im_ewh(lehrer_text: str) -> PruefungsErgebnis:
    """Prüft ob im Erwartungshorizont Operatoren nach EPA verwendet werden.
    Laut Auswertung fehlen manchmal Operatoren komplett im EWH."""
    # Suche Erwartungshorizont-Abschnitt
    ewh_start = re.search(r"Erwartungshorizont", lehrer_text, re.IGNORECASE)
    if not ewh_start:
        return PruefungsErgebnis("X.8",
            "Operatoren im Erwartungshorizont",
            None,
            "Kein Erwartungshorizont-Abschnitt gefunden.")

    ewh_text = lehrer_text[ewh_start.start():]
    ops = find_operatoren_in_text(ewh_text)

    if len(ops) >= 3:
        op_namen = sorted(set(o["operator"] for o in ops))
        return PruefungsErgebnis("X.8",
            "Operatoren im Erwartungshorizont",
            True,
            f"{len(ops)} Operatoren im EWH gefunden: {', '.join(op_namen[:10])}"
            + ("..." if len(op_namen) > 10 else ""))
    elif ops:
        return PruefungsErgebnis("X.8",
            "Operatoren im Erwartungshorizont",
            None,
            f"Nur {len(ops)} Operatoren im EWH. Bitte prüfen ob der EWH "
            f"operatorenbezogen formuliert ist.")
    else:
        return PruefungsErgebnis("X.8",
            "Operatoren im Erwartungshorizont",
            False,
            "Keine Operatoren nach EPA im Erwartungshorizont gefunden. "
            "Der EWH sollte operatorenbezogen formuliert sein.")


def check_nicht_epa_operatoren(schueler_text: str) -> PruefungsErgebnis:
    """Prüft ob Nicht-EPA-Operatoren als Arbeitsauftrag verwendet werden.
    Diese müssen im Lehrermaterial als erweiterte Operatoren dokumentiert sein."""
    # Suche Nicht-EPA-Operatoren in Imperativ-Form
    gefundene = []
    for op in sorted(NICHT_EPA_OPERATOREN):
        pattern = re.compile(
            r"\b" + re.escape(op) + r"\w*\s+Sie\b",
            re.IGNORECASE
        )
        matches = pattern.findall(schueler_text)
        if matches:
            gefundene.append(op)

    if not gefundene:
        return PruefungsErgebnis("X.9",
            "Keine Nicht-EPA-Operatoren als Arbeitsauftrag",
            True,
            "Keine bekannten Nicht-EPA-Operatoren als Arbeitsauftrag verwendet.")
    else:
        return PruefungsErgebnis("X.9",
            "Keine Nicht-EPA-Operatoren als Arbeitsauftrag",
            False,
            f"Folgende Nicht-EPA-Operatoren werden als Arbeitsauftrag verwendet: "
            f"{', '.join(sorted(gefundene))}. "
            f"Diese müssen im Lehrermaterial als erweiterte Operatoren mit "
            f"AFB-Zuordnung dokumentiert sein.")


def check_punkteverteilung_transparent(lehrer_text: str) -> PruefungsErgebnis:
    """Prüft ob die Punkteverteilung im EWH transparent und nachvollziehbar ist.
    Bei mehreren Operatoren pro Teilaufgabe soll erkennbar sein,
    welcher Operator wie viele BE ergibt."""
    # Suche nach tabellarischer Aufschlüsselung im EWH
    hat_tabelle = bool(re.search(
        r"(?:I\s+II\s+III|AFB\s*I\s*AFB\s*II\s*AFB\s*III)",
        lehrer_text, re.IGNORECASE
    ))
    hat_be_spalte = bool(re.search(r"(?:Summe|∑|Σ|BE\s*gesamt)", lehrer_text, re.IGNORECASE))
    hat_teilaufgaben_be = len(re.findall(r"\d+\.\d+.*?\d+", lehrer_text)) > 3

    if hat_tabelle and hat_teilaufgaben_be:
        return PruefungsErgebnis("X.10",
            "Punkteverteilung im EWH transparent",
            True,
            "Tabellarische AFB-Zuordnung mit BE-Verteilung erkennbar.")
    elif hat_tabelle:
        return PruefungsErgebnis("X.10",
            "Punkteverteilung im EWH transparent",
            None,
            "AFB-Tabelle vorhanden, aber Zuordnung zu Teilaufgaben unklar. "
            "Bitte prüfen ob bei mehreren Operatoren pro Aufgabe die "
            "BE-Verteilung transparent ist.")
    else:
        return PruefungsErgebnis("X.10",
            "Punkteverteilung im EWH transparent",
            None,
            "Keine tabellarische AFB-Zuordnung erkannt. "
            "Bitte manuell prüfen.")


def check_unterrichtszusammenhang(lehrer_text: str) -> PruefungsErgebnis:
    """2.3: Beschreibung des Unterrichtszusammenhangs (EPA 3.3).

    Laut Gutachten-Auswertung (Hannover): 'Der Bezug zum Halbjahresthema reicht nicht
    aus. Wie ist der Bezug zum Unterricht? Welche Aufgabenstellungen wurden im Unterricht
    behandelt? Warum müssen die Schülerinnen und Schüler diese Aufgabe lösen können?'

    Der regelbasierte Check prüft nur ob ÜBERHAUPT eine Beschreibung vorhanden ist.
    Die Qualität (Tiefe, Konkretheit) prüft die KI.
    """
    # Schlüsselwörter für das Vorhandensein einer Unterrichtszusammenhang-Beschreibung
    vorhanden_patterns = [
        r"Bezug\s+der\s+Aufgaben",
        r"[Uu]nterrichtliche\s+[Vv]oraussetzungen",
        r"[Uu]nterrichtlicher\s+[Kk]ontext",
        r"[Vv]oraussetzungen?\s+(?:im\s+)?[Uu]nterricht",
        r"[Uu]nterrichtszusammenhang",
        r"[Hh]albjahresthema",
        r"[Qq]ualifikationsphase\s+\d",
        r"wurde[n]?\s+(?:in\s+(?:der\s+)?(?:Klasse|Jahrgangsstufe|Kurs|QK?))\s*(?:\d{2}[\.,]\d)?",
        r"[Ll]erngebiet\s+(?:IT[1-5])\s+(?:wurde[n]?\s+)?(?:behandelt|thematisiert|unterrichtet)",
        r"[Ii]m\s+[Uu]nterricht\s+(?:wurden|wurde|sind|hat)\s",
        r"[Tt]hema\s+des\s+(?:Unterrichts|Kurses|Halbjahres)",
    ]

    hat_beschreibung = any(
        re.search(pat, lehrer_text, re.IGNORECASE)
        for pat in vorhanden_patterns
    )

    # Hinweise auf minimale Qualität
    hat_konkreten_inhalt = bool(re.search(
        r"(?:wurden\s+(?:folgende|die\s+folgenden|verschiedene)|\b(?:IT[1-5])\b.*?behandelt"
        r"|[Uu]nterrichtet\s+wurden|[Ss]chüler(?:innen)?.{3,80}(?:kennen|können|haben\s+gelernt))",
        lehrer_text, re.IGNORECASE
    ))

    if not hat_beschreibung:
        return PruefungsErgebnis("2.3",
            "Beschreibung Unterrichtszusammenhang (EPA 3.3)",
            False,
            "KEINE Beschreibung des Unterrichtszusammenhangs im Lehrermaterial gefunden. "
            "Gemäß EPA 3.3 muss der Bezug der Aufgaben zum vorangegangenen Unterricht "
            "beschrieben werden: Welche Lerngebiete wurden behandelt? Welche Aufgaben "
            "wurden im Unterricht geübt? Warum können die Schüler diese Prüfung lösen?")

    # Beschreibung vorhanden, aber Qualität unklar → KI soll prüfen
    qualitaets_hinweis = (
        "KI PRÜFT QUALITÄT: Beschreibung vorhanden, aber ausreichend konkret? "
        "Laut Gutachten-Auswertung reicht der bloße Verweis auf das Halbjahresthema NICHT aus. "
        "Erforderlich: Konkrete Unterrichtsinhalte, Aufgabentypen, Kompetenzbegründung."
    )
    if hat_konkreten_inhalt:
        qualitaets_hinweis += " Hinweise auf konkreten Inhalt gefunden."

    return PruefungsErgebnis("2.3",
        "Beschreibung Unterrichtszusammenhang (EPA 3.3)",
        None,
        qualitaets_hinweis)


def check_afb_zuordnung_ewh_zeilenweise(lehrer_text: str) -> PruefungsErgebnis:
    """X.5-Ergänzung: Prüft bekannte AFB-Fehlzuordnungen in EWH-Tabellenzeilen.

    Versucht, aus dem EWH-Text Zeilen zu extrahieren, in denen bekannte Risiko-Operatoren
    vorkommen, und prüft ob die nachfolgenden Zahlen auf eine Fehlzuordnung hindeuten.
    Häufigster Fehler: 'Begründen' mit Punkten in AFB I, 'Dokumentieren' in AFB I/II.
    """
    # EWH-Abschnitt isolieren
    ewh_match = re.search(r"Erwartungshorizont", lehrer_text, re.IGNORECASE)
    if not ewh_match:
        return PruefungsErgebnis("X.5b",
            "AFB-Fehlzuordnung EWH (Zeilenanalyse)",
            None,
            "Kein Erwartungshorizont-Abschnitt gefunden – übersprungen.")

    ewh_text = lehrer_text[ewh_match.start():]

    # EWH-Zeilen: Teilaufgabe-Pattern gefolgt von Text und Zahlen
    # Typisches Format (nach PDF-Extraktion): "1.2 Begründen Sie... 4 4" (nur AFB I = FALSCH)
    zeilen_pattern = re.compile(
        r"^(\d+\.\d+[a-z]?)\s+(.+?)[\s]+(\d+)[\s]+(\d+)[\s]+(\d+)[\s]+(\d+)\s*$",
        re.MULTILINE
    )
    zeilen_pattern_kurz = re.compile(
        r"^(\d+\.\d+[a-z]?)\s+(.+?)[\s]+(\d+)[\s]+(\d+)\s*$",
        re.MULTILINE
    )

    verdaechtig = []

    # Risiko-Operatoren mit ihren ERLAUBTEN AFBs (welche Spalten dürfen Punkte haben)
    risiko_ops = {
        "begründen":    {"verboten_i": True,  "nur_ii": True,  "afb": "II"},
        "dokumentieren": {"verboten_i": True, "verboten_ii": True, "afb": "III"},
        "skizzieren":   {"verboten_i": True,  "nur_ii": True,  "afb": "II"},
        "ermitteln":    {"verboten_i": True,  "nur_ii": True,  "afb": "II"},
        "ableiten":     {"verboten_i": True,  "nur_ii": True,  "afb": "II"},
        "beschreiben":  {"verboten_ii": True, "verboten_iii": True, "afb": "I"},
        "nennen":       {"verboten_ii": True, "verboten_iii": True, "afb": "I"},
    }

    for m in zeilen_pattern.finditer(ewh_text):
        ta_nr, zeilentext, n1, n2, n3, n4 = (
            m.group(1), m.group(2), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6))
        )
        # n1=AFB I, n2=AFB II, n3=AFB III, n4=Summe (typisches EWH-Format)
        zeilentext_lower = zeilentext.lower()
        for op, regeln in risiko_ops.items():
            if op in zeilentext_lower:
                fehler = []
                if regeln.get("verboten_i") and n1 > 0:
                    fehler.append(f"AFB I = {n1} (verboten für '{op}')")
                if regeln.get("verboten_ii") and n2 > 0:
                    fehler.append(f"AFB II = {n2} (verboten für '{op}')")
                if regeln.get("verboten_iii") and n3 > 0:
                    fehler.append(f"AFB III = {n3} (verboten für '{op}')")
                if fehler:
                    verdaechtig.append(
                        f"Teilaufgabe {ta_nr}: Operator '{op}' (korrekt: AFB {regeln['afb']}) "
                        f"→ {', '.join(fehler)}"
                    )

    if verdaechtig:
        return PruefungsErgebnis("X.5b",
            "AFB-Fehlzuordnung EWH (Zeilenanalyse)",
            False,
            f"WAHRSCHEINLICHE AFB-FEHLZUORDNUNGEN im EWH erkannt: "
            f"{'; '.join(verdaechtig)}. Bitte zwingend manuell prüfen!")

    # Auch Kurzformat prüfen (nur 2 Zahlen am Ende: Operator, Σ – kann auf AFB-I-Zuordnung hinweisen)
    kurzform_verdaechtig = []
    for m in zeilen_pattern_kurz.finditer(ewh_text):
        ta_nr, zeilentext, n1, n2 = (
            m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        )
        zeilentext_lower = zeilentext.lower()
        for op, regeln in risiko_ops.items():
            if op in zeilentext_lower and regeln.get("verboten_i") and n1 > 0:
                kurzform_verdaechtig.append(
                    f"Teilaufgabe {ta_nr}: '{op}' – 1 Zahl erkannt ({n1}), "
                    f"ggf. fälschlich AFB I?"
                )

    if not verdaechtig and not kurzform_verdaechtig:
        return PruefungsErgebnis("X.5b",
            "AFB-Fehlzuordnung EWH (Zeilenanalyse)",
            None,
            "Keine eindeutigen AFB-Fehlzuordnungen per Zeilenanalyse erkannt. "
            "KI (X.5) prüft die AFB-Verteilung im Detail.")

    return PruefungsErgebnis("X.5b",
        "AFB-Fehlzuordnung EWH (Zeilenanalyse)",
        None,
        f"Mögliche Fehlzuordnungen in Kurzformat-Zeilen (bitte prüfen): "
        f"{'; '.join(kurzform_verdaechtig[:3])}")


def check_lerngebiete_verknuepfung(lehrer_text: str, schueler_text: str) -> PruefungsErgebnis:
    """X.14: Prüft ob mindestens zwei Lerngebiete abgedeckt sind.

    Laut Gutachten-Auswertung (Zeven): 'Keine Aufgabe verbindet mehr als ein Lerngebiet.'
    Laut EPA müssen alle verbindlichen Lerngebiete (IT1, IT2) und ein optionales
    (IT3/IT4/IT5) im Abitur vertreten sein. Beide Vorschläge zusammen müssen
    mindestens 3 Lerngebiete abdecken.
    """
    text = lehrer_text + " " + schueler_text

    # Suche nach IT-Lerngebiet-Bezeichnungen
    gefundene_lgs = set()
    for lg_id, lg_titel in IT_LERNGEBIETE.items():
        if re.search(re.escape(lg_id) + r"\b", text, re.IGNORECASE):
            gefundene_lgs.add(lg_id)
        # Titel-Fragmente suchen (Hauptwort des Lerngebietstitels)
        hauptwort = lg_titel.split()[0]
        if len(hauptwort) > 5 and hauptwort.lower() in text.lower():
            gefundene_lgs.add(lg_id)

    # Verbindliche Lerngebiete prüfen
    verbindlich_gefunden = gefundene_lgs & IT_VERBINDLICH
    optional_gefunden = gefundene_lgs & IT_OPTIONAL

    detail = (
        f"Erkannte Lerngebiete: {', '.join(sorted(gefundene_lgs)) if gefundene_lgs else 'keine'}. "
        f"Verbindlich (IT1, IT2) erkannt: {', '.join(sorted(verbindlich_gefunden)) or 'keine'}. "
        f"Optional (IT3–IT5) erkannt: {', '.join(sorted(optional_gefunden)) or 'keine'}."
    )

    if not gefundene_lgs:
        return PruefungsErgebnis("X.14",
            "Lerngebiete abgedeckt (mind. IT1+IT2+1 optional)",
            None,
            f"Keine IT-Lerngebiet-Kennungen erkannt. {detail} "
            f"Bitte manuell prüfen ob IT1 (verbindlich) und IT2 (verbindlich) "
            f"sowie ein optionales Lerngebiet abgedeckt sind.")

    if len(gefundene_lgs) < 2:
        return PruefungsErgebnis("X.14",
            "Lerngebiete abgedeckt (mind. IT1+IT2+1 optional)",
            False,
            f"Nur 1 Lerngebiet erkannt. {detail} "
            f"Laut Vorgabe müssen die Vorschläge aus mind. 3 Lerngebieten stammen.")

    if verbindlich_gefunden != IT_VERBINDLICH:
        fehlende = IT_VERBINDLICH - verbindlich_gefunden
        return PruefungsErgebnis("X.14",
            "Lerngebiete abgedeckt (mind. IT1+IT2+1 optional)",
            None,
            f"Verbindliches Lerngebiet möglicherweise nicht erkannt: "
            f"{', '.join(sorted(fehlende))}. {detail} "
            f"Bitte manuell prüfen.")

    return PruefungsErgebnis("X.14",
        "Lerngebiete abgedeckt (mind. IT1+IT2+1 optional)",
        True if len(gefundene_lgs) >= 2 else None,
        detail)


def check_wiederholungen_text(schueler_text: str) -> PruefungsErgebnis:
    """Prüft auf offensichtliche Textwiederholungen (z.B. 'Sie Sie')."""
    wiederholungen = re.findall(
        r"\b(\w{3,})\s+\1\b", schueler_text, re.IGNORECASE
    )
    # Filtere gewollte Doppelungen heraus
    ungewollt = [w for w in wiederholungen
                 if w.lower() not in {"das", "die", "der", "und", "oder", "ist"}]

    if not ungewollt:
        return PruefungsErgebnis("X.11",
            "Keine unbeabsichtigten Textwiederholungen",
            True,
            "Keine offensichtlichen Textwiederholungen gefunden.")
    else:
        beispiele = [f"'{w} {w}'" for w in ungewollt[:5]]
        return PruefungsErgebnis("X.11",
            "Keine unbeabsichtigten Textwiederholungen",
            False,
            f"Mögliche Textwiederholungen: {', '.join(beispiele)}")


def check_digitales_material(schueler_text: str) -> PruefungsErgebnis:
    """Prüft ob digitales Material (Dateien, USB, CD) erwähnt und vorhanden ist."""
    keywords = ["usb", "cd-rom", "cd", "dvd", "datei", "digital",
                "datenträger", "anlage", "anhang"]
    text_low = schueler_text.lower()
    found = [kw for kw in keywords if kw in text_low]

    if found:
        return PruefungsErgebnis("X.12",
            "Digitales Material / Anlagen",
            None,
            f"Hinweise auf digitales Material: {', '.join(found)}. "
            f"Bitte manuell prüfen ob entsprechende Dateien/Datenträger beiliegen.")
    else:
        return PruefungsErgebnis("X.12",
            "Digitales Material / Anlagen",
            True,
            "Kein Verweis auf digitales Material erkannt.")


def check_gesamtpunktzahl(aufgaben: list[Aufgabe], afb_data: dict) -> PruefungsErgebnis:
    """Prüft ob die Gesamtpunktzahl der Aufgaben mit der Summe im EWH übereinstimmt."""
    gesamt_aufgaben = sum(a.gesamtpunkte for a in aufgaben if a.gesamtpunkte)
    gesamt_ewh = afb_data.get("gesamt", 0)

    aufgaben_detail = " + ".join(
        f"Aufg. {a.nummer}: {a.gesamtpunkte} BE"
        for a in aufgaben if a.gesamtpunkte
    )

    if gesamt_aufgaben == 0:
        return PruefungsErgebnis("X.13",
            "Gesamtpunktzahl konsistent",
            None,
            "Gesamtpunktzahl der Aufgaben nicht ermittelbar.")

    if gesamt_ewh == 0:
        return PruefungsErgebnis("X.13",
            "Gesamtpunktzahl konsistent",
            None,
            f"Gesamtpunktzahl Aufgaben: {gesamt_aufgaben} BE ({aufgaben_detail}). "
            f"EWH-Gesamtzahl nicht ermittelbar – bitte manuell vergleichen.")

    if gesamt_aufgaben == gesamt_ewh:
        return PruefungsErgebnis("X.13",
            "Gesamtpunktzahl konsistent",
            True,
            f"Gesamtpunktzahl stimmt überein: {gesamt_aufgaben} BE "
            f"({aufgaben_detail}) = {gesamt_ewh} BE (EWH).")
    else:
        return PruefungsErgebnis("X.13",
            "Gesamtpunktzahl konsistent",
            False,
            f"ABWEICHUNG: SM: {gesamt_aufgaben} BE ({aufgaben_detail}) "
            f"≠ EWH: {gesamt_ewh} BE!")


# ---------------------------------------------------------------------------
# Schülersicherheits-Prüfungen
# ---------------------------------------------------------------------------
# Diese Prüfungen sollen verhindern, dass ein Prüfling auf eine Klausur trifft,
# die formal nicht abnahmebereit ist (Platzhalter unausgefüllt, Anlagen fehlen,
# referenzierte Dateien nicht beigefügt, Nummerierungslücken).
#
# Wichtig: Jede Prüfung MUSS bei nicht erfüllbarer Vorbedingung erfuellt=None
# setzen.  Spekulative Befunde sind ausdrücklich nicht zulässig.

# Sentinel-Wert, mit dem die echte Klausurvorlage des MK markiert, dass ein
# Wert noch einzutragen ist.
_PLATZHALTER_PATTERNS: list[tuple[str, str]] = [
    (r"\bXXX+\b",                       "freier Platzhalter 'XXX'"),
    (r"\b20\s*[_]\s*[_]\b",             "Jahresangabe '20__' nicht ausgefüllt"),
    (r"\b20XX\b",                       "Jahresangabe '20XX' nicht ausgefüllt"),
    (r"\bVersion\s+X\.Y\b",             "Versionsangabe 'Version X.Y' nicht ausgefüllt"),
    (r"\bVersion\s+X\.X\b",             "Versionsangabe 'Version X.X' nicht ausgefüllt"),
    (r"\(\s*unvollständig\s*\)",        "Markierung '(unvollständig)' im Material"),
    (r"\(\s*noch zu ergänzen\s*\)",     "Markierung '(noch zu ergänzen)' im Material"),
    (r"\[\s*Platzhalter\s*\]",          "explizite '[Platzhalter]'-Marke"),
    (r"\bTODO\b",                       "TODO-Marker im Material"),
    (r"\bFIXME\b",                      "FIXME-Marker im Material"),
    (r"\bAbitur_20XX_xxx\b",            "Pfad-Platzhalter 'Abitur_20XX_xxx' nicht ersetzt"),
    (r"\bBBS\s*…",                      "Schulkürzel 'BBS …' noch nicht ersetzt"),
]


def check_unausgefuellte_platzhalter(
    schueler_text: str, lehrer_text: str
) -> PruefungsErgebnis:
    """X.15: Schülersicherheit – kein offener Platzhalter im Material.

    Vorbedingung: SM/LM enthalten extrahierbaren Text (≥ 100 Zeichen kombiniert).
    """
    if len(schueler_text) + len(lehrer_text) < 100:
        return PruefungsErgebnis("X.15",
            "Keine unausgefüllten Platzhalter im Material",
            None,
            "Material zu kurz/leer extrahiert – Platzhalter-Prüfung nicht valide.")

    treffer: list[str] = []
    for muster, beschr in _PLATZHALTER_PATTERNS:
        if re.search(muster, schueler_text):
            treffer.append(f"SM: {beschr}")
        if re.search(muster, lehrer_text):
            treffer.append(f"LM: {beschr}")

    if not treffer:
        return PruefungsErgebnis("X.15",
            "Keine unausgefüllten Platzhalter im Material",
            True,
            "Keine offenen Platzhalter erkannt.")

    return PruefungsErgebnis("X.15",
        "Keine unausgefüllten Platzhalter im Material",
        False,
        "Platzhalter gefunden: " + "; ".join(sorted(set(treffer))) +
        ". Ein Schüler darf in einer Klausur keine 'XXX'/'20XX'/'(unvollständig)'-"
        "Marker vorfinden. Vor Einreichung alle Platzhalter durch konkrete Werte "
        "ersetzen.")


# Suchmuster für Verweise im SM, die ein zugehöriges Bild/Anlage verlangen.
_ANLAGE_PATTERNS = [
    r"Anlage\s+\d+[a-z]?",
    r"Vorlage\s+\d+[a-z]?",
    r"Abbildung\s*[:\s]\s*[\w\-„""]+",
    r"Technologieschema\s+\d+",
    r"Schaltplan",
    r"Schaltbild",
    r"Anschlussplan",
    r"Datenblatt",
]


def check_anlagen_und_abbildungen(
    sm_pages: list[str], schueler_pfad: str
) -> PruefungsErgebnis:
    """X.16: Verweise auf Anlagen/Schemata sind mit Inhalt hinterlegt.

    Sucht in jeder Seite nach Verweisen auf Anlagen, Vorlagen,
    Technologieschemata, Schaltbildern usw. und prüft mit pypdf, ob die
    betroffene Seite ein eingebettetes Bild **oder** ausreichend Text
    (> 250 Zeichen ohne Header/Footer) enthält.

    Vorbedingung: pypdf liefert Seitenobjekte und Bild-Metadaten.
    """
    if not sm_pages:
        return PruefungsErgebnis("X.16",
            "Anlagen und Abbildungen vorhanden",
            None,
            "Keine seitenweise Extraktion möglich – Prüfung nicht valide.")
    try:
        import pypdf  # type: ignore
        reader = pypdf.PdfReader(schueler_pfad)
        seitenbilder: list[int] = []
        for page in reader.pages:
            # ``page.images`` ist robust verfügbar ab pypdf>=3.0
            try:
                anzahl = sum(1 for _ in page.images)
            except Exception:
                anzahl = -1
            seitenbilder.append(anzahl)
        # Wenn Bilder-API durchgängig keine Daten liefert: Prüfung nicht valide
        if all(n < 0 for n in seitenbilder):
            return PruefungsErgebnis("X.16",
                "Anlagen und Abbildungen vorhanden",
                None,
                "pypdf liefert keine Bildinformationen – Prüfung nicht valide.")
    except Exception as e:
        return PruefungsErgebnis("X.16",
            "Anlagen und Abbildungen vorhanden",
            None,
            f"PDF-Bildanalyse fehlgeschlagen ({type(e).__name__}) – nicht valide.")

    befunde: list[str] = []
    anlage_re = re.compile("|".join(_ANLAGE_PATTERNS), re.IGNORECASE)
    for idx, seite in enumerate(sm_pages):
        if not anlage_re.search(seite):
            continue
        # Header/Footer entfernen für eine ehrliche Textmengenmessung
        text_nutz = "\n".join(
            l for l in seite.splitlines()
            if not _SEITEN_HEADER_PATTERN.match(l.strip())
            and "BBS" not in l
            and "Bearbeitungszeit" not in l
        )
        text_len = len(text_nutz.strip())
        # Explizite "(unvollständig)"-Marker melden wir hier nicht erneut
        # (das übernimmt X.15) – aber wenn weder Bild noch Inhalt da ist,
        # ist die Anlage nicht abnahmebereit.
        bilder = seitenbilder[idx] if idx < len(seitenbilder) else -1
        if bilder == 0 and text_len < 250:
            # Verweis auf Anlage X aus dieser Seite extrahieren
            m = anlage_re.search(seite)
            verweis = m.group(0) if m else "Anlage"
            befunde.append(
                f"S. {idx + 1}: '{verweis}' angekündigt, "
                f"aber kein Bild und nur {text_len} Zeichen Inhalt.")
    if not befunde:
        return PruefungsErgebnis("X.16",
            "Anlagen und Abbildungen vorhanden",
            True,
            "Alle erkannten Anlagen-/Schema-Verweise haben Inhalt.")
    return PruefungsErgebnis("X.16",
        "Anlagen und Abbildungen vorhanden",
        False,
        "Fehlende Anlagen/Abbildungen für Schülerbearbeitung: "
        + " | ".join(befunde))


def check_externe_dateien(
    schueler_text: str, schueler_pfad: str
) -> PruefungsErgebnis:
    """X.17: Referenzierte externe Dateien liegen im Klausurordner.

    Sucht im Schülermaterial nach Dateinamen-Verweisen (.pdf/.lsc/.java/
    .html/.css/.xlsx/.csv/.docx/.zip) und prüft, ob diese Dateien neben
    dem SM-PDF im gleichen Ordner liegen.

    Vorbedingung: SM-Pfad existiert und der Elternordner ist lesbar.
    """
    elt = Path(schueler_pfad).parent
    if not elt.exists() or not elt.is_dir():
        return PruefungsErgebnis("X.17",
            "Referenzierte externe Dateien vorhanden",
            None,
            "Klausurordner nicht lesbar – Prüfung nicht valide.")

    # Dateinamen-Muster: Wort.endung, max. 64 Zeichen, keine URLs.
    # Java-FQNs ausschließen: ``java.sql`` in ``java.sql.Connection`` ist kein
    # Dateiname.  Daher: vor dem Match darf kein ``import``/``package`` stehen,
    # nach dem Match kein weiterer ``.<Buchstabe>``.
    erlaubte_endungen = r"(?:pdf|lsc|java|html?|css|xlsx?|csv|docx?|zip|txt|sql|ods|odt)"
    treffer = set()
    for m in re.finditer(
        r"(?<![./\w\-])(?<!import\s)(?<!package\s)"
        r"([\w\-]{2,64}\." + erlaubte_endungen + r")"
        r"(?![./\w\-])",
        schueler_text, re.IGNORECASE,
    ):
        name = m.group(1).lower()
        # Java-Standardpackages (java.sql, java.io, java.util, javax.*)
        # immer ausschließen.
        if name in {"java.sql", "java.io", "java.util", "java.net",
                    "java.lang", "javax.sql"}:
            continue
        treffer.add(name)
    # SM/LM-eigene Dateinamen ausschließen
    sm_name = Path(schueler_pfad).name.lower()
    treffer.discard(sm_name)
    treffer = {n for n in treffer
               if "schuelermaterial" not in n and "lehrermaterial" not in n}

    if not treffer:
        return PruefungsErgebnis("X.17",
            "Referenzierte externe Dateien vorhanden",
            True,
            "Keine externen Dateinamen im Schülermaterial referenziert.")

    vorhandene_namen = {p.name.lower() for p in elt.iterdir() if p.is_file()}
    fehlend = sorted(n for n in treffer if n not in vorhandene_namen)
    if not fehlend:
        return PruefungsErgebnis("X.17",
            "Referenzierte externe Dateien vorhanden",
            True,
            f"Alle {len(treffer)} referenzierten Dateien liegen im Klausurordner.")
    return PruefungsErgebnis("X.17",
        "Referenzierte externe Dateien vorhanden",
        False,
        f"Referenzierte Dateien fehlen im Klausurordner: "
        f"{', '.join(fehlend)}. Schüler benötigen diese Dateien zur Bearbeitung.")


def check_aufgabe_numerierung_konsistent(
    schueler_text: str, aufgaben: list
) -> PruefungsErgebnis:
    """X.18: Nummerierung der Teilaufgaben ist lückenlos und ohne Doppelung.

    Vorbedingung: Mindestens eine Aufgabe mit Teilaufgaben erkannt.
    """
    if not aufgaben or all(not a.teilaufgaben for a in aufgaben):
        return PruefungsErgebnis("X.18",
            "Konsistente Nummerierung der Teilaufgaben",
            None,
            "Keine Teilaufgaben strukturiert erkannt – Prüfung nicht valide.")

    befunde: list[str] = []

    # Doppelnummerierungen wie "1.1, 1.1, 1.2" suchen (Tippfehler in
    # Bearbeitungs­hinweisen) – nur in Sätzen mit drei aufeinanderfolgenden
    # Nummern.
    for m in re.finditer(
        r"\b(\d+\.\d+)\s*,\s*(\d+\.\d+)\s*,\s*(\d+\.\d+)\b", schueler_text):
        nrs = [m.group(1), m.group(2), m.group(3)]
        if len(set(nrs)) < 3:
            befunde.append(f"Doppelnummerierung in Bearbeitungs­hinweis: "
                           f"'{m.group(0)}'")

    # Lücken pro Hauptaufgabe
    for aufg in aufgaben:
        nums = []
        for t in aufg.teilaufgaben:
            try:
                _, subnr = t.nummer.split(".")
                nums.append(int(subnr))
            except (ValueError, IndexError):
                continue
        if len(nums) < 2:
            continue
        nums_sorted = sorted(nums)
        erwartet = list(range(nums_sorted[0], nums_sorted[-1] + 1))
        fehlend = [n for n in erwartet if n not in nums_sorted]
        if fehlend:
            fehl_str = ", ".join(f"{aufg.nummer}.{n}" for n in fehlend)
            befunde.append(f"Lücke in Aufgabe {aufg.nummer}: fehlt {fehl_str}")
        if len(nums_sorted) != len(set(nums_sorted)):
            doppelt = sorted({n for n in nums_sorted if nums_sorted.count(n) > 1})
            befunde.append(f"Doppelte Teilaufgabe(n) in Aufgabe {aufg.nummer}: "
                           f"{doppelt}")

    if not befunde:
        return PruefungsErgebnis("X.18",
            "Konsistente Nummerierung der Teilaufgaben",
            True,
            "Nummerierung der Teilaufgaben ist lückenlos und ohne Doppelung.")
    return PruefungsErgebnis("X.18",
        "Konsistente Nummerierung der Teilaufgaben",
        False,
        " | ".join(befunde))


def check_optischer_eindruck(
    sm_pages: list[str], schueler_pfad: str
) -> PruefungsErgebnis:
    """1.1: Lesbarer optischer Eindruck – nur klar messbare Faktoren prüfen.

    Geprüft wird:
      • Seitenanzahl im sinnvollen Bereich (3–60 Seiten)
      • Keine Seite mit nur Header/Footer und ohne Bild (= „leere Seite")
      • Keine extrem langen Zeilen (> 160 Zeichen → vermutlich Layout-Bruch)

    Vorbedingung: SM ist eine PDF, pypdf-Seitenobjekte lesbar.
    Wenn pypdf keine Bilder-Info liefert, wird die Leerseiten-Prüfung
    übersprungen, andere Faktoren werden geprüft.
    """
    if not sm_pages:
        return PruefungsErgebnis("1.1",
            "Einheitliches, lesbares Schriftbild",
            None,
            "Keine Seiten extrahiert – Prüfung nicht valide.")

    befunde: list[str] = []
    seitenzahl = len(sm_pages)
    if seitenzahl < 3:
        befunde.append(f"Nur {seitenzahl} Seiten erkannt – ungewöhnlich kurz "
                       f"für eine eA-Klausur.")
    elif seitenzahl > 60:
        befunde.append(f"{seitenzahl} Seiten – ungewöhnlich umfangreich; "
                       f"Bearbeitbarkeit prüfen.")

    # Bilder pro Seite – nur wenn pypdf das verlässlich liefert
    bilder: list[int] | None = None
    try:
        import pypdf  # type: ignore
        reader = pypdf.PdfReader(schueler_pfad)
        bilder = []
        for page in reader.pages:
            try:
                bilder.append(sum(1 for _ in page.images))
            except Exception:
                bilder = None
                break
    except Exception:
        bilder = None

    if bilder is not None:
        for idx, seite in enumerate(sm_pages):
            text_nutz = "\n".join(
                l for l in seite.splitlines()
                if not _SEITEN_HEADER_PATTERN.match(l.strip())
                and "BBS" not in l and "Bearbeitungszeit" not in l
            ).strip()
            text_len = len(text_nutz)
            anzahl_bilder = bilder[idx] if idx < len(bilder) else 0
            if text_len < 80 and anzahl_bilder == 0:
                befunde.append(
                    f"S. {idx + 1}: leere Seite (kein Bild, "
                    f"nur {text_len} Zeichen Nutztext).")

    # Sehr lange Zeilen
    for idx, seite in enumerate(sm_pages):
        for zeile in seite.splitlines():
            if len(zeile) > 160:
                befunde.append(
                    f"S. {idx + 1}: Zeile mit {len(zeile)} Zeichen "
                    "(möglicher Layout-Bruch).")
                break

    if not befunde:
        return PruefungsErgebnis("1.1",
            "Einheitliches, lesbares Schriftbild",
            True,
            f"Optisch unauffällig ({seitenzahl} Seiten, keine leeren Seiten, "
            f"keine überlangen Zeilen).")
    return PruefungsErgebnis("1.1",
        "Einheitliches, lesbares Schriftbild",
        False,
        " | ".join(befunde))


# ---------------------------------------------------------------------------
# Zusammenstellung der Operatorenanalyse
# ---------------------------------------------------------------------------

def erstelle_operatoren_analyse(schueler_text: str, lehrer_text: str) -> str:
    """Erstellt eine detaillierte Analyse der verwendeten Operatoren."""
    ops = find_operatoren_in_aufgabenstellung(schueler_text)
    erweiterte = parse_erweiterte_operatoren(lehrer_text)

    zeilen = ["Verwendete Operatoren in der Aufgabenstellung:", ""]

    if not ops:
        zeilen.append(">>> Keine Operatoren in Imperativ-Form ('... Sie') erkannt.")
        zeilen.append("    Bitte manuell prüfen ob Operatoren verwendet werden.")
        return "\n".join(zeilen)

    # Gruppiere nach Operator
    op_gruppen = {}
    for op in ops:
        name = op["operator"]
        if name not in op_gruppen:
            op_gruppen[name] = {"count": 0, "afb": op["afb"], "kontexte": []}
        op_gruppen[name]["count"] += 1
        op_gruppen[name]["kontexte"].append(op["kontext"])

    for name, info in sorted(op_gruppen.items()):
        afb_str = "/".join(info["afb"])
        quelle = " (erweitert)" if name in erweiterte else ""
        zeilen.append(f"  • {name.capitalize()}{quelle} – AFB {afb_str} – {info['count']}x verwendet")

    # Zusammenfassung AFB-Abdeckung
    afbs_abgedeckt = set()
    for info in op_gruppen.values():
        afbs_abgedeckt.update(info["afb"])

    zeilen.append("")
    zeilen.append(f"Abgedeckte Anforderungsbereiche durch Operatoren: {', '.join(sorted(afbs_abgedeckt))}")

    return "\n".join(zeilen)


# ---------------------------------------------------------------------------
# Gesamtbegutachtung
# ---------------------------------------------------------------------------

def begutachte(schueler_pfad: str, lehrer_pfad: str) -> tuple[list[PruefungsErgebnis], str, list[Aufgabe], dict, dict, list[str], list[str]]:
    """
    Führt die automatische Begutachtung durch.
    Gibt (Ergebnisliste, Analyse-Text, Aufgaben, SM-Seitenmap, LM-Seitenmap,
          SM-Seiten-Texte, LM-Seiten-Texte) zurück.
    """
    print(f"Lese Schülermaterial: {schueler_pfad}")
    schueler_text = extract_text(schueler_pfad)
    print(f"  → {len(schueler_text)} Zeichen extrahiert.")

    print(f"Lese Lehrermaterial: {lehrer_pfad}")
    lehrer_text = extract_text(lehrer_pfad)
    print(f"  → {len(lehrer_text)} Zeichen extrahiert.")

    # Seitenweise Analyse für Rückmeldung
    sm_seiten = {}
    lm_seiten = {}
    sm_pages: list[str] = []
    lm_pages: list[str] = []
    ext_sm = Path(schueler_pfad).suffix.lower()
    ext_lm = Path(lehrer_pfad).suffix.lower()
    if ext_sm == ".pdf":
        sm_pages = extract_pages_pdf(schueler_pfad)
        sm_seiten = finde_aufgaben_seiten(sm_pages)
    if ext_lm == ".pdf":
        lm_pages = extract_pages_pdf(lehrer_pfad)
        lm_seiten = finde_aufgaben_seiten(lm_pages)

    # Aufgaben parsen
    aufgaben = parse_aufgaben(schueler_text)
    print(f"  → {len(aufgaben)} Aufgaben erkannt.")
    for a in aufgaben:
        print(f"    Aufgabe {a.nummer}: {a.titel} ({a.gesamtpunkte} P), "
              f"{len(a.teilaufgaben)} Teilaufgaben")

    # AFB-Verteilung
    afb_data = parse_erwartungshorizont_afb(lehrer_text)
    print(f"  → AFB-Verteilung: I={afb_data['afb_I']}, II={afb_data['afb_II']}, "
          f"III={afb_data['afb_III']}, Gesamt={afb_data['gesamt']}")

    # Erweiterte Operatoren – Layout-Extraktion ist hier deutlich verlässlicher,
    # weil die EWH-/Operator-Tabelle im PDF zeilenweise erhalten bleibt.
    lehrer_text_layout = (
        extract_text_pdf(lehrer_pfad, layout=True)
        if ext_lm == ".pdf" else lehrer_text
    )
    erweiterte_ops = parse_erweiterte_operatoren(lehrer_text_layout)
    if not erweiterte_ops:
        # Fallback auf den Standard-Extrakt – falls Layout-Mode kein Ergebnis
        # liefert, könnte die Tabelle anders gesetzt sein.
        erweiterte_ops = parse_erweiterte_operatoren(lehrer_text)
    if erweiterte_ops:
        print(f"  → Erweiterte Operatoren: {', '.join(erweiterte_ops.keys())}")

    # Alle Prüfungen durchführen
    ergebnisse = []

    # 1.x Formale Anforderungen
    ergebnisse.append(check_optischer_eindruck(sm_pages, schueler_pfad))
    ergebnisse.append(check_dokumentenvorlage(schueler_text))
    ergebnisse.append(PruefungsErgebnis("1.3",
        "Deckblatt nach Muster",
        None, "Bitte manuell prüfen ob Deckblatt vorhanden ist."))

    # 2.x Anforderungen an die eingereichten Vorschläge
    ergebnisse.append(PruefungsErgebnis("2.1",
        "Zwei Vorschläge aus mind. 3 Lerngebieten",
        None,
        "Es wird nur ein Vorschlag gleichzeitig geprüft. "
        "Bitte manuell prüfen ob zwei Vorschläge aus mind. 3 Lerngebieten vorliegen."))
    ergebnisse.append(check_lerngebiete(lehrer_text))
    ergebnisse.append(check_unterrichtszusammenhang(lehrer_text))
    ergebnisse.append(check_erwartungshorizont(lehrer_text))
    ergebnisse.append(check_loesung(lehrer_text))
    ergebnisse.append(check_bewertungsschema(lehrer_text))
    ergebnisse.append(check_hilfsmittel(schueler_text))
    ergebnisse.append(check_formelsammlung(schueler_text))

    # 3.x Fachliche Anforderungen
    ergebnisse.append(check_kompetenzen_rrl(schueler_text, lehrer_text))
    ergebnisse.append(check_aufgaben_lerngebiete_rrl(lehrer_text))
    ergebnisse.append(check_ganzheitlichkeit(schueler_text, aufgaben))
    ergebnisse.append(check_berufliche_handlungskompetenz(schueler_text, lehrer_text))
    ergebnisse.append(check_verschiedene_kompetenzen(schueler_text))

    # 4.x Transparenz der Anforderungen
    ergebnisse.append(check_aufgaben_klar_formuliert(schueler_text))
    ergebnisse.append(check_unabhaengigkeit_teilaufgaben(schueler_text))
    ergebnisse.append(check_anforderungen_bearbeitungszeit(schueler_text, aufgaben))
    ergebnisse.append(check_aufgabe_als_arbeitsauftrag(schueler_text))
    ergebnisse.append(check_operatoren_epa(schueler_text, erweiterte_ops))
    ergebnisse.append(check_afb_verteilung(afb_data))
    ergebnisse.append(check_punkte_schueler(schueler_text, aufgaben))

    # Zusatz-Prüfungen (aus Beachte.pdf)
    ergebnisse.append(check_erste_aufgabe_nicht_afb3(schueler_text))
    ergebnisse.append(check_operatoren_erweitert_dokumentiert(lehrer_text, schueler_text))

    # Zusatz-Prüfungen (aus Auswertung Gutachten der Vorjahre)
    ergebnisse.append(check_punkte_vs_be(schueler_text, lehrer_text))
    ergebnisse.append(check_operatoren_schueler_vs_ewh(schueler_text, lehrer_text))
    ergebnisse.append(check_afb_zuordnung_korrekt(lehrer_text))
    ergebnisse.append(check_afb_zuordnung_ewh_zeilenweise(lehrer_text))
    ergebnisse.append(check_schwerpunkt_angabe(schueler_text))
    ergebnisse.append(check_be_zeit_verhaeltnis(schueler_text, aufgaben))
    ergebnisse.append(check_operatoren_im_ewh(lehrer_text))
    ergebnisse.append(check_nicht_epa_operatoren(schueler_text))
    ergebnisse.append(check_punkteverteilung_transparent(lehrer_text))
    ergebnisse.append(check_wiederholungen_text(schueler_text))
    ergebnisse.append(check_digitales_material(schueler_text))
    ergebnisse.append(check_gesamtpunktzahl(aufgaben, afb_data))
    ergebnisse.append(check_lerngebiete_verknuepfung(lehrer_text, schueler_text))

    # Schülersicherheits-Prüfungen (neu)
    ergebnisse.append(check_unausgefuellte_platzhalter(schueler_text, lehrer_text))
    ergebnisse.append(check_anlagen_und_abbildungen(sm_pages, schueler_pfad))
    ergebnisse.append(check_externe_dateien(schueler_text, schueler_pfad))
    ergebnisse.append(check_aufgabe_numerierung_konsistent(schueler_text, aufgaben))

    # Operatoren-Analyse
    analyse = erstelle_operatoren_analyse(schueler_text, lehrer_text)

    return ergebnisse, analyse, aufgaben, sm_seiten, lm_seiten, sm_pages, lm_pages


# ---------------------------------------------------------------------------
# Gutachten-DOCX erstellen
# ---------------------------------------------------------------------------

def erstelle_gutachten_docx(
    ergebnisse: list[PruefungsErgebnis],
    analyse_text: str,
    template_pfad: str,
    output_pfad: str,
    schueler_datei: str,
    lehrer_datei: str,
    mit_hinweisen: bool = False,
):
    """Erstellt ein ausgefülltes Gutachten-DOCX basierend auf der Vorlage.

    Das Raster (✔ / ✘ / ?) wird immer ausgefüllt. Die Hinweise an die Schule
    stehen standardmäßig NICHT im Gutachten, sondern in der Hinweisliste
    (src/bewertung/hinweisliste.py → XLSX/CSV). mit_hinweisen=True schreibt
    den früheren Hinweistext zusätzlich unter „Hinweise für den Referenten“.
    """
    doc = Document(template_pfad)

    # Tabelle ausfüllen
    if doc.tables:
        table = doc.tables[0]

        # Mapping: Kriterium-Nr -> Zeile in der Tabelle
        kriterium_zu_zeile = {}
        for row_idx, row in enumerate(table.rows):
            nr_cell = row.cells[0].text.strip()
            if nr_cell:
                kriterium_zu_zeile[nr_cell] = row_idx

        # Ergebnisse eintragen
        for erg in ergebnisse:
            nr = erg.kriterium_nr
            if nr in kriterium_zu_zeile:
                row_idx = kriterium_zu_zeile[nr]
                erfuellt_cell = table.rows[row_idx].cells[2]
                # Zelle leeren
                for p in erfuellt_cell.paragraphs:
                    p.text = ""
                if erg.erfuellt is True:
                    erfuellt_cell.paragraphs[0].text = "✔"
                elif erg.erfuellt is False:
                    erfuellt_cell.paragraphs[0].text = "✘"
                    # Rote Farbe für nicht erfüllt
                    for run in erfuellt_cell.paragraphs[0].runs:
                        run.font.color.rgb = RGBColor(255, 0, 0)
                else:
                    erfuellt_cell.paragraphs[0].text = "?"

    if not mit_hinweisen:
        doc.save(output_pfad)
        print(f"\nGutachten gespeichert: {output_pfad}")
        return

    # Hinweise eintragen (Absätze nach "Hinweise für den Referenten")
    hinweise_text = _erstelle_hinweise_text(ergebnisse, analyse_text, schueler_datei, lehrer_datei)

    # Finde den Absatz "Hinweise für den Referenten/die Referentin:"
    hinweise_idx = None
    for i, para in enumerate(doc.paragraphs):
        if "Hinweise für den Referenten" in para.text:
            hinweise_idx = i
            break

    if hinweise_idx is not None:
        # Die folgenden leeren Absätze mit Hinweisen füllen
        absatz_nr = 0
        zeilen = hinweise_text.split("\n")
        for i in range(hinweise_idx + 1, len(doc.paragraphs)):
            if absatz_nr >= len(zeilen):
                break
            para = doc.paragraphs[i]
            if para.text.strip() == "" and para.style.name == "Title":
                # Stil auf Normal setzen für bessere Lesbarkeit
                para.text = zeilen[absatz_nr]
                para.style = doc.styles["Normal"]
                # Schriftgröße
                for run in para.runs:
                    run.font.size = Pt(10)
                absatz_nr += 1
            elif "Gesprächsnotiz" in para.text or "Wiedervorlage" in para.text:
                break

        # Falls nicht genug leere Absätze: Rest vor Gesprächsnotiz einfügen
        if absatz_nr < len(zeilen):
            # Finde Gesprächsnotiz-Absatz
            for i, para in enumerate(doc.paragraphs):
                if "Gesprächsnotiz" in para.text:
                    # Restliche Zeilen davor einfügen (als ein Block)
                    rest = "\n".join(zeilen[absatz_nr:])
                    new_para = doc.paragraphs[i]
                    # Vor dem Gesprächsnotiz-Absatz einfügen
                    p_element = new_para._element
                    from docx.oxml.ns import qn
                    from lxml import etree
                    for line in zeilen[absatz_nr:]:
                        new_p = copy.deepcopy(doc.paragraphs[hinweise_idx + 1]._element)
                        new_p_obj = type(doc.paragraphs[0])
                        # Einfacher: direkt text setzen
                        for child in list(new_p):
                            new_p.remove(child)
                        r = etree.SubElement(new_p, qn("w:r"))
                        t = etree.SubElement(r, qn("w:t"))
                        t.text = line
                        p_element.addprevious(new_p)
                    break

    doc.save(output_pfad)
    print(f"\nGutachten gespeichert: {output_pfad}")


def _erstelle_hinweise_text(
    ergebnisse: list[PruefungsErgebnis],
    analyse_text: str,
    schueler_datei: str,
    lehrer_datei: str,
) -> str:
    """Erstellt den Hinweistext für das Gutachten."""
    zeilen = []
    zeilen.append(f"Automatische Begutachtung")
    zeilen.append(f"Schülermaterial: {os.path.basename(schueler_datei)}")
    zeilen.append(f"Lehrermaterial: {os.path.basename(lehrer_datei)}")
    zeilen.append("")

    # Nicht erfüllte Kriterien
    nicht_erfuellt = [e for e in ergebnisse if e.erfuellt is False]
    manuell = [e for e in ergebnisse if e.erfuellt is None]
    erfuellt = [e for e in ergebnisse if e.erfuellt is True]

    if nicht_erfuellt:
        zeilen.append("BEANSTANDUNGEN:")
        for e in nicht_erfuellt:
            zeilen.append(f"  [{e.kriterium_nr}] {e.kriterium_text}:")
            zeilen.append(f"    {e.kommentar}")
        zeilen.append("")

    if manuell:
        zeilen.append("MANUELL ZU PRÜFEN:")
        for e in manuell:
            zeilen.append(f"  [{e.kriterium_nr}] {e.kriterium_text}:")
            zeilen.append(f"    {e.kommentar}")
        zeilen.append("")

    zeilen.append(f"ERFÜLLT: {len(erfuellt)} Kriterien")
    zeilen.append(f"BEANSTANDET: {len(nicht_erfuellt)} Kriterien")
    zeilen.append(f"MANUELL PRÜFEN: {len(manuell)} Kriterien")
    zeilen.append("")

    # Strukturierte Empfehlung am Ende
    zeilen.append("=" * 50)
    zeilen.append("EMPFEHLUNG:")
    empfehlung, auflagen = erzeuge_empfehlung(ergebnisse)
    zeilen.append(empfehlung)
    if auflagen:
        zeilen.append("")
        zeilen.append("Auflagen vor Annahme:")
        for i, auflage in enumerate(auflagen, 1):
            zeilen.append(f"  {i}. {auflage}")
    zeilen.append("")
    zeilen.append(analyse_text)

    return "\n".join(zeilen)


def erzeuge_empfehlung(
    ergebnisse: list[PruefungsErgebnis],
) -> tuple[str, list[str]]:
    """Erzeugt eine strukturierte Empfehlung aus den Prüfergebnissen.

    Rückgabe: (Empfehlungstext, Liste der Auflagen).

    Logik:
      - 0 ❌-Befunde, 0 kritische Hinweise → Annahme ohne Auflagen
      - 1–5 ❌-Befunde, alle inhaltlich heilbar → Annahme mit Auflagen
      - ≥ 6 ❌-Befunde ODER struktureller Mangel
        (Bearbeitungszeit/AFB-Verteilung/Musterlösung fehlt) → Ablehnung
    """
    nicht_erfuellt = [e for e in ergebnisse if e.erfuellt is False]
    n = len(nicht_erfuellt)

    # Strukturelle Mängel = Kriterien, die ohne Neuformulierung der Klausur
    # nicht behebbar sind (Musterlösung fehlt, EWH fehlt, AFB-Verteilung
    # grob daneben).
    STRUKTURELL_NRS = {"2.4", "2.5", "2.6", "4.6"}
    # Schülersicherheits-Mängel = Klausur ist so nicht bearbeitbar; muss vor
    # Ausgabe an die Schüler behoben werden.
    SCHUELERSICHERHEIT_NRS = {"X.15", "X.16", "X.17", "X.18"}

    strukturell = [e for e in nicht_erfuellt if e.kriterium_nr in STRUKTURELL_NRS]
    schuelersicherheit = [
        e for e in nicht_erfuellt if e.kriterium_nr in SCHUELERSICHERHEIT_NRS
    ]

    auflagen = [
        f"[{e.kriterium_nr}] {e.kriterium_text} – {e.kommentar.split('.')[0]}."
        for e in nicht_erfuellt
    ]

    if n == 0:
        return ("Annahme ohne Auflagen.", [])
    if strukturell and n >= 6:
        return (
            "Ablehnung: Mehrere strukturelle Mängel "
            f"({', '.join(e.kriterium_nr for e in strukturell)}) "
            "erfordern eine Neufassung des Vorschlags.",
            auflagen,
        )
    if schuelersicherheit:
        nr_list = ", ".join(e.kriterium_nr for e in schuelersicherheit)
        return (
            f"Annahme NUR nach Behebung der Schülersicherheits-Mängel "
            f"({nr_list}): in der vorliegenden Form ist die Klausur für "
            f"eine Prüfungsbearbeitung nicht freigegeben.",
            auflagen,
        )
    return (
        f"Annahme mit Überarbeitungsauflagen ({n} Beanstandung(en)).",
        auflagen,
    )


# ---------------------------------------------------------------------------
# Rückmeldung-DOCX erstellen (aufgabenorientiert)
# ---------------------------------------------------------------------------

# Zuordnung: Kriterium-Nr → betrifft Schülermaterial (SM), Lehrermaterial (LM) oder beide
_KRITERIUM_MATERIAL = {
    "1.1": "SM", "1.2": "SM", "1.2a": "SM", "1.3": "SM",
    "2.1": "LM", "2.2": "LM", "2.3": "LM", "2.4": "LM",
    "2.5": "LM", "2.6": "LM", "2.7": "SM", "2.8": "SM",
    "3.1": "SM", "3.2": "SM", "3.3": "SM", "3.4": "SM", "3.5": "SM",
    "4.1": "SM", "4.2": "SM", "4.3": "SM", "4.4": "SM",
    "4.5": "SM", "4.6": "LM", "4.7": "SM",
    "X.1": "SM", "X.2": "LM", "X.3": "SM", "X.4": "BEIDE",
    "X.5": "LM", "X.6": "SM", "X.7": "SM", "X.8": "LM",
    "X.9": "SM", "X.10": "LM", "X.11": "SM", "X.12": "SM", "X.13": "BEIDE",
    "X.15": "BEIDE", "X.16": "SM", "X.17": "SM", "X.18": "SM",
}

# Zuordnung: Kriterium-Nr → kann einer spezifischen Aufgabe zugeordnet werden?
# "AUFGABE" = pro Aufgabe prüfbar (nur wenn im Kommentar spezifische Aufgaben stehen),
# "ALLGEMEIN" = betrifft den gesamten Vorschlag
_KRITERIUM_EBENE = {
    "1.1": "ALLGEMEIN", "1.2": "ALLGEMEIN", "1.2a": "ALLGEMEIN", "1.3": "ALLGEMEIN",
    "2.1": "ALLGEMEIN", "2.2": "ALLGEMEIN", "2.3": "ALLGEMEIN", "2.4": "ALLGEMEIN",
    "2.5": "ALLGEMEIN", "2.6": "ALLGEMEIN", "2.7": "ALLGEMEIN", "2.8": "ALLGEMEIN",
    "3.1": "ALLGEMEIN", "3.2": "ALLGEMEIN", "3.3": "ALLGEMEIN",
    "3.4": "ALLGEMEIN", "3.5": "ALLGEMEIN",
    "4.1": "ALLGEMEIN", "4.2": "AUFGABE", "4.3": "ALLGEMEIN", "4.4": "ALLGEMEIN",
    "4.5": "ALLGEMEIN", "4.6": "ALLGEMEIN", "4.7": "AUFGABE",
    "X.1": "ALLGEMEIN", "X.2": "ALLGEMEIN", "X.3": "ALLGEMEIN",
    "X.4": "ALLGEMEIN", "X.5": "ALLGEMEIN", "X.6": "ALLGEMEIN",
    "X.7": "ALLGEMEIN", "X.8": "ALLGEMEIN",
    "X.9": "ALLGEMEIN", "X.10": "ALLGEMEIN", "X.11": "AUFGABE",
    "X.12": "ALLGEMEIN", "X.13": "ALLGEMEIN",
    "X.15": "ALLGEMEIN", "X.16": "AUFGABE", "X.17": "ALLGEMEIN", "X.18": "AUFGABE",
}

_KRITERIUM_HINWEIS = {
    "1.2":  "Bitte Dokumentenvorlage des MK verwenden.",
    "1.2a": "Bearbeitungszeit eintragen.",
    "2.2":  "Lerngebiete zuordnen und Unterrichtsbezug beschreiben.",
    "2.4":  "Erwartungshorizont mit AFB-Zuordnung erstellen.",
    "2.5":  "Komplette Lösung/Musterlösung beifügen.",
    "2.6":  "Bewertungsschema mit KMK-Umrechnung beifügen.",
    "2.7":  "Erlaubte Hilfsmittel angeben.",
    "3.1":  "Kompetenzen gemäß RRL (bgtechnik2016.pdf, Abschnitt 1.3) prüfen.",
    "3.2":  "Aufgaben müssen aus Lerngebieten IT1–IT5 der RRL stammen.",
    "3.3":  "Ganzheitliche, problembezogene Aufgabenstellung sicherstellen.",
    "3.4":  "Orientierung an beruflicher Handlungskompetenz prüfen.",
    "3.5":  "Verschiedene Kompetenzen (Fach-, Methoden-, Selbstkompetenz) abdecken.",
    "4.1":  "Aufgaben klar formulieren, Lösungsweg darf nicht vorgezeichnet sein.",
    "4.2":  "Sicherstellen, dass Teilaufgaben unabhängig lösbar sind (ggf. Alternativwerte angeben).",
    "4.3":  f"Anforderungen müssen in {ABITUR_BEARBEITUNGSZEIT_MIN} Min bearbeitbar sein.",
    "4.4":  "Aufgaben als Arbeitsauftrag mit EPA-Operatoren formulieren.",
    "4.5":  "Nur EPA-Operatoren verwenden oder erweiterte dokumentieren.",
    "4.6":  "AFB-Verteilung anpassen (ca. 30%/40%/30%).",
    "4.7":  "Punkte (BE) bei jeder Aufgabe und Teilaufgabe angeben.",
    "X.1":  "Erste Aufgabe/Teilaufgabe nicht mit AFB III beginnen.",
    "X.2":  "Erweiterte Operatoren im Lehrermaterial dokumentieren (mit AFB-Zuordnung).",
    "X.3":  "'Punkte' durch 'BE' (Bewertungseinheiten) ersetzen.",
    "X.4":  "Operatoren in Schülermaterial und EWH abgleichen.",
    "X.5":  "AFB-Zuordnungen im EWH mit Operatorentabelle abgleichen.",
    "X.6":  "Schwerpunkt 'Informationstechnik' im Kopfbereich ergänzen.",
    "X.7":  "Verhältnis BE / Bearbeitungszeit prüfen und ggf. anpassen.",
    "X.8":  "Erwartungshorizont operatorenbezogen formulieren.",
    "X.9":  "Nicht-EPA-Operatoren entweder ersetzen oder als erweiterte Operatoren dokumentieren.",
    "X.10": "BE-Verteilung pro Operator/Teilaufgabe transparent darstellen.",
    "X.11": "Textwiederholungen korrigieren.",
    "X.12": "Digitales Material als Datei beifügen.",
    "X.13": "Gesamtpunktzahl in Aufgaben und EWH angleichen.",
    "X.15": "Alle Platzhalter (XXX, 20__, '(unvollständig)') vor Einreichung füllen.",
    "X.16": "Fehlende Anlagen/Schaltbilder/Datenblätter ergänzen – Schüler benötigen sie.",
    "X.17": "Referenzierte externe Dateien (Logo.pdf, .java, .css, …) dem Klausurordner beilegen.",
    "X.18": "Nummerierungslücken/Doppelnummerierungen der Teilaufgaben korrigieren.",
}


def _seite_fuer_aufgabe(aufgabe_nr: str, seiten_map: dict[str, int]) -> str:
    """Gibt 'S. X' zurück, falls die Aufgabe in der Seitenmap steht, sonst ''."""
    if aufgabe_nr in seiten_map:
        return f"S. {seiten_map[aufgabe_nr]}"
    return ""


def _ordne_ergebnis_aufgaben_zu(
    ergebnis: PruefungsErgebnis,
    aufgaben: list[Aufgabe],
) -> list[str]:
    """Ordnet ein PruefungsErgebnis konkreten (Teil-)Aufgabennummern zu.
    Gibt eine Liste von Aufgabennummern zurück (z.B. ['1.1', '2.3']).
    Falls nicht zuordenbar, wird ['Allgemein'] zurückgegeben."""
    ebene = _KRITERIUM_EBENE.get(ergebnis.kriterium_nr, "ALLGEMEIN")
    if ebene == "ALLGEMEIN":
        return ["Allgemein"]

    # Versuche spezifische Aufgaben/Teilaufgaben aus dem Kommentar zu extrahieren
    kommentar = ergebnis.kommentar
    zugeordnete = []

    # Suche nach "Aufgabe X" oder "Teilaufgabe X.Y" im Kommentar
    for m in re.finditer(r"(?:Teil)?[Aa]ufgabe\s+(\d+(?:\.\d+)?)", kommentar):
        zugeordnete.append(m.group(1))

    # Suche nach Muster "X.Y:" (Teilaufgabennummer)
    for m in re.finditer(r"\b(\d+\.\d+)\s*:", kommentar):
        nr = m.group(1)
        if nr not in zugeordnete:
            zugeordnete.append(nr)

    if zugeordnete:
        return zugeordnete

    # Keine spezifische Aufgabe erkannt → als "Allgemein" behandeln
    return ["Allgemein"]


def erstelle_aufgabenbezogene_befunde(
    aufgaben: list[Aufgabe],
    sm_pages: list[str],
    lm_pages: list[str],
    sm_seiten: dict[str, int],
    lm_seiten: dict[str, int],
) -> list[dict]:
    """Erstellt aufgabenbezogene Befunde durch seitenweise Analyse.

    Prüft für jede (Teil-)Aufgabe auf der zugehörigen Seite:
    - Verwendung von 'Punkte' statt 'BE'
    - Nicht-EPA-Operatoren als Arbeitsauftrag
    - Operatoren in SM vs. LM (Abgleich)
    - Textwiederholungen

    Gibt eine Liste von Dicts zurück, die direkt als Tabellenzeilen dienen.
    """
    befunde = []

    # Aufgabennummern sammeln (Hauptaufgabe + Teilaufgaben)
    aufgaben_nummern = []
    for a in aufgaben:
        aufgaben_nummern.append((str(a.nummer), a))
        for t in a.teilaufgaben:
            aufgaben_nummern.append((t.nummer, a))

    # Seitentext-Cache: Aufgabennummer → SM-Seitentext
    def sm_text_fuer(aufg_nr):
        seite = sm_seiten.get(aufg_nr)
        if seite and 0 < seite <= len(sm_pages):
            return sm_pages[seite - 1]
        return ""

    def lm_text_fuer(aufg_nr):
        seite = lm_seiten.get(aufg_nr)
        if seite and 0 < seite <= len(lm_pages):
            return lm_pages[seite - 1]
        return ""

    # --- Prüfung 1: "Punkte" statt "BE" pro Aufgabe ---
    for aufg_nr, aufg in aufgaben_nummern:
        sm_text = sm_text_fuer(aufg_nr)
        if not sm_text:
            continue
        treffer = re.findall(r"\b\d+\s+Punkte\b", sm_text, re.IGNORECASE)
        hat_be = bool(re.search(r"\b\d+\s+BE\b", sm_text, re.IGNORECASE))
        if treffer and not hat_be:
            befunde.append({
                "aufgabe": aufg_nr,
                "kriterium": "[X.3] 'Punkte' statt 'BE'",
                "kommentar": f"{len(treffer)}x \u201ePunkte\u201c auf dieser Seite. "
                             f"Korrekt: \u201eBE\u201c (Bewertungseinheiten).",
                "sm_seite": f"S. {sm_seiten[aufg_nr]}",
                "lm_seite": "",
                "hinweis": _KRITERIUM_HINWEIS.get("X.3", ""),
                "status": "fehler",
            })

    # --- Prüfung 2: Nicht-EPA-Operatoren pro Aufgabe ---
    for aufg_nr, aufg in aufgaben_nummern:
        sm_text = sm_text_fuer(aufg_nr)
        if not sm_text:
            continue
        for op in sorted(NICHT_EPA_OPERATOREN):
            pattern = re.compile(
                r"\b" + re.escape(op) + r"\w*\s+Sie\b", re.IGNORECASE
            )
            if pattern.search(sm_text):
                befunde.append({
                    "aufgabe": aufg_nr,
                    "kriterium": f"[X.9] Nicht-EPA-Operator '{op.capitalize()}'",
                    "kommentar": f"'{op.capitalize()} Sie ...' ist kein EPA-Operator. "
                                 f"Als erweiterten Operator dokumentieren oder ersetzen.",
                    "sm_seite": f"S. {sm_seiten[aufg_nr]}",
                    "lm_seite": "",
                    "hinweis": _KRITERIUM_HINWEIS.get("X.9", ""),
                    "status": "fehler",
                })

    # --- Prüfung 3: Operatoren SM vs. EWH pro Aufgabe ---
    for aufg_nr, aufg in aufgaben_nummern:
        sm_text = sm_text_fuer(aufg_nr)
        lm_text = lm_text_fuer(aufg_nr)
        if not sm_text:
            continue
        # Operatoren auf dieser SM-Seite
        sm_ops = find_operatoren_in_aufgabenstellung(sm_text)
        sm_op_set = set(o["operator"] for o in sm_ops)
        if not sm_op_set:
            continue
        # Operatoren auf der zugehörigen LM-Seite (+ benachbarte Seiten)
        lm_op_set = set()
        lm_seite_nr = lm_seiten.get(aufg_nr)
        if lm_seite_nr:
            # Prüfe auch benachbarte LM-Seiten (EWH kann umfangreicher sein)
            for offset in range(0, 4):
                idx = lm_seite_nr - 1 + offset
                if 0 <= idx < len(lm_pages):
                    ops_page = find_operatoren_in_text(lm_pages[idx])
                    lm_op_set.update(o["operator"] for o in ops_page)
        # Operatoren die im SM, aber nicht im LM vorkommen
        nur_sm = sm_op_set - lm_op_set
        if nur_sm:
            befunde.append({
                "aufgabe": aufg_nr,
                "kriterium": "[X.4] Operatoren SM ↔ EWH",
                "kommentar": f"Operator(en) im SM, aber nicht im EWH: "
                             f"{', '.join(sorted(o.capitalize() for o in nur_sm))}",
                "sm_seite": f"S. {sm_seiten.get(aufg_nr, '?')}",
                "lm_seite": f"S. {lm_seiten.get(aufg_nr, '?')}" if lm_seite_nr else "",
                "hinweis": _KRITERIUM_HINWEIS.get("X.4", ""),
                "status": "fehler",
            })

    # --- Prüfung 4: Textwiederholungen pro Aufgabe ---
    for aufg_nr, aufg in aufgaben_nummern:
        sm_text = sm_text_fuer(aufg_nr)
        if not sm_text:
            continue
        wiederholungen = re.findall(r"\b(\w{3,})\s+\1\b", sm_text, re.IGNORECASE)
        ungewollt = [w for w in wiederholungen
                     if w.lower() not in {"das", "die", "der", "und", "oder", "ist"}]
        if ungewollt:
            beispiele = [f"'{w} {w}'" for w in ungewollt[:3]]
            befunde.append({
                "aufgabe": aufg_nr,
                "kriterium": "[X.11] Textwiederholung",
                "kommentar": f"Mögliche Wiederholungen: {', '.join(beispiele)}",
                "sm_seite": f"S. {sm_seiten[aufg_nr]}",
                "lm_seite": "",
                "hinweis": _KRITERIUM_HINWEIS.get("X.11", ""),
                "status": "fehler",
            })

    # --- Prüfung 5: Fehlende Punkteangabe pro Teilaufgabe ---
    for a in aufgaben:
        if a.gesamtpunkte is None:
            befunde.append({
                "aufgabe": str(a.nummer),
                "kriterium": "[4.7] Fehlende Gesamtpunktzahl",
                "kommentar": f"Aufgabe {a.nummer}: keine Gesamtpunktzahl gefunden.",
                "sm_seite": _seite_fuer_aufgabe(str(a.nummer), sm_seiten),
                "lm_seite": "",
                "hinweis": _KRITERIUM_HINWEIS.get("4.7", ""),
                "status": "fehler",
            })
        for t in a.teilaufgaben:
            if t.punkte is None:
                befunde.append({
                    "aufgabe": t.nummer,
                    "kriterium": "[4.7] Fehlende Punkteangabe",
                    "kommentar": f"Teilaufgabe {t.nummer}: keine Punkte gefunden.",
                    "sm_seite": _seite_fuer_aufgabe(t.nummer, sm_seiten),
                    "lm_seite": "",
                    "hinweis": _KRITERIUM_HINWEIS.get("4.7", ""),
                    "status": "fehler",
                })

    # Seitenbezogene Deduplizierung: gleiches Kriterium + gleiche Seite
    # → nur einmal melden, erste Teilaufgabe als Referenz
    seen_seite = set()
    unique_befunde = []
    for b in befunde:
        key = (b["kriterium"], b["sm_seite"], b["lm_seite"])
        if key not in seen_seite:
            seen_seite.add(key)
            unique_befunde.append(b)

    return unique_befunde


def erstelle_rueckmeldung_xlsx(
    ergebnisse: list[PruefungsErgebnis],
    aufgaben: list[Aufgabe],
    sm_seiten: dict[str, int],
    lm_seiten: dict[str, int],
    output_pfad: str,
    schueler_datei: str,
    lehrer_datei: str,
    sm_pages: list[str] | None = None,
    lm_pages: list[str] | None = None,
):
    """Erstellt eine aufgabenorientierte Rückmeldung als XLSX-Tabellenkalkulation.

    Spalten: Aufgabe | Prüfkriterium | Ergebnis | Kommentar |
             Schülermaterial | Lehrermaterial | Hinweise | Rückmeldung

    Enthält alle Prüfergebnisse (erfüllt, beanstandet, manuell prüfen)
    mit Autofilter zum Filtern und Sortieren.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Rückmeldung"

    # --- Kopfbereich ---
    ws["A1"] = "Rückmeldung zur Begutachtung"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Schülermaterial: {os.path.basename(schueler_datei)}"
    ws["A3"] = f"Lehrermaterial: {os.path.basename(lehrer_datei)}"

    # --- Aufgabenbezogene Befunde erstellen ---
    aufg_befunde = []
    if sm_pages or lm_pages:
        aufg_befunde = erstelle_aufgabenbezogene_befunde(
            aufgaben, sm_pages or [], lm_pages or [],
            sm_seiten, lm_seiten,
        )

    # Kriterien die aufgabenbezogen detailliert werden
    aufg_detaillierte_kriterien = set()
    for b in aufg_befunde:
        m = re.match(r"\[([^\]]+)\]", b["kriterium"])
        if m:
            aufg_detaillierte_kriterien.add(m.group(1))

    # --- Alle Ergebnisse als Zeilen aufbauen ---
    zeilen_daten = []

    for e in ergebnisse:
        # Aufgabenbezogen detaillierte überspringen (kommen als aufg_befunde)
        if e.kriterium_nr in aufg_detaillierte_kriterien and e.erfuellt is not True:
            continue

        aufg_nummern = _ordne_ergebnis_aufgaben_zu(e, aufgaben)
        material = _KRITERIUM_MATERIAL.get(e.kriterium_nr, "SM")
        hinweis = _KRITERIUM_HINWEIS.get(e.kriterium_nr, "")

        if e.erfuellt is True:
            status = "✅ Erfüllt"
        elif e.erfuellt is False:
            status = "❌ Beanstandet"
        else:
            status = "⚠️ Manuell prüfen"

        for aufg_nr in aufg_nummern:
            sm_seite = ""
            lm_seite = ""
            if material in ("SM", "BEIDE"):
                sm_seite = _seite_fuer_aufgabe(aufg_nr, sm_seiten)
            if material in ("LM", "BEIDE"):
                lm_seite = _seite_fuer_aufgabe(aufg_nr, lm_seiten)

            zeilen_daten.append({
                "aufgabe": aufg_nr,
                "kriterium_nr": e.kriterium_nr,
                "kriterium": f"[{e.kriterium_nr}] {e.kriterium_text}",
                "status": status,
                "kommentar": e.kommentar,
                "sm_seite": sm_seite,
                "lm_seite": lm_seite,
                "hinweis": hinweis,
            })

    # Aufgabenbezogene Befunde hinzufügen
    for b in aufg_befunde:
        zeilen_daten.append({
            "aufgabe": b["aufgabe"],
            "kriterium_nr": "",
            "kriterium": b["kriterium"],
            "status": "❌ Beanstandet",
            "kommentar": b["kommentar"],
            "sm_seite": b["sm_seite"],
            "lm_seite": b["lm_seite"],
            "hinweis": b["hinweis"],
        })

    # Sortieren: Allgemein zuerst, dann nach Aufgabennummer
    def sort_key(z):
        aufg = z["aufgabe"]
        if aufg == "Allgemein":
            return (0, 0, 0)
        parts = aufg.split(".")
        return (1, int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)

    zeilen_daten.sort(key=sort_key)

    # Duplikate entfernen
    seen = set()
    unique_zeilen = []
    for z in zeilen_daten:
        key = (z["aufgabe"], z["kriterium"])
        if key not in seen:
            seen.add(key)
            unique_zeilen.append(z)
    zeilen_daten = unique_zeilen

    # --- Tabellenkopf (Zeile 5) ---
    header_row = 5
    headers = ["Aufgabe", "Prüfkriterium", "Ergebnis", "Kommentar",
               "Schülermaterial", "Lehrermaterial", "Hinweise", "Rückmeldung"]
    col_widths = [10, 40, 16, 55, 16, 16, 40, 30]

    header_font = Font(bold=True, size=10)
    header_fill = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    # Spaltenbreiten
    for col_idx, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    # --- Farbpaletten für Status ---
    fill_ok = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    fill_fehler = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    fill_warnung = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
    wrap_align = Alignment(vertical="top", wrap_text=True)
    center_align = Alignment(horizontal="center", vertical="top", wrap_text=True)

    # --- Datenzeilen ---
    for row_offset, zeile in enumerate(zeilen_daten):
        row_num = header_row + 1 + row_offset

        ws.cell(row=row_num, column=1, value=zeile["aufgabe"]).alignment = center_align
        ws.cell(row=row_num, column=2, value=zeile["kriterium"]).alignment = wrap_align
        status_cell = ws.cell(row=row_num, column=3, value=zeile["status"])
        status_cell.alignment = center_align
        ws.cell(row=row_num, column=4, value=zeile["kommentar"]).alignment = wrap_align
        ws.cell(row=row_num, column=5, value=zeile["sm_seite"]).alignment = center_align
        ws.cell(row=row_num, column=6, value=zeile["lm_seite"]).alignment = center_align
        ws.cell(row=row_num, column=7, value=zeile["hinweis"]).alignment = wrap_align
        ws.cell(row=row_num, column=8, value="").alignment = wrap_align

        # Farbkennzeichnung
        if "Erfüllt" in zeile["status"]:
            status_cell.fill = fill_ok
        elif "Beanstandet" in zeile["status"]:
            status_cell.fill = fill_fehler
        elif "prüfen" in zeile["status"]:
            status_cell.fill = fill_warnung

        # Rahmen
        for col_idx in range(1, 9):
            ws.cell(row=row_num, column=col_idx).border = thin_border

    # --- Autofilter ---
    last_row = header_row + len(zeilen_daten)
    ws.auto_filter.ref = f"A{header_row}:H{last_row}"

    # --- Zeilen fixieren (Kopfzeile sichtbar beim Scrollen) ---
    ws.freeze_panes = f"A{header_row + 1}"

    # --- Zusammenfassung ---
    summary_row = last_row + 2
    nicht_erfuellt = sum(1 for e in ergebnisse if e.erfuellt is False)
    manuell = sum(1 for e in ergebnisse if e.erfuellt is None)
    erfuellt_cnt = sum(1 for e in ergebnisse if e.erfuellt is True)
    ws.cell(row=summary_row, column=1,
            value=f"Zusammenfassung: {nicht_erfuellt} Beanstandungen, "
                  f"{manuell} manuell zu prüfen, {erfuellt_cnt} erfüllt, "
                  f"{len(ergebnisse)} Kriterien gesamt.").font = Font(bold=True, size=10)

    # Die Rückmeldung an die Schule steht in der Hinweisliste
    # (src/bewertung/hinweisliste.py), nicht mehr als zweites Blatt hier.
    wb.save(output_pfad)
    print(f"Rückmeldung gespeichert: {output_pfad}")


# ---------------------------------------------------------------------------
# Formulierungen für die Hinweisliste an die Schule
# ---------------------------------------------------------------------------
# Rückfall-Formulierungen für src/bewertung/hinweisliste.py, wenn dort keine
# kürzere Formulierung im Stil der versendeten Hinweise hinterlegt ist.

# Höfliche Standard-Formulierungen pro Kriterium.  ``{kommentar}`` wird
# durch den konkreten Vorabcheck-Kommentar ersetzt; ``{seite_sm}`` und
# ``{seite_lm}`` durch die jeweilige Fundstelle (falls vorhanden).
_RUECKMELDUNG_TEMPLATES: dict[str, str] = {
    "1.1":  "Aus dem Layout der Datei ergeben sich Auffälligkeiten ({kommentar}). "
            "Möglicherweise kann der Gesamteindruck der Klausur durch eine "
            "Überarbeitung verbessert werden – die Bewertung liegt bei Ihnen.",
    "1.2":  "Bitte prüfen, ob die aktuelle Dokumentenvorlage des MK verwendet wurde.",
    "1.2a": "Bitte prüfen, ob die Bearbeitungszeit auf dem Deckblatt eingetragen ist.",
    "1.3":  "Bitte prüfen, ob das Deckblatt nach amtlichem Muster vollständig ist "
            "(Abitur [Jahr], Technik, Informationstechnik, Vorschlag, eA/gA, "
            "Bearbeitungszeit).",
    "2.1":  "Es wird nur ein Vorschlag automatisch geprüft. Bitte prüfen, ob "
            "der zweite Vorschlag vorliegt und die beiden Vorschläge gemeinsam "
            "aus mindestens drei Lerngebieten stammen.",
    "2.2":  "Bitte prüfen, ob die Lerngebietszuordnung der Aufgaben so wie "
            "dargestellt aus Ihrer Sicht zutreffend ist ({kommentar}).",
    "2.8":  "Bitte prüfen, ob – soweit für die Aufgabenstellung erforderlich – "
            "eine Formelsammlung beiliegt.",
    "3.1":  "Bitte prüfen, ob die übergeordneten Kompetenzen des Fachs Technik "
            "gemäß Rahmenrichtlinien (bgtechnik2016, Abschnitt 1.3) durch die "
            "Aufgaben angesprochen werden.",
    "2.3":  "Zur Beschreibung des Unterrichtszusammenhangs: Bitte prüfen, ob "
            "neben dem Halbjahresthema auch die konkreten Unterrichtsinhalte "
            "und Aufgabentypen genannt werden, anhand derer die Prüflinge auf "
            "diese Klausur vorbereitet wurden (EPA 3.3).",
    "2.4":  "Im Lehrermaterial wurde kein eindeutiger Erwartungshorizont mit "
            "AFB-Zuordnung erkannt. Bitte prüfen, ob die Tabelle ggf. an "
            "anderer Stelle zu finden ist oder ergänzt werden sollte.",
    "2.5":  "Bitte prüfen, ob im Lehrermaterial eine vollständige Musterlösung "
            "vorhanden ist.",
    "2.6":  "Bitte prüfen, ob das Bewertungsschema mit KMK-Umrechnung im "
            "Lehrermaterial enthalten ist.",
    "2.7":  "Bitte prüfen, ob die erlaubten Hilfsmittel im Schülermaterial "
            "ausdrücklich angegeben sind.",
    "3.2":  "Bitte prüfen, ob die Zuordnung zu den Lerngebieten der "
            "Rahmenrichtlinien aus Ihrer Sicht so passt ({kommentar}).",
    "3.3":  "Aus unserer Sicht wäre es wünschenswert, dass die Aufgaben in "
            "einen zusammenhängenden Praxisbezug eingebettet sind. "
            "Bitte prüfen, ob dies bereits in ausreichendem Maße der Fall ist.",
    "3.4":  "Bitte prüfen, ob die berufliche Handlungsorientierung in den "
            "Aufgaben aus Ihrer Sicht ausreichend deutlich wird.",
    "3.5":  "Bitte prüfen, ob alle drei Anforderungsbereiche und die "
            "geforderten Kompetenzbereiche durch die Aufgaben angesprochen "
            "werden.",
    "4.1":  "An einzelnen Stellen erscheint die Aufgabenstellung möglicherweise "
            "mehrdeutig ({kommentar}). Bitte prüfen, ob eine Präzisierung "
            "sinnvoll wäre.",
    "4.2":  "Bitte prüfen, ob die Vorgabe 4.2 (Jede Teilaufgabe kann, "
            "unabhängig von Fehlleistungen in anderen Aufgaben, gelöst werden) "
            "erfüllt ist. Andernfalls könnte ein Alternativwert angegeben werden.",
    "4.3":  "Die Bearbeitungszeit weicht möglicherweise vom Sollwert für das "
            "eA (300 Min.) ab ({kommentar}). Bitte prüfen, ob dies aus Ihrer "
            "Sicht angemessen ist.",
    "4.4":  "Bitte prüfen, ob die Aufgaben durchgängig als Arbeitsauftrag mit "
            "EPA-Operatoren formuliert sind.",
    "4.5":  "Bitte prüfen, ob die verwendeten Operatoren den EPA entsprechen "
            "oder als erweiterte Operatoren im Lehrermaterial dokumentiert sind "
            "({kommentar}).",
    "4.6":  "Die AFB-Verteilung liegt möglicherweise außerhalb des Richtwertes "
            "(ca. 30 % / 40 % / 30 %, Toleranz ±10 %) – {kommentar}. Bitte "
            "prüfen, ob eine Anpassung aus Ihrer Sicht sinnvoll ist.",
    "4.7": "Bitte prüfen, ob die zu erreichenden Bewertungseinheiten bei "
            "jeder (Teil-)Aufgabe angegeben sind.",
    "X.1":  "Die erste Teilaufgabe scheint dem Anforderungsbereich III "
            "zuzufallen. Möglicherweise ist ein Einstieg über AFB I oder II "
            "für die Prüflinge zugänglicher – die Entscheidung liegt bei Ihnen.",
    "X.2":  "Bitte prüfen, ob die im Material verwendeten erweiterten "
            "Operatoren im Lehrermaterial mit AFB-Zuordnung dokumentiert "
            "sind ({kommentar}).",
    "X.3":  ('Im Schülermaterial wird die Bezeichnung „Punkte" verwendet. '
             'Bitte prüfen, ob hier durchgängig „BE" (Bewertungseinheiten) '
             'stehen sollte – so wäre die Anschlussfähigkeit an den '
             'Erwartungshorizont gegeben.'),
    "X.4":  "Möglicherweise stimmen die Operatoren in Aufgabenstellung und "
            "Erwartungshorizont nicht durchgängig überein ({kommentar}). "
            "Bitte prüfen, ob sich SM und EWH an dieser Stelle angleichen "
            "lassen.",
    "X.5":  "Bitte prüfen, ob die AFB-Zuordnungen im Erwartungshorizont an "
            "den gemeldeten Stellen ({kommentar}) mit der Operatorentabelle "
            "übereinstimmen. Ein Operator kann höchstens zwei Anforderungs"
            "bereiche abdecken.",
    "X.5b": "Bitte prüfen, ob die AFB-Zuordnung der einzelnen EWH-Zeilen mit "
            "der Operatorentabelle und mit der eigenen erweiterten "
            "Operatorenliste übereinstimmt ({kommentar}).",
    "X.6":  ('Bitte prüfen, ob der Schwerpunkt „Informationstechnik" im '
             'Kopfbereich des Materials angegeben ist.'),
    "X.7":  "Das Verhältnis BE / Bearbeitungszeit weicht möglicherweise vom "
            "Richtwert (ca. 2,5–3,0 Min. je BE) ab ({kommentar}). Bitte "
            "prüfen, ob eine Anpassung von Punktezahl oder Bearbeitungszeit "
            "in Erwägung gezogen werden sollte.",
    "X.8":  "Bitte prüfen, ob der Erwartungshorizont durchgängig "
            "operatorenbezogen formuliert ist.",
    "X.9":  "Im Schülermaterial sind Formulierungen enthalten, die nicht "
            "der EPA-Operatorenliste entstammen ({kommentar}). Möglicher"
            "weise lassen sich diese durch EPA-Operatoren ersetzen oder als "
            "erweiterte Operatoren dokumentieren.",
    "X.10": "Bitte prüfen, ob die BE-Verteilung pro Teilaufgabe für die "
            "Prüflinge transparent erkennbar ist.",
    "X.11": "An einzelnen Stellen wurden Textwiederholungen erkannt "
            "({kommentar}). Zur Information.",
    "X.12": "Im Schülermaterial wird auf digitales Begleitmaterial verwiesen "
            "({kommentar}). Bitte prüfen, ob ein entsprechender Datenträger "
            "vorgesehen ist.",
    "X.13": "Die Gesamtpunktzahl im Schülermaterial weicht von der Summe im "
            "Erwartungshorizont ab ({kommentar}). Bitte prüfen, ob hier eine "
            "Angleichung beabsichtigt ist.",
    "X.14": "Möglicherweise verbinden die Aufgaben Inhalte aus weniger als "
            "zwei Lerngebieten ({kommentar}). Bitte prüfen, ob aus Ihrer "
            "Sicht eine breitere Lerngebiet-Abdeckung sinnvoll wäre.",
    "X.15": "Im Material wurden Stellen erkannt, die wie unausgefüllte "
            "Platzhalter aussehen ({kommentar}). Bitte prüfen, ob diese vor "
            "Ausgabe an die Prüflinge durch konkrete Werte ersetzt werden "
            "sollen – ggf. handelt es sich um beabsichtigte Marker.",
    "X.16": "An einigen Stellen wird auf eine Anlage / ein Schaltbild / "
            "ein Datenblatt verwiesen, das im PDF nicht eingebettet zu sein "
            "scheint ({kommentar}). Bitte prüfen, ob die Abbildungen den "
            "Prüflingen separat zur Verfügung stehen.",
    "X.17": "Im Schülermaterial werden Dateien referenziert, die nicht im "
            "selben Ordner liegen ({kommentar}). Bitte prüfen, ob diese "
            "Dateien den Prüflingen separat (z. B. auf Datenträger) zur "
            "Verfügung gestellt werden.",
    "X.18": "Bei der Nummerierung der Teilaufgaben wurden Auffälligkeiten "
            "festgestellt ({kommentar}). Möglicherweise handelt es sich um "
            "einen Tippfehler – bitte prüfen.",
}


def _formuliere_hoeflich(erg: PruefungsErgebnis) -> str:
    """Wandelt einen automatischen Befund in eine zurückhaltende
    Rückmeldungsformulierung um. Fällt auf eine generische Form zurück, wenn
    kein spezifisches Template vorliegt."""
    template = _RUECKMELDUNG_TEMPLATES.get(erg.kriterium_nr)
    # Imperativ-Marker und intern wirkende Floskeln aus dem Kommentar entfernen
    kommentar = erg.kommentar
    for marker in (
        "ABWEICHUNG:", "MANUELL PRÜFEN:", "Vorabcheck:", "Bitte manuell prüfen.",
        "Bitte manuell prüfen,", "Bitte manuell prüfen", ">>>",
    ):
        kommentar = kommentar.replace(marker, "")
    kommentar = kommentar.strip(" -–.")
    # Den ersten Satz / die erste Zeile übernehmen, max. 220 Zeichen, damit die
    # Spalte „Anmerkung" lesbar bleibt.
    kommentar_kurz = kommentar.split("\n")[0].strip()
    if len(kommentar_kurz) > 220:
        kommentar_kurz = kommentar_kurz[:220].rstrip(" ,;") + " …"

    if template is None:
        return (
            f'Bitte prüfen, ob das Kriterium [{erg.kriterium_nr}] '
            f'„{erg.kriterium_text}" aus Ihrer Sicht ausreichend erfüllt '
            f'ist. Hinweis aus der Vorprüfung: {kommentar_kurz}.'
        )
    try:
        return template.format(kommentar=kommentar_kurz)
    except (KeyError, IndexError):
        return template.replace("{kommentar}", kommentar_kurz)


# ---------------------------------------------------------------------------
# Konsolenausgabe
# ---------------------------------------------------------------------------

def drucke_ergebnis(ergebnisse: list[PruefungsErgebnis], analyse_text: str):
    """Druckt die Ergebnisse auf die Konsole."""
    print("\n" + "=" * 80)
    print("ERGEBNIS DER BEGUTACHTUNG")
    print("=" * 80)

    erfuellt = [e for e in ergebnisse if e.erfuellt is True]
    nicht_erfuellt = [e for e in ergebnisse if e.erfuellt is False]
    manuell = [e for e in ergebnisse if e.erfuellt is None]

    if nicht_erfuellt:
        print(f"\n❌ BEANSTANDUNGEN ({len(nicht_erfuellt)}):")
        print("-" * 40)
        for e in nicht_erfuellt:
            print(f"  [{e.kriterium_nr}] {e.kriterium_text}")
            print(f"         → {e.kommentar}")

    if manuell:
        print(f"\n⚠️  MANUELL ZU PRÜFEN ({len(manuell)}):")
        print("-" * 40)
        for e in manuell:
            print(f"  [{e.kriterium_nr}] {e.kriterium_text}")
            print(f"         → {e.kommentar}")

    print(f"\n✅ ERFÜLLT ({len(erfuellt)}):")
    print("-" * 40)
    for e in erfuellt:
        print(f"  [{e.kriterium_nr}] {e.kriterium_text}")
        print(f"         → {e.kommentar}")

    print("\n" + "-" * 80)
    print(analyse_text)
    print("-" * 80)

    print(f"\nZUSAMMENFASSUNG:")
    print(f"  ✅ Erfüllt:        {len(erfuellt)}")
    print(f"  ❌ Beanstandet:    {len(nicht_erfuellt)}")
    print(f"  ⚠️  Manuell prüfen: {len(manuell)}")
    gesamt = len(ergebnisse)
    print(f"  Gesamt:            {gesamt}")


# ---------------------------------------------------------------------------
# Verzeichnis-Scanner: Abiturvorschläge automatisch erkennen
# ---------------------------------------------------------------------------

# Muster, die auf Lehrermaterial hindeuten (case-insensitive)
_LM_PATTERNS = [
    re.compile(r"_L\b", re.IGNORECASE),                     # …AufgA_L.pdf/.docx
    re.compile(r"Lehrer", re.IGNORECASE),                     # …Lehrer_A.pdf/.docx
    re.compile(r"_EWH\b", re.IGNORECASE),                     # …_I_EWH.pdf/.docx
    re.compile(r"\dL\.(pdf|docx)$", re.IGNORECASE),          # …A1L.pdf / A1L.docx
]


def _ist_lehrermaterial(name: str) -> bool:
    """Erkennt anhand des Dateinamens, ob es sich um Lehrermaterial handelt."""
    return any(p.search(name) for p in _LM_PATTERNS)


def _vorschlags_kennung(name: str) -> str:
    """Extrahiert eine Kennung zum Paaren von SM/LM.

    Entfernt LM-spezifische Suffixe, sodass SM- und LM-Dateien
    die gleiche Kennung bekommen.

    Beispiele:
        2021TechnikMechaBGEAAufgA.pdf     → 2021TechnikMechaBGEAAufgA
        2021TechnikMechaBGEAAufgA_L.pdf   → 2021TechnikMechaBGEAAufgA
        2024_TechnikMecha_eA_I.pdf        → 2024_TechnikMecha_eA_I
        2024_TechnikMecha_eA_I_EWH.pdf    → 2024_TechnikMecha_eA_I
        2023MechatronikEAAufg1.pdf        → 2023MechatronikEAAufg1
        2023MechatronikEAA1L.pdf          → 2023MechatronikEAAufg1
        2022TechnikMechaBGEAAufg_A.pdf    → 2022TechnikMechaBGEAAufg_A
        2022TechnikMechaBGEALehrer_A.pdf  → 2022TechnikMechaBGEAAufg_A
    """
    stem = Path(name).stem

    # _EWH entfernen (2024+)
    stem = re.sub(r"_EWH$", "", stem, flags=re.IGNORECASE)

    # _L am Ende entfernen (2021)
    stem = re.sub(r"_L$", "", stem, flags=re.IGNORECASE)

    # Lehrer_ → Aufg_ (2022: Lehrer_A → Aufg_A)
    # Negative lookahead: „lehrermaterial" als Kompositum NICHT transformieren
    stem = re.sub(r"Lehrer_", "Aufg_", stem, flags=re.IGNORECASE)
    stem = re.sub(r"Lehrer(?!material)", "Aufg", stem, flags=re.IGNORECASE)

    # A1L → Aufg1 (2023: 2023MechatronikEAA1L → 2023MechatronikEAAufg1)
    stem = re.sub(r"A(\d+)L$", r"Aufg\1", stem, flags=re.IGNORECASE)

    # Muster-Vorschläge: _schuelermaterial... / _lehrermaterial... am Ende entfernen
    # (z.B. mustervorschlag_..._schuelermaterial_270min / ..._lehrermaterial)
    stem = re.sub(r"_(?:schuelermaterial|lehrermaterial).*$", "", stem, flags=re.IGNORECASE)

    return stem


def finde_vorschlaege(verzeichnis: str) -> list[dict]:
    """Durchsucht ein Verzeichnis rekursiv nach Abiturvorschlägen.

    Gibt eine Liste von Dicts zurück:
        [{"sm": <Pfad SM>, "lm": <Pfad LM>, "name": <Kennung>}, ...]
    """
    verzeichnis = os.path.abspath(verzeichnis)
    if not os.path.isdir(verzeichnis):
        print(f"FEHLER: Verzeichnis nicht gefunden: {verzeichnis}")
        return []

    # Alle PDFs und DOCX-Dateien sammeln
    alle_dateien = []
    for root, _dirs, files in os.walk(verzeichnis):
        for f in files:
            if f.lower().endswith((".pdf", ".docx")):
                alle_dateien.append(os.path.join(root, f))

    # Nach SM und LM klassifizieren
    sm_dateien = {}  # Kennung → Pfad
    lm_dateien = {}  # Kennung → Pfad

    for pfad in sorted(alle_dateien):
        name = os.path.basename(pfad)
        kennung = _vorschlags_kennung(name)

        if _ist_lehrermaterial(name):
            lm_dateien[kennung] = pfad
        else:
            sm_dateien[kennung] = pfad

    # Paare bilden
    vorschlaege = []
    for kennung, sm_pfad in sorted(sm_dateien.items()):
        lm_pfad = lm_dateien.get(kennung)
        if lm_pfad:
            vorschlaege.append({
                "sm": sm_pfad,
                "lm": lm_pfad,
                "name": kennung,
            })
        else:
            print(f"WARNUNG: Kein Lehrermaterial gefunden für: {sm_pfad}")
            print(f"  Kennung: {kennung}")

    # Ungepaarte LM melden
    gepaarte_lm = {v["lm"] for v in vorschlaege}
    for kennung, lm_pfad in sorted(lm_dateien.items()):
        if lm_pfad not in gepaarte_lm:
            print(f"WARNUNG: Kein Schülermaterial gefunden für: {lm_pfad}")
            print(f"  Kennung: {kennung}")

    return vorschlaege


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Automatische Begutachtung von Abiturklausur-Vorschlägen "
                    "(BG Technik - Informationstechnik)")
    parser.add_argument("schuelermaterial", nargs="?", default=None,
        help="Pfad zum Schülermaterial (PDF oder DOCX)")
    parser.add_argument("lehrermaterial", nargs="?", default=None,
        help="Pfad zum Lehrermaterial (PDF oder DOCX)")
    parser.add_argument("--verzeichnis", default=None,
        help="Verzeichnis mit Abiturvorschlägen. Wird rekursiv durchsucht "
             "und alle gefundenen SM/LM-Paare werden begutachtet.")
    parser.add_argument("--vorlage", default=None,
        help="Pfad zur Gutachten-Vorlage (DOCX). "
             "Standard: Material/bg-abi_te_gutachten 2026.docx")
    parser.add_argument("--output", default=None,
        help="Pfad für das erzeugte Gutachten (DOCX). "
             "Standard: Auswertungen/Gutachten_<Schülermaterial-Name>.docx")
    parser.add_argument("--rueckmeldung", default=None,
        help="Pfad für das erzeugte Rückmeldungs-XLSX. "
             "Standard: Auswertungen/Rueckmeldung_<Schülermaterial-Name>.xlsx")
    parser.add_argument("--nur-konsole", action="store_true",
        help="Nur Konsolenausgabe, kein DOCX erzeugen")

    args = parser.parse_args()

    # Gutachten-Vorlage
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if args.vorlage:
        vorlage_pfad = os.path.abspath(args.vorlage)
    else:
        kandidaten = [
            os.path.join(script_dir, "Material", "bg-abi_te_gutachten 2026.docx"),
            os.path.join(script_dir, "..", "..", "data", "material",
                         "bg-abi_te_gutachten 2026.docx"),
        ]
        vorlage_pfad = os.path.abspath(next(
            (k for k in kandidaten if os.path.isfile(k)), kandidaten[0]))

    # Ausgabe-Verzeichnis
    output_dir = os.path.join(script_dir, "Auswertungen")

    # -----------------------------------------------------------------------
    # Batch-Modus: --verzeichnis
    # -----------------------------------------------------------------------
    if args.verzeichnis:
        verzeichnis = os.path.abspath(args.verzeichnis)
        vorschlaege = finde_vorschlaege(verzeichnis)
        if not vorschlaege:
            print("Keine Vorschläge gefunden.")
            sys.exit(1)

        print(f"\n{'='*72}")
        print(f"Batch-Modus: {len(vorschlaege)} Vorschlag/Vorschläge gefunden")
        print(f"Ausgabe-Verzeichnis: {output_dir}")
        print(f"{'='*72}")
        for i, v in enumerate(vorschlaege, 1):
            print(f"  {i}. {v['name']}")
            print(f"     SM: {v['sm']}")
            print(f"     LM: {v['lm']}")
        print()

        bloecke = []
        for i, v in enumerate(vorschlaege, 1):
            print(f"\n{'='*72}")
            print(f"[{i}/{len(vorschlaege)}] {v['name']}")
            print(f"{'='*72}")

            block = _begutachte_einzeln(
                schueler_pfad=v["sm"],
                lehrer_pfad=v["lm"],
                vorlage_pfad=vorlage_pfad,
                output_dir=output_dir,
                output_pfad=None,
                rueckmeldung_pfad=None,
                nur_konsole=args.nur_konsole,
            )
            if block is not None:
                bloecke.append(block)

        # Sammelliste: alle Vorschläge des Verzeichnisses (z. B. A und B
        # einer Schule) in einer Datei – wie die versendeten Hinweise.
        if bloecke and not args.nur_konsole:
            from src.bewertung.hinweisliste import schreibe_hinweisliste
            name = Path(verzeichnis).name or "Verzeichnis"
            xlsx, csv_pfad = schreibe_hinweisliste(
                bloecke, os.path.join(output_dir, f"Hinweise_{name}"))
            print(f"Sammel-Hinweisliste: {xlsx}")
            print(f"                     {csv_pfad}")

        print(f"\n{'='*72}")
        print(f"Batch-Lauf abgeschlossen: {len(vorschlaege)} Vorschlag/Vorschläge verarbeitet.")
        print(f"Ausgaben in: {output_dir}")
        print(f"{'='*72}")
        return

    # -----------------------------------------------------------------------
    # Einzel-Modus: Schüler- und Lehrermaterial als Argumente
    # -----------------------------------------------------------------------
    if not args.schuelermaterial or not args.lehrermaterial:
        parser.error("Im Einzelmodus sind schuelermaterial und lehrermaterial erforderlich. "
                     "Alternativ: --verzeichnis für Batch-Modus nutzen.")

    schueler_pfad = os.path.abspath(args.schuelermaterial)
    lehrer_pfad = os.path.abspath(args.lehrermaterial)

    if not os.path.isfile(schueler_pfad):
        print(f"FEHLER: Schülermaterial nicht gefunden: {schueler_pfad}")
        sys.exit(1)
    if not os.path.isfile(lehrer_pfad):
        print(f"FEHLER: Lehrermaterial nicht gefunden: {lehrer_pfad}")
        sys.exit(1)

    _begutachte_einzeln(
        schueler_pfad=schueler_pfad,
        lehrer_pfad=lehrer_pfad,
        vorlage_pfad=vorlage_pfad,
        output_dir=output_dir,
        output_pfad=os.path.abspath(args.output) if args.output else None,
        rueckmeldung_pfad=os.path.abspath(args.rueckmeldung) if args.rueckmeldung else None,
        nur_konsole=args.nur_konsole,
    )


def _begutachte_einzeln(
    schueler_pfad: str,
    lehrer_pfad: str,
    vorlage_pfad: str,
    output_dir: str,
    output_pfad: str | None,
    rueckmeldung_pfad: str | None,
    nur_konsole: bool,
):
    """Führt die Begutachtung für ein einzelnes SM/LM-Paar durch.

    Gibt den HinweisBlock (für die Sammelliste im Batch-Modus) zurück.
    """
    from src.bewertung.hinweisliste import (
        hinweisblock_fuer_vorschlag, schreibe_hinweisliste,
    )
    basis = Path(schueler_pfad).stem

    if not output_pfad:
        output_pfad = os.path.join(output_dir, f"Gutachten_{basis}.docx")
    if not rueckmeldung_pfad:
        rueckmeldung_pfad = os.path.join(output_dir, f"Rueckmeldung_{basis}.xlsx")

    # Begutachtung durchführen
    regel = begutachte(schueler_pfad, lehrer_pfad)
    ergebnisse, analyse, aufgaben, sm_seiten, lm_seiten, sm_pages, lm_pages = regel
    block = hinweisblock_fuer_vorschlag(schueler_pfad, lehrer_pfad, regel=regel)

    # Konsolenausgabe
    drucke_ergebnis(ergebnisse, analyse)

    # Dateien erzeugen
    if not nur_konsole:
        os.makedirs(output_dir, exist_ok=True)

        if not os.path.isfile(vorlage_pfad):
            print(f"\nWARNUNG: Gutachten-Vorlage nicht gefunden: {vorlage_pfad}")
            print("  → Kein Gutachten-DOCX wird erzeugt. Nutzen Sie --vorlage um den Pfad anzugeben.")
        else:
            erstelle_gutachten_docx(
                ergebnisse, analyse, vorlage_pfad, output_pfad,
                schueler_pfad, lehrer_pfad
            )

        # Rückmeldung als XLSX erzeugen
        erstelle_rueckmeldung_xlsx(
            ergebnisse, aufgaben, sm_seiten, lm_seiten,
            output_pfad=rueckmeldung_pfad,
            schueler_datei=schueler_pfad,
            lehrer_datei=lehrer_pfad,
            sm_pages=sm_pages,
            lm_pages=lm_pages,
        )

        # Hinweise an die Schule: eigene Liste (XLSX + CSV), nicht im Gutachten
        xlsx, csv_pfad = schreibe_hinweisliste(
            [block], os.path.join(os.path.dirname(rueckmeldung_pfad), f"Hinweise_{basis}"))
        print(f"Hinweisliste gespeichert: {xlsx}")
        print(f"                          {csv_pfad}")

    return block


if __name__ == "__main__":
    main()
