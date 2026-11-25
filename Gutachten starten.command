#!/bin/bash
# ============================================================================
# Gutachten starten.command – Begutachtung von Abiturvorschlägen (macOS)
# ----------------------------------------------------------------------------
# Doppelklick im Finder. Beim ersten Start wird die Umgebung eingerichtet
# (Python 3.12 + pdftotext im Benutzerordner, ohne Administratorrechte,
# einige Minuten). Danach öffnet sich die Oberfläche im Browser.
#
# Blockiert macOS den ersten Start („nicht verifizierter Entwickler“):
#   Systemeinstellungen → Datenschutz & Sicherheit → „Dennoch öffnen“
# oder im Terminal:  bash "Gutachten starten.command"
#
# Beenden: dieses Terminalfenster schließen (oder Ctrl+C).
# Läuft auch unter Linux (statt open wird xdg-open benutzt).
# ============================================================================

cd "$(dirname "$0")" || exit 1
PROJEKT="$(pwd)"
PORT="${GUTACHTEN_PORT:-8501}"
URL="http://localhost:$PORT"

# shellcheck source=scripts/umgebung.sh
source "$PROJEKT/scripts/umgebung.sh"

ende() {
    echo ""
    read -r -p "Enter drücken zum Schließen … " _
    exit "${1:-0}"
}

oeffne_browser() {
    if command -v open >/dev/null 2>&1 && [ "$(uname -s)" = "Darwin" ]; then
        open "$URL"
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" >/dev/null 2>&1 &
    else
        echo "Bitte im Browser öffnen: $URL"
    fi
}

echo "============================================"
echo " Gutachten Abiturklausur"
echo " Ordner: $PROJEKT"
echo "============================================"

# Läuft die Oberfläche schon (z. B. zweiter Doppelklick)? Dann nur Browser.
if curl -fs "$URL/_stcore/health" >/dev/null 2>&1; then
    _info "Oberfläche läuft bereits – öffne $URL"
    oeffne_browser
    exit 0
fi

umgebung_einrichten --app || {
    _fehler "Einrichtung nicht abgeschlossen. Meldungen oben beachten."
    _fehler "Neuer Versuch: diese Datei erneut öffnen (Download wird fortgesetzt)."
    ende 1
}
export PATH="$UMG_BIN:$PATH"    # pdftotext für die Regelprüfung

if [ ! -f "$PROJEKT/.env" ]; then
    cp "$PROJEKT/.env.example" "$PROJEKT/.env"
    _info ".env aus .env.example angelegt (Vorbelegung: LM Studio, lokal)."
fi

if ! command -v pdftotext >/dev/null 2>&1; then
    _hinweis "pdftotext fehlt – Regelprüfung mit eingeschränkter Textextraktion."
fi

_info "Starte die Oberfläche unter $URL …"
"$UMG_BIN/python" -m streamlit run app.py \
    --server.port="$PORT" --server.address=localhost --server.headless=true \
    --browser.gatherUsageStats=false &
APP_PID=$!
trap 'kill $APP_PID 2>/dev/null; exit 0' INT TERM HUP

# Ruhezustand verhindern, solange die App läuft (lange KI-Läufe; nur macOS)
command -v caffeinate >/dev/null 2>&1 && caffeinate -i -w "$APP_PID" &

for _ in $(seq 1 60); do
    if curl -fs "$URL/_stcore/health" >/dev/null 2>&1; then
        oeffne_browser
        echo ""
        _info "Bereit. Zum Beenden dieses Fenster schließen oder Ctrl+C drücken."
        break
    fi
    kill -0 "$APP_PID" 2>/dev/null || { _fehler "Die Oberfläche hat sich beendet."; ende 1; }
    sleep 1
done

wait "$APP_PID"
