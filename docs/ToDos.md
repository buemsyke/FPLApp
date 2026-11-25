# ToDos

Stand 2026-11-23 (Vorbereitung Durchlauf 2026/27, MacBook Air M4)

## Erledigt
- Live-Fortschritt in der Oberfläche (KI- und Lösbarkeitsprüfung, `progress_callback`)
- Checkpoint für die Lösbarkeitsprüfung, Checkpoints unabhängig vom tmp-Verzeichnis
- Provider `ollama` und `bonsai`, Auswahl von Provider und Modell in der Seitenleiste
- Oberfläche wertet `begutachte()` richtig aus und erzeugt das DOCX-Gutachten
- Vergleichsskript `scripts/vergleichslauf_mac.sh`
- Hinweise an die Schule als eigene Liste (`src/bewertung/hinweisliste.py`, XLSX + CSV im
  Format der versendeten Hinweise), nicht mehr im Gutachten-DOCX; Tests in
  `tests/test_hinweisliste.py`

## Offen
- Erster Vergleichslauf auf dem M4: Gemma 4 12B (LM Studio, Ollama) und Bonsai 27B,
  Messwerte in `LOKALE_LLM_TRICKS.md` eintragen
- Ergebnisse mit den Gutachter-Auswertungen (`data/Auswertung Gutachter/`) abgleichen
- Prüfen, ob Gemma 4 / Bonsai eine Denkphase ausgeben (Rohantworten in den Logs) und
  `KI_DENKPHASE_UEBERSPRINGEN` festlegen
- Lösbarkeits-Ergebnisdateien mit Modellnamen versehen (wie bei der KI-Prüfung); die
  Lösbarkeits-CLI schreibt noch keine Hinweisliste (nur die Oberfläche führt beide zusammen)
- Formulierungen der Hinweisliste am ersten echten Durchlauf schärfen (`_KURZ` in
  `hinweisliste.py`)
