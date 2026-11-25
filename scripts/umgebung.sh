#!/bin/bash
# ============================================================================
# umgebung.sh – Laufzeitumgebung ohne Administratorrechte (macOS, Linux)
# ----------------------------------------------------------------------------
# Legt Python 3.12 und Poppler (pdftotext) im Benutzerordner an – kein
# Homebrew, kein sudo, keine Änderung am System. Gemeinsam genutzt von
#   - "Gutachten starten.command" (App, alle Pakete aus requirements.txt)
#   - Skill abiturvorschlag-begutachten (scripts/einrichten.sh, nur Prüfkern)
#
# Aufruf:
#   bash scripts/umgebung.sh einrichten [--app]   # --app: Pakete der App dazu
#   bash scripts/umgebung.sh pfad                  # bin-Ordner ausgeben
#   bash scripts/umgebung.sh pruefen               # Zustand anzeigen
#   bash scripts/umgebung.sh entfernen             # Umgebung löschen
#
# Ort der Umgebung (außerhalb von iCloud „Dokumente“, damit nichts
# synchronisiert wird):
#   macOS: ~/Library/Application Support/GutachtenAbiturklausur
#   Linux: ${XDG_DATA_HOME:-~/.local/share}/gutachten-abiturklausur
#   abweichend: GUTACHTEN_UMGEBUNG=/pfad
#
# Werkzeug: micromamba (eine Datei, conda-forge). Version fest, damit jeder
# Rechner dieselbe Umgebung bekommt. Läuft nur mit bash 3.2-Mitteln (macOS).
# ============================================================================

MICROMAMBA_VERSION="2.9.0-0"
PYTHON_VERSION="3.12"
# Prüfkern (Skill) – App-Pakete kommen aus requirements.txt dazu
KERN_PAKETE="python-docx>=1.0 openpyxl>=3.1 pypdf>=3.0 lxml>=4.9"

if [ "$(uname -s)" = "Darwin" ]; then
    _BASIS_STANDARD="$HOME/Library/Application Support/GutachtenAbiturklausur"
else
    _BASIS_STANDARD="${XDG_DATA_HOME:-$HOME/.local/share}/gutachten-abiturklausur"
fi
UMG_BASIS="${GUTACHTEN_UMGEBUNG:-$_BASIS_STANDARD}"
UMG="$UMG_BASIS/umgebung"
UMG_BIN="$UMG/bin"
MICROMAMBA="$UMG_BASIS/micromamba"
STAND_DATEI="$UMG/.gutachten-stand"

_SKRIPT_ORDNER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_info()   { printf '\033[0;32m[INFO]\033[0m %s\n' "$*"; }
_hinweis(){ printf '\033[1;33m[HINWEIS]\033[0m %s\n' "$*"; }
_fehler() { printf '\033[0;31m[FEHLER]\033[0m %s\n' "$*" >&2; }

_plattform() {
    case "$(uname -s)-$(uname -m)" in
        Darwin-arm64)              echo "osx-arm64" ;;
        Darwin-x86_64)             echo "osx-64" ;;
        Linux-aarch64|Linux-arm64) echo "linux-aarch64" ;;
        Linux-x86_64)              echo "linux-64" ;;
        *) return 1 ;;
    esac
}

_sha() {  # Prüfsumme über stdin (macOS: shasum, Linux: sha256sum)
    if command -v shasum >/dev/null 2>&1; then shasum -a 256 | cut -d' ' -f1
    else sha256sum | cut -d' ' -f1; fi
}

_lade_micromamba() {
    [ -x "$MICROMAMBA" ] && return 0
    local plattform url
    plattform="$(_plattform)" || { _fehler "Plattform $(uname -s)/$(uname -m) wird nicht unterstützt."; return 1; }
    url="https://github.com/mamba-org/micromamba-releases/releases/download/${MICROMAMBA_VERSION}/micromamba-${plattform}"
    _info "Lade micromamba ${MICROMAMBA_VERSION} (${plattform}) …"
    mkdir -p "$UMG_BASIS" || return 1
    if ! curl -fsSL --retry 3 -o "$MICROMAMBA.tmp" "$url"; then
        _fehler "Download fehlgeschlagen: $url"
        _fehler "Internetverbindung prüfen (ggf. Proxy/WLAN der Dienststelle)."
        rm -f "$MICROMAMBA.tmp"; return 1
    fi
    chmod +x "$MICROMAMBA.tmp" && mv "$MICROMAMBA.tmp" "$MICROMAMBA"
}

_mamba() {
    MAMBA_ROOT_PREFIX="$UMG_BASIS/mamba" "$MICROMAMBA" "$@"
}

# Fallback ohne micromamba: vorhandenes Python ≥ 3.11 (dann ohne pdftotext)
_venv_fallback() {
    local py=""
    for c in python3.13 python3.12 python3.11 python3; do
        if command -v "$c" >/dev/null 2>&1 && \
           "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
            py="$c"; break
        fi
    done
    [ -n "$py" ] || return 1
    _hinweis "Nutze vorhandenes $("$py" --version 2>&1) ohne Poppler."
    _hinweis "Ohne pdftotext kann die Regelprüfung einzelne Kriterien falsch werten (z. B. 4.7)."
    "$py" -m venv "$UMG"
}

_eduwerkzeuge_quelle() {
    # 1. ausdrücklich gesetzt  2. mitgeliefertes Wheel  3. Ordner neben dem Projekt
    local projekt="$1" k
    if [ -n "${EDUWERKZEUGE_PFAD:-}" ] && [ -f "$EDUWERKZEUGE_PFAD/pyproject.toml" ]; then
        echo "$EDUWERKZEUGE_PFAD"; return 0
    fi
    k="$(ls -1 "$projekt"/vendor/eduwerkzeuge-*.whl 2>/dev/null | sort | tail -n 1)"
    if [ -n "$k" ]; then echo "$k"; return 0; fi
    for k in "$projekt/../_lib/eduwerkzeuge" "$projekt/../../_lib/eduwerkzeuge" \
             "$projekt/../Skill-Bibliothek-Unterrichtsentwicklung/_lib/eduwerkzeuge"; do
        if [ -f "$k/pyproject.toml" ]; then echo "$k"; return 0; fi
    done
    return 1
}

umgebung_einrichten() {
    local mit_app="" projekt
    [ "${1:-}" = "--app" ] && mit_app=1
    projekt="$(cd "$_SKRIPT_ORDNER/.." && pwd)"

    # --- Stand ermitteln: nur neu installieren, wenn sich etwas geändert hat
    local stand edu=""
    stand="micromamba=$MICROMAMBA_VERSION python=$PYTHON_VERSION kern=$KERN_PAKETE"
    if [ -n "$mit_app" ]; then
        edu="$(_eduwerkzeuge_quelle "$projekt")" || {
            _fehler "eduwerkzeuge nicht gefunden (vendor/eduwerkzeuge-*.whl fehlt)."
            return 1; }
        stand="$stand app=$(cat "$projekt/requirements.txt" | _sha) edu=$(basename "$edu")"
    fi
    if [ -x "$UMG_BIN/python" ] && [ -f "$STAND_DATEI" ] && grep -qxF "$stand" "$STAND_DATEI"; then
        return 0   # alles aktuell
    fi

    _info "Richte die Umgebung ein (einmalig, einige Minuten, ca. 1 GB Download) …"
    _info "Ort: $UMG"

    # --- Python + Poppler
    if [ ! -x "$UMG_BIN/python" ]; then
        if _lade_micromamba && _mamba create -y -q -p "$UMG" -c conda-forge --override-channels \
                "python=$PYTHON_VERSION" poppler pip; then
            :
        else
            _hinweis "micromamba-Einrichtung nicht möglich – versuche vorhandenes Python."
            rm -rf "$UMG"
            _venv_fallback || {
                _fehler "Weder micromamba noch Python ≥ 3.11 verfügbar."
                return 1; }
        fi
    elif [ ! -x "$UMG_BIN/pdftotext" ] && _lade_micromamba; then
        _mamba install -y -q -p "$UMG" -c conda-forge --override-channels poppler || true
    fi

    # --- Python-Pakete
    "$UMG_BIN/python" -m pip install -q --disable-pip-version-check $KERN_PAKETE || return 1
    if [ -n "$mit_app" ]; then
        "$UMG_BIN/python" -m pip install -q --disable-pip-version-check \
            -r "$projekt/requirements.txt" || return 1
        _info "eduwerkzeuge aus $(basename "$edu")"
        "$UMG_BIN/python" -m pip install -q --disable-pip-version-check --force-reinstall --no-deps "$edu" \
            && "$UMG_BIN/python" -m pip install -q --disable-pip-version-check "PyYAML>=6.0" || return 1
    fi

    # Stand nur nach Erfolg schreiben; App-Stand schließt den Kern ein
    echo "$stand" >> "$STAND_DATEI"
    _info "Umgebung bereit."
}

umgebung_pruefen() {
    echo "Umgebung:   $UMG"
    if [ -x "$UMG_BIN/python" ]; then
        echo "Python:     $("$UMG_BIN/python" --version 2>&1)"
    else
        echo "Python:     fehlt (bash scripts/umgebung.sh einrichten)"
    fi
    if [ -x "$UMG_BIN/pdftotext" ]; then
        echo "pdftotext:  $("$UMG_BIN/pdftotext" -v 2>&1 | head -n 1)"
    else
        echo "pdftotext:  fehlt"
    fi
    if [ -x "$UMG_BIN/python" ]; then
        "$UMG_BIN/python" - <<'PY'
import importlib
for m in ("docx", "openpyxl", "pypdf", "streamlit", "openai", "eduwerkzeuge"):
    try:
        mod = importlib.import_module(m)
        print(f"{m + ':':<12}{getattr(mod, '__version__', 'vorhanden')}")
    except Exception:
        print(f"{m + ':':<12}fehlt")
PY
    fi
}

# Direktaufruf (beim Einbinden mit "source" passiert hier nichts)
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    case "${1:-}" in
        einrichten) shift; umgebung_einrichten "$@" ;;
        pfad)       echo "$UMG_BIN" ;;
        pruefen)    umgebung_pruefen ;;
        entfernen)  rm -rf "$UMG_BASIS" && _info "Entfernt: $UMG_BASIS" ;;
        *) sed -n '2,25p' "$0"; exit 1 ;;
    esac
fi
