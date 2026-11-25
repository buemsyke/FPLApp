# Lokale LLM-Tricks – Raspberry Pi 5/500 (aarch64, 16 GB)

Wiederverwendbare Parameter, Konfigurationen und Tricks für lokale Sprachmodelle via **LM Studio** (OpenAI-kompatibel). Erprobt in diesem Projekt mit Qwen3.5-9B, Ministral-3-14B-reasoning, GPT-OSS-20B, LFM2-24B-A2B und Gemma.

Übertragbar auf andere Projekte mit OpenAI-kompatiblem Inferenz-Server (LM Studio, llama.cpp, vLLM, Ollama).

---

## Plattform-Setup Raspberry Pi 500 (16 GB RAM, aarch64)

**LM Studio ARM64** (Standard-Installer von lmstudio.ai funktioniert NICHT auf aarch64):
- AppImage von [github.com/lmstudio-ai/lmstudio-releases](https://github.com/lmstudio-ai/lmstudio-releases) → getestet: **v0.4.13-1-arm64** (Mai 2026)
- CLI nach Install unter `~/.lmstudio/bin/lms` (nicht im PATH → manuell exportieren):
  ```bash
  echo 'export PATH="$PATH:$HOME/.lmstudio/bin"' >> ~/.bashrc
  ```

**OS-Tuning (verhindert OOM-Abbrüche)** – siehe [setup_raspi.sh](setup_raspi.sh):
- Swap = **4096 MB** auf NVMe via `dphys-swapfile`
- `vm.overcommit_memory = 1` (Speicher-Overcommit erlauben)
- `vm.swappiness = 10` (RAM bevorzugen)

**LM Studio GUI-Einstellungen (Tab Developer → Zahnrad):**
| Einstellung | Wert | Grund |
|-------------|------|-------|
| Parallel Requests | **1** | OOM-Schutz |
| Context Length | 16384 (max 32768 via `lms load --context-length 32768`) | Reicht für vollständige Prüfung |
| GPU Layers | **0** | RPi hat keine kompatible GPU |

---

## Modellspezifische Tricks

### Qwen3.5-9B (Q4_K_M, 5,6 GB) – empfohlen für RPi 500
- Modell-ID in LM Studio: `qwen/qwen3.5-9b`
- Performance: ~1 tok/s, Prefill Batch 1 ~10 min, gesamte 12-Krit.-Prüfung 60–80 min
- **Thinking-Unterdrückung via Assistant-Prefill:** `enable_thinking=False` wird IGNORIERT – nur Prefill funktioniert
- `max_tokens = 1500` (statt 3000, kein Reasoning mehr nötig)

### Ministral-3-14B-reasoning / Magistral
- Modell-ID: `mistralai/ministral-3-14b-reasoning`
- Gleicher Prefill-Trick wie Qwen3 (Pattern-Match: `-reasoning`, `ministral`, `magistral`)

### GPT-OSS-20B
- Modell-ID: `openai/gpt-oss-20b`
- KEIN Thinking-Modell → `max_tokens = 3000`, kein Prefill nötig
- Primär für Apple Silicon ≥ 24 GB, läuft aber auch auf RPi

### LFM2-24B-A2B (Liquid)
- Modell-ID: `liquid/lfm2-24b-a2b`
- MoE mit ~2B aktiven Parametern → läuft mit Standard-Settings, kein Thinking-Trick

### Gemma-4 – auf dem RPi **NICHT empfohlen**, auf Apple Silicon neu messen
- RPi (CPU): Kein KV-Cache-Wiederverwendung (SWA = Sliding Window Attention) → jeder Batch komplettes Prefill → extrem langsam
- Die Messung stammt von der CPU-Inferenz auf dem RPi. Auf dem M4 (GPU, Metal/MLX) ist
  Prefill um ein Vielfaches schneller; Gemma 4 12B ist dort Erstwahl für den Durchlauf
  2026/27 (siehe Abschnitt *Apple Silicon M4* unten). Erst nach eigener Messung übernehmen.

### NVIDIA Nemotron-3-Nano-4B – **NICHT empfohlen**
- Modell-ID in LM Studio: `nvidia/nemotron-3-nano-4b`
- Architektur: **Nemotron-H** (Mamba/Attention-Hybrid) – kein Standard-Transformer
- Kein Thinking-Modell → kein `<think>`-Prefill, `max_tokens = 3000`
- **Prefill RPi 4 (aarch64, 8 GB):** ~15 Tok/s → 11k-Token-Kontext ≈ 12 Min Prefill
  - Mit `--timeout 600` (Default): ReadTimeout vor erstem Token → Kriterium landet in `nicht_pruefbar`
  - Mit `--timeout 1800` (30 Min): Prefill abgeschlossen, aber Modell liefert für ~60 % der
    Kriterien **leere oder nicht-JSON-konforme Antworten** (`ki_ergebnis: nicht_pruefbar, begruendung: "KI-Antwort war kein gültiges JSON: "`)
- Endergebnis Musterklausur: 5/13 ✅ | 8/13 ⚠️ nicht_pruefbar — nicht auswertbar
- **Fazit:** 4B zu klein für strukturierten JSON-Output bei komplexen Kriterien; nur empfehlenswert als Smoke-Test

### Modellgröße-Warnung
Modelle **< 12 B** liefern bei Tabellen-Interpretation und logischem Schließen deutlich schlechtere Ergebnisse.

Pattern-Fallstrick: `"4b-"` matcht fälschlich `"14b-"` (Ministral 14B) – nur `"-4b"` verwenden.

---

## Globale API-Parameter (alle Modelle, OpenAI-SDK)

```python
temperature = 0.1          # Hauptaufruf (konsistente Antworten)
temperature = 0.0          # Health-Check
stream      = True         # Timeout zählt nur zwischen Tokens
max_retries = 0            # im SDK – eigene Retry-Logik (SDK-Default 2 versteckt Wartezeiten)
max_tokens  = 1500 * n     # Thinking-Modelle mit Prefill
max_tokens  = 3000 * n     # Standard-Modelle
API_TIMEOUT = 3600         # RPi/CPU
API_TIMEOUT = 600          # Apple Silicon (GPU-beschleunigt)
API_TIMEOUT = 300          # Cloud-Provider
HEALTH_CHECK_TIMEOUT = 300 # 14B+ braucht ~2 min nur für Prompt-Verarbeitung
BATCH_GROESSE = 1          # lokal (maximale Zuverlässigkeit)
BATCH_GROESSE = 4          # Cloud
PAUSE_ZWISCHEN_AUFRUFEN = 2  # Sekunden – LM Studio kann Ressourcen freigeben
```

---

## Wiederverwendbare Tricks

### Trick A – Thinking-Modelle zwingen, sofort JSON zu liefern
```python
messages = [
    {"role": "system",    "content": SYSTEM_PROMPT},
    {"role": "user",      "content": prompt},
    {"role": "assistant", "content": "<think>\n\n</think>\n\n"},  # Prefill
]
```
Wirkt bei Qwen3.x, Ministral-reasoning, Magistral. Erkennung per Pattern-Match im Modellnamen.

### Trick B – Fallback-Cleanup von Thinking-Artefakten
```python
text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text, flags=re.IGNORECASE)
```

### Trick C – Kontextfenster-Überlauf erkennen (LM Studio / llama.cpp)
```python
m = re.search(r"n_keep:\s*\d+\s*>=?\s*n_ctx:\s*(\d+)", fehler_text)
```
Bei Treffer: automatisch auf Einzelabfragen mit gekürztem Text (≈30 % von n_ctx · 4 Zeichen) wechseln.

### Trick D – Streaming mit Live-Fortschritt
Alle 20 Chunks ein `"."` ausgeben → erkennbar ob Modell noch arbeitet oder hängt.

### Trick E – Aktive Bereitschaftsprüfung vor jedem Aufruf
`/v1/models` alle 0.5 s pollen (leichtgewichtig) statt direkt schweren Chat-Aufruf wagen.

### Trick F – Wrapper-Verwechslung verhindern
Wenn Software Inhalte mit Markern wie `=== ABSCHNITT ===` umhüllt, interpretieren kleinere Modelle das als Dokumentanfang. Explizite Regel im System-Prompt nötig: „Diese Trennzeichen sind KEIN Inhalt, sondern Software-Marker."

### Trick G – OpenAI-kompatible Provider-Abstraktion
Lokal (LM Studio), Hetzner, GWDG über identisches SDK – nur `base_url`, `api_key`, `model`, `timeout`, `batch_groesse` unterscheiden sich. Wechsel ohne Code-Änderung möglich.

### Trick H – CLI-basiertes Auto-Laden mit Präferenzliste
```bash
lms load <pref> --yes --context-length 32768
```
Iteriere bevorzugte Modelle und nimm das erste lokal vorhandene.

---

## Kontextfenster-Budget berechnen (dynamisch)

```
overhead_system    = 700                  # System-Prompt
overhead_kriterien = 300 * batch_groesse
output_tokens      = 1500*b (Thinking)  oder  3000*b (Standard)
puffer             = 10 % von n_ctx
verfuegbar = n_ctx − overhead_system − overhead_kriterien − output_tokens − puffer
pro_dokument = max(2000, verfuegbar / 2 * 3.5)   # 3.5 Zeichen/Token (Deutsch)
```

Kontextgrößen-Erkennung in dieser Reihenfolge:
1. `GET /v1/models` → `context_length` / `max_model_len`
2. `lms ps` (Plausibilitätsbereich 1k–200k Token)
3. Fallback **8192**

---

## Performance-Erwartungen RPi 500 (Cortex-A76, 16 GB)

| Phase | Dauer |
|-------|-------|
| Modell laden | ~30 s |
| Kontextaufbau Batch 1 (Prefill ~8000 Tokens) | ~10 min |
| Folgebatches mit KV-Cache | ~5–8 min/Batch |
| Vollständige Prüfung (12 Kriterien) | ~60–80 min |

## Performance-Erwartungen RPi 4 (Cortex-A72, 8 GB)

| Modell | Prefill ~11k Token | Tok/s | Vollst. Prüfung |
|--------|--------------------|-------|------------------|
| Nemotron-3-Nano-4B (Q4_K_M, 2,84 GB) | ~12 min | ~15 | ~120 min (viele Fehler) |
| Qwen3.5-9B (Q4_K_M, 5,6 GB) | ~15 min (est.) | ~10 | ~90–120 min |

**Wichtig RPi 4:** `--timeout 1800` Mindestvorgabe bei Modellen > 4B; `--timeout 3600` für 9B+ sicherer.

---

## Cloud-Alternativen (DSGVO, OpenAI-kompatibel)

| Provider | base_url | Modell | Hinweis |
|----------|----------|--------|---------|
| Hetzner AI Inference | `https://inference.de1.hetzner.ai/v1` | `mistral-small-latest` | Schnell, kostenpflichtig |
| GWDG Akademische Cloud | `https://chat.gwdg.de/api/v1` | `meta-llama-3.1-70b-instruct` | Kostenlos für Schulen via DFN-AAI |

---

*Quellen im Repo: [klausur_ki_gestuetzt.py](klausur_ki_gestuetzt.py), [setup_raspi.sh](setup_raspi.sh), [INSTALLATION.md](INSTALLATION.md)*


✅ Lessons Learned
Was war das Problem?
KI antwortet mit Markdown Code-Blocks: \``json {...}````
Standard JSON-Parser schlägt fehl
Fallback-Regex-Matching war nicht implementiert
Was war die Lösung?

def extrahiere_json_robust(text):
    # Fallback 1: Direktes Parsing
    # Fallback 2: Code-Blocks entfernen mit regex
    # Fallback 3: JSON-Block mit regex finden
    # Fallback 4: Denk-Artefakte entfernen + retry
Dieser 4-stufige Fallback macht das System robust gegen verschiedene LLM-Response-Formate.

Jetzt habe ich verstanden: bei Abitur-Klausur BATCH_GROESSE=1 für lokales LLM — pro Kriterium EIN Call, der alles in einem Schritt liefert (Bewertung + Begründungstext + Fundstellen). Plus: persistente Zwischenergebnisse für Resume.

Update Todos

pruefung_fixed.py refactorn: pro Kriterium 1 KI-Call (Bewertung+Text+Belege kombiniert)

Resume-Fähigkeit: nach jedem Kriterium Zwischenergebnis speichern

Test-Modus mit --test N und CLI-Args (limit, output, resume)

Markdown-Output mit allen 11 Kriterien strukturiert

Test-Lauf mit --test 1 zur Validierung

---

## Erkenntnisse aus Real-Lauf `Entwurf.pdf` (2026-05-18)

### 1) Häufiger Praxisfehler: Pfad-Groß/Kleinschreibung (`Material` vs `material`)
- Symptom: `FileNotFoundError` auf der Bewertungsvorlage, obwohl Datei vorhanden ist.
- Ursache: Standardpfad zeigte auf `data/Material`, im Repo liegt die Datei unter `data/material`.
- Robuste Lösung im Code:
  - Mehrere Kandidatenpfade prüfen und den ersten existierenden verwenden.
  - Erst wenn keiner existiert, auf einen definierten Fallback gehen.

### 2) Vision-OCR nur mit visionfähigem Modell
- Symptom: `400 Model does not support images. Please use a model that does.`
- Ursache: `--ocr vision` wurde mit einem reinen Textmodell (hier: `nvidia/nemotron-3-nano-4b`) gestartet.
- Regel:
  - `vision` nur mit VL/Multimodal-Modell.
  - Bei Textmodell automatisch auf `--text` (vorgezogener OCR-Text) oder `--ocr tesseract` wechseln.

### 3) Lange Hänger im ersten KI-Call früh erkennen und abbrechen
- Beobachtung: Lauf blieb bei `[1/22]` ohne Fortschritt stehen.
- Operative Strategie:
  - Lauf beobachten (Log + Prozessdauer).
  - Bei ausbleibendem Fortschritt frühzeitig beenden.
  - Mit reduziertem Timeout und robuster Fehlerbehandlung neu starten.

### 4) Pro-Teilaufgabe-Fehler dürfen den Gesamtlauf nicht stoppen
- Vorher: Ein einzelner KI-Fehler konnte den gesamten Bewertungsdurchlauf blockieren.
- Nachher (robust):
  - `try/except` pro Teilaufgabe,
  - Fallback-Ergebnis mit `flags=["ki_fehler"]`,
  - Schleife läuft weiter bis alle Teilaufgaben verarbeitet sind.

### 5) Praxisparameter fuer schwache lokale Modelle (RPi)
- Für instabile/kleine lokale Modelle im Bewertungsmodus hilfreich:
  - `LMSTUDIO_TIMEOUT=35` (oder moderat höher, wenn zu viele False-Negatives auftreten)
  - `--text <ocr_text.txt>` statt Vision-Pfad, wenn kein visionfähiges Modell geladen ist
  - weiter mit `stream=True`, damit zumindest Aktivität sichtbar bleibt

### 6) Interpretiere Ergebnis 0/100 richtig
- Im Real-Lauf wurden nur `3/22` Teilaufgaben mit Text erkannt.
- Mit fehlenden Antworten plus konservativem Modell kam durchgängig `Es liegt keine Lösung vor.`
- Daher ist ein `0/100` nicht automatisch ein Bewertungs-Bug, sondern oft ein Input-/Extraktionsproblem.

### 7) Checkliste fuer schnelle Fehlersuche (Runbook)
1. Vorlagenpfad/Case prüfen (`data/material/...`).
2. Modellfähigkeit prüfen (Vision vs. Text).
3. Wenn Vision-Fehler: sofort auf `--text` oder `--ocr tesseract` umstellen.
4. Bei Hänger > einige Minuten auf erstem Item: Prozess beenden, mit kleinem Timeout neu starten.
5. Laufende Logs immer timestamped schreiben (`run_*.log`) und Ende auf Artefakte prüfen.

### 8) Modellauswahl: explizites Modell wird trotzdem durch erstgeladenes überschrieben
- Symptom: `--modell openai/gpt-oss-20b` übergeben, aber Lauf zeigt `Geladenes Modell: nvidia/nemotron-3-nano-4b`.
- Ursache: `_erkenne_geladenes_modell()` lieferte schlicht `models.data[0].id` – das erste in der API-Liste, unabhängig vom gewünschten Modell.
- Fix: Vor dem API-List-Fallback gezielt nach dem gewünschten Modell suchen; wenn nicht vorhanden, via `lms load` nachladen und auf aktive Bereitschaft warten.

### 9) Zwei Modelle gleichzeitig geladen → Ressourcenkonkurrenz
- Symptom: Bereitschaftstest FEHLGESCHLAGEN; gpt-oss-20b läuft zuverlässig, aber Ministral reagiert nicht.
- Ursache: RPi 500 hat 16 GB RAM; `openai/gpt-oss-20b` (12 GB) + `ministral-3-14b-reasoning` (8 GB) passen nicht gleichzeitig flüssig rein.
- Strategie: Vor dem Start sicherstellen, dass nur das gewünschte Modell geladen ist. Alte Modelle via `lms unload <id>` entladen oder LM Studio GUI nutzen.
- Faustregel: pro RPi-Lauf maximal ein Modell mit > 8 GB aktiv halten.

### 10) Client-Disconnect bei langsamem Prefill (ReadTimeout)
- Symptom: `ReadTimeout (Versuch 1/3)` während der erste Batch noch verarbeitet wird; LM-Studio-Log zeigt `Client disconnected` bei ~50 % Prompt-Processing.
- Ursache: `--timeout 1200` war kürzer als der Prefill-Bedarf von gpt-oss-20b auf dem RPi (~7 Tok/s × 7056 Token ≈ 17 min).
- Fix: `--timeout 5400` (90 min) als Untergrenze für 20B-Modelle auf RPi; stream=True bewirkt, dass der Timeout pro Token gilt – nicht für die gesamte Prefill-Phase.
- Hinweis: Wenn Prefill sehr lang dauert, den Lauf im Hintergrund starten und über Logdatei überwachen statt auf Terminal-Output zu warten.

### 11) gpt-oss-20b liefert Antwort mit `<|channel|>...<|message|>`-Trennzeichen
- Symptom: JSON-Parse-Fehler; Rohausgabe beginnt mit `<|channel|>final <|constrain|>JSON<|message|>{"ergebnis": ...}`
- Ursache: OpenAI gpt-oss-20b nutzt ein internes Kanal/Constraint-Format, das vor dem eigentlichen JSON-Payload steht.
- Fix im Code: Vor dem JSON-Regex-Match explizit `<|channel|>...<|message|>`-Prefix abschneiden:
  ```python
  text = re.sub(r"<\|channel\|>[\s\S]*?<\|message\|>", "", text)
  ```

### 12) Nicht-prüfbare Kriterien mit JSON-Parse-Fehler vs. echtem Datenfehler unterscheiden
- Symptom: Kriterium landet unter „nicht prüfbar" obwohl das Modell eine valide Antwort geliefert hat (Rohtext enthält `"ergebnis":"keine_beanstandung"`).
- Ursache: Modell-spezifisches Prefix (Trick 11) wurde nicht bereinigt → JSON-Regex trifft auf falsches Fragment.
- Unterscheidung im Bericht: `JSON-Parse-Fehler: <|channel|>...` ist ein Parse-Problem; `Im vorliegenden Schülermaterial sind keine Angaben zu ... vorhanden` ist ein echter Datenfehler.
- Regel: Immer Raw-Output der ersten 200 Zeichen im Fehlermeldungstext speichern, damit Ursache rekonstruierbar ist.

### 13) Kleines Modell (<8B) liefert leere JSON-Antworten für komplexe Kriterien
- Symptom: `begruendung: "KI-Antwort war kein gültiges JSON: "` (komplett leer nach dem Doppelpunkt) – kein Rohtext, kein Fallback möglich.
- Ursache: Das Modell bricht die Generierung ab oder gibt komplett freien Text ohne JSON-Struktur aus. Tritt besonders bei Kriterien mit langen Prompts + großem Dokumentkontext auf.
- Betroffene Modelle: Nemotron-3-Nano-4B (getestet RPi 4, Mai 2026): 4/7 Kriterien kein JSON.
- Kein Fix durch `--timeout`; das Modell hat genug Zeit, ist aber nicht fähig strukturierten Output zu erzeugen.
- Diagnose: `konfidenz == 0` + leere `begruendung` → Modell zu klein, kein Timeout-Problem.
- Abhilfe: Modell mit ≥ 9B wählen; für dieses Projekt mindestens Qwen3.5-9B.

### 14) Checkpoint nach erfolgreichem Abschluss automatisch gelöscht
- Verhalten: `_loesche_checkpoint()` wird am Ende von `main()` aufgerufen, sobald XLSX + JSON gespeichert sind.
- Folge: Jeder Folgelauf auf denselben PDFs startet fresh – auch mit anderem Modell.
- Wenn Resume gewünscht: Lauf abbrechen (SIGINT) bevor der finale Schreibvorgang abgeschlossen ist.
- Der Checkpoint-Pfad wird beim Laden angezeigt: `(Checkpoint löschen um neu zu starten: ...)`.

### 7 (Update) – Runbook erweitert
6. Nach jedem Volllauf: in `not_pruefbar`-Einträgen prüfen, ob der Rohtext mit `<|channel|>` beginnt (Trick 11) oder tatsächlich Daten fehlen (Trick 12).
7. Wenn zwei Modelle geladen sind und eines davon ein 20B-Modell: altes Modell erst entladen, dann starten (Trick 9).
8. Leere `begruendung` (Trick 13) = Modell zu klein → Modell wechseln, nicht Timeout erhöhen.
9. Checkpoint nach erfolgreichem Lauf nicht mehr vorhanden (Trick 14) → Folgelauf mit anderem Modell startet immer fresh.

---

## Session 2026-05-19: Ministral-3 vs LFM2-24B Performance-Test

### Kontext
Prüflauf mit 12 Kriterien auf 2025 Mechatronik-Klausur (9.273 + 7.925 Zeichen). Ziel: Vergleich Reasoning-Modell (Ministral-3-14B) vs. schnelles MoE-Modell (LFM2-24B-A2B) auf RPi 500.

### Bugfixes vor dem Test

#### Bug 15: Import-Fehler in `ki_gestuetzt.py:42`
**Symptom:** `NameError: name 'openai' is not defined` bei Zeile 1454 (`_TRANSIENT_KI_EXC`).

**Ursache:**
```python
# ❌ FALSCH:
from openai import OpenAI

# Exception-Typen openai.APITimeoutError werden später referenziert
_TRANSIENT_KI_EXC = (openai.APITimeoutError, ...)  # ← openai nicht verfügbar
```

**Fix:**
```python
# ✅ RICHTIG:
import openai
from openai import OpenAI
```

#### Bug 16: Pattern-Referenz in `regelbasiert.py:399`
**Symptom:** `NameError: name 'insgesamt_pattern' is not defined` beim Parsen der Aufgaben.

**Ursache:** Tippfehler – Pattern ist als `_INSGESAMT_PATTERN` definiert (Zeile 237), aber als `insgesamt_pattern` (ohne Unterstriche, kleingeschrieben) referenziert.

**Fix:**
```python
# regelbasiert.py:399
pm4 = _INSGESAMT_PATTERN.search(next_line)  # nicht: insgesamt_pattern
```

### Performance-Messung: Ministral-3 vs LFM2-24B

**Testbedingungen:**
- Hardware: Raspberry Pi 500 (aarch64, 16 GB RAM)
- 12 KI-Kriterien + 2 nicht KI-prüfbar
- Checkpoint: 2 Kriterien bereits geprüft (aus vorherigem Lauf)
- Netto: 10 neue Kriterien zu prüfen

#### Ministral-3-14B-reasoning – ABGEBROCHEN nach 10+ Min

| Metrik | Wert |
|--------|------|
| **Erwartung** | 30-45s/Kriterium |
| **Realität** | **>10 Min/Kriterium** |
| **Status** | ⚠️ **Zu langsam für RPi** |
| **Batch 1 Dauer** | >10 Min ohne Output |
| **CPU-Last** | 6,5% → 3,0% (sinkend, wartend) |
| **Prozess-Status** | `STAT=S`, `WCHAN=do_sys_poll` (wartet auf LM Studio) |

**Ursachen:**
1. **Reasoning-Overhead:** Modell generiert 500-2000 Reasoning-Tokens vor der eigentlichen Antwort
2. **CPU-Inferenz:** ~0,5-1 Token/s → 10-30 Min nur für Thinking-Phase
3. **Assistant-Prefill ignoriert:** `<think>\n\n</think>` wird trotz Code-Trick nicht beachtet
4. **Bereitschaftstest langsam:** >4 Min bis erste Antwort

**Entscheidung:** Nach 10+ Min abgebrochen, Wechsel zu LFM2-24B.

#### LFM2-24B-A2B – ERFOLGREICH in 67 Min

| Metrik | Wert |
|--------|------|
| **Erwartung** | 30-45s/Kriterium |
| **Realität** | **~6,7 Min/Kriterium** (∅) |
| **Status** | ✅ **Optimal für RPi** |
| **Gesamtdauer** | 67 Min (statt geschätzter 4h!) |
| **Start → Ende** | 15:42 → 16:49 Uhr |
| **Ergebnis** | 0 Beanstandungen, 95% Konfidenz |

**Performance-Dynamik:**
- **Batch 1:** ~10-15 Min (Modell-Warmup + Prefill)
- **Batch 2-12:** ~4-6 Min (KV-Cache aktiv)
- Checkpoint-System: 2 Kriterien übersprungen → 10 neue geprüft

**Qualität:** Alle 12 Kriterien mit **95% Konfidenz** als konform bewertet:
- Deckblatt nach Muster ✓
- Kompetenzen gemäß RRL ✓
- AFB-Zuordnung korrekt ✓
- Punkteverteilung transparent ✓
- Ganzheitlichkeit ✓
- (und 7 weitere)

### Aktualisierte Modell-Empfehlung für RPi 500

**Neue Reihenfolge (nach Benchmark 2026-05-19):**

1. **LFM2-24B-A2B** (`liquid/lfm2-24b-a2b`) — **6,7 Min/Krit.** ✅ **BESTE WAHL**
   - MoE mit ~2B aktiven Parametern
   - Kein Thinking-Overhead
   - Konstant gute Performance nach Warmup
   
2. **GPT-OSS-20B** (`openai/gpt-oss-20b`) — geschätzt 10-12 Min/Krit.
   - Höhere Qualität als LFM2 (empirisch)
   - Aber langsamer durch größere Modellgröße
   - Für finale Prüfungen empfohlen

3. **Qwen3.5-9B** (`qwen/qwen3.5-9b`) — 8-10 Min/Krit.
   - Kleiner, etwas schneller als GPT-OSS
   - Thinking-Unterdrückung erforderlich

4. **Devstral-Small-2-2512** — sehr schnell, aber Code-optimiert
   - Evtl. weniger präzise für Fachtext

5. ~~**Ministral-3-14B**~~ — ❌ **NICHT für RPi** (>10 Min/Krit.)
   - Nur auf GPU oder Apple Silicon nutzen

**Aktualisierte Code-Prioritätsliste:**
```python
# src/bewertung/ki_gestuetzt.py
BEVORZUGTE_MODELLE = [
    "liquid/lfm2-24b",         # NEU an Position 1 nach Benchmark!
    "gpt-oss-20b",
    "qwen3.5",
    "qwen2.5-14b",
    "devstral-small",
    # "Ministral" entfernt - zu langsam für RPi
]
```

### Monitoring-Techniken für lange Prüfläufe

#### Prozess-Status diagnostizieren (hängt vs. arbeitet)
```bash
ps -p <PID> -o pid,stat,wchan:25,etime,pcpu
```

**Interpretation:**
- `STAT=S` + `WCHAN=do_sys_poll` → wartet auf I/O (LM Studio generiert)
- `STAT=R` → aktiv rechnend
- `WCHAN=poll_schedule_timeout` → idle/wartend
- CPU sinkend (6% → 3% → 1%) → Reasoning-Phase (normal bei Thinking-Modellen)

#### Netzwerk-Verbindung verifizieren
```bash
lsof -i :1234 | grep ESTABLISHED
```
Prüft, ob Python-Prozess noch mit LM Studio verbunden ist. Wenn keine Verbindung: Timeout oder Crash.

#### LM Studio Modell-Status
```bash
curl -s http://localhost:1234/v1/models | jq -r '.data[0].id'
```
Zeigt aktuell geladenes Modell. Wichtig bei Modellwechsel-Tests.

#### Live-Log-Monitoring mit Änderungs-Erkennung
```bash
LAST_LINES=0
while ps -p <PID> > /dev/null; do
  CURRENT=$(wc -l < logfile.log)
  if [ $CURRENT -gt $LAST_LINES ]; then
    tail -n $((CURRENT - LAST_LINES)) logfile.log | grep -E "Batch|✓|Dauer"
    LAST_LINES=$CURRENT
  fi
  sleep 120  # Alle 2 Min
done
```

Zeigt nur neue Log-Zeilen → kein Spam, spart Ressourcen.

### Checkpoint-System Details

**Funktionsweise:**
- Datei: `checkpoint_ki_<hash_schueler>_<hash_lehrer>.json` in `Auswertungen/`
- Hash basiert auf PDF-Inhalten → gleiche Dateien = gleicher Checkpoint
- Speichert: Liste der geprüften Kriterium-IDs + komplette Ergebnisse
- Bei Neustart: `if kriterium_id in checkpoint: skip`

**Automatisches Löschen:**
- Nach erfolgreichem Abschluss wird Checkpoint gelöscht
- Bei SIGINT (Strg+C) bleibt Checkpoint erhalten → Resume möglich

**Bei Modellwechsel:**
- Checkpoint bleibt → bereits geprüfte Kriterien werden mit **altem Modell** übersprungen
- Im Log: `Checkpoint geladen: 2 Kriterien bereits geprüft – überspringe diese.`
- **Achtung:** Mischbetrieb verschiedener Modelle möglich!

**Checkpoint löschen für kompletten Neustart:**
```bash
# Pfad wird im Log angezeigt:
rm /pfad/zu/checkpoint_ki_ab24f27c_fdf1ac57.json
```

Oder in Streamlit UI: Checkbox "🔄 Bestehende Checkpoints ignorieren"

### Timeout-Strategien nach Benchmark

**Bereitschaftstest (HEALTH_CHECK_TIMEOUT):**
- Standard: **300s** (5 Min)
- Bei Reasoning-Modellen: **600s** (10 Min) empfohlen
- Ministral-3 braucht >4 Min für ersten Response

**API-Timeout pro Kriterium:**
```python
# Neue Empfehlungen basierend auf Messungen:
TIMEOUT_LFM2    = 1800   # 30 Min – ausreichend für 6-7 Min/Krit. + Puffer
TIMEOUT_GPT_OSS = 2400   # 40 Min – für 10-12 Min/Krit. + Puffer
TIMEOUT_MINISTRAL = 3600 # 60 Min – für Reasoning-Phase (wenn überhaupt auf RPi)
TIMEOUT_CLOUD   = 300    # 5 Min
```

**Faustregel:** Timeout = 3-4× erwartete Durchschnittszeit (Sicherheitspuffer für Batch 1 Warmup)

**Warnung bei zu kurzem Timeout:**
- Symptom: `ReadTimeout` während Batch 1, obwohl Modell noch generiert
- LM Studio Log: `Client disconnected` bei ~50% Prompt-Processing
- Fix: Timeout verdoppeln oder verdreifachen

### Warum LFM2 deutlich schneller als geschätzt?

**Ursprüngliche Fehlschätzung:**
- Annahme: 25 Min/Kriterium (basierend auf ersten 10 Min für Batch 1)
- Hochrechnung: 12 Kriterien × 25 Min = 5h

**Tatsächlicher Verlauf:**
- Batch 1: ~10-15 Min (Warmup + Prefill)
- Batch 2-12: ~4-6 Min (KV-Cache + Modell warm)
- Durchschnitt: (15 + 11×5) / 12 ≈ **6,7 Min/Kriterium**

**Erkenntnis:** Nicht linear von Batch 1 hochrechnen! KV-Cache und Warmup-Effekte reduzieren Folgebatches drastisch.

### Vergleich: Ministral-3 vs LFM2-24B

| Aspekt | Ministral-3-14B | LFM2-24B-A2B |
|--------|-----------------|--------------|
| **Modellgröße** | 14B (dicht) | 24B MoE (~2B aktiv) |
| **Reasoning** | Ja (eingebaut) | Nein |
| **Prefill-Trick** | Ignoriert | Nicht nötig |
| **Batch 1 (Warmup)** | >10 Min | ~10-15 Min |
| **Folgebatches** | Unbekannt (abgebrochen) | ~4-6 Min |
| **Durchschnitt** | >10 Min/Krit. | ~6,7 Min/Krit. |
| **Gesamtlaufzeit (12 Krit.)** | >2h (geschätzt) | 67 Min ✅ |
| **RPi 500 Empfehlung** | ❌ Zu langsam | ✅ Optimal |
| **Apple Silicon** | ✅ Gut (GPU) | ✅ Noch schneller |
| **Qualität (95% Konfidenz)** | Unbekannt | ✅ 12/12 OK |

### Lessons Learned

1. **Reasoning-Modelle auf CPU vermeiden:** Ministral-3 generiert zu viele Thinking-Tokens für CPU-Inferenz.

2. **MoE-Vorteil:** LFM2 mit 24B Parametern, aber nur ~2B aktiv → schneller als dichte 14B-Modelle.

3. **Warmup einplanen:** Batch 1 dauert 2-3× länger als Folgebatches → nicht linear hochrechnen.

4. **Checkpoint spart Zeit:** Bei Unterbrechung/Modellwechsel werden geprüfte Kriterien übersprungen.

5. **Monitoring essentiell:** Bei >5 Min ohne Output: Prozess-Status prüfen (do_sys_poll = OK, wartend).

6. **LFM2 als neue Standard-Empfehlung:** Beste Balance aus Geschwindigkeit und Qualität für RPi 500.

---

## Apple Silicon M4 (MacBook Air, 24 GB) – Durchlauf 2026/27

Stand 2026-11-23: Werkzeug vorbereitet, **noch nicht auf dem M4 gemessen**.
Messwerte nach dem ersten Vergleichslauf hier eintragen (`laufzeiten.csv`).

### Neue Provider
| Provider | Server | Adresse | Besonderheit |
|----------|--------|---------|--------------|
| `lokal`  | LM Studio | `LMSTUDIO_BASE_URL` (1234) | Modell vorher mit `lms load … --context-length 32768` laden |
| `ollama` | Ollama | `OLLAMA_BASE_URL` (11434) | `OLLAMA_CONTEXT_LENGTH=32768` vor `ollama serve`, sonst stilles Abschneiden |
| `bonsai` | Bonsai-Laufzeit (OpenAI-kompatibel) | `BONSAI_BASE_URL` (8080) | Kontext über `/props`, sonst `KI_KONTEXT` |

### Neue Schalter in `.env`
- `KI_MODELL` – Modell-ID oder Teilstring für lokale Provider (leer = Präferenzliste)
- `KI_KONTEXT` – Kontextgröße erzwingen, wenn der Server sie nicht meldet
- `KI_DENKPHASE_UEBERSPRINGEN=auto|ja|nein` – Prefill-Trick A ohne Codeänderung erzwingen
  (z. B. für Bonsai auf Qwen-Basis)
- `KI_TIMEOUT` – Timeout pro Aufruf (Standard Apple Silicon 600 s)

### Fallstricke (aus der Vorbereitung)
1. **Checkpoint ≠ Modell:** Checkpoints hängen am PDF-Inhalt. Beim Modellvergleich vorher löschen
   (`vergleichslauf_mac.sh` erledigt das), sonst Mischbetrieb (siehe Trick 14).
2. **Ein Modell zur Zeit:** LM Studio und Ollama halten Modelle unabhängig voneinander im Speicher.
   Vor dem Wechsel `lms unload --all` bzw. `ollama stop <modell>`.
3. **Größenwarnung:** Das alte Muster `"7b"` traf auch `27b` – jetzt entscheidet die Zahl im Namen
   (`_ist_kleines_modell`).
4. **Oberfläche nutzte immer LM Studio:** `KI_PROVIDER` wurde nur angezeigt; jetzt wählt die
   Seitenleiste Provider und Modell (`setze_provider`).
5. **MacBook Air drosselt** ohne Lüfter bei langen Läufen → Netzteil, Pausen, Laufzeiten nur
   unter gleichen Bedingungen vergleichen.

### Zu messen
| Modell | Laufzeit | Prefill Batch 1 | ∅ je Kriterium | KI gesamt | Lösbarkeit gesamt | nicht_pruefbar | Abgleich mit Gutachtern |
|--------|----------|-----------------|----------------|-----------|-------------------|----------------|-------------------------|
| Gemma 4 12B | LM Studio | | | | | | |
| Gemma 4 12B | Ollama | | | | | | |
| Bonsai 27B | Bonsai | | | | | | |
