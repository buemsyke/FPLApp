# Verbesserungen beitragen

Dieses Werkzeug ist so aufgebaut, dass es schrittweise verbessert werden kann –
auch ohne tiefe Python-Kenntnisse. Jeder Kollege, der Erfahrungen beim Prüfen
von Klausurvorschlägen gesammelt hat, kann sinnvolle Beiträge leisten.

---

## Inhaltsverzeichnis

1. [Wo welche Verbesserungen eingetragen werden](#1-wo-welche-verbesserungen-eingetragen-werden)
2. [Neue regelbasierte Prüfung hinzufügen](#2-neue-regelbasierte-prüfung-hinzufügen)
3. [KI-Prüfanweisung verbessern oder hinzufügen](#3-ki-prüfanweisung-verbessern-oder-hinzufügen)
4. [Bekannte Nicht-EPA-Operatoren ergänzen](#4-bekannte-nicht-epa-operatoren-ergänzen)
5. [Operatoren-Tabelle anpassen](#5-operatoren-tabelle-anpassen)
6. [Konfigurationsparameter anpassen](#6-konfigurationsparameter-anpassen)
7. [Neues KI-Modell / Provider hinzufügen](#7-neues-ki-modell--provider-hinzufügen)
8. [Prüfung testen](#8-prüfung-testen)
9. [Hinweise zur Codestruktur](#9-hinweise-zur-codestruktur)

---

## 1. Wo welche Verbesserungen eingetragen werden

| Was verbessern? | Datei | Bereich |
|-----------------|-------|---------|
| Regelbasierte Prüfung (automatisch) | `klausur_regelbasiert.py` | `check_*()` Funktionen, `begutachte()` |
| KI-Prüfanweisung (Prompt) | `klausur_ki_gestuetzt.py` | `KI_PRUEF_PROMPTS` |
| Neue Nicht-EPA-Operatoren | `klausur_regelbasiert.py` | `NICHT_EPA_OPERATOREN` |
| Operatoren-Tabelle / AFB | `klausur_regelbasiert.py` | `OPERATOREN` |
| Konfiguration (Schwelle, Timeout) | `klausur_ki_gestuetzt.py` | Konstanten am Anfang |
| Neuer Cloud-Provider | `klausur_ki_gestuetzt.py` | `PROVIDER` Dict |
| Startskripte | `starten.sh`, `starten.bat`, `run_ki.sh` | – |

---

## 2. Neue regelbasierte Prüfung hinzufügen

Regelbasierte Prüfungen (ohne KI) stehen in `klausur_regelbasiert.py` als `check_*()`-Funktionen.

### Schritt 1: Prüffunktion schreiben

```python
def check_mein_neues_kriterium(schueler_text: str) -> PruefungsErgebnis:
    """X.14: Beschreibung des neuen Kriteriums."""
    # Prüflogik – einfaches Beispiel: Schlüsselwort suchen
    if re.search(r"mein_schlüsselwort", schueler_text, re.IGNORECASE):
        return PruefungsErgebnis(
            "X.14",                          # Kriterium-Nummer
            "Mein neues Kriterium",          # Kriterium-Beschreibung
            True,                            # True=erfüllt, False=nicht erfüllt, None=manuell prüfen
            "Schlüsselwort gefunden – OK.",  # Kommentar
        )
    else:
        return PruefungsErgebnis(
            "X.14",
            "Mein neues Kriterium",
            False,
            "Schlüsselwort nicht gefunden.",
        )
```

**Rückgabewerte `erfuellt`:**
- `True` → ✅ Kriterium erfüllt (kein weiteres Handeln nötig)
- `False` → ❌ Beanstandung (erscheint im Gutachten)
- `None` → ⚠️ Manuell / KI prüfen (wird an Stufe 2 übergeben)

### Schritt 2: In `begutachte()` einhängen

In der Funktion `begutachte()` (ca. Zeile 1800 in `klausur_regelbasiert.py`) die neue
Prüfung in der Liste `ergebnisse.append(...)` ergänzen:

```python
# Zusatz-Prüfungen
ergebnisse.append(check_gesamtpunktzahl(aufgaben, afb_data))
ergebnisse.append(check_mein_neues_kriterium(schueler_text))  # ← NEU
```

### Schritt 3: Metadaten eintragen (optional aber empfohlen)

In `_KRITERIUM_MATERIAL` eintragen, ob das Kriterium SM, LM oder beide betrifft:
```python
"X.14": "SM",   # oder "LM" oder "BEIDE"
```

In `_KRITERIUM_EBENE` eintragen, ob aufgabenbezogen oder allgemein:
```python
"X.14": "ALLGEMEIN",  # oder "AUFGABE"
```

In `_KRITERIUM_HINWEIS` einen Korrekturhinweis eintragen:
```python
"X.14": "Bitte das Schlüsselwort ergänzen.",
```

---

## 3. KI-Prüfanweisung verbessern oder hinzufügen

Wenn ein Kriterium mit `erfuellt=None` zurückgegeben wird, übergibt
`klausur_ki_gestuetzt.py` es an das Sprachmodell. Die Prüfanweisung steht im
Dict `KI_PRUEF_PROMPTS` in `klausur_ki_gestuetzt.py`.

### Bestehenden Prompt verbessern

```python
KI_PRUEF_PROMPTS: dict[str, str] = {
    "3.3": (
        "Prüfe, ob die Aufgabenstellung ganzheitlich und problembezogen ist.\n\n"
        # ↑ Hier die Anweisung präzisieren, z. B. Beispiele ergänzen:
        "Ganzheitlich bedeutet: Es gibt eine zusammenhängende Situation, "
        "die mehrere Lerngebiete verbindet.\n\n"
        "Positives Beispiel: 'Ein Unternehmen plant eine SPS-Steuerung ...'\n"
        "Negatives Beispiel: 'Aufgabe 1: Nennen Sie drei Gatter-Typen.'\n\n"
        "Melde eine Beanstandung NUR, wenn die Aufgaben OFFENSICHTLICH "
        "zusammenhanglos oder trivial sind."
    ),
```

### Neues Kriterium für KI-Prüfung hinzufügen

1. Die `check_*()`-Funktion gibt `erfuellt=None` zurück.
2. Prüfanweisung im Dict `KI_PRUEF_PROMPTS` eintragen:

```python
KI_PRUEF_PROMPTS: dict[str, str] = {
    # ... vorhandene Einträge ...
    "X.14": (
        "Prüfe, ob [Beschreibung des Kriteriums].\n\n"
        "Beanstandungsgründe wären:\n"
        "- Grund 1\n"
        "- Grund 2\n\n"
        "Melde NUR eindeutige Verstöße. Im Zweifel: keine Beanstandung."
    ),
}
```

**Verfügbare Platzhalter** (werden automatisch ersetzt):

| Platzhalter | Inhalt |
|------------|--------|
| `{rrl_kompetenzen}` | Alle RRL-Kompetenzen als Aufzählung |
| `{lerngebiete}` | IT1–IT5 mit Beschreibung |
| `{verbindlich}` | Verbindliche Lerngebiete (IT1, IT2) |
| `{optional}` | Optionale Lerngebiete (IT3, IT4, IT5) |
| `{operatoren_tabelle}` | Alle Operatoren mit AFB (kompakt) |
| `{operatoren_detail}` | Alle Operatoren mit AFB + Beschreibung |
| `{bearbeitungszeit}` | Bearbeitungszeit in Minuten (300) |

### Kriterium von KI-Prüfung ausschließen

Kriterien, die nur visuell oder physisch geprüft werden können
(z. B. Schriftbild, Datenträger), werden in `KI_NICHT_PRUEFBAR` eingetragen:

```python
KI_NICHT_PRUEFBAR = {
    "1.1",   # Schriftbild – visuell
    "X.14",  # Beispiel: neues Kriterium das nicht per KI prüfbar ist
}
```

---

## 4. Bekannte Nicht-EPA-Operatoren ergänzen

In `klausur_regelbasiert.py` steht die Liste der häufig fälschlich verwendeten
Nicht-EPA-Operatoren:

```python
NICHT_EPA_OPERATOREN = {
    "erstellen", "kommentieren", "implementieren", "programmieren",
    # ← Weitere ergänzen, wenn in der Praxis gefunden:
    "testen", "konfigurieren", "installieren",
}
```

Diese werden automatisch erkannt, wenn sie als `Operator Sie ...`
in der Aufgabenstellung erscheinen.

---

## 5. Operatoren-Tabelle anpassen

Die Operatoren-Tabelle in `klausur_regelbasiert.py` entspricht der offiziellen
EPA-Tabelle. Wenn die Tabelle aktualisiert wird:

```python
OPERATOREN = {
    "beschreiben": {"afb": ["I"], "desc": "..."},
    # Neuen Operator ergänzen:
    "neuer_operator": {
        "afb": ["II"],          # AFB-Zuordnung: "I", "II", "III" (Mehrfachzuordnung möglich)
        "desc": "Beschreibung der erwarteten Leistung"
    },
}
```

---

## 6. Konfigurationsparameter anpassen

In `klausur_ki_gestuetzt.py` stehen alle Schwellenwerte und Timeouts:

```python
# Konfidenz-Schwelle: unter diesem Wert → "nicht sicher prüfbar"
KONFIDENZ_SCHWELLE = 75      # 0–100, Standard 75

# Maximale Textlänge pro Dokument für den KI-Kontext
MAX_TEXT_LAENGE = 12000      # Zeichen (ca. 3000–4000 Token)

# Anzahl Kriterien pro Batch-Aufruf
BATCH_GROESSE = 1            # 1 = einzeln, 4 = bis zu 4 Kriterien gleichzeitig

# API-Timeout in Sekunden
API_TIMEOUT = 1800           # 30 Minuten (konservativ für RPi)

# Anzahl Wiederholungsversuche bei Timeout
MAX_RETRIES = 2

# Pause zwischen API-Aufrufen (Sekunden)
PAUSE_ZWISCHEN_AUFRUFEN = 2
```

Diese Parameter können auch über die Kommandozeile überschrieben werden:
```bash
python klausur_ki_gestuetzt.py --schwelle 80 --timeout 600 --batch-groesse 2 ...
```

---

## 7. Neues KI-Modell / Provider hinzufügen

Jeder OpenAI-API-kompatible Anbieter kann als neuer Provider eingetragen werden:

```python
PROVIDER: dict[str, ProviderConfig] = {
    # ... vorhandene Provider ...
    "mein_provider": ProviderConfig(
        name="Mein Provider",
        beschreibung="Kurze Beschreibung und wo der API-Key erhältlich ist.",
        base_url="https://api.mein-provider.de/v1",
        api_key_env="MEIN_PROVIDER_API_KEY",   # Name der Umgebungsvariable
        api_key_default="",
        model="llama-3.1-70b-instruct",        # Modellname lt. Provider-Docs
        timeout=300,
        batch_groesse=4,
    ),
}
```

Danach aufrufbar mit:
```bash
export MEIN_PROVIDER_API_KEY='...'
python klausur_ki_gestuetzt.py --provider mein_provider --verzeichnis Klausuren
```

---

## 8. Prüfung testen

### Einzelne Prüffunktion testen

```python
# In der Python-Konsole:
from klausur_regelbasiert import extract_text, check_mein_neues_kriterium

text = extract_text("Klausuren/Abiturvorschläge/2025Mechatronik/SM.pdf")
ergebnis = check_mein_neues_kriterium(text)
print(ergebnis)
```

### Vollständigen Lauf mit Beispieldaten testen

```bash
# Automatische Prüfung (ohne KI)
python klausur_regelbasiert.py \
  "Klausuren/Abiturvorschläge/2025Mechatronik/SM.pdf" \
  "Klausuren/Abiturvorschläge/2025Mechatronik/LM_EWH.pdf" \
  --nur-konsole

# KI-Prüfung (mit Cloud-Provider zum schnellen Testen)
export HETZNER_AI_API_KEY='...'
python klausur_ki_gestuetzt.py \
  --provider hetzner \
  "Klausuren/Abiturvorschläge/2025Mechatronik/SM.pdf" \
  "Klausuren/Abiturvorschläge/2025Mechatronik/LM_EWH.pdf" \
  --nur-konsole
```

### Einzelnen KI-Prompt testen

```python
from klausur_regelbasiert import extract_text
from klausur_ki_gestuetzt import _baue_prompt, _aktiviere_provider

sm = extract_text("Klausuren/Abiturvorschläge/2025Mechatronik/SM.pdf")
lm = extract_text("Klausuren/Abiturvorschläge/2025Mechatronik/LM_EWH.pdf")

prompt = _baue_prompt("3.3", "Ganzheitlichkeit", "MANUELL PRÜFEN", sm, lm)
print(prompt[:2000])   # Prompt-Vorschau
```

---

## 9. Hinweise zur Codestruktur

### `klausur_regelbasiert.py` – Aufbau

```
Konstanten (OPERATOREN, IT_LERNGEBIETE, RRL_KOMPETENZEN, ...)
  ↓
Hilfsfunktionen (extract_text, extract_pages_pdf, ...)
  ↓
Parser (parse_aufgaben, parse_erwartungshorizont_afb, ...)
  ↓
Prüffunktionen (check_*) – eine Funktion pro Kriterium
  ↓
begutachte()     – ruft alle Prüffunktionen auf
  ↓
XLSX/DOCX-Ausgabe (erstelle_gutachten_docx, erstelle_rueckmeldung_xlsx, ...)
  ↓
main()           – Kommandozeilen-Interface
```

### `klausur_ki_gestuetzt.py` – Aufbau

```
Konstanten und Provider-Konfiguration
  ↓
KI_PRUEF_PROMPTS – Dict mit Prüfanweisungen pro Kriterium
  ↓
LM Studio-Verwaltung (stelle_lmstudio_bereit, _starte_lmstudio_server, ...)
  ↓
API-Aufruf (_rufe_ki_auf, _rufe_ki_batch_auf, ...)
  ↓
fuehre_ki_pruefung_durch() – Hauptlogik
  ↓
Checkpoint-Verwaltung (_lade_checkpoint, _speichere_checkpoint, ...)
  ↓
XLSX-Ausgabe (schreibe_ki_bericht_xlsx)
  ↓
main()
```

### Datenfluss zwischen den Skripten

`klausur_regelbasiert.py` exportiert:
- `begutachte()` – liefert Ergebnisliste + Aufgabenstruktur
- `extract_text()`, `extract_text_pdf()`
- `finde_vorschlaege()` – SM/LM-Paare in Verzeichnis finden
- Alle Konstanten (`OPERATOREN`, `IT_LERNGEBIETE`, ...)

`klausur_ki_gestuetzt.py` importiert diese und ergänzt die KI-Prüfung.

### Umgang mit `erfuellt=None`

Funktionen die `erfuellt=None` zurückgeben, **müssen** in `klausur_ki_gestuetzt.py`
entweder einen Eintrag in `KI_PRUEF_PROMPTS` haben oder in `KI_NICHT_PRUEFBAR`
stehen. Andernfalls wird ein generischer Fallback-Prompt verwendet, der meist
schlechtere Ergebnisse liefert.

Prüfung:
```python
from klausur_regelbasiert import begutachte
from klausur_ki_gestuetzt import KI_PRUEF_PROMPTS, KI_NICHT_PRUEFBAR

ergebnisse, *_ = begutachte("SM.pdf", "LM.pdf")
manuell = {e.kriterium_nr for e in ergebnisse if e.erfuellt is None}
ohne_prompt = manuell - set(KI_PRUEF_PROMPTS.keys()) - KI_NICHT_PRUEFBAR
if ohne_prompt:
    print(f"Kriterien ohne KI-Prompt: {ohne_prompt}")
```
