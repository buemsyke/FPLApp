# Installation und Einrichtung

Anleitung für **Windows**, **macOS** und **Linux / Raspberry Pi**.

---

## Inhaltsverzeichnis

1. [Windows](#1-windows)
2. [macOS (Apple Silicon)](#2-macos-apple-silicon)
3. [Linux / Raspberry Pi](#3-linux--raspberry-pi)
4. [LM Studio einrichten (lokale KI)](#4-lm-studio-einrichten-lokale-ki)
5. [Cloud-Provider einrichten (optional)](#5-cloud-provider-einrichten-optional)
6. [Erste Prüfung durchführen](#6-erste-prüfung-durchführen)
7. [Fehlerbehebung](#7-fehlerbehebung)
8. [Skill für Referentinnen und Referenten](#8-skill-für-referentinnen-und-referenten)

---

## 1. Windows

### 1.1 Python installieren

1. [python.org/downloads](https://www.python.org/downloads/) → Python 3.11 oder neuer herunterladen.
2. Im Installer: **„Add Python to PATH"** aktivieren (wichtig!).
3. Prüfen:
   ```
   python --version
   ```
   Erwartete Ausgabe: `Python 3.11.x` (oder neuer)

### 1.2 Projekt-Ordner öffnen

Den Ordner `GutachtenAbiturklausur` auf dem PC ablegen, z. B. unter
`C:\Users\<Name>\Dokumente\GutachtenAbiturklausur\`.

### 1.3 Starten

Doppelklick auf `starten.bat`.

Beim ersten Start:
- wird automatisch eine virtuelle Python-Umgebung (`.venv`) erstellt,
- werden alle nötigen Pakete installiert (`openai`, `openpyxl`, `python-docx`, `pypdf`).

> **Hinweis PDF-Extraktion:** `pypdf` wird automatisch als Fallback genutzt.
> Für bessere Tabellenerkennung (besonders EWH-Tabellen) kann **Poppler** optional
> installiert werden:
> 1. [github.com/oschwartz10612/poppler-windows/releases](https://github.com/oschwartz10612/poppler-windows/releases)
>    → neueste Version als ZIP herunterladen und entpacken.
> 2. Den `bin`-Unterordner zum **PATH** hinzufügen:
>    Systemsteuerung → System → Erweiterte Systemeinstellungen → Umgebungsvariablen
>    → `PATH` → `C:\...\poppler-xx.xx.x\bin` hinzufügen.
> 3. Prüfen: `pdftotext --version`

### 1.4 LM Studio (lokale KI, optional)

Siehe [Abschnitt 4](#4-lm-studio-einrichten-lokale-ki).

### 1.5 Cloud-Provider (alternativ zur lokalen KI)

Siehe [Abschnitt 5](#5-cloud-provider-einrichten-optional).

---

## 2. macOS (Apple Silicon)

### 2.1 Einrichtung und Start – ohne Administratorrechte

Den Ordner `GutachtenAbiturklausur` auf den Mac holen (z. B. nach `Dokumente`),
dann im Finder **Doppelklick auf `Gutachten starten.command`**. Das ist alles.

**Projekt aus dem privaten GitHub-Repository holen** (`buemsyke/GutachtenAbiturklausur`,
Zugriff nur nach Einladung):

- **GitHub Desktop** (empfohlen, hält den Stand aktuell): App aus dem Download nach
  `~/Programme` ziehen (kein Administratorpasswort), anmelden, *Clone Repository* →
  `GutachtenAbiturklausur`. Später genügt *Fetch/Pull*.
- **ZIP:** auf github.com angemeldet → *Code* → *Download ZIP* → entpacken. Aus dem
  Browser geladene Dateien markiert macOS als „aus dem Internet“; dann beim ersten
  Doppelklick wie unten beschrieben *Dennoch öffnen* – oder einmal im Terminal:
  `xattr -dr com.apple.quarantine ~/Dokumente/GutachtenAbiturklausur`.

Echte Abiturvorschläge und Gutachter-Rückmeldungen liegen **nicht** im Repository
(`.gitignore`); sie bleiben lokal in `data/klausuren/Abiturvorschlaege/`.

Beim **ersten Start** (einige Minuten, ca. 1 GB Download, Internet nötig) lädt die
Datei das Werkzeug *micromamba* und legt damit Python 3.12, `pdftotext` (Poppler) und
alle Pakete im Benutzerordner an:

```
~/Library/Application Support/GutachtenAbiturklausur/
```

Kein Homebrew, kein `sudo`, keine Xcode-Werkzeuge, keine Änderung am System. Der Ort
liegt bewusst außerhalb von `Dokumente`, damit iCloud die Umgebung nicht synchronisiert.
Die gemeinsame Bibliothek **eduwerkzeuge** liegt dem Projekt als Wheel bei
(`vendor/`); `EDUWERKZEUGE_PFAD=/pfad` nimmt stattdessen einen Quellordner.
Nach einer neuen Fassung der Bibliothek das Wheel erneuern (auf dem Entwicklungsrechner):
`rm vendor/*.whl && .venv/bin/python -m pip wheel --no-deps -w vendor ../../_lib/eduwerkzeuge`
– der nächste Start auf dem Mac installiert es dann neu.

Danach öffnet sich die Oberfläche im Browser (http://localhost:8501). Weitere Starts
dauern wenige Sekunden. Beenden: Terminalfenster schließen. Während die App läuft,
verhindert `caffeinate` den Ruhezustand (lange KI-Läufe).

**macOS blockiert den ersten Doppelklick** („nicht verifizierter Entwickler“):
Systemeinstellungen → *Datenschutz & Sicherheit* → **Dennoch öffnen** (kein
Administratorpasswort nötig). Alternativ im Terminal:

```bash
bash "Gutachten starten.command"
```

Nützlich:

```bash
bash scripts/umgebung.sh pruefen     # Python, pdftotext, Pakete anzeigen
bash scripts/umgebung.sh entfernen   # Umgebung löschen (nächster Start richtet neu ein)
```

`./scripts/starten.sh` ruft auf dem Mac dieselbe Startdatei auf.

### 2.2 KI-Laufzeit ohne Administratorrechte

Provider und Modell wählt man links in der Seitenleiste von **Vorschlag prüfen**;
`.env` legt nur die Vorbelegung fest (`KI_PROVIDER`, `KI_MODELL`). Die
Regelprüfung läuft auch ganz ohne KI.

- **LM Studio:** DMG von lmstudio.ai laden, `LM Studio.app` statt nach *Programme*
  in den Ordner **`~/Programme`** (Benutzerordner → *Programme*, ggf. anlegen) ziehen –
  dafür braucht es keine Administratorrechte. Die CLI `lms` liegt danach unter
  `~/.lmstudio/bin/lms` und wird vom Werkzeug dort gefunden.
- **Ollama:** `Ollama.app` ebenso nach `~/Programme`; beim ersten Start die Frage nach
  der Installation des Befehlszeilenwerkzeugs (verlangt ein Passwort) überspringen –
  der Server läuft trotzdem.

### 2.3 Durchlauf 2026/27: MacBook Air M4, 24 GB

**Speicher:** macOS gibt der GPU standardmäßig nur einen Teil der 24 GB frei
(grob 16 GB). Deshalb gilt: **immer nur ein Modell geladen**, und LM Studio
und Ollama nicht gleichzeitig mit Modell betreiben.

| Modell | Laufzeit | Einschätzung für 24 GB |
|--------|----------|------------------------|
| Gemma 4 12B (Q4/Q8) | LM Studio oder Ollama | passt gut, auch Q8 mit 32k Kontext |
| Bonsai 27B | Bonsai-Laufzeit | Größe hängt von der Quantisierung ab; als dichtes 27B in Q4 (~16 GB) knapp, als Niedrig-Bit-Variante unkritisch |

Die genauen Modell-IDs zeigt die Seitenleiste bzw. `lms ls`, `ollama list`.
Die Präferenzliste im Code beginnt auf diesem Rechner mit
`gemma-4-12b`, `gemma4:12b`, `bonsai`.

**LM Studio** (Provider `lokal`):

```bash
lms server start
lms load gemma-4-12b --context-length 32768 --yes   # ID ggf. aus `lms ls`
```

Vorher laden, nicht erst beim ersten Aufruf (JIT): Beim automatischen Laden
nimmt LM Studio den Standardkontext des Modells, und lange Klausuren werden dann
stärker gekürzt.

**Ollama** (Provider `ollama`):

```bash
OLLAMA_CONTEXT_LENGTH=32768 ollama serve      # in eigenem Terminal
ollama pull gemma4:12b                        # Tag ggf. anpassen
```

Ohne `OLLAMA_CONTEXT_LENGTH` arbeitet Ollama mit kleinem Kontext und schneidet
den Prompt **ohne Fehlermeldung** ab. Das Werkzeug liest die Kontextgröße über
`/api/ps` aus und warnt unter 16k. Läuft die Ollama-App aus der Menüleiste, gilt
die Variable dort nicht: App beenden und `ollama serve` wie oben starten.

**Bonsai** (Provider `bonsai`): Laufzeit mit Bonsai 27B starten, Adresse des
OpenAI-kompatiblen Servers in `.env` eintragen (`BONSAI_BASE_URL`, ohne `/v1`,
Standard `http://localhost:8080`). Meldet der Server die Kontextgröße nicht
(`/props`), `KI_KONTEXT=32768` setzen. Liefert das Modell eine Denkphase vor dem
JSON, `KI_DENKPHASE_UEBERSPRINGEN=ja` setzen und Ergebnis vergleichen.

**Vergleichslauf** über alle drei Laufzeiten (KI-Prüfung + Lösbarkeit):

```bash
./scripts/vergleichslauf_mac.sh "data/klausuren/Abiturvorschlaege/Muster Informationstechnik"
```

Das Skript löscht vor jedem Modell die Checkpoints (sie hängen am PDF-Inhalt,
nicht am Modell), entlädt danach alle Modelle, hält den Mac mit `caffeinate`
wach und schreibt Ergebnisse und `laufzeiten.csv` nach
`data/auswertungen/vergleich_<datum>/`. Die Liste `LAEUFE` im Skript bei Bedarf
an die tatsächlichen Modell-IDs anpassen.

> **MacBook Air ohne Lüfter:** Bei langen Läufen taktet der M4 herunter. Am
> Netzteil, auf harter Unterlage und mit Pausen zwischen den Modellen arbeiten
> (das Skript wartet 60 s). Laufzeiten deshalb nur unter gleichen Bedingungen
> vergleichen.

### 2.4 Weitere Modelle (Apple Silicon)

| RAM | Empfohlenes Modell | Qualität | Ladezeit |
|-----|-------------------|----------|----------|
| ≥ 24 GB | `GPT-OSS-20B` oder `Gemma-3-27B-Q4` | sehr gut | ~30 s |
| 16 GB | `Qwen2.5-14B-Q4` | gut | ~20 s |
| 8 GB | `Gemma-3-12B-Q4` | ausreichend | ~15 s |
| < 8 GB | lokal nicht sinnvoll | – | – |

> **Achtung:** Modelle < 12 B Parameter (z. B. 7B, 8B) liefern bei der Interpretation
> von EWH-Tabellen und logischem Schließen deutlich schlechtere Ergebnisse.

---

## 3. Linux / Raspberry Pi

### 3.1 Abhängigkeiten installieren

```bash
# Ubuntu / Debian / Raspberry Pi OS
sudo apt-get update
sudo apt-get install -y python3 python3-venv poppler-utils

# Projekt starten (richtet venv automatisch ein)
cd GutachtenAbiturklausur
chmod +x run_ki.sh
./run_ki.sh --help
```

### 3.2 Raspberry Pi – Leistungsoptimierung

Für den lokalen Betrieb auf einem Raspberry Pi 5 / 500 (16 GB RAM) empfiehlt
sich eine Swap-Vergrößerung:

```bash
sudo ./setup_raspi.sh
```

Das Skript:
- vergrößert den Swap auf 4 GB (NVMe-basiert),
- setzt `vm.overcommit_memory=1` (verhindert OOM-Abbrüche bei großen Modellen),
- setzt `vm.swappiness=10` (RAM bevorzugen).

### 3.3 LM Studio ARM64 installieren

Für den Raspberry Pi 500 / Pi 5 wird die ARM64-Version von LM Studio benötigt.
Der Standard-Installer von lmstudio.ai ist nicht für aarch64 ausgelegt.

1. ARM64-AppImage herunterladen:
   [github.com/lmstudio-ai/lmstudio-releases](https://github.com/lmstudio-ai/lmstudio-releases)
   → Datei: `LM-Studio-<version>-arm64.AppImage`
   (getestet: **v0.4.13-1-arm64**, Mai 2026)

2. Ausführbar machen und starten:
   ```bash
   chmod +x ~/Desktop/LM-Studio-0.4.13-1-arm64.AppImage
   ~/Desktop/LM-Studio-0.4.13-1-arm64.AppImage
   ```

3. LM Studio CLI aktivieren:
   Im LM Studio GUI unter **Einstellungen → Developer** → *Install CLI* klicken.
   Die CLI liegt danach unter `~/.lmstudio/bin/lms` (nicht automatisch im PATH).
   ```bash
   # Dauerhaft in ~/.bashrc eintragen:
   echo 'export PATH="$PATH:$HOME/.lmstudio/bin"' >> ~/.bashrc
   source ~/.bashrc
   ```

### 3.4 Empfohlene Modelle (Raspberry Pi)

**Lokaler Betrieb – getestetes Setup (Raspberry Pi 500, 16 GB RAM):**

| Modell | Größe | Geschwindigkeit | Status |
|--------|-------|-----------------|--------|
| `qwen/qwen3.5-9b` (Q4_K_M) | 5,6 GB | ~1 tok/s | ✅ getestet, empfohlen |
| Gemma-4 (beliebig) | je nach Quantisierung | sehr langsam | ❌ kein KV-Cache (SWA) |

Download in LM Studio:
1. Tab **"Discover"** → Suchfeld: `qwen3.5`
2. `Qwen3.5-9B` → **„Download"** → Quantisierung `Q4_K_M` wählen (5,6 GB)

> **Hinweis Thinking-Modell:** Qwen3.5-9b ist ein Thinking-Modell. Das Skript
> `klausur_ki_gestuetzt.py` erkennt Qwen3-Modelle automatisch und deaktiviert das
> Thinking intern – kein manueller Eingriff nötig.

**LM Studio Servereinstellungen (wichtig für RPi):**

Im LM Studio GUI, Tab **"Developer"** → Modell laden → Einstellungen (Zahnrad):

| Einstellung | Wert | Begründung |
|-------------|------|------------|
| Parallel Requests | **1** | Verhindert OOM-Abbrüche bei 16 GB RAM |
| Context Length | 16384 | Reicht für eine vollständige Prüfung |
| GPU Layers | 0 | RPi hat keine kompatible GPU |

```bash
# LM Studio Server starten:
~/.lmstudio/bin/lms server start
# Geladenes Modell prüfen:
~/.lmstudio/bin/lms ps
# Server erreichbar?
curl http://localhost:1234/v1/models
```

**Performance-Erwartungen auf dem Raspberry Pi 500 (Cortex-A76, 16 GB):**

| Phase | Dauer |
|-------|-------|
| Modell laden | ~30 s |
| Kontextaufbau Batch 1 (Prefill ~8000 Tokens) | ~10 min |
| Folgebatches mit KV-Cache | ~5–8 min/Batch |
| Vollständige KI-Prüfung (12 Kriterien) | ~60–80 min |

**Cloud-Provider (Alternative für schnellere Ergebnisse):**

```bash
# GWDG – kostenlos für Schulen (DFN-AAI-Account)
export GWDG_API_KEY='dein-key'
./run_ki.sh --provider gwdg --verzeichnis Klausuren

# Hetzner – kostenpflichtig, sehr schnell
export HETZNER_AI_API_KEY='dein-key'
./run_ki.sh --provider hetzner --verzeichnis Klausuren
```

---

## 4. LM Studio einrichten (lokale KI)

LM Studio stellt eine lokale, OpenAI-kompatible API bereit.
Die Klausurtexte verlassen den Rechner nicht.

### 4.1 LM Studio installieren

| Plattform | Download |
|-----------|----------|
| Windows | [lmstudio.ai](https://lmstudio.ai) |
| macOS | [lmstudio.ai](https://lmstudio.ai) |
| Linux (x86_64) | [lmstudio.ai](https://lmstudio.ai) |
| **Raspberry Pi (aarch64)** | [github.com/lmstudio-ai/lmstudio-releases](https://github.com/lmstudio-ai/lmstudio-releases) → ARM64-AppImage |

> **Raspberry Pi:** Nur die ARM64-Version funktioniert auf aarch64-Systemen.
> Details: [Abschnitt 3.3](#33-lm-studio-arm64-installieren).

### 4.2 Modell herunterladen

**Empfohlene Modelle nach Plattform:**

| Plattform | Empfohlenes Modell | Größe | Hinweis |
|-----------|--------------------|-------|---------|
| Raspberry Pi 500/5 (16 GB) | `qwen/qwen3.5-9b` Q4_K_M | 5,6 GB | ✅ getestet |
| macOS Apple Silicon ≥ 24 GB | `Gemma-3-27B` Q4 | ~16 GB | sehr gut |
| macOS Apple Silicon 16 GB | `Qwen2.5-14B` Q4 | ~9 GB | gut |
| Windows / Linux ≥ 16 GB RAM | `Qwen2.5-14B` Q4 | ~9 GB | gut |

> **Achtung:** Modelle < 12 B Parameter (z. B. 7B, 8B) liefern bei der Interpretation
> von EWH-Tabellen und logischem Schließen deutlich schlechtere Ergebnisse.

> **Hinweis Thinking-Modelle:** Qwen3.x-Modelle haben standardmäßig einen
> Reasoning-Modus aktiv. `klausur_ki_gestuetzt.py` erkennt Qwen3-Modelle automatisch
> am Modellnamen und aktiviert die nötige Gegenmaßnahme – kein manueller Eingriff nötig.

In LM Studio:
1. Tab **„Discover"** → Suchfeld: Modellname (z. B. `qwen3.5`)
2. Modell herunterladen, Quantisierung `Q4_K_M` wählen

Oder über die CLI:
```bash
# Raspberry Pi:
~/.lmstudio/bin/lms download qwen/qwen3.5-9b-mlx --quantization q4_k_m
# macOS (lms im PATH):
lms download google/gemma-3-27b-it-qat-q4_0-gguf
```

### 4.3 Server starten

In LM Studio:
1. Tab **„Developer"** → Modell auswählen und laden
2. Server starten (grüner Button, Port 1234)

Oder per CLI:
```bash
# macOS / Linux mit lms im PATH:
lms server start

# Raspberry Pi (lms nicht automatisch im PATH):
~/.lmstudio/bin/lms server start
```

Das Skript `klausur_ki_gestuetzt.py` erkennt und startet den Server automatisch,
wenn die CLI (`lms`) im PATH vorhanden ist.

### 4.4 Server-URL prüfen

```bash
curl http://localhost:1234/v1/models
```
Erwartete Ausgabe: JSON mit dem Namen des geladenen Modells.

---

## 5. Cloud-Provider einrichten (optional)

### 5.1 Hetzner AI Inference

Serverstandort Deutschland, DSGVO-konform, sehr schnell.

1. Account unter [console.hetzner.cloud](https://console.hetzner.cloud) erstellen.
2. Unter **API-Tokens** einen neuen Token erstellen.
3. Umgebungsvariable setzen:
   ```bash
   export HETZNER_AI_API_KEY='htz-...'
   ```
4. Prüfung starten:
   ```bash
   ./starten.sh --provider hetzner
   # oder unter Linux:
   ./run_ki.sh --provider hetzner --verzeichnis Klausuren
   ```

### 5.2 GWDG Akademische Cloud

Serverstandort Göttingen, DSGVO-konform, für Schulen / Hochschulen geeignet
(DFN-AAI / GWDG-Account erforderlich).

1. Account unter [chat.gwdg.de](https://chat.gwdg.de) mit DFN-AAI-Login erstellen.
2. Im GWDG-Portal unter **„API-Schlüssel"** einen Token erstellen.
3. Umgebungsvariable setzen:
   ```bash
   export GWDG_API_KEY='gwdg-...'
   ```
4. Prüfung starten:
   ```bash
   ./starten.sh --provider gwdg
   ```

### 5.3 API-Keys dauerhaft speichern

```bash
# In ~/.zshrc (macOS) oder ~/.bashrc (Linux) eintragen:
echo 'export HETZNER_AI_API_KEY="htz-..."' >> ~/.zshrc
echo 'export GWDG_API_KEY="gwdg-..."' >> ~/.zshrc
source ~/.zshrc
```

Unter Windows: Systemsteuerung → System → Erweiterte Systemeinstellungen
→ Umgebungsvariablen.

---

## 6. Erste Prüfung durchführen

### 6.1 Testdaten nutzen

Im Ordner `Klausuren/Abiturvorschläge/` befinden sich Beispiel-Vorschläge aus den
Vorjahren 2021–2025 (sofern vorhanden).

```bash
# macOS – Beispielvorschlag 2025 prüfen:
./starten.sh --verzeichnis Klausuren/Abiturvorschläge/2025Mechatronik

# Linux:
./run_ki.sh --verzeichnis Klausuren/Abiturvorschläge/2025Mechatronik
```

### 6.2 Nur die automatische Prüfung (ohne KI)

```bash
python klausur_regelbasiert.py Klausuren/Vorschlag/SM.pdf Klausuren/Vorschlag/LM_EWH.pdf
```

### 6.3 Vollständige KI-Prüfung

```bash
python klausur_ki_gestuetzt.py --verzeichnis Klausuren
```

### 6.4 Alle Optionen anzeigen

```bash
python klausur_ki_gestuetzt.py --help
python klausur_regelbasiert.py --help
```

---

## 7. Fehlerbehebung

### „pdftotext nicht gefunden"

```bash
# macOS: wird von „Gutachten starten.command“ mit eingerichtet
bash scripts/umgebung.sh pruefen

# Ubuntu / Debian:
sudo apt-get install poppler-utils
```

`pypdf` wird automatisch als Fallback verwendet – die Prüfung läuft auch ohne
`pdftotext`, aber Tabellenstrukturen (EWH) werden eventuell schlechter erkannt.

### „LM Studio Server nicht erreichbar"

1. LM Studio öffnen → Tab **„Developer"** → Server starten (grüner Button).
2. Prüfen ob Port 1234 frei ist: `lsof -i :1234`
3. Alternativ Cloud-Provider nutzen: `--provider hetzner`

### „Modell antwortet nicht / Timeout"

- Wurde das Modell vollständig geladen? (LM Studio GUI → Modell-Status)
- Reicht der RAM? Ein 9B-Modell (Q4) benötigt ca. 6–7 GB RAM, ein 14B ca. 10 GB.
- Kleineres Modell versuchen (z. B. `Qwen3.5-9B`).
- Timeout erhöhen: `python klausur_ki_gestuetzt.py --timeout 3600 ...`
- **Raspberry Pi:** `Parallel Requests` in LM Studio auf **1** setzen
  (Tab Developer → Modell laden → Einstellungen/Zahnrad).

### Qwen3-Modell gibt leere Antworten

`klausur_ki_gestuetzt.py` erkennt Qwen3-Modelle am Modellnamen und aktiviert die
Thinking-Unterdrückung automatisch. Voraussetzung: Der in LM Studio angezeigte
Modellname enthält `qwen3` oder `qwen3.5`. Prüfen:

```bash
curl -s http://localhost:1234/v1/models | python3 -m json.tool
```

Der `id`-Wert muss `qwen3` oder `qwen3.5` enthalten.

### Checkpoint löschen (Prüfung neu starten)

```bash
rm Auswertungen/checkpoint_*.json
```

### „Keine Vorschläge gefunden"

Das SM/LM-Paar wird über den Dateinamen erkannt. Lehrermaterial muss
`_EWH`, `Lehrer`, `_L` oder `<Zahl>L` im Dateinamen enthalten.
Beispiel: `2025MechaAufg.pdf` + `2025MechaAufg_EWH.pdf`.

Diagnose:
```bash
python -c "
from klausur_regelbasiert import finde_vorschlaege
vs = finde_vorschlaege('Klausuren')
for v in vs:
    print(v)
"
```

### Python-Paket fehlt

```bash
source .venv/bin/activate      # (Linux/macOS)
.venv\Scripts\activate.bat     # (Windows)
pip install openai python-docx openpyxl pypdf
```

---

## 8. Skill für Referentinnen und Referenten

Dieselbe Prüfung gibt es als Claude-Skill **`abiturvorschlag-begutachten`**. Regelprüfung,
Prüfanweisungen, Gutachten-Raster und Hinweisliste kommen aus denselben Modulen wie
die App; statt eines lokalen Modells urteilt Claude. Ergebnis: `Gutachten_*.docx`
(Raster), `Hinweise_*_claude.xlsx/.csv`, `KI_Pruefung_*`, `Loesbarkeit_*`, `Bericht_*.md`.

> **Vertraulichkeit:** Der Skill gibt die Texte der Vorschläge an Claude. Nur in einer
> von der Dienststelle für vertrauliche Prüfungsunterlagen freigegebenen Umgebung
> verwenden – sonst die App mit lokalem Modell.

### 8.1 Paket bauen (Fachberatung)

```bash
python3 scripts/skill_bauen.py                 # → dist/abiturvorschlag-begutachten.skill
python3 scripts/skill_bauen.py --installieren  # zusätzlich für Claude Code dieses Benutzers
```

Nach jeder Änderung an `src/` oder `skill/` neu bauen und die `.skill`-Datei weitergeben.

Fertige Pakete liegen im privaten Repository unter **Releases**
(`abiturvorschlag-begutachten.skill`). Neue Fassung veröffentlichen:

```bash
python3 scripts/skill_bauen.py
gh release create skill-v1.1 dist/abiturvorschlag-begutachten.skill --title "Skill 1.1" --notes "…"
```

Die `.skill`-Datei nur an Referentinnen und Referenten weitergeben, nicht in die
öffentliche Skill-Bibliothek – sie enthält die vollständigen Prüfanweisungen.

### 8.2 Installieren (keine Administratorrechte)

- **Claude-App / claude.ai:** Einstellungen → *Fähigkeiten* → *Skills* → Skill
  hochladen → `abiturvorschlag-begutachten.skill`. Die Skripte laufen in der
  Code-Ausführung von Claude; auf dem Mac ist nichts zu installieren.
- **Claude Code (Mac):** Paket nach `~/.claude/skills/` entpacken:

  ```bash
  mkdir -p ~/.claude/skills && unzip -o abiturvorschlag-begutachten.skill -d ~/.claude/skills
  ```

  Die Skripte laufen dann lokal. Ist die App eingerichtet, nutzen sie deren Umgebung
  automatisch; sonst einmalig
  `bash ~/.claude/skills/abiturvorschlag-begutachten/scripts/einrichten.sh`
  (Python 3.12 + pdftotext im Benutzerordner, wie 2.1).

### 8.3 Verwenden

Im Chat: *„Begutachte Vorschlag A – Schülermaterial `SM.pdf`, Lehrermaterial `LM.pdf`.“*
Claude führt `vorbereiten` aus, prüft die offenen Kriterien und alle Teilaufgaben,
trägt die Urteile in `urteile.json` ein und erzeugt mit `abschliessen` die Dateien.
Beanstandungen ohne wörtlich belegtes Zitat oder unter 75 % Konfidenz werden
automatisch zu „nicht prüfbar“.

