# KI-gestützte Begutachtung von Abiturklausur-Vorschlägen

Automatisches Werkzeug zur Vorprüfung von Abiturklausur-Vorschlägen am
**Beruflichen Gymnasium Technik – Schwerpunkt Informationstechnik (Niedersachsen)**.

Es prüft Schüler- und Lehrermaterial gegen die amtlichen Kriterien der
Gutachtenvorlage, die Operatorentabelle und die Vorgaben aus den
Rahmenrichtlinien.

---

## Was das Werkzeug leistet

### Stufe 1 – Regelbasierte automatische Prüfung (`klausur_regelbasiert.py`)

Rund **30 Kriterien** werden vollautomatisch geprüft:

| Bereich | Beispielkriterien |
|---------|------------------|
| **1. Formales** | Dokumentenvorlage MK, Bearbeitungszeit, Deckblatt |
| **2. Eingereichte Unterlagen** | Lerngebietszuordnung, Erwartungshorizont, Bewertungsschema, Hilfsmittel |
| **3. Fachliches** | RRL-Kompetenzen, Lerngebiete IT1–IT5, Ganzheitlichkeit, Praxisbezug |
| **4. Transparenz** | Aufgabenformulierung, Unabhängigkeit der Teilaufgaben, AFB-Verteilung, Operatoren nach EPA |
| **X. Zusatz** | BE statt „Punkte", Operatoren SM ↔ EWH, BE/Zeit-Verhältnis, Nicht-EPA-Operatoren |

**Ausgabe:**
- Konsolenausgabe mit ✅ / ❌ / ⚠️ pro Kriterium
- **DOCX-Gutachten**: Das Raster der Vorlage wird mit ✔ / ✘ / ? ausgefüllt. Hinweise stehen
  nicht darin, die „?“-Kriterien prüft die Fachberatung selbst.
- **Hinweisliste** (`Hinweise_*.xlsx` und `.csv`): Hinweise an die Schule im Format der
  versendeten Listen – je Vorschlag ein Block mit Aufgabe · Hinweis · Schülermaterial ·
  Lehrermaterial · Hinweise · Überarbeitet am. Die interne Spalte „Herkunft“ nennt Regel
  bzw. Modell und Konfidenz; KI-Hinweise sind gelb markiert. Vor dem Versand prüfen und
  die Spalte „Herkunft“ löschen. Im Verzeichnismodus entsteht zusätzlich eine Sammelliste
  `Hinweise_<Verzeichnis>.*` mit allen Vorschlägen.
- **XLSX-Rückmeldung** (alle Kriterien, aufgabenorientiert, sortierbar – internes Prüfprotokoll)

### Stufe 2 – KI-gestützte Prüfung (`klausur_ki_gestuetzt.py`)

Kriterien, die sich nicht rein regelbasiert prüfen lassen (z. B. Ganzheitlichkeit,
Kompetenzorientierung, AFB-Zuordnungsqualität), werden an ein **Sprachmodell** übergeben.

### Stufe 3 – Lösbarkeits- und Richtigkeitsprüfung (`klausur_loesbarkeit.py`)

Pro Teilaufgabe wird das Sprachmodell mit Aufgabentext, Musterlösung und
lerngebietsspezifischen Prüfhinweisen (IT1–IT5) gefragt:

- **A) Lösbarkeit:** Hat der Prüfling alle Informationen?
- **B) Fachliche Richtigkeit:** Ist die Musterlösung korrekt?

Aufruf: `./starten.sh --loesbarkeit` (macOS) bzw.
`python klausur_loesbarkeit.py <SM.pdf> <LM.pdf>`.

Ausgabe: `Auswertungen/Loesbarkeit_<…>.xlsx` und `.json`.

Validitätsregel: bei fehlender Musterlösung, leeren Anlagenverweisen oder
rein visuell zu lösenden Aufgaben (IT5) wird `nicht_pruefbar` gemeldet – es
wird nie geraten.

- **Lokal** (Standard): [LM Studio](https://lmstudio.ai) auf dem eigenen Rechner –
  Daten verlassen den Rechner nicht.
- **Cloud** (DSGVO-konform, optional): Hetzner AI Inference oder GWDG Akademische Cloud
  (Serverstandort Deutschland).

Das Modell antwortet strukturiert (JSON) mit Ergebnis, Konfidenzwert und Begründung.
Nur Ergebnisse mit Konfidenz ≥ 75 % werden als Beanstandung gewertet.

**Ausgabe:**
- Konsolenausgabe mit ❌ / ✅ / ⚠️ pro KI-geprüftem Kriterium
- **XLSX-Bericht** (KI-Ergebnis, Konfidenz, Begründung, Fundstellen)
- **Hinweisliste je Modell** (`Hinweise_<…>_<modell>.xlsx/.csv`): Regel-Hinweise plus
  KI-Beanstandungen ab 75 %. Weil die Urteile stark vom Modell abhängen, lassen sich die
  Listen verschiedener Modelle so direkt nebeneinanderlegen.

---

## Projektstruktur

> **Einrichtung:** Den Ordner `GutachtenAbiturklausur/` auf den Rechner kopieren –
> das ist alles. Dann die passende Startdatei für das jeweilige Betriebssystem öffnen.

```
GutachtenAbiturklausur/
├── klausur_regelbasiert.py  # Stufe 1: Regelbasierte automatische Prüfung
├── klausur_ki_gestuetzt.py  # Stufe 2: KI-gestützte Prüfung
│
├── starten.bat              # Windows:           Doppelklick zum Starten
├── Gutachten starten.command # macOS:            Doppelklick (ohne Adminrechte)
├── skill/                   # Quelle des Claude-Skills abiturvorschlag-begutachten
├── vendor/                  # eduwerkzeuge als Wheel (für den Mac)
├── run_ki.sh                # Linux / Raspberry Pi: ./run_ki.sh im Terminal
├── setup_mac.sh             # macOS: Ersteinrichtung (Homebrew, Python, LM Studio)
├── setup_raspi.sh           # Raspberry Pi: Optimierung (Swap, Overcommit)
│
├── Klausuren/               # ← Hier eigene Klausuren ablegen
│   ├── HINWEIS.txt          #   Erläuterung zur Datei-Konvention
│   └── Abiturvorschläge/    #   Beispielvorschläge aus Vorjahren (2021–2025)
│       ├── 2021Mecha/
│       ├── 2022Mecha/
│       ├── 2023Mechatronik/
│       ├── 2024_Mechatronik/
│       └── 2025Mechatronik/
├── Material/                # Gutachten-Vorlage (DOCX)
└── Auswertungen/            # ← Hier erscheinen die Ergebnisse
```

---

## Schnellstart

### 1. Klausur-PDFs ablegen

Lege Schüler- und Lehrermaterial paarweise in `Klausuren/` ab.
Das Lehrermaterial wird automatisch erkannt, wenn der Dateiname eines der
folgenden Muster enthält: `_EWH`, `Lehrer`, `_L` oder `<Zahl>L`.

```
Klausuren/
  Vorschlag_A/
    2025MechaEAAufgA.pdf          ← Schülermaterial
    2025MechaEAAufgA_EWH.pdf      ← Lehrermaterial
```

Zum Testen liegen im Ordner `Klausuren/Abiturvorschläge/` fertige Beispiele
aus den Vorjahren 2021–2025.

Ausführliche Beschreibung: [Klausuren/HINWEIS.txt](Klausuren/HINWEIS.txt)

### 2. Starten

| Betriebssystem | Datei / Befehl |
|----------------|----------------|
| **Windows** | Doppelklick auf `starten.bat` |
| **macOS** | Doppelklick auf `Gutachten starten.command` – ohne Adminrechte, richtet Python + pdftotext selbst ein |
| **Linux / RPi** | `./run_ki.sh` im Terminal |

Beim **ersten Start** wird die Python-Umgebung automatisch eingerichtet
(macOS: im Benutzerordner, ohne Homebrew – siehe [INSTALLATION.md](docs/INSTALLATION.md#2-macos-apple-silicon)).

**Als Claude-Skill** für Referentinnen und Referenten: `python3 scripts/skill_bauen.py`
erzeugt `dist/abiturvorschlag-begutachten.skill` – gleiche Prüfung, Claude statt
lokalem Modell ([INSTALLATION.md, Abschnitt 8](docs/INSTALLATION.md#8-skill-für-referentinnen-und-referenten)).
Das fertige Paket hängt in diesem (privaten) Repository unter *Releases*.

### 3. Ergebnisse öffnen

Die Ergebnisse erscheinen im Ordner `Auswertungen/`:

| Datei | Inhalt |
|-------|--------|
| `Gutachten_*.docx` | Gutachten-Raster (✔ / ✘ / ?), ohne Hinweistext |
| `Hinweise_*.xlsx` / `.csv` | Hinweise an die Schule im Format der versendeten Listen |
| `Rueckmeldung_*.xlsx` | Aufgabenorientiertes Prüfprotokoll (alle Kriterien) |
| `KI_Pruefung_*.xlsx` | KI-Ergebnisse (nur bei `klausur_ki_gestuetzt.py`) |

---

## Wie die automatische Prüfung funktioniert

```
PDF/DOCX
   │
   ▼
extract_text()          ← pdftotext (Poppler) oder pypdf als Fallback
   │
   ▼
parse_aufgaben()        ← Erkennt Aufgaben, Teilaufgaben, Punkte
parse_erwartungshorizont_afb()  ← Liest AFB-Verteilung aus EWH-Tabelle
   │
   ▼
check_*()               ← ~30 regelbasierte Prüffunktionen
   │
   ├── erfuellt=True    → ✅ Direkt ins Gutachten
   ├── erfuellt=False   → ❌ Beanstandung ins Gutachten
   └── erfuellt=None    → ⚠️  → weiter zu Stufe 2 (KI)
```

### Wie die KI-Prüfung funktioniert

```
⚠️-Kriterien aus Stufe 1
   │
   ▼
_baue_prompt()          ← Kriterium + Schülermaterial + Lehrermaterial
   │
   ▼
LLM-Aufruf              ← LM Studio (lokal) oder Cloud-Provider
   │
   ▼
JSON-Antwort:           ergebnis | konfidenz | begründung | fundstellen
   │
   ├── konfidenz < 75%  → ⚠️  „nicht sicher prüfbar"
   ├── keine_beanstandung → ✅
   └── beanstandung     → ❌ mit Begründung + Fundstellen
```

Ein **Checkpoint-Mechanismus** speichert den Fortschritt nach jedem Kriterium.
Bei Abbruch (z. B. Timeout) kann die Prüfung dort fortgesetzt werden.

---

## KI-Provider

```bash
# Lokale KI (Standard, kein API-Key nötig) – Provider in der Seitenleiste wählbar
./scripts/starten.sh

# Lokale Laufzeiten (Vorbelegung in .env: KI_PROVIDER, KI_MODELL)
#   lokal  = LM Studio (1234) · ollama = Ollama (11434) · bonsai = Bonsai-Laufzeit
python -m src.bewertung.ki_gestuetzt --provider ollama --modell gemma4:12b SM.pdf LM.pdf

# Vergleich mehrerer lokaler Modelle (MacBook M4): siehe docs/INSTALLATION.md 2.3
./scripts/vergleichslauf_mac.sh "data/klausuren/Abiturvorschlaege/Muster Informationstechnik"

# Hetzner AI (DSGVO, Serverstandort DE)
export HETZNER_AI_API_KEY='dein-key'
./starten.sh --provider hetzner

# GWDG Akademische Cloud (Göttingen, DSGVO)
export GWDG_API_KEY='dein-key'
./starten.sh --provider gwdg

# Provider-Übersicht
./starten.sh --provider-info
```

Für den lokalen Modus wird [LM Studio](https://lmstudio.ai) benötigt.
Empfohlene Modelle und Einrichtung: [INSTALLATION.md](INSTALLATION.md)

---

## Voraussetzungen

- **Python 3.10+**
- **Python-Pakete:** `openai`, `python-docx`, `openpyxl`, `pypdf`
- **PDF-Extraktion:** `pdftotext` (Poppler) oder pypdf (automatischer Fallback)
- **KI lokal:** LM Studio mit geladenem Modell (≥ 12 B Parameter empfohlen)

Detaillierte Installationsanleitung: [INSTALLATION.md](INSTALLATION.md)

---

## Datenschutz

| Modus | Datenweitergabe |
|-------|-----------------|
| Lokal (LM Studio, Ollama, Bonsai) | Keine – Daten verlassen den Rechner nicht |
| Hetzner | Server in Deutschland, DSGVO-konform |
| GWDG | Server in Göttingen (DFN/GWDG), für Schulen geeignet |

---

## Weiterentwicklung

Das Werkzeug ist darauf ausgelegt, schrittweise verbessert zu werden.
Anleitung zum Hinzufügen neuer Kriterien, Verbessern der KI-Prompts und
Anpassen der Konfiguration: [CONTRIBUTING.md](CONTRIBUTING.md)
