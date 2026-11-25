#!/usr/bin/env python3
"""
Automatische Bewertung von Schüler-Abiturklausuren (BG Technik – Informationstechnik).

Pipeline:
  1. Bewertungsschema aus XLSX-Vorlage (Lehrer) lesen.
  2. Erwartungshorizont aus Lehrermaterial-PDF pro Teilaufgabe extrahieren.
  3. Schüler-PDF via Vision-LLM (LM Studio) OCR + Strukturierung.
     Fallback: Tesseract-OCR. Fallback²: bereits extrahierter Text (--text).
  4. Pro Teilaufgabe: KI vergleicht Antwort gegen Erwartungshorizont
     und vergibt Punkte je Anforderungsbereich (AFB I/II/III).
  5. Kopie der XLSX-Vorlage je Schüler befüllen.
  6. Markdown- + JSON-Detailbericht erzeugen.

Voraussetzungen:
  - LM Studio läuft lokal auf http://localhost:1234 mit geladenem Modell.
    Für handschriftliche PDFs: Vision-Modell empfohlen (z.B. Qwen2.5-VL,
    MiniCPM-V, Pixtral). Für reine Text-/Bewertungs-Phase reicht ein
    Text-Modell ≥ 12 B Parameter.
  - poppler-utils (pdftoppm) für PDF→PNG-Konvertierung.
  - Optional: tesseract als OCR-Fallback.

Verwendung:
  python klausur_schueler_bewerten.py SCHUELER.pdf
  python klausur_schueler_bewerten.py SCHUELER.pdf --vorlage Material/BGI3_*.xlsx
  python klausur_schueler_bewerten.py --text SCHUELER.txt --name "Max Mustermann"
  python klausur_schueler_bewerten.py --verzeichnis Klausuren/Schueler/
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from openai import OpenAI

# --- Pfade & Standardwerte --------------------------------------------------

PROJEKT_WURZEL = Path(__file__).resolve().parent.parent.parent
_MATERIAL_DIR_KANDIDATEN = [
    PROJEKT_WURZEL / "data" / "material",
    PROJEKT_WURZEL / "data" / "Material",
]
MATERIAL_DIR = next((p for p in _MATERIAL_DIR_KANDIDATEN if p.exists()), _MATERIAL_DIR_KANDIDATEN[0])
STANDARD_VORLAGE = MATERIAL_DIR / "BGI3_Abiturbewertung_2025 Vorschlag A.xlsx"
STANDARD_LEHRER_PDF = MATERIAL_DIR / "mustervorschlag_niedersachsen_bg_technik_informationstechnik_lehrermaterial.pdf"
STANDARD_SCHUELER_PDF = MATERIAL_DIR / "mustervorschlag_niedersachsen_bg_technik_informationstechnik_schuelermaterial_270min.pdf"
AUSGABE_WURZEL = PROJEKT_WURZEL / "data" / "Auswertungen" / "Schueler"

# --- LM Studio Provider ----------------------------------------------------

LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
LMSTUDIO_API_KEY = os.environ.get("LMSTUDIO_API_KEY", "lm-studio")
LMSTUDIO_TIMEOUT = int(os.environ.get("LMSTUDIO_TIMEOUT", "1800"))

# Wenn als optionaler Vision-Modell-Name gesetzt: für Schüler-OCR verwenden,
# sonst wird das aktuell geladene Modell genommen (muss dann vision-fähig sein).
VISION_MODELL = os.environ.get("LMSTUDIO_VISION_MODELL", "")

KONFIDENZ_SCHWELLE = 60       # unter dieser Konfidenz → manuelle Nachprüfung markieren
SEITEN_DPI = 200              # DPI für PDF→PNG-Konvertierung (Vision-OCR)
SEITEN_MAX_BREITE_PX = 1600   # Bild-Längskante für Vision-Aufruf cappen


# --- Standardsätze (aus „Bewertung (Standard Sätze)" der Vorlage) ----------
# Bewertungsbogen-Sätze in absteigender Reihenfolge der erreichten Prozent.
# (Quelle: Sheet "Bewertung (Standard Sätze)" der Vorlage.)
STANDARDSAETZE: list[tuple[float, str]] = [
    (1.00, "o.K."),
    (0.75, "Die Lösung entspricht weitestgehend den Erwartungen."),
    (0.667, "Die Lösung entspricht weitgehend den Erwartungen."),
    (0.50, "Die Lösung entspricht zum Teil den Erwartungen."),
    (0.333, "Die Lösung entspricht nur zum geringen Teil den Erwartungen."),
    (0.25, "Die Lösung entspricht kaum den Erwartungen."),
    (0.0, "Die Lösung entspricht nicht den Erwartungen."),
]

# Sonderfälle (werden vom KI-Modell direkt angefordert)
SATZ_FALSCH = "Die vorgelegte Lösung ist falsch und entspricht somit nicht den Erwartungen."
SATZ_LEER = "Es liegt keine Lösung vor."


def waehle_standardsatz(prozent: float) -> str:
    """Wählt den passenden Bewertungs-Standardsatz für einen Prozent-Anteil."""
    for schwelle, satz in STANDARDSAETZE:
        if prozent >= schwelle - 1e-9:
            return satz
    return STANDARDSAETZE[-1][1]


# --- Notenschlüssel (aus „Notenschlüssel" der Vorlage) ---------------------
# (Prozent-Untergrenze, Punktewert, Notentext, qualitatives Adjektiv)
NOTENSCHLUESSEL: list[tuple[float, int, str, str]] = [
    (95, 15, "1+", "voll sehr gut"),
    (90, 14, "1",  "sehr gut"),
    (85, 13, "1-", "knapp sehr gut"),
    (80, 12, "2+", "voll gut"),
    (75, 11, "2",  "gut"),
    (70, 10, "2-", "knapp gut"),
    (65,  9, "3+", "voll befriedigend"),
    (60,  8, "3",  "befriedigend"),
    (55,  7, "3-", "knapp befriedigend"),
    (50,  6, "4+", "voll ausreichend"),
    (45,  5, "4",  "ausreichend"),
    (40,  4, "4-", "knapp ausreichend"),
    (33,  3, "5+", "voll mangelhaft"),
    (27,  2, "5",  "mangelhaft"),
    (20,  1, "5-", "knapp mangelhaft"),
    (0,   0, "6",  "ungenügend"),
]


def punkte_und_note(prozent: float) -> tuple[int, str, str]:
    """Liefert (Notenpunkte 0–15, Notenkennung, Notentext) zu einem Prozentwert."""
    for schwelle, punkte, kennung, text in NOTENSCHLUESSEL:
        if prozent >= schwelle:
            return punkte, kennung, text
    return 0, "6", "ungenügend"


# ---------------------------------------------------------------------------
# Datenstrukturen
# ---------------------------------------------------------------------------

@dataclass
class Teilaufgabe:
    """Eine bewertbare Teilaufgabe aus dem Bewertungsschema."""
    nummer: str                # z.B. "1.1", "2.1.7.2"
    aufgabe: int               # 1, 2, 3
    max_punkte_i: float = 0.0
    max_punkte_ii: float = 0.0
    max_punkte_iii: float = 0.0
    zeile_in_vorlage: int = 0  # Zeilennummer im Schüler-Bewertungsbogen
    erwartungstext: str = ""   # aus Lehrermaterial (Erwartungshorizont)

    @property
    def max_punkte_gesamt(self) -> float:
        return self.max_punkte_i + self.max_punkte_ii + self.max_punkte_iii


@dataclass
class BewertungsErgebnis:
    """KI-Bewertung einer einzelnen Teilaufgabe."""
    teilaufgabe: str
    erreicht_i: float = 0.0
    erreicht_ii: float = 0.0
    erreicht_iii: float = 0.0
    standardsatz: str = ""
    bemerkung: str = ""
    konfidenz: int = 0
    schueler_antwort: str = ""   # extrahierter Antworttext (für Nachvollzug)
    flags: list[str] = field(default_factory=list)  # z.B. "konfidenz_niedrig"

    @property
    def erreicht_gesamt(self) -> float:
        return self.erreicht_i + self.erreicht_ii + self.erreicht_iii


@dataclass
class SchuelerBewertung:
    """Komplette Bewertung einer Schülerarbeit."""
    schueler_name: str
    quelldatei: str
    ergebnisse: list[BewertungsErgebnis] = field(default_factory=list)
    sprachabzug: int = 0   # 0, 1, oder 2 Notenpunkte Abzug
    modell: str = ""
    ocr_methode: str = ""
    erzeugt_am: str = ""

    def summen_pro_aufgabe(self) -> dict[int, dict[str, float]]:
        """Aggregierte Punkte pro Aufgabe (1/2/3)."""
        out: dict[int, dict[str, float]] = {}
        for e in self.ergebnisse:
            aufgabe = int(e.teilaufgabe.split(".")[0])
            d = out.setdefault(aufgabe, {"i": 0.0, "ii": 0.0, "iii": 0.0, "gesamt": 0.0})
            d["i"] += e.erreicht_i
            d["ii"] += e.erreicht_ii
            d["iii"] += e.erreicht_iii
            d["gesamt"] += e.erreicht_gesamt
        return out

    def gesamtsummen(self) -> dict[str, float]:
        s = {"i": 0.0, "ii": 0.0, "iii": 0.0, "gesamt": 0.0}
        for d in self.summen_pro_aufgabe().values():
            for k in s:
                s[k] += d[k]
        return s


# ---------------------------------------------------------------------------
# 1. Bewertungsschema-Loader (XLSX → Liste[Teilaufgabe])
# ---------------------------------------------------------------------------

# Im "Muster Muster"-Sheet stehen die Teilaufgaben in Spalte B (Index 1),
# erreichbare Punkte AFB I/II/III in C/D/E (Indizes 2/3/4).
# Erreichte Punkte gehören in F/G/H (5/6/7), Bemerkung ab I (8).
SCHEMA_SHEET = "Muster Muster"
SCHUELER_DATEN_SHEET = "Daten"

# Spalten im Bewertungsbogen pro Sub-Task
COL_TEILAUFGABE = 2     # B
COL_MAX_I = 3           # C
COL_MAX_II = 4          # D
COL_MAX_III = 5         # E
COL_ERR_I = 6           # F
COL_ERR_II = 7          # G
COL_ERR_III = 8         # H
COL_BEMERKUNG = 9       # I


def lade_bewertungsschema(vorlage_pfad: Path) -> list[Teilaufgabe]:
    """Liest aus der XLSX-Vorlage die Liste aller Teilaufgaben mit AFB-Punkten.

    Erkennt Teilaufgaben anhand des Musters „<ziffer>.<ziffer>..." in Spalte B.
    Speichert die Zeilennummer für späteres Befüllen der Schüler-Kopie.
    """
    import openpyxl  # späte Import: nur wenn Bewertung läuft

    if not vorlage_pfad.exists():
        raise FileNotFoundError(f"Bewertungsvorlage nicht gefunden: {vorlage_pfad}")

    wb = openpyxl.load_workbook(vorlage_pfad, data_only=True)
    if SCHEMA_SHEET not in wb.sheetnames:
        raise ValueError(
            f"Sheet '{SCHEMA_SHEET}' nicht in Vorlage gefunden. "
            f"Vorhandene Sheets: {wb.sheetnames}"
        )

    ws = wb[SCHEMA_SHEET]
    pattern = re.compile(r"^\s*(\d)(?:\.\d+)+\s*$")  # 1.1, 2.1.7.2 etc.
    teilaufgaben: list[Teilaufgabe] = []
    for row_idx in range(1, ws.max_row + 1):
        cell_b = ws.cell(row=row_idx, column=COL_TEILAUFGABE).value
        if cell_b is None:
            continue
        s = str(cell_b).strip()
        m = pattern.match(s)
        if not m:
            continue
        aufgabe_nr = int(m.group(1))
        ta = Teilaufgabe(
            nummer=s,
            aufgabe=aufgabe_nr,
            max_punkte_i=_zahl(ws.cell(row=row_idx, column=COL_MAX_I).value),
            max_punkte_ii=_zahl(ws.cell(row=row_idx, column=COL_MAX_II).value),
            max_punkte_iii=_zahl(ws.cell(row=row_idx, column=COL_MAX_III).value),
            zeile_in_vorlage=row_idx,
        )
        if ta.max_punkte_gesamt > 0:
            teilaufgaben.append(ta)
    return teilaufgaben


def _zahl(v: Any) -> float:
    """Wandelt einen Zellen-Wert sicher in float; leere/None Werte → 0.0."""
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# 2. Erwartungshorizont-Loader (Lehrermaterial-PDF → {nummer: text})
# ---------------------------------------------------------------------------

def extract_text_pdf_einfach(pdf: Path) -> str:
    """Extrahiert Text aus einem PDF mit pypdf (für textbasierte PDFs)."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def lade_erwartungshorizont(lehrer_pdf: Path) -> dict[str, str]:
    """Extrahiert pro Teilaufgabe den Erwartungshorizont-Text.

    Heuristik:
      Nach dem Vorkommen von „Erwartungshorizont" werden Zeilen beginnend mit
      Teilaufgabennummern (z.B. „1.1") als Aufgabenanker erkannt; der bis zum
      nächsten Anker folgende Text wird zugeordnet. Funktioniert bei dem
      Niedersachsen-Lehrermaterial-Layout. Bei anderen Layouts gibt es ggf.
      Lücken – diese werden später als „kein Erwartungstext verfügbar"
      kenntlich gemacht.
    """
    if not lehrer_pdf.exists():
        print(f"  ⚠️  Lehrermaterial-PDF nicht gefunden: {lehrer_pdf}")
        return {}

    text = extract_text_pdf_einfach(lehrer_pdf)
    # Auf den Abschnitt „Erwartungshorizont" beschränken (falls vorhanden)
    eh_idx = text.find("Erwartungshorizont")
    if eh_idx >= 0:
        text = text[eh_idx:]
    # „Kommentar [N]:" sind PDF-Marginalien – wegschneiden
    text = re.sub(r"Kommentar \[\d+\]:.*", "", text, flags=re.DOTALL)

    # Layout A: Nummer steht isoliert auf eigener Zeile.
    nummer_zeilen = re.compile(r"^\s*(\d(?:\.\d+){1,3})\s*$", re.MULTILINE)
    matches = list(nummer_zeilen.finditer(text))
    if len(matches) >= 3:
        return _eintraege_aus_matches(text, matches)

    # Layout B: Nummer steht inline („1.1 Erläutern eines …  1.2 Erläutern …").
    # Links MUSS Whitespace stehen, rechts ein Großbuchstabe (typische
    # Anfangsverben "Erläutern", "Berechnen", …). So vermeiden wir
    # Falschtreffer auf inline-Punktwerte wie „2 1 1".
    nummer_inline = re.compile(
        r"(?:(?<=\s)|(?<=^))(\d(?:\.\d+){1,3})\s+(?=[A-ZÄÖÜ])",
        re.MULTILINE,
    )
    matches = list(nummer_inline.finditer(text))
    if matches:
        return _eintraege_aus_matches(text, matches)
    return {}


def _eintraege_aus_matches(text: str, matches: list[re.Match]) -> dict[str, str]:
    """Teilt den Text an Match-Positionen in pro-Nummer-Blöcke auf.

    Bei mehrfacher Erwähnung einer Nummer wird der längste Block
    behalten (Layout B hat oft Summenzeilen dazwischen).
    """
    eintraege: dict[str, str] = {}
    for i, m in enumerate(matches):
        nummer = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = re.sub(r"\s+", " ", text[start:end]).strip()
        # Nach „Summen N. Aufgabe …" abschneiden (Tabellen-Summenzeile)
        block = re.split(r"\bSummen\s+\d\.\s*Aufgabe\b", block, maxsplit=1)[0].strip()
        if not block:
            continue
        if len(block) > len(eintraege.get(nummer, "")):
            eintraege[nummer] = block
    return eintraege


# ---------------------------------------------------------------------------
# 3. Schüler-PDF-Reader (handschriftlich → strukturierter Text pro Teilaufgabe)
# ---------------------------------------------------------------------------

def pdf_zu_pngs(pdf: Path, ausgabe_dir: Path, dpi: int = SEITEN_DPI) -> list[Path]:
    """Konvertiert ein PDF in eine Liste von PNG-Bildern (pro Seite)."""
    ausgabe_dir.mkdir(parents=True, exist_ok=True)
    praefix = ausgabe_dir / "seite"
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(praefix)],
        check=True, capture_output=True,
    )
    return sorted(ausgabe_dir.glob("seite-*.png"))


def _bild_als_data_uri(png: Path) -> str:
    """Liest eine PNG-Datei und liefert sie als data:image/png;base64 URI."""
    daten = png.read_bytes()
    return "data:image/png;base64," + base64.b64encode(daten).decode("ascii")


VISION_OCR_PROMPT = """\
Lies die handschriftliche Schülerantwort auf diesem Bild und gib sie als \
strukturierten Text wieder. Beachte:

1. Erkenne Aufgaben-/Teilaufgabennummern (z.B. „1.1", „2.1.7.2", „Aufg. 3.4"). \
   Schreibe jede Teilaufgabe als eigenen Block, eingeleitet mit „### TA <Nummer>".
2. Gib die handschriftliche Lösung möglichst wortgetreu wieder. \
   Erhalte Code-Schnipsel, Formeln, Tabellen, IP-Adressen, Bitmuster.
3. Bei Skizzen, Schaltplänen oder Tabellen: beschreibe sie in einem \
   kurzen Absatz, eingeleitet mit „[SKIZZE]" oder „[TABELLE]".
4. Unklare Wörter markiere mit „[?]" – rate nicht.
5. KEIN zusätzlicher Kommentar, KEINE Bewertung – nur die Transkription.
"""


def ocr_seite_via_vision(client: OpenAI, modell: str, png: Path) -> str:
    """Sendet ein Seitenbild an ein Vision-LLM und gibt den transkribierten Text zurück."""
    bild_uri = _bild_als_data_uri(png)
    response = client.chat.completions.create(
        model=modell,
        messages=[
            {"role": "system", "content": "Du bist ein präziser Handschrift-OCR-Assistent."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_OCR_PROMPT},
                    {"type": "image_url", "image_url": {"url": bild_uri}},
                ],
            },
        ],
        temperature=0.0,
        max_tokens=4000,
        stream=False,
    )
    return (response.choices[0].message.content or "").strip()


def ocr_seite_via_tesseract(png: Path) -> str:
    """Fallback-OCR via tesseract (für gedruckte/saubere Scans, KEINE Handschrift)."""
    try:
        out = subprocess.run(
            ["tesseract", str(png), "-", "-l", "deu", "--psm", "6"],
            check=True, capture_output=True, text=True, timeout=120,
        )
        return out.stdout.strip()
    except Exception as e:
        print(f"    Tesseract-Fehler ({png.name}): {e}")
        return ""


def lese_schuelerarbeit_pdf(
    pdf: Path,
    modus: str = "vision",
    client: OpenAI | None = None,
    modell: str = "",
) -> str:
    """Konvertiert ein Schüler-PDF in strukturierten Text.

    modus:
      "vision"    – via Vision-LLM (LM Studio). Beste Qualität bei Handschrift.
      "tesseract" – via Tesseract OCR (nur sinnvoll bei Druck/Schreibmaschine).
    """
    if not pdf.exists():
        raise FileNotFoundError(f"Schüler-PDF nicht gefunden: {pdf}")

    with tempfile.TemporaryDirectory(prefix="schueler_ocr_") as tmpdir:
        tmp = Path(tmpdir)
        print(f"  → PDF nach PNGs konvertieren (DPI={SEITEN_DPI}) ...")
        pngs = pdf_zu_pngs(pdf, tmp)
        print(f"    {len(pngs)} Seite(n) erkannt.")

        seitentexte: list[str] = []
        for i, png in enumerate(pngs, 1):
            print(f"  → Seite {i}/{len(pngs)}: OCR ({modus}) ...", flush=True)
            if modus == "vision":
                if client is None or not modell:
                    raise ValueError("Vision-OCR benötigt client + modell")
                txt = ocr_seite_via_vision(client, modell, png)
            else:
                txt = ocr_seite_via_tesseract(png)
            seitentexte.append(f"\n--- SEITE {i} ---\n{txt}")
        return "\n".join(seitentexte)


def extrahiere_antworten_pro_teilaufgabe(
    rohtext: str,
    teilaufgaben: list[Teilaufgabe],
) -> dict[str, str]:
    """Teilt den Rohtext der Schülerarbeit in Blöcke pro Teilaufgabe auf.

    Erkennung:
      - „### TA 1.1"  (vom Vision-Prompt erzeugt)
      - „Aufg. 1.1", „Aufgabe 1.1", „1.1)", „zu 1.1"
      - Standalone „1.1" am Zeilenanfang
    """
    nummern = sorted({ta.nummer for ta in teilaufgaben}, key=lambda n: [int(p) for p in n.split(".")])
    # Pattern, das eine der bekannten Nummern matcht, optional eingeleitet
    nummern_re = "|".join(re.escape(n) for n in nummern)
    anker_pattern = re.compile(
        rf"(?:^|\n)(?:\s*(?:###\s*TA\s*|Aufg\.?\s*|Aufgabe\s*|zu\s*|Teilaufgabe\s*)?)({nummern_re})\b[):.]?",
        re.IGNORECASE,
    )
    treffer = list(anker_pattern.finditer(rohtext))
    bloecke: dict[str, list[str]] = {n: [] for n in nummern}
    for i, m in enumerate(treffer):
        nummer = m.group(1)
        start = m.end()
        end = treffer[i + 1].start() if i + 1 < len(treffer) else len(rohtext)
        block = rohtext[start:end].strip(" \t:)\n")
        if block:
            bloecke[nummer].append(block)
    return {n: "\n\n".join(parts).strip() for n, parts in bloecke.items()}


# ---------------------------------------------------------------------------
# 4. KI-Bewertungsengine
# ---------------------------------------------------------------------------

BEWERTUNGS_SYSTEM_PROMPT = """\
Du bist erfahrene/r Lehrkraft am Beruflichen Gymnasium Technik – Informationstechnik \
(Niedersachsen) und bewertest schriftliche Abiturklausuren.

DEINE AUFGABE:
Du erhältst für EINE Teilaufgabe:
  - den Erwartungshorizont (was die Schülerin/der Schüler liefern soll),
  - die maximal erreichbaren Punkte pro Anforderungsbereich (AFB I, II, III),
  - die tatsächliche Schülerantwort (aus OCR; ggf. fehlerbehaftet).

Bewerte die Antwort sachgerecht und vergib Punkte je AFB.

REGELN:
1. Vergib pro AFB NIE mehr Punkte als das Maximum. Halbpunkte (0,5) sind erlaubt.
2. Wenn ein AFB nicht vorhanden ist (max=0), vergib dort 0 Punkte.
3. „Es liegt keine Lösung vor" wenn die Antwort komplett fehlt oder nur \
   unleserlich/unverständlich ist → 0 Punkte, Standardsatz „SATZ_LEER".
4. Wenn die Antwort substantiell falsch ist (z.B. Werte komplett verkehrt) → \
   0 Punkte, Standardsatz „SATZ_FALSCH".
5. OCR-Fehler wohlwollend interpretieren – wenn ein Begriff offensichtlich \
   gemeint ist (z.B. „Pott1" statt „Poti1"), nicht abwerten.
6. Setze „konfidenz" nur >70, wenn der OCR-Text klar lesbar UND der \
   Erwartungshorizont eindeutig vergleichbar ist.

ANTWORTFORMAT (NUR JSON, kein Fließtext davor/danach):
{
  "punkte_i": <Zahl>,
  "punkte_ii": <Zahl>,
  "punkte_iii": <Zahl>,
  "prozent": <0.0–1.0>,            // erreicht / maximal (gesamt über alle AFB)
  "standardsatz": "<einer der Sätze siehe unten>",
  "bemerkung": "<kurze sachliche Begründung, 1–2 Sätze>",
  "konfidenz": <0–100>
}

ERLAUBTE STANDARDSAETZE (genau übernehmen):
  - "o.K."
  - "Die Lösung entspricht weitestgehend den Erwartungen."
  - "Die Lösung entspricht weitgehend den Erwartungen."
  - "Die Lösung entspricht zum Teil den Erwartungen."
  - "Die Lösung entspricht nur zum geringen Teil den Erwartungen."
  - "Die Lösung entspricht kaum den Erwartungen."
  - "Die Lösung entspricht nicht den Erwartungen."
  - "Die vorgelegte Lösung ist falsch und entspricht somit nicht den Erwartungen."
  - "Es liegt keine Lösung vor."
"""


def bewerte_teilaufgabe(
    client: OpenAI,
    modell: str,
    teilaufgabe: Teilaufgabe,
    schueler_antwort: str,
) -> BewertungsErgebnis:
    """Lässt die KI eine Teilaufgabe bewerten und gibt das strukturierte Ergebnis zurück."""
    if not schueler_antwort.strip():
        # Keine Antwort gefunden → direkt 0 Punkte, „keine Lösung"
        return BewertungsErgebnis(
            teilaufgabe=teilaufgabe.nummer,
            erreicht_i=0.0, erreicht_ii=0.0, erreicht_iii=0.0,
            standardsatz=SATZ_LEER,
            bemerkung="Im OCR-Text wurde keine Antwort zu dieser Teilaufgabe gefunden.",
            konfidenz=80,
            schueler_antwort="",
            flags=["keine_antwort"],
        )

    nutzer_prompt = (
        f"### TEILAUFGABE {teilaufgabe.nummer}\n\n"
        f"### ERWARTUNGSHORIZONT\n{teilaufgabe.erwartungstext or '(nicht verfügbar)'}\n\n"
        f"### MAXIMALE PUNKTE\n"
        f"AFB I = {teilaufgabe.max_punkte_i}\n"
        f"AFB II = {teilaufgabe.max_punkte_ii}\n"
        f"AFB III = {teilaufgabe.max_punkte_iii}\n"
        f"Summe = {teilaufgabe.max_punkte_gesamt}\n\n"
        f"### SCHÜLERANTWORT (aus OCR)\n{schueler_antwort.strip()}\n\n"
        f"### AUFGABE\n"
        f"Bewerte die Schülerantwort gegen den Erwartungshorizont und antworte "
        f"ausschließlich im vorgegebenen JSON-Format."
    )
    raw = _ki_anfrage(client, modell, BEWERTUNGS_SYSTEM_PROMPT, nutzer_prompt)
    daten = _parse_json_robust(raw)

    if not daten:
        # Fallback: KI-Antwort nicht parsbar → markieren, alles 0
        return BewertungsErgebnis(
            teilaufgabe=teilaufgabe.nummer,
            standardsatz=SATZ_LEER,
            bemerkung=f"KI-Antwort nicht auswertbar. Rohausgabe (gekürzt): {raw[:200]}",
            konfidenz=0,
            schueler_antwort=schueler_antwort,
            flags=["ki_parse_fehler"],
        )

    pi = _clamp(_zahl(daten.get("punkte_i")), 0, teilaufgabe.max_punkte_i)
    pii = _clamp(_zahl(daten.get("punkte_ii")), 0, teilaufgabe.max_punkte_ii)
    piii = _clamp(_zahl(daten.get("punkte_iii")), 0, teilaufgabe.max_punkte_iii)
    konfidenz = int(_zahl(daten.get("konfidenz")))

    standardsatz = (daten.get("standardsatz") or "").strip()
    if standardsatz not in {s for _, s in STANDARDSAETZE} | {SATZ_FALSCH, SATZ_LEER}:
        # KI hat freien Text geliefert → über Prozent ableiten
        prozent = (pi + pii + piii) / teilaufgabe.max_punkte_gesamt if teilaufgabe.max_punkte_gesamt else 0.0
        standardsatz = waehle_standardsatz(prozent)

    flags: list[str] = []
    if konfidenz < KONFIDENZ_SCHWELLE:
        flags.append("konfidenz_niedrig")

    return BewertungsErgebnis(
        teilaufgabe=teilaufgabe.nummer,
        erreicht_i=pi, erreicht_ii=pii, erreicht_iii=piii,
        standardsatz=standardsatz,
        bemerkung=(daten.get("bemerkung") or "").strip(),
        konfidenz=konfidenz,
        schueler_antwort=schueler_antwort,
        flags=flags,
    )


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _ki_anfrage(client: OpenAI, modell: str, system: str, nutzer: str) -> str:
    """Einfacher Stream-Aufruf mit Punkt-Fortschrittsanzeige."""
    stream = client.chat.completions.create(
        model=modell,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": nutzer},
        ],
        temperature=0.1,
        max_tokens=1500,
        stream=True,
    )
    out = []
    n = 0
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            out.append(chunk.choices[0].delta.content)
            n += 1
            if n % 25 == 0:
                print(".", end="", flush=True)
    if n >= 25:
        print(flush=True)
    return "".join(out).strip()


def _parse_json_robust(text: str) -> dict[str, Any]:
    """Extrahiert das erste JSON-Objekt aus einer Modellantwort."""
    if not text:
        return {}
    # <think>…</think> entfernen
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
    # Code-Fences entfernen
    text = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # ersten balanced {...}-Block suchen
    start = text.find("{")
    if start < 0:
        return {}
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


# ---------------------------------------------------------------------------
# 5. XLSX-Filler (Kopie der Vorlage pro Schüler)
# ---------------------------------------------------------------------------

def fuelle_xlsx(
    vorlage_pfad: Path,
    ausgabe_pfad: Path,
    bewertung: SchuelerBewertung,
    teilaufgaben: list[Teilaufgabe],
) -> None:
    """Erstellt eine Kopie der Vorlage und befüllt das Bewertungs-Sheet des Schülers.

    Strategie: Kopiert „Muster Muster"-Sheet → benennt um auf Schülername,
    trägt erreichte Punkte (Spalten F/G/H) und Bemerkung (I) je Teilaufgaben-
    Zeile ein. Vorhandene Formeln (Summen, %, Note) bleiben unangetastet.
    """
    import openpyxl
    from copy import copy

    shutil.copy(vorlage_pfad, ausgabe_pfad)
    wb = openpyxl.load_workbook(ausgabe_pfad)

    if SCHEMA_SHEET not in wb.sheetnames:
        raise ValueError(f"Sheet '{SCHEMA_SHEET}' nicht in Vorlage – abgebrochen.")

    # Bewertungs-Sheet duplizieren und umbenennen
    ziel_name = _safe_sheet_name(bewertung.schueler_name)
    if ziel_name in wb.sheetnames:
        ziel_name = f"{ziel_name}_neu"
    ziel = wb.copy_worksheet(wb[SCHEMA_SHEET])
    ziel.title = ziel_name

    erg_index: dict[str, BewertungsErgebnis] = {e.teilaufgabe: e for e in bewertung.ergebnisse}
    for ta in teilaufgaben:
        e = erg_index.get(ta.nummer)
        if not e:
            continue
        zeile = ta.zeile_in_vorlage
        if ta.max_punkte_i > 0:
            ziel.cell(row=zeile, column=COL_ERR_I).value = e.erreicht_i
        if ta.max_punkte_ii > 0:
            ziel.cell(row=zeile, column=COL_ERR_II).value = e.erreicht_ii
        if ta.max_punkte_iii > 0:
            ziel.cell(row=zeile, column=COL_ERR_III).value = e.erreicht_iii
        # Bemerkung: Standardsatz + (optional) KI-Bemerkung
        kommentar = e.standardsatz
        if e.bemerkung and e.standardsatz not in ("o.K.", SATZ_LEER):
            kommentar = f"{e.standardsatz} {e.bemerkung}"
        ziel.cell(row=zeile, column=COL_BEMERKUNG).value = kommentar

    # Sprachabzug eintragen (Zelle K85/K86 im Bewertungsblatt 4 laut Vorlage)
    # In „Muster Muster" steht der Abzugswert in Zeile 86, Spalte K (Index 11).
    try:
        ziel.cell(row=86, column=11).value = bewertung.sprachabzug
    except Exception:
        pass

    # Schülernamen in den 4 Bewertungsblättern eintragen (Zelle C6, C33, C53, C76)
    for zeile in (6, 33, 53, 76):
        try:
            ziel.cell(row=zeile, column=3).value = bewertung.schueler_name
        except Exception:
            pass

    wb.save(ausgabe_pfad)


def _safe_sheet_name(name: str) -> str:
    """Bereinigt einen Namen für die Verwendung als Excel-Sheet-Name (max 31 Zeichen)."""
    bereinigt = re.sub(r"[\\/?*\[\]:]", "", name).strip()
    return (bereinigt or "Schueler")[:31]


# ---------------------------------------------------------------------------
# 6. Detailbericht (Markdown + JSON)
# ---------------------------------------------------------------------------

def schreibe_detailbericht_markdown(
    bewertung: SchuelerBewertung,
    teilaufgaben: list[Teilaufgabe],
    ausgabe_pfad: Path,
) -> None:
    """Erzeugt einen Markdown-Bericht mit allen Teilaufgaben und Begründungen."""
    summen = bewertung.summen_pro_aufgabe()
    gesamt = bewertung.gesamtsummen()
    max_gesamt = sum(ta.max_punkte_gesamt for ta in teilaufgaben)
    prozent = (gesamt["gesamt"] / max_gesamt * 100) if max_gesamt else 0.0
    punkte, note_kennung, note_text = punkte_und_note(prozent)
    punkte_final = max(0, punkte - bewertung.sprachabzug)

    lines: list[str] = []
    lines.append(f"# Bewertung: {bewertung.schueler_name}\n")
    lines.append(f"_Erzeugt am {bewertung.erzeugt_am} mit Modell `{bewertung.modell}` "
                 f"(OCR-Methode: {bewertung.ocr_methode})_\n")
    lines.append(f"_Quelldatei: `{bewertung.quelldatei}`_\n\n")

    lines.append("## Endbewertung\n")
    lines.append(f"- Erreichte Punkte: **{gesamt['gesamt']:.1f} / {max_gesamt:.0f}** "
                 f"({prozent:.1f} %)")
    lines.append(f"- Notenpunkte (vor Sprachabzug): **{punkte}** – {note_kennung} ({note_text})")
    if bewertung.sprachabzug:
        lines.append(f"- Sprachabzug: **−{bewertung.sprachabzug} Notenpunkte**")
        lines.append(f"- **Endnote: {punkte_final} Notenpunkte**")
    lines.append("")

    lines.append("## Summen pro Aufgabe\n")
    lines.append("| Aufgabe | AFB I | AFB II | AFB III | Gesamt | Max |")
    lines.append("|--------|------|--------|---------|--------|-----|")
    for nr in sorted(summen.keys()):
        d = summen[nr]
        max_a = sum(ta.max_punkte_gesamt for ta in teilaufgaben if ta.aufgabe == nr)
        lines.append(f"| {nr} | {d['i']:.1f} | {d['ii']:.1f} | {d['iii']:.1f} | "
                     f"{d['gesamt']:.1f} | {max_a:.0f} |")
    lines.append(f"| **∑** | **{gesamt['i']:.1f}** | **{gesamt['ii']:.1f}** | "
                 f"**{gesamt['iii']:.1f}** | **{gesamt['gesamt']:.1f}** | **{max_gesamt:.0f}** |")
    lines.append("")

    lines.append("## Detail pro Teilaufgabe\n")
    erg_index = {e.teilaufgabe: e for e in bewertung.ergebnisse}
    for ta in teilaufgaben:
        e = erg_index.get(ta.nummer)
        lines.append(f"### Teilaufgabe {ta.nummer}\n")
        lines.append(
            f"- Max AFB I/II/III: {ta.max_punkte_i:.1f} / {ta.max_punkte_ii:.1f} / "
            f"{ta.max_punkte_iii:.1f} (Summe {ta.max_punkte_gesamt:.0f})"
        )
        if not e:
            lines.append("- _keine Bewertung erzeugt_\n")
            continue
        lines.append(
            f"- Erreicht AFB I/II/III: **{e.erreicht_i:.1f} / {e.erreicht_ii:.1f} / "
            f"{e.erreicht_iii:.1f}** (Summe **{e.erreicht_gesamt:.1f}**)"
        )
        lines.append(f"- Standardsatz: _{e.standardsatz}_")
        if e.bemerkung:
            lines.append(f"- Bemerkung: {e.bemerkung}")
        lines.append(f"- Konfidenz: {e.konfidenz}%"
                     + (f" · Flags: {', '.join(e.flags)}" if e.flags else ""))
        if ta.erwartungstext:
            kurz = ta.erwartungstext[:300].replace("\n", " ")
            lines.append(f"- Erwartungshorizont (Auszug): {kurz}{' …' if len(ta.erwartungstext) > 300 else ''}")
        if e.schueler_antwort:
            kurz = e.schueler_antwort[:400].replace("\n", " ")
            lines.append(f"- Schülerantwort (OCR-Auszug): {kurz}{' …' if len(e.schueler_antwort) > 400 else ''}")
        lines.append("")

    ausgabe_pfad.write_text("\n".join(lines), encoding="utf-8")


def schreibe_detailbericht_json(bewertung: SchuelerBewertung, ausgabe_pfad: Path) -> None:
    """Serialisiert die komplette Bewertung als JSON."""
    daten = asdict(bewertung)
    ausgabe_pfad.write_text(json.dumps(daten, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Hauptlauf: alles zusammensetzen
# ---------------------------------------------------------------------------

def _erkenne_modell(client: OpenAI) -> str:
    """Liest das aktuell in LM Studio geladene Modell."""
    try:
        models = client.models.list()
        if models.data:
            return models.data[0].id
    except Exception:
        pass
    return "auto"


def bewerte_schueler(
    schueler_pdf: Path | None,
    schueler_text: Path | None,
    name: str,
    vorlage: Path,
    lehrer_pdf: Path,
    ocr_modus: str,
    ausgabe_dir: Path,
    nur_teilaufgaben: list[str] | None = None,
) -> Path:
    """Hauptfunktion: führt alle Schritte aus und schreibt die Ausgaben.

    Liefert den Pfad der erzeugten XLSX-Bewertung zurück.
    """
    ausgabe_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n=== Bewertung für {name} ===")

    # Schritt 1: Schema laden
    print(f"  [1/6] Bewertungsschema aus {vorlage.name} laden ...")
    teilaufgaben = lade_bewertungsschema(vorlage)
    print(f"    → {len(teilaufgaben)} Teilaufgaben (max. "
          f"{sum(ta.max_punkte_gesamt for ta in teilaufgaben):.0f} Punkte)")

    # Schritt 2: Erwartungshorizont laden
    print(f"  [2/6] Erwartungshorizont aus {lehrer_pdf.name} laden ...")
    erwartungen = lade_erwartungshorizont(lehrer_pdf)
    for ta in teilaufgaben:
        ta.erwartungstext = erwartungen.get(ta.nummer, "")
    fehlend = [ta.nummer for ta in teilaufgaben if not ta.erwartungstext]
    if fehlend:
        print(f"    ⚠️  Erwartungshorizont fehlt für: {', '.join(fehlend)}")
    else:
        print(f"    → Erwartungstexte für alle Teilaufgaben gefunden.")

    # KI-Client + Modell
    client = OpenAI(base_url=LMSTUDIO_BASE_URL, api_key=LMSTUDIO_API_KEY,
                    timeout=float(LMSTUDIO_TIMEOUT), max_retries=0)
    modell = _erkenne_modell(client)
    if modell == "auto":
        raise RuntimeError(
            "LM Studio: kein Modell geladen. Bitte ein Modell in LM Studio laden."
        )
    vision_modell = VISION_MODELL or modell
    print(f"  KI-Modell (Bewertung): {modell}")

    # Schritt 3: Schülerarbeit lesen
    print(f"  [3/6] Schülerarbeit lesen ...")
    if schueler_text:
        rohtext = schueler_text.read_text(encoding="utf-8")
        ocr_methode = "vorgegebener-text"
    elif schueler_pdf:
        if ocr_modus == "vision":
            print(f"    Vision-Modell: {vision_modell}")
        rohtext = lese_schuelerarbeit_pdf(
            schueler_pdf, modus=ocr_modus, client=client, modell=vision_modell
        )
        ocr_methode = f"pdf+{ocr_modus}"
    else:
        raise ValueError("Weder Schüler-PDF noch Text-Quelle angegeben.")

    # OCR-Roh-Text persistent ablegen
    (ausgabe_dir / "ocr_text.txt").write_text(rohtext, encoding="utf-8")
    print(f"    OCR-Text: {len(rohtext)} Zeichen → ocr_text.txt")

    # Schritt 4: Antworten pro Teilaufgabe extrahieren
    print(f"  [4/6] Antworten pro Teilaufgabe extrahieren ...")
    antworten = extrahiere_antworten_pro_teilaufgabe(rohtext, teilaufgaben)
    abgedeckt = sum(1 for v in antworten.values() if v.strip())
    print(f"    → {abgedeckt}/{len(teilaufgaben)} Teilaufgaben enthalten Text")

    # Schritt 5: KI-Bewertung pro Teilaufgabe
    print(f"  [5/6] KI-Bewertung ({modell}) ...")
    ergebnisse: list[BewertungsErgebnis] = []
    for i, ta in enumerate(teilaufgaben, 1):
        if nur_teilaufgaben and ta.nummer not in nur_teilaufgaben:
            continue
        antwort = antworten.get(ta.nummer, "")
        print(f"    [{i}/{len(teilaufgaben)}] {ta.nummer} ...", end="", flush=True)
        try:
            e = bewerte_teilaufgabe(client, modell, ta, antwort)
        except Exception as exc:
            e = BewertungsErgebnis(
                teilaufgabe=ta.nummer,
                standardsatz=SATZ_LEER,
                bemerkung=f"KI-Aufruf fehlgeschlagen: {exc}",
                konfidenz=0,
                schueler_antwort=antwort,
                flags=["ki_fehler"],
            )
        bewertung_kurz = f"{e.erreicht_gesamt:.1f}/{ta.max_punkte_gesamt:.0f}"
        marker = "⚠️" if e.flags else "✓"
        print(f" {marker} {bewertung_kurz} ({e.standardsatz[:30]})")
        ergebnisse.append(e)
        time.sleep(0.5)

    bewertung = SchuelerBewertung(
        schueler_name=name,
        quelldatei=str(schueler_pdf or schueler_text or ""),
        ergebnisse=ergebnisse,
        modell=modell,
        ocr_methode=ocr_methode,
        erzeugt_am=time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    # Schritt 6: Ausgaben schreiben
    print(f"  [6/6] Ausgaben schreiben ...")
    xlsx_pfad = ausgabe_dir / f"{_dateiname_safe(name)}_bewertung.xlsx"
    md_pfad = ausgabe_dir / "detailbericht.md"
    json_pfad = ausgabe_dir / "detailbericht.json"
    fuelle_xlsx(vorlage, xlsx_pfad, bewertung, teilaufgaben)
    schreibe_detailbericht_markdown(bewertung, teilaufgaben, md_pfad)
    schreibe_detailbericht_json(bewertung, json_pfad)
    print(f"    → {xlsx_pfad.name}")
    print(f"    → {md_pfad.name}")
    print(f"    → {json_pfad.name}")

    # Kurzfazit
    gesamt = bewertung.gesamtsummen()
    max_gesamt = sum(ta.max_punkte_gesamt for ta in teilaufgaben)
    prozent = (gesamt["gesamt"] / max_gesamt * 100) if max_gesamt else 0.0
    punkte, kennung, text = punkte_und_note(prozent)
    print(f"\n  Ergebnis: {gesamt['gesamt']:.1f}/{max_gesamt:.0f} = {prozent:.1f} % "
          f"→ {punkte} NP ({kennung}, {text})")
    return xlsx_pfad


def _dateiname_safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", name).strip("_") or "schueler"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Automatische Bewertung einer Schüler-Abiturklausur "
                    "(Niedersachsen, BG Technik – Informationstechnik).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("eingabe", nargs="?", type=Path,
                   help="PDF mit der (gescannten) Schülerarbeit.")
    p.add_argument("--text", type=Path,
                   help="Alternativ: bereits extrahierter Text der Schülerarbeit.")
    p.add_argument("--verzeichnis", type=Path,
                   help="Verzeichnis mit mehreren Schüler-PDFs (Batch-Modus).")
    p.add_argument("--name", default="",
                   help="Schülername (sonst aus Dateiname abgeleitet).")
    p.add_argument("--vorlage", type=Path, default=STANDARD_VORLAGE,
                   help=f"XLSX-Bewertungsvorlage (Standard: {STANDARD_VORLAGE.name})")
    p.add_argument("--lehrer-pdf", type=Path, default=STANDARD_LEHRER_PDF,
                   help="Lehrermaterial-PDF (Erwartungshorizont).")
    p.add_argument("--ausgabe", type=Path, default=AUSGABE_WURZEL,
                   help=f"Ausgabe-Wurzelverzeichnis (Standard: {AUSGABE_WURZEL}).")
    p.add_argument("--ocr", choices=["vision", "tesseract"], default="vision",
                   help="OCR-Methode (Standard: vision, benötigt Vision-Modell in LM Studio).")
    p.add_argument("--teilaufgabe", action="append", default=[],
                   help="Nur diese Teilaufgaben bewerten (mehrfach möglich; z.B. --teilaufgabe 1.1).")
    args = p.parse_args(argv)

    if not args.eingabe and not args.text and not args.verzeichnis:
        p.error("Bitte eine Eingabe angeben: PDF, --text oder --verzeichnis.")

    nur_ta = args.teilaufgabe or None

    # Batch-Modus
    if args.verzeichnis:
        pdfs = sorted(args.verzeichnis.glob("*.pdf"))
        if not pdfs:
            print(f"Keine PDFs in {args.verzeichnis} gefunden.")
            return 1
        for pdf in pdfs:
            name = args.name or pdf.stem.replace("_", " ")
            ziel = args.ausgabe / _dateiname_safe(name)
            try:
                bewerte_schueler(
                    schueler_pdf=pdf, schueler_text=None, name=name,
                    vorlage=args.vorlage, lehrer_pdf=args.lehrer_pdf,
                    ocr_modus=args.ocr, ausgabe_dir=ziel, nur_teilaufgaben=nur_ta,
                )
            except Exception as e:
                print(f"  FEHLER bei {pdf.name}: {e}")
        return 0

    # Einzelmodus
    name = args.name or (args.eingabe.stem if args.eingabe else args.text.stem).replace("_", " ")
    ziel = args.ausgabe / _dateiname_safe(name)
    bewerte_schueler(
        schueler_pdf=args.eingabe, schueler_text=args.text, name=name,
        vorlage=args.vorlage, lehrer_pdf=args.lehrer_pdf,
        ocr_modus=args.ocr, ausgabe_dir=ziel, nur_teilaufgaben=nur_ta,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
