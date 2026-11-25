#!/bin/bash
# ============================================================================
# Vergleichslauf: dieselben Abiturvorschläge mit mehreren lokalen Modellen
# MacBook Air M4 (24 GB) – LM Studio, Ollama, Bonsai-Laufzeit
#
# Aufruf (aus dem Projektordner):
#   ./scripts/vergleichslauf_mac.sh data/klausuren/Abiturvorschlaege/2025Mechatronik
#   ./scripts/vergleichslauf_mac.sh <ordner> --nur-ki         # ohne Lösbarkeit
#
# Ergebnis: data/auswertungen/vergleich_<datum>/<provider>_<modell>/
#           plus laufzeiten.csv (Dauer je Modell und Stufe)
#
# Vorher:
#   - LM Studio: Server an, Gemma 4 12B heruntergeladen (lädt das Skript selbst)
#   - Ollama:    OLLAMA_CONTEXT_LENGTH=32768 ollama serve ; ollama pull gemma4:12b
#   - Bonsai:    Laufzeit mit Bonsai 27B gestartet, Adresse in .env (BONSAI_BASE_URL)
#   - Netzteil anschließen (MacBook Air ohne Lüfter drosselt im Akkubetrieb stärker)
# ============================================================================

set -u
cd "$(dirname "$0")/.."

# Läufe: "provider|modell"  (Modell = ID oder Teilstring; auto = Präferenzliste)
# Bei Bedarf anpassen – die Modell-IDs zeigt die Oberfläche in der Seitenleiste.
LAEUFE=(
    "lokal|gemma-4-12b"
    "ollama|gemma4:12b"
    "bonsai|auto"
)

ORDNER="${1:-}"
NUR_KI="${2:-}"
if [ -z "$ORDNER" ] || [ ! -d "$ORDNER" ]; then
    echo "Aufruf: $0 <ordner-mit-vorschlaegen> [--nur-ki]"
    exit 1
fi

PY=".venv/bin/python"
[ -x "$PY" ] || { echo "Erst ./scripts/starten.sh einmal ausführen (richtet .venv ein)."; exit 1; }

STEMPEL="$(date +%Y%m%d_%H%M)"
ZIEL="data/auswertungen/vergleich_${STEMPEL}"
AUSW_KI="src/bewertung/Auswertungen"
mkdir -p "$ZIEL" logs "$AUSW_KI" Auswertungen
echo "provider;modell;stufe;sekunden;exitcode" > "$ZIEL/laufzeiten.csv"

# Ruhezustand während des Laufs verhindern (nur macOS)
WACH=""
command -v caffeinate >/dev/null && WACH="caffeinate -i"

speicher_freigeben() {
    command -v lms    >/dev/null && lms unload --all >/dev/null 2>&1
    if command -v ollama >/dev/null; then
        for m in $(ollama ps 2>/dev/null | awk 'NR>1{print $1}'); do ollama stop "$m" >/dev/null 2>&1; done
    fi
}

stufe() {  # stufe <name> <provider> <modell> <befehl…>
    local name="$1" prov="$2" mod="$3"; shift 3
    local log="logs/vergleich_${STEMPEL}_${prov}_${mod//[:\/]/-}_${name}.log"
    local start=$(date +%s)
    echo "  → $name  (Log: $log)"
    $WACH "$@" > "$log" 2>&1
    local rc=$?
    echo "$prov;$mod;$name;$(( $(date +%s) - start ));$rc" >> "$ZIEL/laufzeiten.csv"
    [ $rc -eq 0 ] || echo "    ⚠️  Exitcode $rc – siehe Log"
}

for lauf in "${LAEUFE[@]}"; do
    PROV="${lauf%%|*}"; MOD="${lauf##*|}"
    UNTER="$ZIEL/${PROV}_${MOD//[:\/]/-}"
    mkdir -p "$UNTER"
    echo ""
    echo "=== $PROV / $MOD ==="

    speicher_freigeben
    # Checkpoints sind an den PDF-Inhalt gebunden, nicht ans Modell → löschen,
    # sonst übernimmt das zweite Modell die Antworten des ersten.
    rm -f "$AUSW_KI"/checkpoint_ki_*.json "$AUSW_KI"/checkpoint_loesbar_*.json
    MARKE="$(mktemp)"

    stufe ki "$PROV" "$MOD" "$PY" -m src.bewertung.ki_gestuetzt \
        --provider "$PROV" --modell "$MOD" --verzeichnis "$ORDNER"

    if [ "$NUR_KI" != "--nur-ki" ]; then
        stufe loesbarkeit "$PROV" "$MOD" "$PY" -m src.bewertung.loesbarkeit \
            --provider "$PROV" --modell "$MOD" --verzeichnis "$ORDNER"
    fi

    # Neue Ergebnisdateien dieses Laufs einsammeln
    find "$AUSW_KI" Auswertungen -maxdepth 1 -type f \( -name '*.xlsx' -o -name '*.json' -o -name '*.csv' \) \
         ! -name 'checkpoint_*' -newer "$MARKE" -exec mv {} "$UNTER"/ \;
    rm -f "$MARKE"

    echo "  Pause 60 s (Abkühlen) …"; sleep 60
done

speicher_freigeben
echo ""
echo "Fertig. Ergebnisse: $ZIEL"
column -s';' -t "$ZIEL/laufzeiten.csv" 2>/dev/null || cat "$ZIEL/laufzeiten.csv"
