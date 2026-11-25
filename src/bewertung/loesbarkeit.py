#!/usr/bin/env python3
"""
Lösbarkeits- und fachliche Richtigkeitsprüfung mit lokalem Sprachmodell.

Ergänzt die regel- und KI-gestützte Begutachtung (siehe ``src.bewertung.regelbasiert``
und ``src.bewertung.ki_gestuetzt``) um eine inhaltliche Prüfung jeder einzelnen
Teilaufgabe gegen die zugehörige Musterlösung im Erwartungshorizont. Pro
Teilaufgabe werden zwei Fragen an das Modell gestellt:

  A) **Lösbarkeit:** Hat der Prüfling alle Informationen, um die Aufgabe in
     der vorgesehenen Zeit fachlich zu lösen?
  B) **Fachliche Richtigkeit:** Ist die Musterlösung im Erwartungshorizont
     fachlich korrekt?

Die Prüfung berücksichtigt die fünf RRL-Lerngebiete IT1–IT5 (bgtechnik2016)
über lerngebietsspezifische Hinweise. Lerngebiete, die nur über grafische
Darstellungen prüfbar wären (IT5), oder Aufgaben mit fehlendem Lösungstext
werden konsequent als ``nicht_pruefbar`` markiert – nicht geraten.

Verwendung:
  python src/bewertung/loesbarkeit.py <SM.pdf> <LM.pdf>
  python src/bewertung/loesbarkeit.py --verzeichnis Klausuren/Abiturvorschläge/2025Mechatronik
  python src/bewertung/loesbarkeit.py --ausgabe Auswertungen/Loesbarkeit_X.xlsx <SM> <LM>

Voraussetzung: LM Studio (oder kompatibles OpenAI-API) erreichbar – die
Infrastruktur dafür wird aus ``src.bewertung.ki_gestuetzt`` übernommen.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

# Reuse der vorhandenen Module
from src.bewertung.regelbasiert import (
    Aufgabe, Teilaufgabe,
    extract_text, extract_text_pdf, parse_aufgaben,
    finde_vorschlaege,
)
# Modellanbindung (openai, eduwerkzeuge) erst bei Bedarf laden: Prompt-Bau,
# Textauszüge und Berichte dieses Moduls nutzt auch der Skill
# abiturvorschlag-begutachten, der ohne diese Pakete läuft.
def _ki():
    from src.bewertung import ki_gestuetzt
    return ki_gestuetzt


def stelle_lokales_modell_bereit(verbose: bool = True) -> str:
    return _ki().stelle_lokales_modell_bereit(verbose)


def _erstelle_client():
    return _ki()._erstelle_client()


def _rufe_ki_auf(*args, **kwargs):
    return _ki()._rufe_ki_auf(*args, **kwargs)


def _strip_think_tags(text: str) -> str:
    return _ki()._strip_think_tags(text)


def _datei_inhaltshash(pfad: str) -> str:
    return _ki()._datei_inhaltshash(pfad)


def aktiver_provider():
    return _ki().aktiver_provider()


from src.analysen.rrl import (
    IT_RRL_UEBERGEORDNETE_KOMPETENZEN,
    kompakter_rrl_block,
)

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

# Schwellenwert: Antworten mit Konfidenz darunter werden zu "unklar".
KONFIDENZ_SCHWELLE = 75

# Maximale Textlängen, die in einen Einzelprompt einfließen. GPT-OSS-20b
# arbeitet typischerweise mit 8–32 k Kontext; wir bleiben deutlich darunter,
# damit auch kleinere Modelle (oder mehr Aufgaben gleichzeitig) funktionieren.
MAX_AUFGABE_TEXT = 4000
MAX_LOESUNG_TEXT = 12000


# Lerngebietsspezifische Prüfhinweise – diese gehen direkt in den Prompt.
# Inhalte sind so formuliert, dass auch ein 20-b-Modell die Schlüsselregeln
# (Subnetting, Verriegelung, SQL-Injection-Risiko, …) abrufen kann.
IT_LERNGEBIET_HINWEISE: dict[str, str] = {
    "IT1": (
        "Lerngebiet IT1 – Technische Prozesse steuern (LOGO!/SPS, "
        "Verbindungs- und speicherprogrammierte Steuerungen).\n"
        "Prüfe bei der Lösung:\n"
        "- Drehrichtungsumkehr (z. B. zwei Motorschütze) erfordert "
        "  zwingend eine gegenseitige Ausgangsverriegelung; ohne diese "
        "  liegt ein Sicherheitsrisiko vor.\n"
        "- Endlagenschalter müssen die Bewegung beenden; Stopp-Taster "
        "  muss in jeder Phase eingreifen können.\n"
        "- Wertetabellen/Funktionsgleichungen Eingang → Ausgang müssen "
        "  vollständig sein.\n"
        "- Wenn die Aufgabe LOGO!-Programmblöcke nur als Schaltbild "
        "  fordert und die Musterlösung nur ein Bild ist (kein Text), "
        "  setze die Richtigkeit auf 'nicht_pruefbar'."
    ),
    "IT2": (
        "Lerngebiet IT2 – Netzwerke analysieren, planen, konfigurieren.\n"
        "Prüfe bei der Lösung:\n"
        "- Netzwerkadresse = IP UND Subnetzmaske (bitweise AND).\n"
        "- Broadcast = Netzwerkadresse OR (NICHT Maske).\n"
        "- Private Adressräume (RFC 1918): 10.0.0.0/8, 172.16.0.0/12, "
        "  192.168.0.0/16.\n"
        "- Adressklassen erstes Oktett: A 0–127, B 128–191, C 192–223.\n"
        "- Subnetzmaske mit n Hostbits ⇒ 2^n − 2 nutzbare Hosts.\n"
        "- RAID 5: mind. 3 Platten; Nutzkapazität = (n−1) × Plattengröße; "
        "  eine Parität pro Stripe; Ausfall einer Platte tolerierbar.\n"
        "- WPA2/AES-CCMP: Pre-Shared-Key + per-session keys; nicht "
        "  durch nur 'WPA' oder 'WEP' ersetzbar.\n"
        "- DHCP-Daten an Client: IP, Subnetzmaske, Standardgateway, "
        "  DNS-Server, Lease-Dauer.\n"
        "- Paketfilter arbeitet auf Layer 3/4 (IP/Port), nicht auf "
        "  Application-Layer.\n"
        "- VPN baut Tunnel über öffentliches Netz auf (IPsec/SSL)."
    ),
    "IT3": (
        "Lerngebiet IT3 – Software zur Prozessdatenverarbeitung (meist "
        "Java oder Python).\n"
        "Prüfe bei der Lösung:\n"
        "- Syntax: Klammern paarweise, Semikolons (Java), korrekte "
        "  Einrückung (Python).\n"
        "- Algorithmus entspricht der Aufgabe (Abbruchbedingungen "
        "  vorhanden, keine Endlosschleifen).\n"
        "- SQL-Strings, die aus Nutzereingaben konkateniert werden, "
        "  sind anfällig für SQL-Injection; korrekt sind "
        "  Prepared Statements.\n"
        "- Object.hashCode() in Java ist KEIN kryptografischer Hash "
        "  (deterministisch, kollisionsanfällig) – als Passwortspeicher "
        "  unzureichend.\n"
        "- Geteilter Zustand (Servlets, Threads) erfordert "
        "  Synchronisation oder thread-lokale Variablen.\n"
        "- Klassendiagramm: Vererbung mit Pfeil zur Oberklasse, "
        "  Methodensignaturen (+ public, − private)."
    ),
    "IT4": (
        "Lerngebiet IT4 – Messwerte erfassen und verarbeiten.\n"
        "Prüfe bei der Lösung:\n"
        "- Sensor-Kennlinie: linear interpolieren, wenn nicht anders "
        "  angegeben.\n"
        "- Einheiten konsistent (Hz, mA, °C, V); Umrechnungen prüfen.\n"
        "- Mess­bereich und Auflösung passen zur Aufgabe.\n"
        "- Bei A/D-Wandler: 2^n Stufen für n-Bit; LSB = U_ref / 2^n.\n"
        "- Sensor-Anschluss: Frequenz­eingänge (schnelle Eingänge) "
        "  vs. Analog­eingang vs. digitaler Eingang."
    ),
    "IT5": (
        "Lerngebiet IT5 – Software zur grafischen Darstellung "
        "technischer Prozesse.\n"
        "Die Lösung ist meist visuell. Wenn die Musterlösung nur als "
        "Bild vorliegt oder weniger als 200 Zeichen Fließtext zeigt, "
        "setze die Richtigkeit AUF JEDEN FALL auf 'nicht_pruefbar'."
    ),
    "unbekannt": (
        "Lerngebiet konnte nicht eindeutig zugeordnet werden – prüfe "
        "konservativ; im Zweifel 'unklar' oder 'nicht_pruefbar' setzen."
    ),
}


# Keyword-Listen für die Lerngebiet-Klassifikation. Bewusst überlappungsarm
# gewählt; bei mehrfachem Treffer entscheidet die höchste gewichtete
# Vorkommens­zahl.
IT_LERNGEBIET_KEYWORDS: dict[str, list[str]] = {
    "IT1": [
        "LOGO", "SPS", "Schütz", "Endlage", "Verriegelung", "Funktionsplan",
        "Stromlaufplan", "Wertetabelle", "Ablaufsteuerung", "Hauptschütz",
        "Tor öffnen", "Tor schließen", "Schaltbild", "Anschlussplan",
        "Sicherheitsleiste", "Drehrichtung",
    ],
    "IT2": [
        "VPN", "DHCP", "DNS", "Subnetz", "Subnetzmaske", "Broadcast",
        "Netzwerkadresse", "Gateway", "Router", "Switch", "Hub",
        "WLAN", "WPA2", "WPA", "WEP", "RAID", "Paketfilter", "Firewall",
        "Port", "OSI", "VLAN", "IPv4", "IPv6", "Subnet", "MAC-Adresse",
    ],
    "IT3": [
        "Java", "Python", "Klassendiagramm", "Algorithmus", "Quellcode",
        "Klasse", "Methode", "Schleife", "Hashcode", "SQL", "JDBC",
        "Servlet", "Programmieren", "Bibliothek", "Rekursion", "Variable",
        "Datenbank", "MySQL", "Tabelle", "Passwort", "Authentifizierung",
        "Eclipse", "Tomcat",
    ],
    "IT4": [
        "Sensor", "Messbereich", "ADC", "Analog-Digital", "Frequenz",
        "Spannung", "Stromstärke", "Datenblatt", "Kennlinie",
        "Ultraschall", "Temperatur", "Drucksensor", "Quantisierung",
        "Messwert", "Auflösung", "Frequenzeingang", "4..20 mA",
        "4...20 mA", "0..10 V",
    ],
    "IT5": [
        "GUI", "Visualisierung", "SVG", "Display", "Chart", "Dashboard",
        "Animation", "HMI", "Touchscreen", "Plot", "Diagramm zeichnen",
    ],
}

# Vorkompilierte Word-Boundary-Pattern pro Lerngebiet – wird einmal beim
# Modul-Import gebaut und in klassifiziere_lerngebiet wiederverwendet
# (statt ~1000 re.compile-Aufrufen pro Lösbarkeitslauf).
IT_LERNGEBIET_PATTERNS: dict[str, list[re.Pattern]] = {
    lg: [re.compile(rf"\b{re.escape(kw.lower())}\b") for kw in kws]
    for lg, kws in IT_LERNGEBIET_KEYWORDS.items()
}


# ---------------------------------------------------------------------------
# Datenklasse
# ---------------------------------------------------------------------------

@dataclass
class LoesbarkeitErgebnis:
    teilaufgabe: str
    lerngebiet: str
    loesbarkeit: str = "nicht_pruefbar"
    loesbarkeit_konfidenz: int = 0
    loesbarkeit_begruendung: str = ""
    fehlende_information: list = field(default_factory=list)
    richtigkeit: str = "nicht_pruefbar"
    richtigkeit_konfidenz: int = 0
    richtigkeit_begruendung: str = ""
    fehler_in_loesung: list = field(default_factory=list)
    vorab_hinweis: str = ""   # Validitäts-Hinweis aus den Vorbedingungen


# ---------------------------------------------------------------------------
# Lerngebiet-Klassifikation
# ---------------------------------------------------------------------------

def klassifiziere_lerngebiet(
    aufgabentext: str, loesungstext: str = ""
) -> tuple[str, dict[str, int]]:
    """Liefert (lerngebiet, scores) für eine Teilaufgabe.

    Bei Score 0 für alle Lerngebiete wird ``"unbekannt"`` zurückgegeben.
    Aufgabentext zählt doppelt, weil der Schüler den primär sieht.
    """
    text_lower = aufgabentext.lower()
    loesung_lower = loesungstext.lower()
    scores: dict[str, int] = {lg: 0 for lg in IT_LERNGEBIET_PATTERNS}
    for lg, patterns in IT_LERNGEBIET_PATTERNS.items():
        for pat in patterns:
            scores[lg] += len(pat.findall(text_lower)) * 2
            scores[lg] += len(pat.findall(loesung_lower))
    best_lg, best_score = max(scores.items(), key=lambda kv: kv[1])
    if best_score == 0:
        return "unbekannt", scores
    return best_lg, scores


# ---------------------------------------------------------------------------
# Text-Extraktion pro Teilaufgabe
# ---------------------------------------------------------------------------

def _normalisiere(text: str) -> str:
    """Kollabiert Whitespace, entfernt PDF-typische Header/Footer-Reste."""
    return re.sub(r"[ \t]+", " ", text).strip()


def extrahiere_teilaufgabentext(
    sm_text: str, teil: Teilaufgabe, aufgaben: list[Aufgabe]
) -> str:
    """Liefert den Aufgabentext einer Teilaufgabe aus dem Schülermaterial."""
    if teil.text and len(_normalisiere(teil.text)) >= 50:
        return _normalisiere(teil.text)
    # Fallback: regex
    m = re.search(
        rf"^\s*{re.escape(teil.nummer)}\s+.+?(?=^\s*\d+\.\d+\s|\Z)",
        sm_text, re.MULTILINE | re.DOTALL,
    )
    return _normalisiere(m.group(0)) if m else ""


def extrahiere_loesungstext(lm_text: str, t_nr: str) -> str:
    """Liefert die Musterlösung zu einer Teilaufgabe aus dem Lehrermaterial.

    Sucht typische Marker („Lösungsvorschlag zur Teilaufgabe X.Y",
    „Musterlösung X.Y") und schneidet bis zum nächsten Lösungsblock oder
    bis zum Beginn der nächsten Hauptaufgabe.
    """
    patterns = [
        rf"L[öo]sungsvorschlag\s+zur?\s+Teilaufgabe\s+{re.escape(t_nr)}\b"
        rf".*?(?=L[öo]sungsvorschlag\s+zur?\s+Teilaufgabe|\d+\.\s*Aufgabe|\Z)",
        rf"Musterl[öo]sung[:\s]+(?:zu(?:r)?\s+)?{re.escape(t_nr)}\b"
        rf".*?(?=Musterl[öo]sung|\d+\.\s*Aufgabe|\Z)",
        rf"^\s*{re.escape(t_nr)}\b[ \t].+?(?=^\s*\d+\.\d+\s|\Z)",
    ]
    for p in patterns:
        m = re.search(p, lm_text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        if m and len(m.group(0)) > 80:
            return _normalisiere(m.group(0))
    return ""


def extrahiere_materialhinweise(sm_text: str, aufgabe_nr: int) -> list[str]:
    """Liefert die in der Aufgabenstellung referenzierten Anlagen/Vorlagen/Dateien."""
    block_match = re.search(
        rf"{aufgabe_nr}\.\s*Aufgabe\b.*?(?=\d+\.\s*Aufgabe|\Z)",
        sm_text, re.DOTALL,
    )
    if not block_match:
        return []
    block = block_match.group()
    treffer: set[str] = set()
    for pattern in (
        r"[Vv]orlage\s+\d+[a-z]?\s*(?:zu\s+Aufgabe\s+\d[\.\d]*)?",
        r"Anlage\s+\d+[a-z]?",
        r"Technologieschema\s+\d+",
        r"Abbildung\s*\d*[:\s]*[^\n,;]{0,40}",
        r"Datenblatt\s+[\w\-]+",
        r"Datei\s+[\w\.\-]+",
    ):
        for m in re.finditer(pattern, block):
            treffer.add(_normalisiere(m.group(0)))
    return sorted(treffer)


# ---------------------------------------------------------------------------
# Prompt-Bau
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_LSG = """\
Du bist Fachgutachter:in für Abiturklausuren am Beruflichen Gymnasium
Technik, Schwerpunkt Informationstechnik (Niedersachsen). Du prüfst eine
EINZELNE Teilaufgabe einer eA-Klausur auf zwei Dinge:

  A) LÖSBARKEIT – Hat der Prüfling alle nötigen Informationen, um die
     Aufgabe in der vorgesehenen Zeit fachlich zu lösen?
  B) FACHLICHE RICHTIGKEIT – Ist die Musterlösung im Erwartungshorizont
     fachlich korrekt?

ABSOLUTE REGELN:
1. Antworte AUSSCHLIESSLICH im vorgegebenen JSON-Format. Kein Text davor
   oder danach. Keine Markdown-Codeblöcke.
2. Setze Konfidenz nur auf > 75, wenn du sicher bist. Bei Unsicherheit
   ⇒ Ergebnis "unklar", Konfidenz < 75.
3. Wenn die Aufgabe auf Abbildungen, Datenblätter, Schaltbilder oder
   andere Anlagen verweist, deren INHALT du nicht im Klartext siehst,
   und die Lösung von diesen Inhalten abhängt, ⇒ Ergebnis
   "nicht_pruefbar" mit Begründung.
4. Wenn die Musterlösung leer, sehr kurz oder offensichtlich
   bruchstückhaft ist, ⇒ richtigkeit = "nicht_pruefbar".
5. Bei rein visuell zu lösenden Aufgaben (Klassendiagramm zeichnen,
   Schaltbild zeichnen, GUI-Mockup) ohne Textlösung
   ⇒ richtigkeit = "nicht_pruefbar".
6. Begründungen sind kurz, sachlich, mit konkretem Bezug zur Aufgabe –
   keine Floskeln.
7. Lies deine Begründung erneut, bevor du Status und Konfidenz setzt.
   Begründung und Ergebnis dürfen sich nicht widersprechen.
8. Lieber "nicht_pruefbar" als raten.
"""


def baue_prompt(
    t_nr: str,
    aufgabentext: str,
    loesungstext: str,
    lerngebiet: str,
    materialhinweise: list[str],
) -> str:
    """Baut den Per-Teilaufgabe-Prompt.

    Eingebettet werden – auf das jeweilige Lerngebiet zugeschnitten:
      1. Verbatim-Auszug aus der RRL bgtechnik2016 (Zielformulierung,
         Inhalte, Unterrichtshinweise), damit das Modell die curriculare
         Erwartung nicht „wissen" muss.
      2. Fachliche Häufige-Fehler-Hinweise (Subnetting, hashCode, …) als
         konkrete Prüf­anker, ergänzend zur RRL.
      3. Aufgabentext, Musterlösung, Materialhinweise – im Klartext.
    """
    rrl_block = kompakter_rrl_block(lerngebiet)
    hinweise = IT_LERNGEBIET_HINWEISE.get(
        lerngebiet, IT_LERNGEBIET_HINWEISE["unbekannt"]
    )
    material_str = "\n".join(f"  - {m}" for m in materialhinweise) \
        or "  (keine zusätzlichen Materialien in der Aufgabenstellung erwähnt)"

    return (
        f"TEILAUFGABE: {t_nr}\n"
        f"ERKANNTES LERNGEBIET: {lerngebiet}\n\n"
        f"=== CURRICULARE GRUNDLAGE (verbindlich, aus den Rahmenrichtlinien) ===\n"
        f"{IT_RRL_UEBERGEORDNETE_KOMPETENZEN}\n\n"
        f"{rrl_block}\n\n"
        f"=== HÄUFIGE FACHLICHE FEHLERMUSTER (ergänzend zur RRL) ===\n"
        f"{hinweise}\n\n"
        f"=== AUFGABENSTELLUNG (aus Schülermaterial) ===\n"
        f'"""\n{aufgabentext}\n"""\n\n'
        f"=== MUSTERLÖSUNG (aus Erwartungshorizont / Lehrermaterial) ===\n"
        f'"""\n{loesungstext or "(keine Lösung im Textextrakt gefunden)"}\n"""\n\n'
        f"=== REFERENZIERTES MATERIAL FÜR PRÜFLING (laut Aufgabentext) ===\n"
        f"{material_str}\n\n"
        f"=== PRÜFFRAGEN ===\n"
        f"A) LÖSBARKEIT – Reicht das Schülermaterial inkl. der genannten "
        f"Anlagen, um diese Teilaufgabe zu bearbeiten? Achte besonders auf: "
        f"fehlende Werte/Abbildungen, mehrdeutige Formulierungen, fehlende "
        f"Zwischenergebnisse aus Voraufgaben (Alternativwert?).\n"
        f"B) FACHLICHE RICHTIGKEIT – Ist die Musterlösung fachlich korrekt? "
        f"Beurteile die Korrektheit auf Basis der RRL-Inhalte und der "
        f"obigen Fehlermuster.\n\n"
        f"Antworte mit GENAU diesem JSON (kein Text drumherum):\n"
        f"{{\n"
        f'  "loesbarkeit": "ja" | "nein" | "unklar" | "nicht_pruefbar",\n'
        f'  "loesbarkeit_konfidenz": <0-100>,\n'
        f'  "loesbarkeit_begruendung": "<kurz, sachlich>",\n'
        f'  "fehlende_information": ["<falls nein/unklar: was fehlt>"],\n'
        f'  "richtigkeit": "ja" | "nein" | "unklar" | "nicht_pruefbar",\n'
        f'  "richtigkeit_konfidenz": <0-100>,\n'
        f'  "richtigkeit_begruendung": "<kurz, sachlich>",\n'
        f'  "fehler_in_loesung": ["<falls nein: konkrete Fehler>"]\n'
        f"}}"
    )


# ---------------------------------------------------------------------------
# KI-Aufruf (eigener System-Prompt, daher nicht das _rufe_ki_auf aus
# src.bewertung.ki_gestuetzt direkt – die JSON-Felder unterscheiden sich)
# ---------------------------------------------------------------------------

_LEER_ANTWORT = {
    "loesbarkeit": "nicht_pruefbar",
    "loesbarkeit_konfidenz": 0,
    "loesbarkeit_begruendung": "(keine Antwort)",
    "fehlende_information": [],
    "richtigkeit": "nicht_pruefbar",
    "richtigkeit_konfidenz": 0,
    "richtigkeit_begruendung": "(keine Antwort)",
    "fehler_in_loesung": [],
}


def _parse_json_robust(text: str) -> dict:
    """Versucht ein JSON-Objekt aus der Modellantwort zu extrahieren."""
    text = _strip_think_tags(text).strip()
    # Markdown-Codeblöcke entfernen
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    # Erste { ... letztes } extrahieren
    erste = text.find("{")
    letzte = text.rfind("}")
    if erste == -1 or letzte == -1 or letzte <= erste:
        return dict(_LEER_ANTWORT,
                    loesbarkeit_begruendung=f"JSON nicht gefunden in Antwort: {text[:120]}")
    blob = text[erste:letzte + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError as e:
        return dict(_LEER_ANTWORT,
                    loesbarkeit_begruendung=f"JSON-Fehler ({e}): {blob[:120]}")


def rufe_modell_auf(
    client, prompt: str, modell: str, max_retries: int = 1
) -> dict:
    """Sendet den Lösbarkeits-Prompt an das Modell und parst die Antwort."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_LSG},
        {"role": "user", "content": prompt},
    ]
    versuch = 0
    while True:
        try:
            resp = client.chat.completions.create(
                model=modell, messages=messages,
                temperature=0.1, max_tokens=900,
            )
            content = resp.choices[0].message.content or ""
            return _parse_json_robust(content)
        except Exception as e:
            if versuch >= max_retries:
                return dict(_LEER_ANTWORT,
                            loesbarkeit_begruendung=f"Modellfehler: {type(e).__name__}: {e}")
            versuch += 1


# ---------------------------------------------------------------------------
# Validitätsfilter
# ---------------------------------------------------------------------------

def _validitaetsfilter(antwort: dict, vorab_hinweis: str = "") -> dict:
    """Setzt Antworten mit niedriger Konfidenz auf 'unklar' bzw. behält
    'nicht_pruefbar' bei. Vorab-Hinweis wird respektiert."""
    if vorab_hinweis:
        antwort["loesbarkeit"] = "nicht_pruefbar"
        antwort["richtigkeit"] = "nicht_pruefbar"
        antwort["loesbarkeit_begruendung"] = (
            (antwort.get("loesbarkeit_begruendung") or "") + " [" + vorab_hinweis + "]"
        ).strip()
        antwort["richtigkeit_begruendung"] = (
            (antwort.get("richtigkeit_begruendung") or "") + " [" + vorab_hinweis + "]"
        ).strip()
        return antwort
    for aspekt in ("loesbarkeit", "richtigkeit"):
        konf = antwort.get(f"{aspekt}_konfidenz", 0) or 0
        try:
            konf = int(konf)
        except (ValueError, TypeError):
            konf = 0
        if antwort.get(aspekt) in ("ja", "nein") and konf < KONFIDENZ_SCHWELLE:
            antwort[aspekt] = "unklar"
            antwort[f"{aspekt}_begruendung"] = (
                f"[Konfidenz {konf} % < Schwelle {KONFIDENZ_SCHWELLE} %] "
                + (antwort.get(f"{aspekt}_begruendung") or "")
            )
        antwort[f"{aspekt}_konfidenz"] = konf
    # Listen sicherstellen
    for feld in ("fehlende_information", "fehler_in_loesung"):
        v = antwort.get(feld)
        if v is None:
            antwort[feld] = []
        elif isinstance(v, str):
            antwort[feld] = [v] if v else []
    return antwort


# ---------------------------------------------------------------------------
# Hauptablauf
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Checkpoint: Zwischenergebnisse bei Abbruch/Timeout sichern
# ---------------------------------------------------------------------------

def _loesbar_checkpoint_pfad(sm_pfad: str, lm_pfad: str | None = None) -> str:
    """Inhalts-gehashter Checkpoint, parallel zu KI-Prüfung."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sm_hash = _datei_inhaltshash(sm_pfad)
    lm_hash = _datei_inhaltshash(lm_pfad) if lm_pfad else ""
    if sm_hash and lm_hash:
        name = f"checkpoint_loesbar_{sm_hash}_{lm_hash}.json"
    else:
        name = f"checkpoint_loesbar_{Path(sm_pfad).stem}.json"
    return os.path.join(script_dir, "Auswertungen", name)


def _lade_loesbar_checkpoint(
    sm_pfad: str, lm_pfad: str
) -> dict[str, "LoesbarkeitErgebnis"] | None:
    """Lädt schon geprüfte Teilaufgaben, key = teilaufgabe-Nummer."""
    pfad = _loesbar_checkpoint_pfad(sm_pfad, lm_pfad)
    if not os.path.isfile(pfad):
        return None
    try:
        with open(pfad, encoding="utf-8") as f:
            daten = json.load(f)
        if (daten.get("sm_hash") != _datei_inhaltshash(sm_pfad)
                or daten.get("lm_hash") != _datei_inhaltshash(lm_pfad)):
            return None
        out: dict[str, LoesbarkeitErgebnis] = {}
        for d in daten.get("ergebnisse", []):
            erg = LoesbarkeitErgebnis(
                teilaufgabe=d.get("teilaufgabe", ""),
                lerngebiet=d.get("lerngebiet", ""),
                loesbarkeit=d.get("loesbarkeit", "nicht_pruefbar"),
                loesbarkeit_konfidenz=int(d.get("loesbarkeit_konfidenz", 0) or 0),
                loesbarkeit_begruendung=d.get("loesbarkeit_begruendung", "") or "",
                fehlende_information=list(d.get("fehlende_information", []) or []),
                richtigkeit=d.get("richtigkeit", "nicht_pruefbar"),
                richtigkeit_konfidenz=int(d.get("richtigkeit_konfidenz", 0) or 0),
                richtigkeit_begruendung=d.get("richtigkeit_begruendung", "") or "",
                fehler_in_loesung=list(d.get("fehler_in_loesung", []) or []),
                vorab_hinweis=d.get("vorab_hinweis", "") or "",
            )
            out[erg.teilaufgabe] = erg
        return out
    except Exception:
        return None


def _speichere_loesbar_checkpoint(
    sm_pfad: str, lm_pfad: str,
    ergebnisse: list["LoesbarkeitErgebnis"],
) -> None:
    pfad = _loesbar_checkpoint_pfad(sm_pfad, lm_pfad)
    try:
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        daten = {
            "sm": sm_pfad,
            "lm": lm_pfad,
            "sm_name": Path(sm_pfad).name,
            "lm_name": Path(lm_pfad).name,
            "sm_hash": _datei_inhaltshash(sm_pfad),
            "lm_hash": _datei_inhaltshash(lm_pfad),
            "ergebnisse": [asdict(e) for e in ergebnisse],
        }
        with open(pfad, "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"  Warnung: Lösbar-Checkpoint nicht gespeichert: {exc}")


def _loesche_loesbar_checkpoint(sm_pfad: str, lm_pfad: str | None = None) -> None:
    pfad = _loesbar_checkpoint_pfad(sm_pfad, lm_pfad)
    try:
        if os.path.isfile(pfad):
            os.remove(pfad)
    except Exception:
        pass


def _vorbedingung(aufgabentext: str, loesungstext: str,
                  lerngebiet: str) -> str:
    """Prüft Vorbedingungen. Gibt einen Hinweis-String zurück oder ''
    wenn alle Vorbedingungen erfüllt sind."""
    if len(aufgabentext) < 50:
        return ("Aufgabentext zu kurz oder fragmentarisch im PDF-Extrakt – "
                "keine valide Prüfung möglich.")
    if lerngebiet == "IT5" and len(loesungstext) < 200:
        return ("Lerngebiet IT5 (grafische Darstellung) und Musterlösung "
                "im Textextrakt zu kurz – keine valide Prüfung möglich.")
    return ""


def fuehre_loesbarkeitspruefung_durch(
    schueler_pfad: str, lehrer_pfad: str, verbose: bool = True,
    progress_callback=None,
) -> list[LoesbarkeitErgebnis]:
    """Hauptablauf für ein Klausurpaar.

    progress_callback(dict): wird nach jeder Teilaufgabe mit
        {"stufe": "loesbarkeit", "aktuell": int, "gesamt": int,
         "label": str, "ergebnis": LoesbarkeitErgebnis|None,
         "uebersprungen": bool} aufgerufen.
    Checkpoint: bereits geprüfte Teilaufgaben werden bei erneutem Start
    übersprungen, sofern SM/LM inhaltlich identisch sind.
    """
    def _melde(event: dict) -> None:
        if progress_callback:
            try:
                progress_callback(event)
            except Exception:
                pass

    if verbose:
        print("=" * 72)
        print("Lösbarkeits- und Richtigkeitsprüfung (lokales Sprachmodell)")
        print("=" * 72)

    # Textgrundlage: bevorzugt Layout-Extraktion (Tabellen erhalten).
    sm_text = extract_text(schueler_pfad)
    lm_text_normal = extract_text(lehrer_pfad)
    lm_text_layout = (
        extract_text_pdf(lehrer_pfad, layout=True)
        if lehrer_pfad.lower().endswith(".pdf") else lm_text_normal
    )
    lm_text = lm_text_layout if lm_text_layout else lm_text_normal

    aufgaben = parse_aufgaben(sm_text)
    gesamt = sum(len(a.teilaufgaben) for a in aufgaben)
    if verbose:
        print(f"  → {len(aufgaben)} Aufgaben, {gesamt} Teilaufgaben.")

    # Checkpoint laden (gleiche PDF-Inhalte → fortsetzen)
    cached = _lade_loesbar_checkpoint(schueler_pfad, lehrer_pfad) or {}
    if cached and verbose:
        print(f"  Checkpoint: {len(cached)} Teilaufgaben bereits geprüft.")
    _melde({"stufe": "loesbarkeit_start", "aktuell": 0, "gesamt": gesamt,
            "label": "Lösbarkeit", "aus_checkpoint": len(cached)})

    # KI bereitstellen
    provider = aktiver_provider()  # frisch abfragen (Oberfläche kann wechseln)
    if provider.is_lokal:
        modell = stelle_lokales_modell_bereit(verbose)
    else:
        modell = provider.model
        if verbose:
            print(f"  Provider: {provider.name}, Modell: {modell}")
    client = _erstelle_client()

    ergebnisse: list[LoesbarkeitErgebnis] = []
    idx = 0
    for a in aufgaben:
        material_a = extrahiere_materialhinweise(sm_text, a.nummer)
        for t in a.teilaufgaben:
            idx += 1

            if t.nummer in cached:
                erg = cached[t.nummer]
                ergebnisse.append(erg)
                if verbose:
                    print(f"  [{idx}/{gesamt}] {t.nummer} ({erg.lerngebiet}): "
                          f"aus Checkpoint")
                _melde({"stufe": "loesbarkeit", "aktuell": idx,
                        "gesamt": gesamt, "label": f"Teilaufgabe {t.nummer}",
                        "ergebnis": erg, "aus_checkpoint": True})
                continue

            aufg_text = extrahiere_teilaufgabentext(sm_text, t, aufgaben)
            loesung_text = extrahiere_loesungstext(lm_text, t.nummer)
            lerngebiet, _ = klassifiziere_lerngebiet(aufg_text, loesung_text)

            hinweis = _vorbedingung(aufg_text, loesung_text, lerngebiet)
            erg = LoesbarkeitErgebnis(
                teilaufgabe=t.nummer, lerngebiet=lerngebiet,
                vorab_hinweis=hinweis,
            )

            if hinweis:
                erg.loesbarkeit_begruendung = hinweis
                erg.richtigkeit_begruendung = hinweis
                ergebnisse.append(erg)
                if verbose:
                    print(f"  [{idx}/{gesamt}] {t.nummer} ({lerngebiet}): ⏭ {hinweis}")
                _speichere_loesbar_checkpoint(schueler_pfad, lehrer_pfad, ergebnisse)
                _melde({"stufe": "loesbarkeit", "aktuell": idx,
                        "gesamt": gesamt, "label": f"Teilaufgabe {t.nummer}",
                        "ergebnis": erg, "uebersprungen": True})
                continue

            prompt = baue_prompt(
                t.nummer,
                aufg_text[:MAX_AUFGABE_TEXT],
                loesung_text[:MAX_LOESUNG_TEXT],
                lerngebiet, material_a,
            )

            if verbose:
                print(f"  [{idx}/{gesamt}] {t.nummer} ({lerngebiet}) … ",
                      end="", flush=True)
            _melde({"stufe": "loesbarkeit_aufruf", "aktuell": idx,
                    "gesamt": gesamt,
                    "label": f"Teilaufgabe {t.nummer} ({lerngebiet})"})

            antwort = rufe_modell_auf(client, prompt, modell)
            antwort = _validitaetsfilter(antwort)

            erg.loesbarkeit = antwort.get("loesbarkeit", "nicht_pruefbar")
            erg.loesbarkeit_konfidenz = antwort.get("loesbarkeit_konfidenz", 0)
            erg.loesbarkeit_begruendung = antwort.get("loesbarkeit_begruendung", "")
            erg.fehlende_information = antwort.get("fehlende_information", [])
            erg.richtigkeit = antwort.get("richtigkeit", "nicht_pruefbar")
            erg.richtigkeit_konfidenz = antwort.get("richtigkeit_konfidenz", 0)
            erg.richtigkeit_begruendung = antwort.get("richtigkeit_begruendung", "")
            erg.fehler_in_loesung = antwort.get("fehler_in_loesung", [])

            if verbose:
                _drucke_kurzzeile(erg)
            ergebnisse.append(erg)
            _speichere_loesbar_checkpoint(schueler_pfad, lehrer_pfad, ergebnisse)
            _melde({"stufe": "loesbarkeit", "aktuell": idx,
                    "gesamt": gesamt, "label": f"Teilaufgabe {t.nummer}",
                    "ergebnis": erg})

    return ergebnisse


def _symbol(status: str) -> str:
    return {
        "ja": "✅",
        "nein": "❌",
        "unklar": "⚠️",
        "nicht_pruefbar": "➖",
    }.get(status, "?")


def _drucke_kurzzeile(erg: LoesbarkeitErgebnis) -> None:
    l = _symbol(erg.loesbarkeit)
    r = _symbol(erg.richtigkeit)
    print(f"L:{l}({erg.loesbarkeit_konfidenz}) R:{r}({erg.richtigkeit_konfidenz})")


# ---------------------------------------------------------------------------
# XLSX-Ausgabe
# ---------------------------------------------------------------------------

def schreibe_loesbarkeitsbericht_xlsx(
    ergebnisse: list[LoesbarkeitErgebnis],
    output_pfad: str,
    schueler_datei: str,
    lehrer_datei: str,
    modell: str = "",
    pruefer: str = "lokales Sprachmodell",
) -> None:
    """Schreibt einen aufgabenorientierten Bericht in XLSX.

    pruefer: Angabe im Titel (der Skill setzt hier „Claude“)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Lösbarkeit & Richtigkeit"

    ws["A1"] = f"Lösbarkeits- und Richtigkeitsprüfung ({pruefer})"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Schülermaterial: {os.path.basename(schueler_datei)}"
    ws["A3"] = f"Lehrermaterial: {os.path.basename(lehrer_datei)}"
    if modell:
        ws["A4"] = f"Modell: {modell}"
    ws["A5"] = (
        'Hinweis: Diese Prüfung wurde automatisch durch ein lokales '
        'Sprachmodell durchgeführt. Antworten mit Konfidenz < '
        f'{KONFIDENZ_SCHWELLE} % werden als „unklar" markiert. Die '
        'abschließende Beurteilung obliegt der Lehrkraft.'
    )
    ws["A5"].font = Font(italic=True, size=10)
    ws.merge_cells("A5:I5")

    header_row = 7
    headers = [
        "Teilaufgabe", "Lerngebiet",
        "Lösbarkeit", "Konfidenz L", "Begründung Lösbarkeit",
        "Richtigkeit", "Konfidenz R", "Begründung Richtigkeit",
        "Fehlende Information / Fehler in Lösung",
    ]
    col_widths = [12, 10, 12, 11, 50, 12, 11, 50, 50]

    header_font = Font(bold=True, size=10)
    header_fill = PatternFill(start_color="D9D9D9", end_color="D9D9D9",
                              fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    for col_idx, h in enumerate(headers, 1):
        c = ws.cell(row=header_row, column=col_idx, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = header_align
        c.border = thin_border
    for col_idx, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = w

    fill_ok = PatternFill(start_color="C6EFCE", end_color="C6EFCE",
                          fill_type="solid")
    fill_fail = PatternFill(start_color="FFC7CE", end_color="FFC7CE",
                            fill_type="solid")
    fill_warn = PatternFill(start_color="FFEB9C", end_color="FFEB9C",
                            fill_type="solid")
    fill_neutral = PatternFill(start_color="E7E6E6", end_color="E7E6E6",
                               fill_type="solid")
    wrap = Alignment(vertical="top", wrap_text=True)
    center = Alignment(horizontal="center", vertical="top", wrap_text=True)

    def _fill_for(status: str):
        return {
            "ja": fill_ok, "nein": fill_fail,
            "unklar": fill_warn, "nicht_pruefbar": fill_neutral,
        }.get(status, fill_neutral)

    for i, erg in enumerate(ergebnisse, start=header_row + 1):
        kombiniert = []
        if erg.fehlende_information:
            kombiniert.append("Fehlt:")
            for f in erg.fehlende_information:
                kombiniert.append(f"  • {f}")
        if erg.fehler_in_loesung:
            kombiniert.append("Fehler in Lösung:")
            for f in erg.fehler_in_loesung:
                kombiniert.append(f"  • {f}")
        ws.cell(row=i, column=1, value=erg.teilaufgabe).alignment = center
        ws.cell(row=i, column=2, value=erg.lerngebiet).alignment = center
        c_l = ws.cell(row=i, column=3,
                      value=f"{_symbol(erg.loesbarkeit)} {erg.loesbarkeit}")
        c_l.alignment = center
        c_l.fill = _fill_for(erg.loesbarkeit)
        ws.cell(row=i, column=4, value=erg.loesbarkeit_konfidenz).alignment = center
        ws.cell(row=i, column=5, value=erg.loesbarkeit_begruendung).alignment = wrap
        c_r = ws.cell(row=i, column=6,
                      value=f"{_symbol(erg.richtigkeit)} {erg.richtigkeit}")
        c_r.alignment = center
        c_r.fill = _fill_for(erg.richtigkeit)
        ws.cell(row=i, column=7, value=erg.richtigkeit_konfidenz).alignment = center
        ws.cell(row=i, column=8, value=erg.richtigkeit_begruendung).alignment = wrap
        ws.cell(row=i, column=9, value="\n".join(kombiniert)).alignment = wrap

        for col in range(1, 10):
            ws.cell(row=i, column=col).border = thin_border

    ws.freeze_panes = f"A{header_row + 1}"
    last_row = header_row + len(ergebnisse)
    if ergebnisse:
        ws.auto_filter.ref = f"A{header_row}:I{last_row}"

    # Zusammenfassung
    zus_row = last_row + 2
    n_l_ja = sum(1 for e in ergebnisse if e.loesbarkeit == "ja")
    n_l_nein = sum(1 for e in ergebnisse if e.loesbarkeit == "nein")
    n_l_unk = sum(1 for e in ergebnisse if e.loesbarkeit == "unklar")
    n_l_np = sum(1 for e in ergebnisse if e.loesbarkeit == "nicht_pruefbar")
    n_r_ja = sum(1 for e in ergebnisse if e.richtigkeit == "ja")
    n_r_nein = sum(1 for e in ergebnisse if e.richtigkeit == "nein")
    n_r_unk = sum(1 for e in ergebnisse if e.richtigkeit == "unklar")
    n_r_np = sum(1 for e in ergebnisse if e.richtigkeit == "nicht_pruefbar")
    ws.cell(row=zus_row, column=1,
            value=(f"Zusammenfassung – Lösbarkeit: ✅{n_l_ja}  ❌{n_l_nein}  "
                   f"⚠️{n_l_unk}  ➖{n_l_np}  |  "
                   f"Richtigkeit: ✅{n_r_ja}  ❌{n_r_nein}  "
                   f"⚠️{n_r_unk}  ➖{n_r_np}")).font = Font(bold=True, size=10)
    ws.merge_cells(start_row=zus_row, start_column=1,
                   end_row=zus_row, end_column=9)

    wb.save(output_pfad)
    print(f"\nLösbarkeitsbericht gespeichert: {output_pfad}")


def schreibe_loesbarkeit_json(
    ergebnisse: list[LoesbarkeitErgebnis], output_pfad: str
) -> None:
    """Speichert die Ergebnisse als JSON (für spätere Wiederverwendung)."""
    data = [asdict(e) for e in ergebnisse]
    with open(output_pfad, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    print(f"JSON-Ergebnis gespeichert: {output_pfad}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Lösbarkeits- und Richtigkeitsprüfung über lokales LLM "
                    "(z.B. GPTOSS-20b via LM Studio).")
    ap.add_argument("schueler", nargs="?", help="Pfad zum Schülermaterial-PDF.")
    ap.add_argument("lehrer", nargs="?", help="Pfad zum Lehrermaterial-PDF.")
    ap.add_argument("--verzeichnis", "-v",
                    help="Ordner mit Klausurpaaren – verarbeitet alle erkannten "
                         "Paare automatisch.")
    ap.add_argument("--ausgabe", "-o",
                    help="XLSX-Ausgabepfad. Default: Auswertungen/Loesbarkeit_<SM>.xlsx")
    ap.add_argument("--leise", action="store_true",
                    help="Weniger Konsolenausgabe.")
    ap.add_argument("--provider", default=None,
                    help="lokal (LM Studio) | ollama | bonsai | hetzner | gwdg. "
                         "Standard: KI_PROVIDER aus .env, sonst lokal.")
    ap.add_argument("--modell", default=None,
                    help="Modell-ID oder Teilstring (Standard: KI_MODELL aus .env).")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    from src.bewertung.ki_gestuetzt import setze_provider
    try:
        cfg = setze_provider(args.provider or os.environ.get("KI_PROVIDER", "lokal"),
                             args.modell)
    except ValueError as e:
        print(f"FEHLER: {e}")
        return 1
    if not args.leise:
        print(f"  Provider: {cfg.name} ({cfg.base_url})")

    if args.verzeichnis:
        pfade = finde_vorschlaege(args.verzeichnis)
        if not pfade:
            print(f"Keine Klausurpaare in {args.verzeichnis!r} gefunden.")
            return 1
        for sm, lm in pfade:
            _verarbeite_paar(sm, lm, args.ausgabe, not args.leise)
        return 0

    if not args.schueler or not args.lehrer:
        ap.error("Bitte entweder zwei Dateien oder --verzeichnis angeben.")
    _verarbeite_paar(args.schueler, args.lehrer, args.ausgabe, not args.leise)
    return 0


def _verarbeite_paar(sm: str, lm: str, ausgabe: str | None,
                     verbose: bool) -> None:
    ergebnisse = fuehre_loesbarkeitspruefung_durch(sm, lm, verbose=verbose)
    basis = Path(sm).stem
    out_dir = Path("Auswertungen")
    out_dir.mkdir(exist_ok=True)
    if ausgabe:
        xlsx_pfad = ausgabe
    else:
        xlsx_pfad = str(out_dir / f"Loesbarkeit_{basis}.xlsx")
    schreibe_loesbarkeitsbericht_xlsx(ergebnisse, xlsx_pfad, sm, lm)
    json_pfad = xlsx_pfad.rsplit(".", 1)[0] + ".json"
    schreibe_loesbarkeit_json(ergebnisse, json_pfad)


if __name__ == "__main__":
    sys.exit(main())
