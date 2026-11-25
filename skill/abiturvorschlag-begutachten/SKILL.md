---
name: abiturvorschlag-begutachten
description: "Vorprüfung von Abiturvorschlägen am Beruflichen Gymnasium Technik, Schwerpunkt Informationstechnik (Niedersachsen), für Fachberatung und Referentinnen und Referenten – dieselbe Prüfung wie die App GutachtenAbiturklausur, nur urteilt Claude statt eines lokalen Modells. Ein Skript prüft Schüler- und Lehrermaterial regelbasiert (rund 40 Kriterien der Gutachtenvorlage, Operatoren nach EPA, AFB, BE, Bearbeitungszeit, Platzhalter, Anlagen) und füllt das Raster der amtlichen Gutachtenvorlage (DOCX, ✔/✘/?). Danach prüft Claude die offenen Kriterien mit den Prüfanweisungen der App sowie Lösbarkeit und fachliche Richtigkeit je Teilaufgabe, mit Konfidenz ≥ 75 % und belegtem Zitat. Ergebnis sind Hinweisliste an die Schule (XLSX/CSV), KI-Prüfbericht, Lösbarkeitsbericht und Kurzbericht. Verwenden bei „Abiturvorschlag begutachten“, „Gutachten Abiturvorschlag IT“, „Vorschlag A/B prüfen“, „Hinweisliste für die Schule“. Nicht für andere Schwerpunkte, Klassenarbeiten oder Klausuren (pruefungsaufgaben-begutachten)."
metadata:
  version: "1.0"
  bereich: pruefen
  stand: "2026-11"
  quelle: "Projekt GutachtenAbiturklausur (src/bewertung), gebaut mit scripts/skill_bauen.py"
---

# Abiturvorschlag begutachten (BG Technik – Informationstechnik)

## Zweck
Vorprüfung eines eingereichten Abiturvorschlags (Schülermaterial **SM** + Lehrermaterial **LM**)
gegen die Kriterien der Gutachtenvorlage. Ergebnis ist ein **Vorschlag**: Das Gutachten und die
„?“-Kriterien verantwortet die Fachberatung bzw. der Referent / die Referentin.

## Vertraulichkeit – vor dem ersten Schritt
Unveröffentlichte Abiturvorschläge sind vertraulich. Dieser Skill gibt ihre Texte an Claude.
- Nur verwenden, wenn die Dienststelle die genutzte Claude-Umgebung für vertrauliche
  Prüfungsunterlagen freigegeben hat. Ist das nicht erkennbar, **einmal nachfragen** und ohne
  Bestätigung nicht weitermachen.
- Ohne Freigabe: nicht diesen Skill nutzen, sondern die App mit lokalem Modell
  (`Gutachten starten.command` im Projekt GutachtenAbiturklausur) – dort verlässt nichts den Rechner.
- Keine Namen von Schulen oder Lehrkräften in Antworten wiederholen, wenn sie nicht nötig sind.

## Umgebung
Das Skript braucht Python ≥ 3.10 mit `python-docx`, `openpyxl`, `pypdf` und möglichst
`pdftotext` (Poppler). Fehlt `pdftotext`, werden einzelne Regelbefunde unzuverlässig (z. B. 4.7) –
das Skript meldet es.
- **claude.ai / Claude-App (Code-Ausführung):** meist alles vorhanden. Sonst
  `pip install python-docx openpyxl pypdf`.
- **Claude Code auf dem Mac/Linux:** Das Skript findet die Umgebung der App automatisch
  (`~/Library/Application Support/GutachtenAbiturklausur`). Ohne App einmalig
  `bash scripts/einrichten.sh` – ohne Administratorrechte, legt Python 3.12 und Poppler im
  Benutzerordner an.
- Prüfen: `python3 scripts/begutachten.py umgebung`

## Ablauf
Pfade relativ zum Skill-Ordner; SM und LM als PDF (oder DOCX).

1. **Vorbereiten (Skript, deterministisch):**
   `python3 scripts/begutachten.py vorbereiten SM.pdf LM.pdf --ausgabe <Ordner>`
   Erzeugt im Ordner: Gutachten-Raster `Gutachten_*.docx`, `Rueckmeldung_*.xlsx`,
   `text/` (SM/LM mit Seitenmarken), `pruefauftrag.md`, `urteile.json` (leer), `lauf.json`.
   Die Regelbefunde (✔/✘/?) sind fest – nicht neu bewerten, nicht überschreiben.
2. **Prüfen (Claude):** `pruefauftrag.md` vollständig lesen und abarbeiten, Material in `text/`
   lesen (bei Tabellen `lehrermaterial_layout.txt`).
   - **Teil A – Kriterien:** je Kriterium die Prüfanweisung der App befolgen und das Urteil in
     `urteile.json` → `kriterien` eintragen.
   - **Teil B – Teilaufgaben:** Lösbarkeit (A) und fachliche Richtigkeit (B) je Teilaufgabe,
     Rechnungen nachrechnen; Urteil in `urteile.json` → `loesbarkeit`.
   - Format und Beispiele: `references/urteile-format.md`.
3. **Abschließen (Skript):**
   `python3 scripts/begutachten.py abschliessen <Ordner>`
   Prüft jedes Urteil (zulässige Werte, Konfidenz, wörtliche Zitate) und schreibt
   `Hinweise_*_claude.xlsx/.csv`, `KI_Pruefung_*_claude.xlsx`, `Loesbarkeit_*_claude.xlsx`,
   `Bericht_*.md`, `ergebnis_claude.json`. Meldet es fehlende Einträge: ergänzen und erneut
   aufrufen. `--unvollstaendig` nur, wenn Einträge bewusst offen bleiben.
4. **Antwort an die Person:** Kurzfassung aus `Bericht_*.md` (Überblick, Beanstandungen,
   Selbst-prüfen-Liste) und die Dateiliste. Herabgestufte Beanstandungen („Zitat nicht im
   Material gefunden“) nennen, nicht verschweigen.

## Regeln für die Urteile
Die Regeln der App stehen wörtlich im Prüfauftrag; die wichtigsten:
- **Lieber nicht prüfbar als raten.** Reicht der Text nicht (Bild, Anlage ohne Text, Auszug
  unvollständig), ist das Ergebnis `nicht_pruefbar`.
- **Beanstandung nur bei eindeutigem, belegbarem Verstoß** mit Konfidenz ≥ 75 %, betroffener
  Aufgabe/Teilaufgabe in der Begründung und mindestens einer Fundstelle mit **wörtlichem Zitat**
  in „…“. Ein Zitat, das das Skript im Text nicht findet, macht die Beanstandung zu „nicht prüfbar“.
- Begründung und Ergebnis dürfen sich nicht widersprechen (Begründung zuerst, dann Ergebnis).
- Kriteriennummern ([4.1], [X.5]) sind Gutachtenkriterien, keine Teilaufgaben.
- Sachlich, ohne Wertung von Personen; Hinweise sind Bitten an die Schule, keine Vorwürfe.

## Grenzen
- Das Raster im DOCX kommt nur aus der Regelprüfung (wie in der App); KI-Urteile stehen in
  Hinweisliste und Berichten, nicht im Raster.
- Inhalte nur in Abbildungen, beigefügte Dateien (USB, Projektdateien) und das Schriftbild
  prüft der Skill nicht – sie stehen in „Selbst prüfen“.
- Nur ein Vorschlag je Lauf; Kriterium 2.1 (zwei Vorschläge aus drei Lerngebieten) bleibt offen.

## Qualitätscheck
- [ ] Freigabe der Umgebung geklärt?
- [ ] `vorbereiten` gelaufen, pdftotext vorhanden (sonst Hinweis an die Person)?
- [ ] Jedes Kriterium und jede Teilaufgabe aus dem Prüfauftrag in `urteile.json` bearbeitet?
- [ ] Jede Beanstandung mit Aufgabenbezug, Konfidenz ≥ 75 % und wörtlichem Zitat?
- [ ] `abschliessen` ohne Fehler; Warnungen und Herabstufungen in der Antwort genannt?

## Beispielaufrufe
> „Begutachte Vorschlag A: `SM_VorschlagA.pdf` und `LM_VorschlagA.pdf` im Ordner Eingang.“

> „Prüf nur, ob die Teilaufgaben von Vorschlag B lösbar sind und die Musterlösung stimmt.“
> → trotzdem den ganzen Ablauf; im Bericht den Schwerpunkt auf Teil B legen.

## Dateien
- `scripts/begutachten.py` – Ablauf (umgebung | vorbereiten | abschliessen)
- `scripts/src/` – Prüfmodule der App (unverändert kopiert; Änderungen nur im Projekt)
- `scripts/einrichten.sh`, `scripts/umgebung.sh` – Einrichtung ohne Administratorrechte
- `assets/gutachtenvorlage.docx` – Gutachtenvorlage BG Technik
- `references/urteile-format.md` – Felder von `urteile.json`, Beispiele, Zitatregel
