#!/usr/bin/env python3
"""
KI-gestützte Prüfung der manuell zu prüfenden Kriterien.

Nutzt eine lokale KI (LM Studio, OpenAI-kompatibles API) um die Kriterien
zu prüfen, die von klausur_regelbasiert.py als „MANUELL ZU PRÜFEN" markiert werden.

Voraussetzungen:
  - LM Studio läuft lokal mit geladenem Modell (z.B. GPT-OSS 20b)
  - Server aktiv auf http://localhost:1234
  - Python-Paket: pip install openai

Verwendung:
  python klausur_ki_gestuetzt.py <schuelermaterial> <lehrermaterial>
  python klausur_ki_gestuetzt.py --verzeichnis Klausuren/Abiturvorschläge/2025Mechatronik

Strategie zur Vermeidung falsch-positiver Meldungen:
  - Die KI wird explizit angewiesen, NUR eindeutige Verstöße zu melden.
  - Bei Unsicherheit wird „keine Beanstandung erkennbar" ausgegeben.
  - Jede Prüfung hat einen Konfidenzwert (0–100). Unter 75 wird das
    Ergebnis als „nicht sicher prüfbar" gewertet, nicht als Beanstandung.
  - Kriterien, die visuell/physisch geprüft werden müssen (Schriftbild,
    Datenträger, Formelsammlung), werden als „nicht durch KI prüfbar" markiert.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import platform
import sys
import time
import urllib.error
from dataclasses import dataclass
from pathlib import Path

import openai
from openai import OpenAI

# Eigene Module
# Update Importe für neue Struktur
from src.core.logging import setup_logging
from src.bewertung.regelbasiert import (
    ABITUR_BEARBEITUNGSZEIT_MIN,
    IT_LERNGEBIETE,
    IT_OPTIONAL,
    IT_VERBINDLICH,
    OPERATOREN,
    RRL_KOMPETENZEN,
    PruefungsErgebnis,
    begutachte,
    extract_text,
    extract_text_pdf,
    finde_vorschlaege,
    parse_erweiterte_operatoren,
)

# Logger-Instanz für dieses Modul
log = setup_logging(__name__)

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

# Plattform-Erkennung (muss vor ProviderConfig-Initialisierung stehen)
_IST_MACOS = sys.platform == "darwin"
_IST_WINDOWS = sys.platform == "win32"
_IST_APPLE_SILICON = _IST_MACOS and platform.machine() == "arm64"

# --- Provider-Konfigurationen -------------------------------------------
# Jeder Provider hat: base_url, api_key, model, name, beschreibung.
# Der API-Key wird bevorzugt aus einer Umgebungsvariable gelesen.
# Alle Provider nutzen das OpenAI-kompatible Chat-API-Format.
#
# DATENSCHUTZ-HINWEIS:
#   „lokal"  – Daten verlassen den Rechner nicht.
#   „hetzner" – Server in Deutschland, DSGVO-konform, AV-Vertrag möglich.
#   „gwdg"   – Akademische Cloud (GWDG Göttingen), Serverstandort DE.
#              Zugang über DFN-AAI / GWDG-Account erforderlich.
# -----------------------------------------------------------------------

# ProviderConfig + PROVIDER-Registry kommen zentral aus der Bibliothek
# (eduwerkzeuge.ki). Siehe _lib/eduwerkzeuge. Die Registry liefert base_url OHNE
# /v1; dieses Modul nutzt die /v1-Variante (cfg.api_base), siehe unten.
from eduwerkzeuge.ki import ProviderConfig
from eduwerkzeuge.ki import PROVIDER as _KI_PROVIDER
from dataclasses import replace as _replace


# Lokale Timeouts und Batch-Größen je nach Hardware
# Apple Silicon mit Unified Memory ist erheblich schneller als RPi.
if _IST_APPLE_SILICON:
    _LOKAL_TIMEOUT = 600       # Apple Silicon: GPU-beschleunigt
    _LOKAL_BATCH_GROESSE = 1   # Einzelabfragen: maximale Zuverlässigkeit bei lokalem LLM
else:
    _LOKAL_TIMEOUT = 3600      # RPi / generische CPU (Thinking-Modelle: langes Prefilling)
    _LOKAL_BATCH_GROESSE = 1   # Einzelabfragen: maximale Zuverlässigkeit bei lokalem LLM

# Lokale Sicht der zentralen Registry: base_url MIT /v1, da dieses Modul base_url
# direkt an OpenAI(base_url=…) und an "<base_url>/models" gibt.
PROVIDER: dict[str, ProviderConfig] = {
    name: _replace(cfg, base_url=cfg.api_base)
    for name, cfg in _KI_PROVIDER.items()
}

# Aktiver Provider (wird in main() gesetzt)
AKTIVER_PROVIDER: ProviderConfig = PROVIDER["lokal"]

# --- Abwärtskompatible Globals (werden von _aktiviere_provider gesetzt) ---
LMSTUDIO_BASE_URL = AKTIVER_PROVIDER.base_url
LMSTUDIO_API_KEY = AKTIVER_PROVIDER.api_key_default
LMSTUDIO_MODEL = AKTIVER_PROVIDER.model

# Pfad zur LM Studio CLI (wird automatisch gesucht)
LMS_CLI_PATHS = [
    os.path.expanduser("~/.lmstudio/bin/lms"),
    # macOS: LM Studio installiert die CLI auch unter /usr/local/bin
    "/usr/local/bin/lms",
    # Windows: typische LM-Studio-Installationspfade
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "LM-Studio", "bin", "lms.exe"),
    os.path.join(os.environ.get("APPDATA", ""), "LM-Studio", "bin", "lms.exe"),
    shutil.which("lms") or "",
    shutil.which("lms.exe") or "",
]


def _system_ram_gb() -> int:
    """Ermittelt den verfügbaren System-RAM in GB (cross-platform)."""
    try:
        if _IST_WINDOWS:
            import ctypes
            class _MEMORYSTATUSEX(ctypes.Structure):  # noqa: N801
                _fields_ = [
                    ("dwLength",                 ctypes.c_ulong),
                    ("dwMemoryLoad",             ctypes.c_ulong),
                    ("ullTotalPhys",             ctypes.c_ulonglong),
                    ("ullAvailPhys",             ctypes.c_ulonglong),
                    ("ullTotalPageFile",         ctypes.c_ulonglong),
                    ("ullAvailPageFile",         ctypes.c_ulonglong),
                    ("ullTotalVirtual",          ctypes.c_ulonglong),
                    ("ullAvailVirtual",          ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullTotalPhys) // (1024 ** 3)
        elif _IST_MACOS:
            import subprocess as _sp
            out = _sp.check_output(["sysctl", "-n", "hw.memsize"],
                                   text=True, timeout=5).strip()
            return int(out) // (1024 ** 3)
        else:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        return int(line.split()[1]) // (1024 ** 2)
    except Exception:
        pass
    return 0


_SYSTEM_RAM_GB = _system_ram_gb()

# Bevorzugtes Modell zum automatischen Laden (Reihenfolge = Präferenz).
# Kann Teilstrings enthalten – erstes Match wird geladen.
# WICHTIG: Modelle < 12B Parameter liefern bei Tabellen-Interpretation
# und logischem Schließen deutlich schlechtere Ergebnisse.
#
# Auf Apple Silicon mit ≥ 24 GB Unified Memory können größere Modelle
# geladen werden (bis ~20B Q8 oder ~27B Q4).
#
# Durchlauf 2026/27 (MacBook Air M4, 24 GB): Gemma 4 12B und Bonsai 27B
# zuerst. Die Teilstrings decken LM-Studio-IDs (gemma-4-12b), Ollama-Tags
# (gemma4:12b) und die Bonsai-Laufzeit ab.
if _IST_APPLE_SILICON and _SYSTEM_RAM_GB >= 24:
    BEVORZUGTE_MODELLE = [
        "gemma-4-12b",
        "gemma4:12b",
        "bonsai",
        "gpt-oss-20b",
        "gemma-3-27b",
        "qwen2.5-14b",
        "qwen3.5",
        "gemma-3-12b",
        "Ministral",
        "gemma-4",
    ]
else:
    BEVORZUGTE_MODELLE = [
        "gpt-oss-20b",
        "Ministral",
        "gemma-3-27b",
        "qwen2.5-14b",
        "qwen3.5",
        "gemma-3n",
        "gemma-4",
    ]

# Bekannte "kleine" Modelle (< 12B), bei denen eine Warnung ausgegeben wird.
# Teilstrings genügen – geprüft wird case-insensitive.
# WICHTIG: "4b-" wurde entfernt, da es fälschlich "14b-" (z.B. Ministral 14B) matcht.
# "-4b" reicht: fast alle 4B-Modelle haben einen Bindestrich vor "4b".
KLEINE_MODELLE_PATTERN = [
    "e4b", "-4b", "3b", "1b", "7b", "8b", "9b",
    "gemma-3n",  # E4B-Variante
    "nemotron-nano",  # Nvidia Nemotron Nano (4B)
]

# Parametergröße im Modellnamen (z. B. "12b", ":27b", "-9b"), ohne dass "27b"
# fälschlich als "7b" oder "14b" als "4b" gilt.
_GROESSE_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)b(?![a-z])", re.IGNORECASE)


def _ist_kleines_modell(modell: str) -> bool:
    """True, wenn das Modell vermutlich < 12 B Parameter hat.

    Steht eine Größe im Namen, entscheidet nur sie. Sonst greifen die
    Namensmuster aus KLEINE_MODELLE_PATTERN (z. B. "gemma-3n", "e4b").
    """
    name = (modell or "").lower()
    groessen = [float(g) for g in _GROESSE_RE.findall(name)]
    if groessen:
        return max(groessen) < 12
    return any(p.lower() in name for p in KLEINE_MODELLE_PATTERN)


def _ist_thinking_modell(modell: str) -> bool:
    """Soll die Denkphase per Assistant-Prefill übersprungen werden?

    Automatisch für Qwen3.x, Ministral-reasoning und Magistral. Über
    KI_DENKPHASE_UEBERSPRINGEN=ja|nein in .env lässt sich das für neue
    Modelle (z. B. Bonsai auf Qwen-Basis) ohne Codeänderung festlegen.
    """
    schalter = os.environ.get("KI_DENKPHASE_UEBERSPRINGEN", "auto").strip().lower()
    if schalter in ("ja", "1", "true"):
        return True
    if schalter in ("nein", "0", "false"):
        return False
    name = (modell or "").lower()
    return any(x in name for x in
               ["qwen3", "qwen3.5", "-reasoning", "ministral", "magistral"])

# Vision-fähige Modelle: für die Textprüfung nicht benötigt und
# können zusätzliche Ressourcen belegen.  Wird nur als Warnung angezeigt.
VISION_MODELLE_PATTERN = [
    "vision", "llava", "pixtral", "qwen-vl", "minicpm-v",
    "cogvlm", "internvl", "moondream", "phi-3-vision",
]


def setze_provider(provider_name: str, modell: str | None = None) -> ProviderConfig:
    """Aktiviert einen Provider ohne Programmabbruch (für die Oberfläche).

    Liest Adresse, Modell und Timeout bei jedem Aufruf neu aus der Umgebung:
      - <PROVIDER>_BASE_URL (LMSTUDIO_/OLLAMA_/BONSAI_BASE_URL)
      - KI_MODELL  – Modell-ID oder Teilstring (leer/auto = automatisch)
      - KI_TIMEOUT – Timeout in Sekunden
    Wirft ValueError bei unbekanntem Provider oder fehlendem API-Key.
    """
    global AKTIVER_PROVIDER, LMSTUDIO_BASE_URL, LMSTUDIO_API_KEY
    global LMSTUDIO_MODEL, API_TIMEOUT, BATCH_GROESSE

    provider_name = (provider_name or "lokal").strip().lower()
    if provider_name not in PROVIDER:
        raise ValueError(f"Unbekannter Provider '{provider_name}'. "
                         f"Verfügbar: {', '.join(PROVIDER)}")

    # Frische Kopie aus der Registry, damit Umgebungswerte (aus .env) greifen.
    original = _KI_PROVIDER[provider_name]
    cfg = _replace(original, base_url=original.api_base)

    api_key = os.environ.get(cfg.api_key_env, "").strip() if cfg.api_key_env else ""
    if not api_key:
        api_key = cfg.api_key_default
    if not api_key and not cfg.is_lokal:
        raise ValueError(f"Kein API-Key für Provider '{cfg.name}'. "
                         f"Umgebungsvariable {cfg.api_key_env} setzen.")

    gewuenscht = (modell if modell is not None
                  else os.environ.get("KI_MODELL", "")).strip()
    if cfg.is_lokal:
        cfg.model = gewuenscht or "auto"
    elif modell:  # KI_MODELL gilt nur lokal; Cloud-Modell nur explizit ändern
        cfg.model = modell.strip()

    timeout_env = os.environ.get("KI_TIMEOUT", "").strip()
    if timeout_env.isdigit():
        cfg.timeout = float(timeout_env)

    PROVIDER[provider_name] = cfg
    AKTIVER_PROVIDER = cfg
    LMSTUDIO_BASE_URL = cfg.base_url
    LMSTUDIO_API_KEY = api_key
    LMSTUDIO_MODEL = cfg.model
    API_TIMEOUT = cfg.timeout
    BATCH_GROESSE = cfg.batch_groesse
    return cfg


def aktiver_provider() -> ProviderConfig:
    """Aktuell aktiver Provider (immer aktuell, auch nach setze_provider)."""
    return AKTIVER_PROVIDER


def _aktiviere_provider(provider_name: str, verbose: bool = True):
    """Aktiviert einen Provider und setzt die globalen Variablen (CLI)."""
    try:
        cfg = setze_provider(provider_name)
    except ValueError as e:
        print(f"FEHLER: {e}")
        sys.exit(1)

    if verbose:
        print(f"  Provider: {cfg.name}")
        print(f"  API-URL:  {cfg.base_url}")
        if cfg.is_lokal:
            print(f"  Modus:    Lokal (Daten verlassen den Rechner nicht)")
            if _IST_APPLE_SILICON:
                print(f"  Hardware: Apple Silicon ({_SYSTEM_RAM_GB} GB Unified Memory)")
            else:
                print(f"  Hardware: {platform.machine()} ({_SYSTEM_RAM_GB} GB RAM)")
        else:
            print(f"  Modus:    Cloud (DSGVO-konform, Serverstandort DE)")
            print(f"  Modell:   {cfg.model}")

# Konfidenz-Schwelle: unter diesem Wert wird das Ergebnis NICHT als
# Beanstandung gewertet, sondern als „nicht sicher prüfbar"
KONFIDENZ_SCHWELLE = 75

# Maximale Textlänge pro Dokument (Zeichen) für den Kontext.
# Konservativ: ~3k Token pro Dokument, passend für 8k-Kontextfenster.
# Bei größerem Kontextfenster wird der Wert automatisch angepasst.
MAX_TEXT_LAENGE = 12000  # pro Dokument (SM + LM)

# Wartezeit nach einem API-Aufruf (Sekunden), damit LM Studio
# Ressourcen freigeben kann.  Zusätzlich wird vor jedem Aufruf
# aktiv geprüft, ob der Server wieder ansprechbar ist.
PAUSE_ZWISCHEN_AUFRUFEN = 2

# Timeout für API-Aufrufe (Sekunden) – RPi ist langsamer als MacBook
# Bei Streaming gilt der Timeout zwischen aufeinanderfolgenden Tokens,
# nicht für die gesamte Antwort.
API_TIMEOUT = 1800

# Anzahl Kriterien pro Batch-Aufruf (spart wiederholtes Senden
# des Dokumentkontexts an das lokale Modell).
# Niedrig halten (2), damit der Prompt inkl. Dokumentkontext innerhalb
# der Kontext-Fenster-Grenze bleibt (8 k–16 k Token).
BATCH_GROESSE = 2

# Anzahl Wiederholungsversuche bei API-Timeout.
MAX_RETRIES = 2

# Timeout für den Bereitschaftstest (kurzer Ping an die KI), in Sekunden.
# 300s: große Modelle (14B+) auf RPi brauchen ~2 Min. nur für Prompt-Verarbeitung.
HEALTH_CHECK_TIMEOUT = 300

# ---------------------------------------------------------------------------
# System-Prompt (wird bei jedem Aufruf vorangestellt)
# ---------------------------------------------------------------------------
from src.bewertung.ki_pruefanweisungen import (  # noqa: E402 – gemeinsam mit dem Skill
    KI_NICHT_PRUEFBAR,
    KI_PRUEF_PROMPTS,
    KIPruefErgebnis,
    SYSTEM_PROMPT,
    _baue_template_vars,
    _extrahiere_ewh_zeilen,
    _formatiere_ewh_vorverarbeitung,
)

SYSTEM_PROMPT_BATCH = """\
Du bist ein erfahrener Gutachter für Abiturklausuren am Beruflichen Gymnasium \
Technik, Schwerpunkt Informationstechnik (Niedersachsen). Du prüfst \
Abiturvorschläge (Schülermaterial + Lehrermaterial) gegen die amtlichen Kriterien.

WICHTIGE REGELN:
1. Melde NUR eindeutige, belegbare Verstöße. Formuliere sachlich und präzise.
2. Wenn du dir nicht sicher bist, ob ein Verstoß vorliegt, antworte mit \
   „keine Beanstandung erkennbar". Lieber ein Problem übersehen als einen \
   falschen Alarm auslösen.
3. Beziehe dich konkret auf Textstellen aus dem Material.
4. Du erhältst MEHRERE Prüfkriterien gleichzeitig. \
   Antworte mit einem JSON-ARRAY – ein Objekt pro Kriterium, in derselben \
   Reihenfolge wie die Kriterien im Prompt. Kein anderer Text davor/danach:
[
  {
    "kriterium_nr": "<Nummer>",
    "ergebnis": "beanstandung" | "keine_beanstandung" | "nicht_pruefbar",
    "konfidenz": <0-100>,
    "begruendung": "<kurze sachliche Begründung mit Textbelegen>",
    "fundstellen": ["<Zitat oder Verweis 1>"]
  },
  ...
]
5. Setze „konfidenz" nur auf >75, wenn du dir wirklich sicher bist.
6. Setze „ergebnis" auf „nicht_pruefbar", wenn der bereitgestellte Text \
   nicht ausreicht, um das Kriterium zu bewerten.

KONSISTENZ-REGELN (UNBEDINGT BEACHTEN):
7. ACHTUNG: Die Kriteriennummer (z.B. [1.3]) bezieht sich auf das \
   PRÜFKRITERIUM im Gutachten, NICHT auf eine Teilaufgabe der Klausur! \
   Verwechsle diese nicht. Lies die PRÜFANWEISUNG, nicht die Aufgabennummer.
8. Lies deine Begründung NOCHMALS, bevor du das Ergebnis setzt: \
   Wenn deine Begründung sagt, das Kriterium sei ERFÜLLT, MUSS das \
   Ergebnis „keine_beanstandung" lauten – und umgekehrt. \
   Begründung und Ergebnis dürfen sich NIEMALS widersprechen.
9. Wenn du feststellst, dass die nötigen Informationen nicht vorhanden \
   sind oder du das Kriterium nicht bewerten kannst, MUSS das Ergebnis \
   „nicht_pruefbar" sein – NICHT „keine_beanstandung" oder „beanstandung".
10. TABELLEN IM PDF: Der Text wurde aus PDF extrahiert. Tabellen können \
    fragmentiert erscheinen (Spalten als separate Textzeilen). Suche gezielt \
    nach Zahlenreihen und ordne sie den Spaltenüberschriften zu. \
    Bei EWH-Tabellen stehen typischerweise die Spalten: \
    Teilaufgabe | Erwartete Schülerleistung | AFB I | AFB II | AFB III | Σ \
    und am Ende eine Zeile „Gesamtsummen".
11. BEANSTANDUNGEN – AUFGABENBEZUG PFLICHT: Wenn du eine Beanstandung \
    meldest, MUSS die Begründung die konkret betroffene Aufgabe und \
    Teilaufgabe benennen (z.B. „Aufgabe 2, Teilaufgabe 2.1" oder \
    „Aufgabe 1, Teilaufgaben 1.2 und 1.4"). \
    Allgemeine Aussagen ohne Aufgabenbezug sind NICHT ausreichend.
12. DOKUMENTRAHMEN: Das Material wird durch die Prüfsoftware mit den \
    Trennzeichen „=== SCHÜLERMATERIAL (Aufgabenstellung) ===" und \
    „=== LEHRERMATERIAL (Erwartungshorizont / Lösung) ===" strukturiert. \
    Diese Zeilen sind KEINE Teile des Klausurinhalts – sie sind nur \
    Software-Markierungen. Das eigentliche Deckblatt, die Aufgaben und \
    der Erwartungshorizont beginnen jeweils NACH dem Trennzeichen.
"""

# Kriterien-Prompts (KI_PRUEF_PROMPTS) und KI_NICHT_PRUEFBAR: siehe
# src/bewertung/ki_pruefanweisungen.py


def _ist_kontextfenster_fehler(fehler_text: str) -> int | None:
    """Erkennt Kontextfenster-Überlauf-Fehler von LM Studio / llama.cpp.

    Gibt die verfügbare Kontextgröße (n_ctx) zurück, wenn erkannt, sonst None.
    """
    m = re.search(r"n_keep:\s*\d+\s*>=?\s*n_ctx:\s*(\d+)", fehler_text)
    if m:
        return int(m.group(1))
    return None


def _kuerze_text(text: str, max_len: int = MAX_TEXT_LAENGE) -> str:
    """Kürzt Text auf max_len Zeichen, ohne mitten im Wort abzuschneiden."""
    if len(text) <= max_len:
        return text
    # Am letzten Leerzeichen vor max_len abschneiden
    cut = text[:max_len].rfind(" ")
    if cut < max_len // 2:
        cut = max_len
    return text[:cut] + "\n[... Text gekürzt ...]"


def _baue_prompt(
    kriterium_nr: str,
    kriterium_text: str,
    kommentar: str,
    schueler_text: str,
    lehrer_text: str,
    max_text_laenge: int | None = None,
) -> str | None:
    """Baut den kriterien-spezifischen User-Prompt.
    Gibt None zurück, wenn das Kriterium nicht per KI prüfbar ist."""

    if kriterium_nr in KI_NICHT_PRUEFBAR:
        return None

    ml = max_text_laenge if max_text_laenge is not None else MAX_TEXT_LAENGE
    sm = _kuerze_text(schueler_text, ml)
    lm = _kuerze_text(lehrer_text, ml)

    # Gemeinsamer Kontext-Block
    material_block = (
        f"=== SCHÜLERMATERIAL (Aufgabenstellung) ===\n{sm}\n\n"
        f"=== LEHRERMATERIAL (Erwartungshorizont / Lösung) ===\n{lm}\n\n"
    )

    # Erweiterte Operatoren aus dem Lehrermaterial parsen und in die
    # AFB-Tabellen einfließen lassen, damit die KI bei X.5/X.4 auch die
    # schulinternen Operatoren akzeptiert bzw. korrekt prüft.
    erweiterte_ops = parse_erweiterte_operatoren(lehrer_text)
    kombinierte_ops = dict(OPERATOREN)
    for op, info in erweiterte_ops.items():
        kombinierte_ops[op] = info

    # Dynamische Platzhalter für Template-Prompts auflösen
    template_vars = _baue_template_vars(kombinierte_ops, erweiterte_ops, kommentar)

    # Für X.5: vorverarbeitete EWH-Tabelle injizieren
    if kriterium_nr == "X.5":
        _ewh_zeilen, _ewh_hinweis = _extrahiere_ewh_zeilen(lehrer_text)
        template_vars["ewh_vorverarbeitet"] = _formatiere_ewh_vorverarbeitung(
            _ewh_zeilen, _ewh_hinweis
        )
        if _ewh_hinweis and not _ewh_zeilen:
            print(f"  ⚠ [X.5] EWH-Tabelle nicht automatisch extrahierbar: "
                  f"{_ewh_hinweis}", flush=True)

    prompt_text = KI_PRUEF_PROMPTS.get(kriterium_nr)
    if prompt_text is None:
        # Generischer Fallback-Prompt für unbekannte Kriterien
        prompt_text = (
            f"Prüfe das folgende Kriterium:\n"
            f"[{kriterium_nr}] {kriterium_text}\n\n"
            f"Bisheriger Hinweis der automatischen Prüfung:\n{kommentar}\n\n"
            f"Melde NUR eindeutige Verstöße. Im Zweifel: keine Beanstandung."
        )
    else:
        # Template-Platzhalter auflösen
        prompt_text = prompt_text.format_map(template_vars)

    # Dokumente zuerst → System-Prompt + Dokumente bilden den gemeinsamen
    # Präfix aller Batches und werden vom KV-Cache ab Batch 2 wiederverwendet.
    return (
        f"{material_block}"
        f"PRÜFKRITERIUM [{kriterium_nr}]: {kriterium_text}\n"
        f"VORABCHECK-HINWEIS (regelbasiert): {kommentar}\n\n"
        f"PRÜFANWEISUNG:\n{prompt_text}\n"
    )


# ---------------------------------------------------------------------------
# LM Studio – Server- und Modell-Management
# ---------------------------------------------------------------------------

def _finde_lms_cli() -> str | None:
    """Findet die LM Studio CLI (lms / lms.exe, cross-platform)."""
    for p in LMS_CLI_PATHS:
        if not p:
            continue
        if os.path.isfile(p):
            # os.access(X_OK) ist auf Windows für .exe-Dateien nicht zuverlässig
            if _IST_WINDOWS or os.access(p, os.X_OK):
                return p
    # Letzte Chance via shutil.which
    return shutil.which("lms") or shutil.which("lms.exe")


def _lms_server_laeuft() -> bool:
    """Prüft ob der LM Studio Server erreichbar ist."""
    try:
        client = OpenAI(base_url=LMSTUDIO_BASE_URL, api_key=LMSTUDIO_API_KEY)
        client.models.list()
        return True
    except (openai.APIConnectionError, openai.APITimeoutError, openai.APIError) as e:
        log.warning("LM Studio Server nicht erreichbar: %s", e, exc_info=True)
        return False


def _starte_lmstudio_server(lms: str, verbose: bool = True) -> bool:
    """Startet den LM Studio Server über die CLI."""
    if verbose:
        print("  LM Studio Server starten ...")
    try:
        subprocess.run(
            [lms, "server", "start", "--port", "1234"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError) as e:
        log.warning("Fehler beim LM Studio Serverstart: %s", e, exc_info=True)
        if verbose:
            print(f"  Warnung beim Serverstart: {e}")
    # Warten bis der Server erreichbar ist
    for _ in range(20):
        time.sleep(2)
        if _lms_server_laeuft():
            if verbose:
                print("  Server läuft.")
            return True
    return False


def _lade_modell(lms: str, verbose: bool = True) -> str | None:
    """Lädt ein bevorzugtes Modell in LM Studio. Gibt den Modellnamen zurück."""
    # Verfügbare Modelle auflisten
    try:
        result = subprocess.run(
            [lms, "ls"], capture_output=True, text=True, timeout=15,
        )
        verfuegbar = result.stdout
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        log.warning("Fehler beim Auflisten verfügbarer Modelle (lms ls): %s", e, exc_info=True)
        return None

    for pref in BEVORZUGTE_MODELLE:
        if pref.lower() in verfuegbar.lower():
            if verbose:
                print(f"  Modell laden: {pref} ...")
            try:
                subprocess.run(
                    [lms, "load", pref, "--yes", "--context-length", "32768"],
                    capture_output=True, text=True, timeout=120,
                )
            except subprocess.TimeoutExpired:
                pass  # Laden kann dauern, wir prüfen danach
            # Kurz warten und prüfen ob es geladen ist
            for _ in range(30):
                time.sleep(3)
                try:
                    result = subprocess.run(
                        [lms, "ps"], capture_output=True, text=True, timeout=10,
                    )
                    if pref.lower() in result.stdout.lower():
                        if verbose:
                            print(f"  Modell geladen: {pref}")
                        return pref
                except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError, OSError):
                    log.debug("Poll-Fehler beim Warten auf Modell-Load (lms ps)")
                    pass
    return None


def _ermittle_kontextgroesse(verbose: bool = True, modell_name: str = "") -> int:
    """Ermittelt die Kontextgröße (n_ctx) des geladenen Modells.

    Versucht zunächst die LM Studio REST-API (GET /v1/models), dann
    die LM Studio CLI (lms ps), dann eine modellbasierte Lookup-Tabelle.
    Gibt den konservativsten bekannten Wert zurück (Standard: 8192).

    Reihenfolge: KI_KONTEXT aus .env → serverspezifische Abfrage
    (Ollama: /api/ps, llama.cpp/Bonsai: /props) → /v1/models → lms ps
    (nur LM Studio) → 8192.
    """
    default = 8192
    kontext_env = os.environ.get("KI_KONTEXT", "").strip()
    if kontext_env.isdigit() and int(kontext_env) >= 1000:
        if verbose:
            print(f"  Kontextfenster (KI_KONTEXT): {int(kontext_env)} Token")
        return int(kontext_env)

    server = getattr(AKTIVER_PROVIDER, "server", "lmstudio")
    if AKTIVER_PROVIDER.is_lokal and server != "lmstudio":
        n_ctx = _kontext_vom_server(server, modell_name)
        if n_ctx:
            if verbose:
                print(f"  Kontextfenster ({server}): {n_ctx} Token")
            if server == "ollama" and n_ctx < 16384:
                print(f"  ⚠️  Ollama läuft mit nur {n_ctx} Token Kontext – lange "
                      f"Klausuren werden abgeschnitten. Ollama mit "
                      f"OLLAMA_CONTEXT_LENGTH=32768 neu starten.")
            return n_ctx

    try:
        import urllib.request, urllib.error
        url = LMSTUDIO_BASE_URL.rstrip("/") + "/models"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {LMSTUDIO_API_KEY}")

        # Lambda für urllib-Aufruf mit Retry
        def _fetch_models():
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())

        data = with_retry(
            _fetch_models,
            attempts=2,
            base_delay=1.0,
            exc_types=(urllib.error.URLError, socket.timeout, TimeoutError),
            beschreibung="Kontextgröße via API"
        )
        # LM Studio kann context_length in den Modell-Metadaten liefern
        for m in data.get("data", []):
            ctx = (m.get("context_length")
                   or m.get("max_model_len")
                   or (m.get("parameters", {}) or {}).get("context_length"))
            if ctx and int(ctx) > 0:
                if verbose:
                    print(f"  Kontextfenster (API): {int(ctx)} Token")
                return int(ctx)
    except (urllib.error.URLError, socket.timeout, TimeoutError, json.JSONDecodeError, ValueError) as e:
        log.debug("Kontextgröße via API nicht ermittelbar: %s", e, exc_info=True)
        pass

    # Fallback 1: lms ps (gibt tatsächlich geladene Kontextgröße aus).
    # Nur für LM Studio – sonst würde ein parallel laufendes LM Studio die
    # Kontextgröße von Ollama/Bonsai vortäuschen.
    lms = _finde_lms_cli() if server == "lmstudio" else None
    if lms:
        try:
            result = subprocess.run(
                [lms, "ps"], capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.splitlines()[1:]:  # Header überspringen
                parts = line.split()
                # Suche erste ganze Zahl im plausiblen Kontextbereich (1k–200k)
                for p in parts:
                    try:
                        val = int(p)
                        if 1000 <= val <= 200000:
                            if verbose:
                                print(f"  Kontextfenster (lms ps): {val} Token")
                            return val
                    except ValueError:
                        continue
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
            log.debug("Kontextgröße via lms ps nicht ermittelbar: %s", e, exc_info=True)
            pass

    if verbose:
        print(f"  Kontextfenster: unbekannt – verwende Annahme {default} Token "
              f"(festlegen mit KI_KONTEXT in .env)")
    return default


def _server_wurzel() -> str:
    """Basis-Adresse des aktiven Servers ohne /v1."""
    url = LMSTUDIO_BASE_URL.rstrip("/")
    return url[:-3] if url.endswith("/v1") else url


def _hole_json(url: str, timeout: float = 5.0):
    import urllib.request
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {LMSTUDIO_API_KEY}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _kontext_vom_server(server: str, modell_name: str = "") -> int:
    """Kontextgröße direkt beim Server erfragen (0 = unbekannt).

    Ollama: GET /api/ps liefert context_length je geladenem Modell
    (erst nach dem ersten Aufruf geladen – der Bereitschaftstest erledigt das).
    llama.cpp-Server (auch Bonsai-Laufzeit): GET /props → n_ctx.
    """
    import urllib.error
    wurzel = _server_wurzel()
    try:
        if server == "ollama":
            daten = _hole_json(wurzel + "/api/ps")
            modelle = daten.get("models", []) or []
            name = (modell_name or "").lower()
            passende = [m for m in modelle
                        if name and name in str(m.get("name", "")).lower()] or modelle
            for m in passende:
                ctx = m.get("context_length")
                if ctx and int(ctx) > 0:
                    return int(ctx)
        else:
            daten = _hole_json(wurzel + "/props")
            dgs = daten.get("default_generation_settings", {}) or {}
            ctx = dgs.get("n_ctx") or daten.get("n_ctx")
            if ctx and int(ctx) > 0:
                return int(ctx)
    except (urllib.error.URLError, socket.timeout, TimeoutError,
            json.JSONDecodeError, ValueError, OSError) as e:
        log.debug("Kontextgröße via %s nicht ermittelbar: %s", server, e)
    return 0


def _stelle_openai_server_bereit(verbose: bool = True) -> str:
    """Bereitstellung für Ollama und andere OpenAI-kompatible lokale Server.

    Diese Server laden Modelle selbst (Ollama bei Bedarf, llama-server/Bonsai
    beim Start). Hier wird nur geprüft, ob der Server antwortet, und ein Modell
    aus /v1/models gewählt: KI_MODELL (Teilstring) → BEVORZUGTE_MODELLE →
    erstes gelistetes. Wirft RuntimeError statt sys.exit (Oberfläche).
    """
    cfg = AKTIVER_PROVIDER
    try:
        client = OpenAI(base_url=LMSTUDIO_BASE_URL, api_key=LMSTUDIO_API_KEY,
                        timeout=15.0, max_retries=0)
        ids = [m.id for m in client.models.list().data]
    except (openai.APIConnectionError, openai.APITimeoutError, openai.APIError) as e:
        hilfe = {
            "ollama": "Ollama starten: OLLAMA_CONTEXT_LENGTH=32768 ollama serve",
            "openai": "Bonsai-Server starten und Adresse in .env unter BONSAI_BASE_URL eintragen",
        }.get(cfg.server, "Server starten")
        raise RuntimeError(f"{cfg.name} unter {LMSTUDIO_BASE_URL} nicht erreichbar ({e}). "
                           f"{hilfe}.") from e

    if not ids:
        raise RuntimeError(f"{cfg.name} meldet keine Modelle. "
                           + ("Modell holen: ollama pull <modell>" if cfg.server == "ollama"
                              else "Server mit Modell starten."))

    gewuenscht = (LMSTUDIO_MODEL or "").strip()
    modell = ""
    if gewuenscht and gewuenscht != "auto":
        modell = next((i for i in ids if i == gewuenscht), "") or \
                 next((i for i in ids if gewuenscht.lower() in i.lower()), "")
        if not modell:
            raise RuntimeError(f"Modell '{gewuenscht}' ist bei {cfg.name} nicht vorhanden. "
                               f"Verfügbar: {', '.join(ids)}")
    else:
        for pref in BEVORZUGTE_MODELLE:
            modell = next((i for i in ids if pref.lower() in i.lower()), "")
            if modell:
                break
        modell = modell or ids[0]

    if verbose:
        print(f"  {cfg.name}: {len(ids)} Modell(e) verfügbar")
        print(f"  Gewähltes Modell: {modell}")
        if _ist_kleines_modell(modell):
            print(f"  ⚠️  WARNUNG: '{modell}' ist vermutlich ein kleines Modell (< 12B).")
    return modell


def stelle_lokales_modell_bereit(verbose: bool = True) -> str:
    """Wählt je nach Server-Art die passende Bereitstellung (LM Studio / Ollama / Bonsai)."""
    if getattr(AKTIVER_PROVIDER, "server", "lmstudio") == "lmstudio":
        return stelle_lmstudio_bereit(verbose)
    return _stelle_openai_server_bereit(verbose)


def liste_modelle() -> list[str]:
    """Modelle, die der aktive Server meldet (für die Auswahl in der Oberfläche)."""
    try:
        client = OpenAI(base_url=LMSTUDIO_BASE_URL, api_key=LMSTUDIO_API_KEY,
                        timeout=5.0, max_retries=0)
        return [m.id for m in client.models.list().data]
    except Exception as e:  # Oberfläche zeigt dann Hinweis
        log.debug("Modellliste nicht abrufbar: %s", e)
        return []


def _berechne_max_text_laenge(n_ctx: int, batch_groesse: int = 1, modell: str = "") -> int:
    """Berechnet eine sichere MAX_TEXT_LAENGE basierend auf Kontextgröße.

    Reserviert Platz für: System-Prompt (~700 Token), Kriterien-Prompts
    (~300 Token pro Kriterium), Ausgabe-Tokens (512 pro Kriterium) und
    einen Sicherheitspuffer (10%).  Der Rest wird gleichmäßig auf die
    zwei Dokumenttexte (SM + LM) aufgeteilt.

    Returns: Maximale Zeichenzahl pro Dokument.
    """
    overhead_system = 700
    overhead_kriterien = 300 * batch_groesse
    # Qwen3 und Ministral-reasoning mit Assistant-Prefill (<think></think>):
    # kein Thinking, nur ~400-1500 JSON-Tokens
    # Andere Thinking-Modelle (Gemma-4 etc.): 3000 für Reasoning + JSON
    if _ist_thinking_modell(modell):
        output_tokens = 1500 * batch_groesse
    else:
        output_tokens = 3000 * batch_groesse
    puffer = int(n_ctx * 0.10)

    verfuegbar = n_ctx - overhead_system - overhead_kriterien - output_tokens - puffer
    # 2 Dokumente, ~3.5 Zeichen pro Token (Deutsch)
    pro_dokument = max(2000, int(verfuegbar / 2 * 3.5))
    return pro_dokument


def _ist_modell_geladen(modell_name: str) -> bool:
    """Prüft, ob ein bestimmtes Modell in LM Studio geladen ist.
    Unterstützt Exakt- und Teilstring-Vergleich (case-insensitive).
    """
    if not modell_name or modell_name == "auto":
        return False
    try:
        client = OpenAI(base_url=LMSTUDIO_BASE_URL, api_key=LMSTUDIO_API_KEY)
        models = client.models.list()
        modell_lower = modell_name.lower()
        return any(
            m.id == modell_name or modell_lower in m.id.lower()
            for m in models.data
        )
    except (openai.APIConnectionError, openai.APITimeoutError, openai.APIError) as e:
        log.debug("Modell-Status-Prüfung fehlgeschlagen: %s", e, exc_info=True)
        return False


def _erkenne_geladenes_modell(preferiert: str = "") -> str:
    """Erkennt ein geladenes Modell über die API.

    Wenn *preferiert* gesetzt und geladen ist, wird dieses zurückgegeben.
    """
    try:
        client = OpenAI(base_url=LMSTUDIO_BASE_URL, api_key=LMSTUDIO_API_KEY)
        models = client.models.list()
        if models.data:
            if preferiert and preferiert != "auto":
                preferiert_lower = preferiert.lower()
                for m in models.data:
                    if m.id == preferiert or preferiert_lower in m.id.lower():
                        return m.id
            return models.data[0].id
    except (openai.APIConnectionError, openai.APITimeoutError, openai.APIError) as e:
        log.debug("Modell-Erkennung fehlgeschlagen: %s", e, exc_info=True)
        pass
    return "auto"


def stelle_lmstudio_bereit(verbose: bool = True) -> str:
    """Stellt sicher, dass LM Studio mit einem Modell bereit ist.

    1. Prüft ob Server läuft → falls nein, startet ihn.
    2. Prüft ob ein Modell geladen ist → falls nein, lädt eines.
    3. Gibt den Modellnamen zurück.
    """
    lms = _finde_lms_cli()

    # Server prüfen / starten
    if _lms_server_laeuft():
        if verbose:
            print("  LM Studio Server: läuft bereits.")
    else:
        if not lms:
            print("FEHLER: LM Studio Server nicht erreichbar und CLI (lms) nicht gefunden.")
            print("  Bitte LM Studio starten und Server aktivieren.")
            print(f"  Erwartete CLI-Pfade: {LMS_CLI_PATHS}")
            sys.exit(1)
        if not _starte_lmstudio_server(lms, verbose):
            print("FEHLER: LM Studio Server konnte nicht gestartet werden.")
            print("  Bitte LM Studio manuell starten (GUI oder: lms server start)")
            sys.exit(1)

    # Modell prüfen / laden
    gewuenschtes_modell = (LMSTUDIO_MODEL or "").strip()
    if gewuenschtes_modell and gewuenschtes_modell != "auto":
        if _ist_modell_geladen(gewuenschtes_modell):
            modell = _erkenne_geladenes_modell(gewuenschtes_modell)  # Teilstring → echte ID
        else:
            if not lms:
                print(f"FEHLER: Gewünschtes Modell '{gewuenschtes_modell}' ist nicht geladen")
                print("  und LM Studio CLI (lms) ist nicht verfügbar, um es zu laden.")
                sys.exit(1)
            if verbose:
                print(f"  Gewünschtes Modell laden: {gewuenschtes_modell} ...")
            try:
                subprocess.run(
                    [lms, "load", gewuenschtes_modell, "--yes", "--context-length", "32768"],
                    capture_output=True, text=True, timeout=240,
                )
            except Exception as e:
                print(f"FEHLER: Modell '{gewuenschtes_modell}' konnte nicht geladen werden: {e}")
                sys.exit(1)

            # kurz warten, bis API das Modell tatsächlich meldet
            for _ in range(30):
                time.sleep(2)
                if _ist_modell_geladen(gewuenschtes_modell):
                    break
            else:
                print(f"FEHLER: Modell '{gewuenschtes_modell}' wurde nicht aktiv.")
                sys.exit(1)
            modell = _erkenne_geladenes_modell(gewuenschtes_modell)  # Teilstring → echte ID
    else:
        modell = _erkenne_geladenes_modell()

    if modell and modell != "auto":
        if verbose:
            print(f"  Geladenes Modell: {modell}")
            if _IST_APPLE_SILICON:
                print(f"  Hardware: Apple Silicon ({_SYSTEM_RAM_GB} GB Unified Memory)")
            # Warnung bei kleinen Modellen
            modell_lower = modell.lower()
            if _ist_kleines_modell(modell):
                print(f"  ⚠️  WARNUNG: '{modell}' ist ein kleines Modell.")
                print(f"     Modelle < 12B liefern bei Tabellen-Interpretation")
                print(f"     und logischem Schließen deutlich schlechtere Ergebnisse.")
                if _IST_APPLE_SILICON and _SYSTEM_RAM_GB >= 24:
                    print(f"     Mit {_SYSTEM_RAM_GB} GB Unified Memory können Sie")
                    print(f"     deutlich größere Modelle laden (bis ~20B Q8).")
                print(f"     Empfehlung: Modell mit ≥ 12B Parametern verwenden.")
            # Warnung bei Vision-Modellen (nicht benötigt für Textprüfung)
            if any(p in modell_lower for p in VISION_MODELLE_PATTERN):
                print(f"  ⚠️  WARNUNG: '{modell}' ist ein Vision-Modell.")
                print(f"     Vision-Fähigkeiten werden nicht benötigt und können")
                print(f"     Ressourcen belegen. Empfehlung: Reines Textmodell")
                print(f"     (z.B. GPT-OSS-20B, Gemma-3-27B, Qwen2.5-14B-Instruct).")
        return modell

    # Kein Modell geladen → versuche eines zu laden
    if verbose:
        print("  Kein Modell geladen – versuche automatisch zu laden ...")
    if lms:
        modell = _lade_modell(lms, verbose)
        if modell:
            return modell

    print("FEHLER: Kein Modell in LM Studio geladen.")
    print("  Bitte ein Modell in LM Studio laden (GUI oder: lms load <modell>)")
    sys.exit(1)


def _pruefe_ki_bereitschaft(
    client: OpenAI, modell: str, verbose: bool = True
) -> bool:
    """Sendet eine kurze Testanfrage, um sicherzustellen, dass das Modell
    tatsächlich Anfragen bearbeitet (nicht nur geladen, sondern antwortbereit).

    Gibt True zurück, wenn das Modell innerhalb von HEALTH_CHECK_TIMEOUT
    antwortet, sonst False.
    """
    if verbose:
        print("  Bereitschaftstest ...", end=" ", flush=True)
    try:
        # Bei Reasoning-Modellen Prefill-Trick anwenden: überspringt Think-Tokens
        # und liefert sofort das eigentliche Token → deutlich schnellerer Ping.
        hc_messages = [{"role": "user", "content": "Antworte mit genau einem Wort: OK"}]
        if _ist_thinking_modell(modell):
            hc_messages.append({"role": "assistant", "content": "<think>\n\n</think>\n\n"})
        response = client.chat.completions.create(
            model=modell,
            messages=hc_messages,
            max_tokens=5,
            temperature=0.0,
            stream=False,
            timeout=float(HEALTH_CHECK_TIMEOUT),
        )
        if response.choices:
            if verbose:
                print("OK ✓")
            return True
    except Exception as e:
        if verbose:
            print(f"FEHLGESCHLAGEN")
            print(f"    → {e}")
            print()
            print("  DIAGNOSE-HINWEISE:")
            print("    • Ist das Modell wirklich vollständig geladen?")
            print("      (LM Studio GUI → Modell-Status prüfen)")
            print("    • Hat das System genug RAM für das Modell?")
            print("      (z.B. 20B-Modell benötigt ~12–16 GB RAM)")
            print("    • Läuft ein anderer Prozess, der GPU/RAM blockiert?")
            print("    • Versuche ein kleineres Modell zu laden.")
    return False


# ---------------------------------------------------------------------------
# LM Studio API-Aufruf
# ---------------------------------------------------------------------------

def _erstelle_client() -> OpenAI:
    """Erstellt den OpenAI-Client für LM Studio.

    - max_retries=0:  Wir steuern Retries selbst; die SDK-internen
      Wiederholungen (Standard: 2) verursachen sonst versteckte
      Wartezeiten bei LM-Studio-Busy-Situationen.
    - timeout:  Einfacher Float – httpx.Timeout kann je nach SDK-Version
      für Streaming-Requests anders interpretiert werden.
    """
    return OpenAI(
        base_url=LMSTUDIO_BASE_URL,
        api_key=LMSTUDIO_API_KEY,
        timeout=float(API_TIMEOUT),
        max_retries=0,
    )


def _warte_auf_bereitschaft(client: OpenAI, max_warte: int = 60) -> bool:
    """Pollt den LM-Studio-Server bis er eine Antwort liefert.

    Nutzt den leichtgewichtigen /v1/models-Endpunkt.
    Gibt True zurück, sobald der Server antwortet, False bei Timeout.
    """
    for _ in range(max_warte * 2):   # alle 0.5 s pollen
        try:
            client.models.list()
            return True
        except Exception:
            time.sleep(0.5)
    return False


def _strip_think_tags(text: str) -> str:
    """Entfernt <think>...</think>- und <thinking>...</thinking>-Blöcke aus dem Text.

    Wird als Fallback eingesetzt, wenn das Modell trotz Prefill-Trick noch
    Thinking-Artefakte in den Content schreibt.  Verhindert, dass der
    JSON-Regex auf Fragment-Objekte innerhalb des Thinking-Blocks trifft.

    Bereinigt zusätzlich modellspezifische Sonder-Token:
    - gpt-oss-20b: <|channel|>final <|constrain|>JSON<|message|>
    """
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text, flags=re.IGNORECASE)
    # LM-Studio / gpt-oss channel-token-Prefix entfernen:
    # Beispiel: "<|channel|>final <|constrain|>JSON<|message|>{...}"
    text = re.sub(r"(<\|[^|]+\|>[^\{<]*)+", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Retry-Helper
# ---------------------------------------------------------------------------

_TRANSIENT_KI_EXC = (openai.APITimeoutError, openai.APIConnectionError, openai.APIError)


def with_retry(fn, *, attempts: int = 1 + MAX_RETRIES,
               base_delay: float = 5.0,
               exc_types: tuple = _TRANSIENT_KI_EXC,
               beschreibung: str = ""):
    """Wrapper für transiente Fehler mit exponentiellem Backoff.

    Args:
        fn: Callable ohne Argumente (Lambda/Closure mit gebundenen Parametern)
        attempts: Maximale Anzahl Versuche (Standard: 1 + MAX_RETRIES)
        base_delay: Basis-Wartezeit in Sekunden (Standard: 5.0)
        exc_types: Tuple der zu wiederholenden Exception-Typen
        beschreibung: Kontext-String für Logging

    Returns:
        Rückgabewert von fn()

    Raises:
        Die letzte Exception, wenn alle Versuche erschöpft sind
    """
    for versuch in range(attempts):
        try:
            return fn()
        except exc_types as e:
            if versuch >= attempts - 1:
                log.warning("Retry erschöpft (%s): %s", beschreibung, e, exc_info=True)
                raise
            warte = base_delay * (versuch + 1)
            log.warning("Retry %d/%d nach %s (%s) → warte %.1fs",
                        versuch + 1, attempts, type(e).__name__, beschreibung, warte)
            time.sleep(warte)


def _rufe_ki_auf(client: OpenAI, prompt: str, modell: str = "auto") -> dict:
    """Sendet einen Prompt an LM Studio und parst die JSON-Antwort.
    Gibt ein Dict mit ergebnis, konfidenz, begruendung, fundstellen zurück.

    Verwendet Streaming, damit der Timeout nur zwischen aufeinanderfolgenden
    Tokens gilt – nicht für die gesamte Antwort.
    Wiederholt bei Timeout bis zu MAX_RETRIES Mal."""

    # Thinking-Kontrolle für Qwen3: Assistant-Prefill mit leerem <think></think>.
    # Das Modell sieht die Thinking-Phase als bereits abgeschlossen an und
    # generiert direkt JSON-Content. enable_thinking=False wird ignoriert.
    ist_thinking = _ist_thinking_modell(modell)
    ki_max_tokens = 1500 if ist_thinking else 3000
    ki_messages_basis = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    if ist_thinking:
        ki_messages_basis.append(
            {"role": "assistant", "content": "<think>\n\n</think>\n\n"}
        )

    # Lambda für API-Call (wird von with_retry gewrappt)
    def _stream_call():
        _warte_auf_bereitschaft(client)
        stream = client.with_options(timeout=float(API_TIMEOUT)).chat.completions.create(
            model=modell,
            messages=ki_messages_basis,
            temperature=0.1,
            max_tokens=ki_max_tokens,
            stream=True,
        )
        antwort_text = ""
        chunk_count = 0
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                antwort_text += chunk.choices[0].delta.content
                chunk_count += 1
                if chunk_count % 20 == 0:
                    print(".", end="", flush=True)
        if chunk_count >= 20:
            print(flush=True)
        return antwort_text.strip()

    try:
        antwort_text = with_retry(_stream_call, beschreibung=f"KI-Aufruf (single, {modell})")
    except _TRANSIENT_KI_EXC as e:
        # Retry erschöpft oder nicht-transient → prüfe Kontextfenster
        letzter_fehler = str(e)
        n_ctx = _ist_kontextfenster_fehler(letzter_fehler)
        if n_ctx:
            return {
                "ergebnis": "nicht_pruefbar",
                "konfidenz": 0,
                "begruendung": (
                    f"Prompt zu lang für Kontextfenster "
                    f"(n_ctx={n_ctx}). Modell mit größerem "
                    f"Kontextfenster laden oder Text kürzen."
                ),
                "fundstellen": [],
            }
        return {
            "ergebnis": "nicht_pruefbar",
            "konfidenz": 0,
            "begruendung": f"API-Fehler nach {1 + MAX_RETRIES} Versuchen: {letzter_fehler}",
            "fundstellen": [],
        }

    # antwort_text ist bereits gesetzt
    # Thinking-Artefakte (<think>...</think>) entfernen – Fallback für Modelle,
    # bei denen der Prefill-Trick nicht vollständig greift.
    antwort_text = _strip_think_tags(antwort_text)

    # JSON aus der Antwort extrahieren (auch wenn drumherum Text steht)
    json_match = re.search(r"\{[\s\S]*\}", antwort_text)
    if not json_match:
        return {
            "ergebnis": "nicht_pruefbar",
            "konfidenz": 0,
            "begruendung": f"KI-Antwort war kein gültiges JSON: {antwort_text[:200]}",
            "fundstellen": [],
        }

    try:
        daten = json.loads(json_match.group())
    except json.JSONDecodeError:
        return {
            "ergebnis": "nicht_pruefbar",
            "konfidenz": 0,
            "begruendung": f"JSON-Parse-Fehler: {antwort_text[:200]}",
            "fundstellen": [],
        }

    # Pflichtfelder sicherstellen
    return {
        "ergebnis": daten.get("ergebnis", "nicht_pruefbar"),
        "konfidenz": int(daten.get("konfidenz", 0)),
        "begruendung": str(daten.get("begruendung", "")),
        "fundstellen": list(daten.get("fundstellen", [])),
    }


def _baue_batch_prompt(
    kriterien: list[tuple[str, str, str]],
    schueler_text: str,
    lehrer_text: str,
    max_text_laenge: int | None = None,
) -> str:
    """Baut einen kombinierten Prompt für mehrere Kriterien.

    kriterien: Liste von (nr, text, kommentar)-Tupeln.
    Gibt einen einzelnen User-Prompt zurück, der alle Kriterien enthält,
    aber den Dokumentkontext nur einmal sendet.
    """
    ml = max_text_laenge if max_text_laenge is not None else MAX_TEXT_LAENGE
    sm = _kuerze_text(schueler_text, ml)
    lm = _kuerze_text(lehrer_text, ml)

    erweiterte_ops = parse_erweiterte_operatoren(lehrer_text)
    kombinierte_ops = dict(OPERATOREN)
    for op, info in erweiterte_ops.items():
        kombinierte_ops[op] = info

    template_vars = _baue_template_vars(kombinierte_ops, erweiterte_ops, "")

    teile = []
    for nr, text, kommentar in kriterien:
        template_vars["kommentar"] = kommentar
        # Für X.5: vorverarbeitete EWH-Tabelle injizieren
        if nr == "X.5":
            _ewh_zeilen, _ewh_hinweis = _extrahiere_ewh_zeilen(lehrer_text)
            template_vars["ewh_vorverarbeitet"] = _formatiere_ewh_vorverarbeitung(
                _ewh_zeilen, _ewh_hinweis
            )
            if _ewh_hinweis and not _ewh_zeilen:
                print(f"  ⚠ [X.5] EWH-Tabelle nicht automatisch extrahierbar: "
                      f"{_ewh_hinweis}", flush=True)
        else:
            template_vars["ewh_vorverarbeitet"] = ""
        prompt_text = KI_PRUEF_PROMPTS.get(nr)
        if prompt_text is None:
            prompt_text = (
                f"Prüfe das folgende Kriterium:\n"
                f"[{nr}] {text}\n"
                f"Bisheriger Hinweis: {kommentar}\n"
                f"Melde NUR eindeutige Verstöße."
            )
        else:
            prompt_text = prompt_text.format_map(template_vars)
        teile.append(
            f"--- KRITERIUM [{nr}]: {text} ---\n"
            f"Vorabcheck-Hinweis: {kommentar}\n\n"
            f"{prompt_text}"
        )

    return (
        f"Prüfe die folgenden {len(kriterien)} Kriterien NACHEINANDER.\n"
        f"Antworte mit einem JSON-Array (ein Objekt pro Kriterium, "
        f"in derselben Reihenfolge).\n\n"
        + "\n\n".join(teile) + "\n\n"
        f"=== SCHÜLERMATERIAL (Aufgabenstellung) ===\n{sm}\n\n"
        f"=== LEHRERMATERIAL (Erwartungshorizont / Lösung) ===\n{lm}\n"
    )


_LEER_ANTWORT = {
    "ergebnis": "nicht_pruefbar",
    "konfidenz": 0,
    "begruendung": "",
    "fundstellen": [],
}


def _fallback_einzelabfragen(
    client: OpenAI,
    kriterien: list[tuple[str, str, str]],
    schueler_text: str,
    lehrer_text: str,
    modell: str = "auto",
    max_text_laenge: int | None = None,
) -> list[dict]:
    """Fragt jedes Kriterium einzeln ab (Fallback bei Batch-Timeout)."""
    ergebnisse = []
    for nr, text, kommentar in kriterien:
        prompt = _baue_prompt(nr, text, kommentar, schueler_text, lehrer_text,
                              max_text_laenge=max_text_laenge)
        if prompt is None:
            ergebnisse.append({**_LEER_ANTWORT,
                               "begruendung": "Kein Prompt definiert."})
        else:
            ergebnisse.append(_rufe_ki_auf(client, prompt, modell))
        time.sleep(PAUSE_ZWISCHEN_AUFRUFEN)
    return ergebnisse


def _rufe_ki_batch_auf(
    client: OpenAI,
    kriterien: list[tuple[str, str, str]],
    schueler_text: str,
    lehrer_text: str,
    modell: str = "auto",
    max_text_laenge: int | None = None,
) -> list[dict]:
    """Sendet mehrere Kriterien in einem einzelnen API-Aufruf.

    Gibt eine Liste von Ergebnis-Dicts zurück (ein Dict pro Kriterium,
    in derselben Reihenfolge).  Bei Fehlern wird für jedes Kriterium
    ein „nicht_pruefbar"-Eintrag zurückgegeben.

    Retry-Strategie:
      1. Versuch: Batch-Aufruf
      2. Bei Timeout: nochmal Batch
      3. Letzter Fallback: jedes Kriterium einzeln anfragen
    """
    prompt = _baue_batch_prompt(kriterien, schueler_text, lehrer_text,
                                max_text_laenge=max_text_laenge)
    n = len(kriterien)

    # Thinking-Kontrolle für Qwen3: Assistant-Prefill mit leerem <think></think>.
    # Das Modell sieht die Thinking-Phase als bereits abgeschlossen an und
    # generiert direkt JSON-Content. enable_thinking=False wird ignoriert.
    ist_thinking = _ist_thinking_modell(modell)
    ki_max_tokens = 1500 * n if ist_thinking else 3000 * n
    ki_messages_basis = [
        {"role": "system", "content": SYSTEM_PROMPT_BATCH},
        {"role": "user", "content": prompt},
    ]
    if ist_thinking:
        ki_messages_basis.append(
            {"role": "assistant", "content": "<think>\n\n</think>\n\n"}
        )

    # Lambda für Batch-API-Call
    def _stream_batch_call():
        _warte_auf_bereitschaft(client)
        stream = client.with_options(timeout=float(API_TIMEOUT)).chat.completions.create(
            model=modell,
            messages=ki_messages_basis,
            temperature=0.1,
            max_tokens=ki_max_tokens,
            stream=True,
        )
        antwort_text = ""
        chunk_count = 0
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                antwort_text += chunk.choices[0].delta.content
                chunk_count += 1
                if chunk_count % 20 == 0:
                    print(".", end="", flush=True)
        if chunk_count >= 20:
            print(flush=True)
        return antwort_text.strip()

    try:
        antwort_text = with_retry(_stream_batch_call, beschreibung=f"KI-Aufruf (batch, {n} Kriterien, {modell})")
    except _TRANSIENT_KI_EXC as e:
        letzter_fehler = str(e)
        # Kontextfenster-Überlauf: sofort auf Einzelabfragen mit reduzierter Textlänge
        n_ctx = _ist_kontextfenster_fehler(letzter_fehler)
        if n_ctx:
            kontext_reduziert = max(2000, int(n_ctx * 4 * 0.3))
            print(f"      ⚠ Kontextfenster zu klein (n_ctx={n_ctx})."
                  f" Textlänge auf {kontext_reduziert} Zeichen reduziert.",
                  flush=True)
            print(f"      ↻ Fallback auf Einzelabfragen mit gekürztem Text",
                  flush=True)
            return _fallback_einzelabfragen(
                client, kriterien, schueler_text, lehrer_text, modell,
                max_text_laenge=kontext_reduziert,
            )
        # Retry erschöpft → Fallback auf Einzelabfragen
        print(f"      ↻ Batch fehlgeschlagen – Fallback auf Einzelabfragen",
              flush=True)
        return _fallback_einzelabfragen(
            client, kriterien, schueler_text, lehrer_text, modell,
        )

    # JSON-Array aus der Antwort extrahieren
    # Thinking-Artefakte entfernen – Fallback für Modelle, bei denen der
    # Prefill-Trick nicht vollständig greift.
    antwort_text = _strip_think_tags(antwort_text)
    json_match = re.search(r"\[[\s\S]*\]", antwort_text)
    if json_match:
        try:
            daten = json.loads(json_match.group())
            if isinstance(daten, list) and len(daten) >= n:
                return [
                    {
                        "ergebnis": d.get("ergebnis", "nicht_pruefbar"),
                        "konfidenz": int(d.get("konfidenz", 0)),
                        "begruendung": str(d.get("begruendung", "")),
                        "fundstellen": list(d.get("fundstellen", [])),
                    }
                    for d in daten[:n]
                ]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    # Fallback: versuche einzelne JSON-Objekte zu finden
    objekte = list(re.finditer(r"\{[^{}]*\}", antwort_text))
    if len(objekte) >= n:
        ergebnisse = []
        for m in objekte[:n]:
            try:
                d = json.loads(m.group())
                ergebnisse.append({
                    "ergebnis": d.get("ergebnis", "nicht_pruefbar"),
                    "konfidenz": int(d.get("konfidenz", 0)),
                    "begruendung": str(d.get("begruendung", "")),
                    "fundstellen": list(d.get("fundstellen", [])),
                })
            except (json.JSONDecodeError, TypeError, ValueError):
                ergebnisse.append({
                    **_LEER_ANTWORT,
                    "begruendung": f"JSON-Parse-Fehler: {m.group()[:100]}",
                })
        return ergebnisse

    # Komplett-Fallback
    return [
        {**_LEER_ANTWORT,
         "begruendung": f"Batch-Antwort nicht parsbar ({len(objekte)}/{n} "
                        f"Objekte): {antwort_text[:200]}"}
        for _ in kriterien
    ]


# ---------------------------------------------------------------------------
# KI-Prüflauf
# ---------------------------------------------------------------------------

from src.bewertung.ki_bericht import (  # noqa: E402 – gemeinsam mit dem Skill
    KombinierterPruefpunkt,
    erstelle_kombinierte_liste,
)


def _schreibe_hinweisliste_ki(
    schueler_pfad: str,
    lehrer_pfad: str,
    ki_ergebnisse: list,
    output_dir: str,
    basis: str,
    modell_suffix: str,
    modell: str | None,
) -> None:
    """Hinweisliste (XLSX + CSV) aus Regelprüfung und KI-Beanstandungen.

    Ein Dateiname je Modell – so lassen sich die Listen verschiedener
    Modelle direkt vergleichen. KI-Hinweise sind gelb markiert."""
    try:
        from src.bewertung.hinweisliste import (
            hinweisblock_fuer_vorschlag, schreibe_hinweisliste,
        )
        block = hinweisblock_fuer_vorschlag(
            schueler_pfad, lehrer_pfad, ki_ergebnisse=ki_ergebnisse,
            modell=_kurzer_modellname(modell) if modell else "")
        xlsx, csv_pfad = schreibe_hinweisliste(
            [block], os.path.join(output_dir, f"Hinweise_{basis}{modell_suffix}"))
        print(f"Hinweisliste gespeichert: {xlsx}")
        print(f"                          {csv_pfad}")
    except Exception as e:  # Hinweisliste ist Zusatz – KI-Bericht bleibt gültig
        print(f"WARNUNG: Hinweisliste nicht erstellt: {e}")


def fuehre_ki_pruefung_durch(
    schueler_pfad: str,
    lehrer_pfad: str,
    verbose: bool = True,
    progress_callback=None,
) -> tuple[list[KIPruefErgebnis], list]:
    """Führt die KI-gestützte Prüfung aller manuellen Kriterien durch.

    progress_callback(dict): wird nach jedem Batch mit
        {"stufe": "ki", "aktuell": int, "gesamt": int,
         "label": str, "ergebnis": KIPruefErgebnis|None,
         "aus_checkpoint": bool} aufgerufen.
    """
    def _melde(event: dict) -> None:
        if progress_callback:
            try:
                progress_callback(event)
            except Exception:
                pass

    # 1. Automatische Begutachtung durchführen
    if verbose:
        print("=" * 72)
        print("Phase 1: Automatische Begutachtung")
        print("=" * 72)

    ergebnisse, analyse, aufgaben, sm_seiten, lm_seiten, sm_pages, lm_pages = \
        begutachte(schueler_pfad, lehrer_pfad)

    # 2. Manuell zu prüfende Kriterien filtern
    manuell = [e for e in ergebnisse if e.erfuellt is None]

    if not manuell:
        if verbose:
            print("\nKeine manuell zu prüfenden Kriterien – KI-Prüfung entfällt.")
        return [], ergebnisse

    if verbose:
        print(f"\n{len(manuell)} Kriterien manuell zu prüfen.")
        print(f"Davon {len(KI_NICHT_PRUEFBAR & {e.kriterium_nr for e in manuell})} "
              f"nicht durch KI prüfbar (visuell/physisch).")

    # 3. Texte laden
    # Für die KI-Prüfung wird das Lehrermaterial zusätzlich mit -layout
    # extrahiert, um Tabellenstrukturen (AFB-Verteilung, BE-Zuordnung)
    # besser zu erhalten. Beide Varianten werden zusammengefügt.
    schueler_text = extract_text(schueler_pfad)
    lehrer_text_normal = extract_text(lehrer_pfad)
    lehrer_text_layout = ""
    if lehrer_pfad.lower().endswith(".pdf"):
        lehrer_text_layout = extract_text_pdf(lehrer_pfad, layout=True)
    if lehrer_text_layout and lehrer_text_layout != lehrer_text_normal:
        # Beide Varianten zusammenfügen, aber jeweils auf die Hälfte des
        # MAX_TEXT_LAENGE begrenzen, damit die spätere _kuerze_text()-Kürzung
        # beide Teile erhalten kann (nicht nur den ersten).
        halb = MAX_TEXT_LAENGE // 2
        lehrer_text = (
            _kuerze_text(lehrer_text_normal, halb)
            + "\n\n=== LEHRERMATERIAL (Layout-Extraktion für Tabellen) ===\n"
            + _kuerze_text(lehrer_text_layout, halb)
        )
    else:
        lehrer_text = lehrer_text_normal

    # 4. KI-Provider bereitstellen (lokal oder Cloud)
    if verbose:
        print("\n" + "=" * 72)
        print(f"Phase 2: KI-gestützte Prüfung ({AKTIVER_PROVIDER.name})")
        print("=" * 72)

    if AKTIVER_PROVIDER.is_lokal:
        # Lokaler Modus: LM Studio Server + Modell prüfen/starten
        modell = stelle_lokales_modell_bereit(verbose)
    else:
        # Cloud-Modus: Modell ist vorkonfiguriert
        modell = AKTIVER_PROVIDER.model
        if verbose:
            print(f"  Provider: {AKTIVER_PROVIDER.name}")
            print(f"  Modell:   {modell}")

    # X.16 Vision-Hinweis: Kein Vision-Modell → Bildinhalt nicht analysiert.
    # pypdf kann Bilddaten erkennen, aber nicht deren Inhalt bewerten.
    if not any(p in (modell or "").lower() for p in VISION_MODELLE_PATTERN):
        for _erg in ergebnisse:
            if _erg.kriterium_nr == "X.16":
                _erg.kommentar += (
                    " | ⚠ Kein Vision-Modell geladen – Bildinhalt wurde nicht analysiert "
                    "(nur Vorhandensein von Bilddaten per pypdf geprüft). "
                    "Visuelle Prüfung der Anlagen erforderlich."
                )

    client = _erstelle_client()

    # 4b. Bereitschaftstest – prüft ob das Modell tatsächlich antwortet
    if not _pruefe_ki_bereitschaft(client, modell, verbose):
        if AKTIVER_PROVIDER.is_lokal:
            print("\n  WARNUNG: Das Modell reagiert nicht auf Anfragen.")
            print("  Die KI-Prüfung wird dennoch versucht, aber Timeouts sind wahrscheinlich.")
            print("  Empfehlung: Modell in LM Studio neu laden oder kleineres Modell wählen.\n")
        else:
            print(f"\n  WARNUNG: Der Provider '{AKTIVER_PROVIDER.name}' antwortet nicht.")
            print(f"  Bitte API-Key und Netzwerkverbindung prüfen.")
            print(f"  API-URL: {AKTIVER_PROVIDER.base_url}\n")

    # 4c. Kontextgröße ermitteln und Textlänge dynamisch anpassen
    n_ctx = _ermittle_kontextgroesse(verbose, modell_name=modell)
    max_text_fuer_batch = _berechne_max_text_laenge(n_ctx, BATCH_GROESSE, modell)
    max_text_fuer_einzel = _berechne_max_text_laenge(n_ctx, 1, modell)
    if verbose:
        print(f"  Max. Textlänge pro Dokument: {max_text_fuer_einzel} Zeichen "
              f"(Einzel), {max_text_fuer_batch} Zeichen (Batch)")
    # Globale Obergrenze nicht überschreiten
    max_text_fuer_batch = min(max_text_fuer_batch, MAX_TEXT_LAENGE)
    max_text_fuer_einzel = min(max_text_fuer_einzel, MAX_TEXT_LAENGE)

    # 5. KI-prüfbare Kriterien sammeln und in Batches aufteilen
    ki_ergebnisse: list[KIPruefErgebnis] = []
    ki_pruefbar: list[PruefungsErgebnis] = []   # für Batch-Verarbeitung

    # Zwischenstand laden (ermöglicht Fortsetzen nach Timeout/Abbruch)
    _checkpoint = _lade_checkpoint(schueler_pfad, lehrer_pfad)
    bereits_gepruefte_nrs: set[str] = set()
    if _checkpoint:
        ki_ergebnisse = list(_checkpoint)
        bereits_gepruefte_nrs = {e.kriterium_nr for e in ki_ergebnisse}
        if verbose:
            print(f"\n  Checkpoint geladen: {len(ki_ergebnisse)} Kriterien bereits "
                  f"geprüft – überspringe diese.")
            print(f"  (Checkpoint löschen um neu zu starten: "
                  f"{_checkpoint_pfad(schueler_pfad, lehrer_pfad)})")

    for erg in manuell:
        nr = erg.kriterium_nr
        if nr in bereits_gepruefte_nrs:
            continue
        if nr in KI_NICHT_PRUEFBAR:
            ki_ergebnisse.append(KIPruefErgebnis(
                kriterium_nr=nr,
                kriterium_text=erg.kriterium_text,
                ki_ergebnis="nicht_pruefbar",
                konfidenz=0,
                begruendung="Kriterium erfordert visuelle/physische Prüfung – "
                            "nicht durch KI prüfbar.",
                fundstellen=[],
                original_kommentar=erg.kommentar,
            ))
            if verbose:
                print(f"  [{nr}] ⏭ Nicht KI-prüfbar (visuell/physisch)")
        else:
            ki_pruefbar.append(erg)

    if not ki_pruefbar:
        return ki_ergebnisse, ergebnisse

    # Initialen Checkpoint speichern (KI_NICHT_PRUEFBAR-Einträge sichern)
    _speichere_checkpoint(schueler_pfad, lehrer_pfad, ki_ergebnisse)

    # In Batches aufteilen
    batches: list[list[PruefungsErgebnis]] = []
    for start in range(0, len(ki_pruefbar), BATCH_GROESSE):
        batches.append(ki_pruefbar[start:start + BATCH_GROESSE])

    if verbose:
        print(f"\n  {len(ki_pruefbar)} KI-Kriterien in {len(batches)} Batch(es) "
              f"à max. {BATCH_GROESSE} Kriterien.")
    _melde({"stufe": "ki_start", "aktuell": 0, "gesamt": len(ki_pruefbar),
            "label": "KI-Prüfung", "aus_checkpoint": len(bereits_gepruefte_nrs)})

    gesamt_idx = 0
    for batch_idx, batch in enumerate(batches, 1):
        kriterien_tupel = [
            (e.kriterium_nr, e.kriterium_text, e.kommentar) for e in batch
        ]
        nrs = ", ".join(e.kriterium_nr for e in batch)

        if verbose:
            print(f"\n  Batch {batch_idx}/{len(batches)}: [{nrs}] ...", flush=True)
        _melde({"stufe": "ki_aufruf",
                "aktuell": gesamt_idx,
                "gesamt": len(ki_pruefbar),
                "label": f"Batch {batch_idx}/{len(batches)} – Kriterium {nrs}"})

        if len(batch) == 1:
            # Einzelaufruf falls nur ein Kriterium im Batch
            prompt = _baue_prompt(
                batch[0].kriterium_nr, batch[0].kriterium_text,
                batch[0].kommentar, schueler_text, lehrer_text,
                max_text_laenge=max_text_fuer_einzel,
            )
            if prompt is None:
                antworten = [{**_LEER_ANTWORT,
                              "begruendung": "Kein Prompt definiert."}]
            else:
                antworten = [_rufe_ki_auf(client, prompt, modell)]
        else:
            antworten = _rufe_ki_batch_auf(
                client, kriterien_tupel, schueler_text, lehrer_text, modell,
                max_text_laenge=max_text_fuer_batch,
            )

        for erg, antwort in zip(batch, antworten):
            gesamt_idx += 1
            effektives_ergebnis = antwort["ergebnis"]
            if (effektives_ergebnis == "beanstandung"
                    and antwort["konfidenz"] < KONFIDENZ_SCHWELLE):
                effektives_ergebnis = "nicht_pruefbar"
                antwort["begruendung"] = (
                    f"[Konfidenz {antwort['konfidenz']}% < Schwelle "
                    f"{KONFIDENZ_SCHWELLE}%] " + antwort["begruendung"]
                )

            ki_ergebnisse.append(KIPruefErgebnis(
                kriterium_nr=erg.kriterium_nr,
                kriterium_text=erg.kriterium_text,
                ki_ergebnis=effektives_ergebnis,
                konfidenz=antwort["konfidenz"],
                begruendung=antwort["begruendung"],
                fundstellen=antwort["fundstellen"],
                original_kommentar=erg.kommentar,
            ))

            if verbose:
                symbole = {
                    "beanstandung": "❌",
                    "keine_beanstandung": "✅",
                    "nicht_pruefbar": "⚠️",
                }
                symbol = symbole.get(effektives_ergebnis, "?")
                print(f"    [{gesamt_idx}/{len(ki_pruefbar)}] [{erg.kriterium_nr}] "
                      f"{erg.kriterium_text[:50]} ... {symbol} ({antwort['konfidenz']}%)")
            _melde({"stufe": "ki",
                    "aktuell": gesamt_idx,
                    "gesamt": len(ki_pruefbar),
                    "label": f"Kriterium {erg.kriterium_nr}",
                    "ergebnis": ki_ergebnisse[-1]})

        # Zwischenstand nach jedem Batch speichern
        _speichere_checkpoint(schueler_pfad, lehrer_pfad, ki_ergebnisse)

        if batch_idx < len(batches):
            time.sleep(PAUSE_ZWISCHEN_AUFRUFEN)

    return ki_ergebnisse, ergebnisse


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------

def drucke_ki_ergebnisse(ki_ergebnisse: list[KIPruefErgebnis]):
    """Druckt die KI-Prüfergebnisse auf der Konsole."""
    print("\n" + "=" * 72)
    print("ERGEBNIS DER KI-GESTÜTZTEN PRÜFUNG")
    print("=" * 72)

    beanstandungen = [e for e in ki_ergebnisse if e.ki_ergebnis == "beanstandung"]
    keine = [e for e in ki_ergebnisse if e.ki_ergebnis == "keine_beanstandung"]
    nicht_pruefbar = [e for e in ki_ergebnisse if e.ki_ergebnis == "nicht_pruefbar"]

    if beanstandungen:
        print(f"\n❌ BEANSTANDUNGEN DURCH KI ({len(beanstandungen)}):")
        print("-" * 50)
        for e in beanstandungen:
            print(f"  [{e.kriterium_nr}] {e.kriterium_text}")
            print(f"    Konfidenz: {e.konfidenz}%")
            print(f"    Begründung: {e.begruendung}")
            if e.fundstellen:
                for f in e.fundstellen:
                    print(f"    Fundstelle: {f}")
            print()

    if keine:
        print(f"\n✅ KEINE BEANSTANDUNG DURCH KI ({len(keine)}):")
        print("-" * 50)
        for e in keine:
            print(f"  [{e.kriterium_nr}] {e.kriterium_text}")
            print(f"    Konfidenz: {e.konfidenz}% – {e.begruendung}")

    if nicht_pruefbar:
        print(f"\n⚠️  NICHT (SICHER) DURCH KI PRÜFBAR ({len(nicht_pruefbar)}):")
        print("-" * 50)
        for e in nicht_pruefbar:
            print(f"  [{e.kriterium_nr}] {e.kriterium_text}")
            print(f"    → {e.begruendung}")

    print(f"\n{'='*72}")
    print(f"ZUSAMMENFASSUNG KI-PRÜFUNG:")
    print(f"  ❌ Beanstandungen:          {len(beanstandungen)}")
    print(f"  ✅ Keine Beanstandung:      {len(keine)}")
    print(f"  ⚠️  Nicht (sicher) prüfbar:  {len(nicht_pruefbar)}")
    print(f"  Gesamt geprüft:             {len(ki_ergebnisse)}")
    print(f"  Konfidenz-Schwelle:         {KONFIDENZ_SCHWELLE}%")
    print(f"{'='*72}")


from src.bewertung import ki_bericht as _ki_bericht  # noqa: E402
from src.bewertung.ki_bericht import (  # noqa: E402
    _LM_SCHLUESSEL,
    _SM_SCHLUESSEL,
    _erstelle_handlungsbedarf_sheet,
    _handlungsbedarf_sortkey,
    _trenne_sm_lm_fundstellen,
    _trenne_sm_lm_kommentar,
)


def schreibe_ki_bericht_xlsx(kombinierte, output_pfad, schueler_datei, lehrer_datei):
    """Prüfbericht als XLSX (siehe src.bewertung.ki_bericht) mit der aktuellen Schwelle."""
    return _ki_bericht.schreibe_ki_bericht_xlsx(
        kombinierte, output_pfad, schueler_datei, lehrer_datei,
        schwelle=KONFIDENZ_SCHWELLE)


# ---------------------------------------------------------------------------
# Checkpoint: Zwischenergebnisse bei Abbruch/Timeout sichern
# ---------------------------------------------------------------------------

def _datei_inhaltshash(pfad: str) -> str:
    """SHA-256 (gekürzt) über den Dateiinhalt – stabil über Pfad-Wechsel hinweg.

    Streamlit legt PDFs in wechselnde /tmp/tmpXXX/-Verzeichnisse ab. Ohne
    inhaltsbasierten Schlüssel passte der Pfad-basierte Checkpoint nie zum
    nächsten Lauf, sodass jeder Streamlit-Restart bei null begann.
    """
    import hashlib
    h = hashlib.sha256()
    try:
        with open(pfad, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()[:16]


def _checkpoint_pfad(sm_pfad: str, lm_pfad: str | None = None) -> str:
    """Inhalts-gehashed: identische PDFs → identischer Checkpoint-Name."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sm_hash = _datei_inhaltshash(sm_pfad)
    lm_hash = _datei_inhaltshash(lm_pfad) if lm_pfad else ""
    if sm_hash and lm_hash:
        name = f"checkpoint_ki_{sm_hash}_{lm_hash}.json"
    else:
        # Fallback (z. B. wenn Datei während Lauf gelöscht): Pfadname.
        name = f"checkpoint_ki_{Path(sm_pfad).stem}.json"
    return os.path.join(script_dir, "Auswertungen", name)


def _lade_checkpoint(
    sm_pfad: str, lm_pfad: str
) -> list[KIPruefErgebnis] | None:
    """Lädt gespeicherte Zwischenergebnisse, wenn SM/LM-Inhalte übereinstimmen."""
    pfad = _checkpoint_pfad(sm_pfad, lm_pfad)
    if not os.path.isfile(pfad):
        return None
    try:
        with open(pfad, encoding="utf-8") as f:
            daten = json.load(f)
        sm_hash = _datei_inhaltshash(sm_pfad)
        lm_hash = _datei_inhaltshash(lm_pfad)
        if (daten.get("sm_hash") != sm_hash
                or daten.get("lm_hash") != lm_hash):
            return None  # anderes Dokument → Checkpoint ignorieren
        return [
            KIPruefErgebnis(
                kriterium_nr=d["kriterium_nr"],
                kriterium_text=d["kriterium_text"],
                ki_ergebnis=d["ki_ergebnis"],
                konfidenz=int(d.get("konfidenz", 0)),
                begruendung=str(d.get("begruendung", "")),
                fundstellen=list(d.get("fundstellen", [])),
                original_kommentar=str(d.get("original_kommentar", "")),
            )
            for d in daten.get("ergebnisse", [])
        ]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        log.warning("Checkpoint konnte nicht geladen werden (%s): %s", pfad, e, exc_info=True)
        return None


def _speichere_checkpoint(
    sm_pfad: str, lm_pfad: str, ergebnisse: list[KIPruefErgebnis]
) -> None:
    """Speichert den aktuellen Prüfstand als JSON-Checkpoint."""
    pfad = _checkpoint_pfad(sm_pfad, lm_pfad)
    try:
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        daten = {
            "sm": sm_pfad,
            "lm": lm_pfad,
            "sm_name": Path(sm_pfad).name,
            "lm_name": Path(lm_pfad).name,
            "sm_hash": _datei_inhaltshash(sm_pfad),
            "lm_hash": _datei_inhaltshash(lm_pfad),
            "ergebnisse": [
                {
                    "kriterium_nr": e.kriterium_nr,
                    "kriterium_text": e.kriterium_text,
                    "ki_ergebnis": e.ki_ergebnis,
                    "konfidenz": e.konfidenz,
                    "begruendung": e.begruendung,
                    "fundstellen": e.fundstellen,
                    "original_kommentar": e.original_kommentar,
                }
                for e in ergebnisse
            ],
        }
        with open(pfad, "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        log.warning("Checkpoint konnte nicht gespeichert werden (%s): %s", pfad, exc, exc_info=True)
        print(f"  Warnung: Checkpoint konnte nicht gespeichert werden: {exc}")


def _loesche_checkpoint(sm_pfad: str, lm_pfad: str | None = None) -> None:
    """Löscht den Checkpoint nach erfolgreichem Abschluss."""
    pfad = _checkpoint_pfad(sm_pfad, lm_pfad)
    try:
        if os.path.isfile(pfad):
            os.remove(pfad)
    except OSError as e:
        log.debug("Checkpoint konnte nicht gelöscht werden (%s): %s", pfad, e, exc_info=True)
        pass


def _kurzer_modellname(modell: str) -> str:
    """Gibt einen kurzen, dateisystemfreundlichen Modellnamen zurück."""
    name = modell.split("/")[-1]
    name = re.sub(r'[^\w\-.]', '-', name)[:25].rstrip('-.')
    return name


def _json_ergebnis_pfad(sm_pfad: str, output_dir: str, modell: str = "") -> str:
    """Leitet den finalen JSON-Ergebnispfad vom Schülermaterial-Name ab.

    Wenn *modell* angegeben wird, wird ein kurzes Modell-Suffix angehängt,
    damit mehrere Modell-Läufe sich nicht gegenseitig überschreiben.
    """
    basis = Path(sm_pfad).stem
    suffix = f"_{_kurzer_modellname(modell)}" if modell else ""
    return os.path.join(output_dir, f"KI_Pruefung_{basis}{suffix}.json")


def schreibe_ki_bericht_json(
    kombinierte: list[KombinierterPruefpunkt],
    output_pfad: str,
    schueler_datei: str,
    lehrer_datei: str,
    modell: str = "",
) -> None:
    """Schreibt alle Prüfpunkte (regelbasiert + KI) als JSON-Datei."""
    import datetime

    regelbasiert_beanstandet = sum(
        1 for e in kombinierte if e.regelbasiert_erfuellt is False
    )
    regelbasiert_erfuellt = sum(
        1 for e in kombinierte if e.regelbasiert_erfuellt is True
    )
    ki_beanstandungen = sum(
        1 for e in kombinierte if e.ki_geprueft and e.ki_ergebnis == "beanstandung"
    )
    ki_keine = sum(
        1 for e in kombinierte
        if e.ki_geprueft and e.ki_ergebnis == "keine_beanstandung"
    )
    ki_nicht_pruefbar = sum(
        1 for e in kombinierte
        if e.ki_geprueft and e.ki_ergebnis == "nicht_pruefbar"
    )

    daten = {
        "version": "2.0",
        "erstellt": datetime.datetime.now().isoformat(timespec="seconds"),
        "schuelermaterial": schueler_datei,
        "lehrermaterial": lehrer_datei,
        "modell": modell,
        "konfidenz_schwelle": KONFIDENZ_SCHWELLE,
        "pruefpunkte": [
            {
                "lfd_nr": e.lfd_nr,
                "kriterium_nr": e.kriterium_nr,
                "kriterium_text": e.kriterium_text,
                "regelbasiert_erfuellt": e.regelbasiert_erfuellt,
                "regelbasiert_kommentar": e.regelbasiert_kommentar,
                "ki_geprueft": e.ki_geprueft,
                "ki_ergebnis": e.ki_ergebnis if e.ki_geprueft else None,
                "konfidenz": e.konfidenz if e.ki_geprueft else None,
                "ki_begruendung": e.ki_begruendung if e.ki_geprueft else None,
                "fundstellen": e.fundstellen if e.ki_geprueft else [],
            }
            for e in kombinierte
        ],
        "zusammenfassung": {
            "regelbasiert_erfuellt": regelbasiert_erfuellt,
            "regelbasiert_beanstandet": regelbasiert_beanstandet,
            "ki_beanstandungen": ki_beanstandungen,
            "ki_keine_beanstandung": ki_keine,
            "ki_nicht_pruefbar": ki_nicht_pruefbar,
            "gesamt_pruefpunkte": len(kombinierte),
        },
    }
    try:
        os.makedirs(os.path.dirname(output_pfad), exist_ok=True)
        with open(output_pfad, "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, indent=2)
        print(f"Prüfbericht (JSON) gespeichert: {output_pfad}")
    except OSError as exc:
        log.warning("JSON-Bericht konnte nicht gespeichert werden (%s): %s", output_pfad, exc, exc_info=True)
        print(f"  Warnung: JSON-Bericht konnte nicht gespeichert werden: {exc}")


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------

def main():
    global LMSTUDIO_BASE_URL, KONFIDENZ_SCHWELLE, API_TIMEOUT, BATCH_GROESSE

    verfuegbare_provider = ", ".join(PROVIDER.keys())

    parser = argparse.ArgumentParser(
        description="KI-gestützte Prüfung der manuell zu prüfenden "
                    "Begutachtungskriterien.",
        epilog=f"Verfügbare Provider: {verfuegbare_provider}\\n"
               f"Beispiele:\\n"
               f"  %(prog)s --provider lokal --verzeichnis Klausuren/Abiturvorschläge/2025Mechatronik\\n"
               f"  %(prog)s --provider hetzner --verzeichnis Klausuren/Abiturvorschläge/2025Mechatronik\\n"
               f"  %(prog)s --provider gwdg SM.pdf LM.pdf\\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("schuelermaterial", nargs="?", default=None,
        help="Pfad zum Schülermaterial (PDF oder DOCX)")
    parser.add_argument("lehrermaterial", nargs="?", default=None,
        help="Pfad zum Lehrermaterial (PDF oder DOCX)")
    parser.add_argument("--verzeichnis", default=None,
        help="Verzeichnis mit Abiturvorschlägen (Batch-Modus)")
    parser.add_argument("--output", default=None,
        help="Pfad für den KI-Prüfbericht (XLSX)")
    parser.add_argument("--provider", default=None,
        choices=list(PROVIDER.keys()),
        help=f"KI-Provider ({verfuegbare_provider}). "
             f"Standard: lokal. Env: KI_PROVIDER")
    parser.add_argument("--api-url", default=None,
        help="API-URL überschreiben (überschreibt Provider-Default)")
    parser.add_argument("--api-key", default=None,
        help="API-Key überschreiben (überschreibt Env-Variable)")
    parser.add_argument("--modell", default=None,
        help="Modellname überschreiben (überschreibt Provider-Default)")
    parser.add_argument("--schwelle", type=int, default=None,
        help=f"Konfidenz-Schwelle 0–100 (Standard: {KONFIDENZ_SCHWELLE})")
    parser.add_argument("--timeout", type=int, default=None,
        help="API-Timeout in Sekunden")
    parser.add_argument("--batch-groesse", type=int, default=None,
        help="Kriterien pro Batch-Aufruf")
    parser.add_argument("--nur-konsole", action="store_true",
        help="Nur Konsolenausgabe, kein XLSX erzeugen")
    parser.add_argument("--provider-info", action="store_true",
        help="Zeigt Informationen zu allen Providern und beendet sich.")

    args = parser.parse_args()

    # --provider-info: Provider auflisten und beenden
    if args.provider_info:
        print("Verfügbare KI-Provider:\n")
        for key, cfg in PROVIDER.items():
            status = "✅ API-Key gesetzt" if os.environ.get(cfg.api_key_env) else "❌ API-Key fehlt"
            if cfg.is_lokal:
                status = "🖥️  Lokal (kein API-Key nötig)"
            print(f"  {key:10s}  {cfg.name}")
            print(f"             {cfg.beschreibung}")
            print(f"             API-URL: {cfg.base_url}")
            print(f"             Modell:  {cfg.model}")
            print(f"             Key-Env: {cfg.api_key_env}  [{status}]")
            print()
        return

    # .env laden (wie die Oberfläche), damit KI_PROVIDER/KI_MODELL greifen
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Provider bestimmen: CLI > Env > Default
    provider_name = args.provider or os.environ.get("KI_PROVIDER", "lokal")
    _aktiviere_provider(provider_name, verbose=True)

    # Manuelle Overrides
    if args.api_url is not None:
        LMSTUDIO_BASE_URL = args.api_url
    if args.api_key is not None:
        global LMSTUDIO_API_KEY
        LMSTUDIO_API_KEY = args.api_key
    if args.modell is not None:
        global LMSTUDIO_MODEL
        LMSTUDIO_MODEL = args.modell
        AKTIVER_PROVIDER.model = args.modell
    if args.schwelle is not None:
        KONFIDENZ_SCHWELLE = args.schwelle
    if args.timeout is not None:
        API_TIMEOUT = args.timeout
    if args.batch_groesse is not None:
        BATCH_GROESSE = args.batch_groesse

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "Auswertungen")

    # ------------------------------------------------------------------
    # Batch-Modus
    # ------------------------------------------------------------------
    if args.verzeichnis:
        verzeichnis = os.path.abspath(args.verzeichnis)
        vorschlaege = finde_vorschlaege(verzeichnis)
        if not vorschlaege:
            print("Keine Vorschläge gefunden.")
            sys.exit(1)

        print(f"\n{'='*72}")
        print(f"KI-Batch-Prüfung: {len(vorschlaege)} Vorschlag/Vorschläge")
        print(f"{'='*72}\n")

        for idx, v in enumerate(vorschlaege, 1):
            print(f"\n{'='*72}")
            print(f"[{idx}/{len(vorschlaege)}] {v['name']}")
            print(f"{'='*72}")

            ki_ergebnisse, regelbasiert_ergebnisse = fuehre_ki_pruefung_durch(
                v["sm"], v["lm"], verbose=True)
            kombinierte = erstelle_kombinierte_liste(regelbasiert_ergebnisse, ki_ergebnisse)

            drucke_ki_ergebnisse(ki_ergebnisse)

            if not args.nur_konsole:
                os.makedirs(output_dir, exist_ok=True)
                akt_modell = _erkenne_geladenes_modell(preferiert=LMSTUDIO_MODEL) if AKTIVER_PROVIDER.is_lokal else AKTIVER_PROVIDER.model
                basis = Path(v["sm"]).stem
                modell_suffix = f"_{_kurzer_modellname(akt_modell)}" if akt_modell else ""
                xlsx_pfad = os.path.join(output_dir, f"KI_Pruefung_{basis}{modell_suffix}.xlsx")
                json_pfad = _json_ergebnis_pfad(v["sm"], output_dir, akt_modell)
                schreibe_ki_bericht_xlsx(kombinierte, xlsx_pfad, v["sm"], v["lm"])
                schreibe_ki_bericht_json(kombinierte, json_pfad, v["sm"], v["lm"], akt_modell)
                _schreibe_hinweisliste_ki(v["sm"], v["lm"], ki_ergebnisse, output_dir,
                                          basis, modell_suffix, akt_modell)
                _loesche_checkpoint(v["sm"], v["lm"])

        print(f"\nBatch-Lauf abgeschlossen.")
        return

    # ------------------------------------------------------------------
    # Einzel-Modus
    # ------------------------------------------------------------------
    if not args.schuelermaterial or not args.lehrermaterial:
        parser.error("Im Einzelmodus sind schuelermaterial und lehrermaterial "
                     "erforderlich. Alternativ: --verzeichnis für Batch-Modus.")

    schueler_pfad = os.path.abspath(args.schuelermaterial)
    lehrer_pfad = os.path.abspath(args.lehrermaterial)

    if not os.path.isfile(schueler_pfad):
        print(f"FEHLER: Schülermaterial nicht gefunden: {schueler_pfad}")
        sys.exit(1)
    if not os.path.isfile(lehrer_pfad):
        print(f"FEHLER: Lehrermaterial nicht gefunden: {lehrer_pfad}")
        sys.exit(1)

    ki_ergebnisse, regelbasiert_ergebnisse = fuehre_ki_pruefung_durch(
        schueler_pfad, lehrer_pfad, verbose=True)
    kombinierte = erstelle_kombinierte_liste(regelbasiert_ergebnisse, ki_ergebnisse)

    drucke_ki_ergebnisse(ki_ergebnisse)

    if not args.nur_konsole:
        os.makedirs(output_dir, exist_ok=True)
        akt_modell = _erkenne_geladenes_modell(preferiert=LMSTUDIO_MODEL) if AKTIVER_PROVIDER.is_lokal else AKTIVER_PROVIDER.model
        basis = Path(schueler_pfad).stem
        modell_suffix = f"_{_kurzer_modellname(akt_modell)}" if akt_modell else ""
        xlsx_pfad = args.output or os.path.join(
            output_dir, f"KI_Pruefung_{basis}{modell_suffix}.xlsx")
        json_pfad = _json_ergebnis_pfad(schueler_pfad, output_dir, akt_modell)
        schreibe_ki_bericht_xlsx(kombinierte, xlsx_pfad,
                                 schueler_pfad, lehrer_pfad)
        schreibe_ki_bericht_json(kombinierte, json_pfad,
                                 schueler_pfad, lehrer_pfad, akt_modell)
        _schreibe_hinweisliste_ki(schueler_pfad, lehrer_pfad, ki_ergebnisse, output_dir,
                                  basis, modell_suffix, akt_modell)
        _loesche_checkpoint(schueler_pfad, lehrer_pfad)


if __name__ == "__main__":
    main()
