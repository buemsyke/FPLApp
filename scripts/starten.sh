#!/bin/bash
# ============================================================================
# GutachtenAbiturklausur - Linux/macOS Einstiegspunkt
# Ausführung: ./starten.sh
# ============================================================================

set -e

# macOS: Einrichtung ohne Homebrew/Adminrechte über die Startdatei im Projektordner
if [ "$(uname -s)" = "Darwin" ]; then
    exec bash "$(dirname "$0")/../Gutachten starten.command" "$@"
fi

# Farben für Ausgabe
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Prüfe Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[FEHLER] Python3 nicht gefunden.${NC}"
    echo "Bitte Python 3.11+ installieren:"
    echo "  macOS: brew install python3"
    echo "  Ubuntu/Debian: sudo apt-get install python3 python3-venv"
    exit 1
fi

echo -e "${GREEN}[INFO] Python3 gefunden:${NC} $(python3 --version)"

# eduwerkzeuge braucht Python ≥ 3.11 (macOS liefert über die Xcode-Tools oft 3.9)
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo -e "${RED}[FEHLER] Python 3.11 oder neuer nötig.${NC}"
    echo "  macOS: brew install python@3.12 (danach Terminal neu öffnen)"
    exit 1
fi

# Ins Projektverzeichnis wechseln (Skript liegt in scripts/)
cd "$(dirname "$0")/.."

# Prüfe ob im richtigen Verzeichnis
if [ ! -f "app.py" ]; then
    echo -e "${RED}[FEHLER] app.py nicht gefunden.${NC}"
    echo "Bitte starten.sh aus dem Projekt-Wurzelverzeichnis aus starten."
    exit 1
fi

# Erstelle .env aus .env.example falls nicht vorhanden
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}[INFO] .env wird aus .env.example erstellt...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}[INFO] .env erstellt. Bitte API-Keys in .env eintragen, falls nötig.${NC}"
fi

# Erstelle venv falls nicht vorhanden
if [ ! -d ".venv" ]; then
    echo -e "${GREEN}[INFO] Virtuelle Umgebung wird erstellt...${NC}"
    python3 -m venv .venv
fi

# Aktiviere venv
source .venv/bin/activate

# Installiere/Update Packages
echo -e "${GREEN}[INFO] Dependencies werden installiert...${NC}"
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Gemeinsame Bibliothek eduwerkzeuge (Provider LM Studio / Ollama / Bonsai).
# Steht nicht in requirements.txt, weil sie aus einem lokalen Ordner kommt.
if ! python -c 'from eduwerkzeuge.ki.core import ProviderConfig as P; assert "server" in P.__dataclass_fields__' 2>/dev/null; then
    EDU_PFAD=""
    for kandidat in "${EDUWERKZEUGE_PFAD:-}" "../_lib/eduwerkzeuge" "../../_lib/eduwerkzeuge" \
                    "../Skill-Bibliothek-Unterrichtsentwicklung/_lib/eduwerkzeuge" \
                    "$HOME/Dokumente/GitHub/_lib/eduwerkzeuge"; do
        if [ -n "$kandidat" ] && [ -f "$kandidat/pyproject.toml" ]; then
            EDU_PFAD="$kandidat"; break
        fi
    done
    if [ -z "$EDU_PFAD" ]; then
        echo -e "${RED}[FEHLER] eduwerkzeuge (aktuelle Fassung) nicht gefunden.${NC}"
        echo "  Ordner _lib/eduwerkzeuge neben das Projekt kopieren oder"
        echo "  EDUWERKZEUGE_PFAD=/pfad/zu/eduwerkzeuge setzen."
        exit 1
    fi
    echo -e "${GREEN}[INFO] Installiere eduwerkzeuge aus ${EDU_PFAD}${NC}"
    pip install -q -e "$EDU_PFAD"
fi

# Starte Streamlit
echo -e "${GREEN}[INFO] Starte Streamlit-App...${NC}"
echo -e "${GREEN}[INFO] Browser wird gleich geöffnet unter http://localhost:8501${NC}"
echo ""

streamlit run app.py --server.port=8501 --browser.gatherUsageStats=false
