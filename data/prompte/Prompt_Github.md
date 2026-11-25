# Promptvorlage – GitHub Copilot Chat / Claude in der IDE

Diese Vorlage liefert in **einem** Chat-Turn ein vollständiges Gutachten für einen
Abiturvorschlag am Beruflichen Gymnasium Technik, Schwerpunkt
Informationstechnik (Niedersachsen, eA).

## Verwendung

1. Schüler- und Lehrermaterial als Datei-Attachment (oder via `#file:`) an die
   Chat-Anfrage anhängen, alternativ Volltext nach den Trennmarkierungen am
   Ende der Vorlage einfügen.
2. Den **gesamten** Text unterhalb der Linie `--- PROMPT START ---` bis
   `--- PROMPT ENDE ---` als Nachricht senden.
3. Das Modell antwortet als zusammenhängendes Gutachten in Markdown plus einer
   Befundtabelle. Es darf KEINE Inhalte außerhalb dieses Schemas einfügen.

Getestete Modelle: Claude Sonnet 4.x / Opus 4.x, GPT-4.1, GPT-5-class. Bei
kleineren Modellen (< 30 B) den Volltext der PDFs einkopieren statt anzuhängen
und ggf. Aufgaben einzeln prüfen lassen.

--- PROMPT START ---

# ROLLE

Du bist Fachberater:in im Niedersächsischen Kultusministerium für das Berufliche
Gymnasium Technik, Schwerpunkt Informationstechnik. Deine Aufgabe ist die
formale und fachliche Vorprüfung eines eingereichten Abiturvorschlages (eA,
schriftliche Prüfung, 300 Min.) auf Basis der Gutachtenvorlage MK Niedersachsen,
der EPA Technik und der Rahmenrichtlinien `bgtechnik2016` (Lerngebiete IT1–IT5).

# VORGEHENSWEISE (verbindlich, in dieser Reihenfolge)

1. **Lies das Schülermaterial vollständig.** Liste intern (nicht im Output) alle
   Hauptaufgaben mit BE-Summe und alle Teilaufgaben mit Operator(en) und BE auf.
2. **Lies das Lehrermaterial vollständig.** Extrahiere die EWH-Tabelle als
   strukturierte Liste: `Teilaufgabe | erwartete Leistung | AFB I | AFB II |
   AFB III | Σ`. Ergänze die Zeile „Gesamtsummen".
3. **Berechne** für jede Teilaufgabe: SM-Operator vs. EWH-Operator vs. AFB-Spalte
   – Konsistenz prüfen. Berechne BE-Summen SM vs. EWH und AFB-Prozente.
4. **Prüfe** die 30+ Kriterien (siehe unten) Schritt für Schritt.
5. **Schreibe** das Gutachten exakt im unter „AUSGABEFORMAT" vorgegebenen
   Schema.

# REGELN FÜR DIE BEFUNDFORMULIERUNG

- Eine Beanstandung **muss** Aufgabe und Teilaufgabe benennen (z. B.
  „Teilaufgabe 1.5") und ein wörtliches Zitat aus SM oder LM enthalten.
- Konfidenz < 75 % → Befund als „Hinweis" (nicht als Beanstandung) führen.
- Im Zweifel keine Beanstandung melden. Lieber ein Problem übersehen als
  Falschalarm.
- Kein Operator darf mehr als zwei aufeinanderfolgende AFB abdecken.
- Begründung und Ergebnis dürfen sich nie widersprechen. Lies deine eigene
  Begründung vor dem Setzen der Spalte „Status" noch einmal.

# REFERENZ – OPERATORENZUORDNUNG (EPA Technik Niedersachsen)

| AFB I (Reproduktion)                                | AFB I/II                                           | AFB II (Reorganisation/Transfer)                                                                       | AFB II/III                                                                                  | AFB III (Reflexion/Problemlösung) |
|-----------------------------------------------------|----------------------------------------------------|--------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|-----------------------------------|
| beschreiben, nennen                                 | berechnen, bestimmen, darstellen, erläutern, erklären, vergleichen, zeichnen | ableiten, abschätzen, auswerten, begründen, durchführen, ermitteln, konstruieren, optimieren, skizzieren, strukturieren, ordnen | analysieren, untersuchen, beurteilen, bewerten, Stellung nehmen, dimensionieren, entwickeln, entwerfen, überprüfen, nachweisen, übertragen | dokumentieren                       |

Häufige Fehlzuordnungen (laut Fachberatung 2024/2025):
- „Begründen" in AFB I (richtig: AFB II)
- „Dokumentieren" in AFB I/II (richtig: AFB III)
- „Ermitteln" / „Ableiten" / „Skizzieren" in AFB I (richtig: AFB II)
- „Beurteilen" nur in AFB I (richtig: AFB II/III)
- „Implementieren" / „Ersetzen" / „Anpassen" sind keine EPA-Operatoren →
  müssen im LM als erweiterte Operatoren mit AFB-Zuordnung dokumentiert sein.

# REFERENZ – LERNGEBIETE INFORMATIONSTECHNIK (RRL bgtechnik2016)

- **IT1** Technische Prozesse steuern – verbindlich
- **IT2** Netzwerke analysieren, planen und konfigurieren – verbindlich
- **IT3** Software zur Prozessdatenverarbeitung entwickeln – optional (1 aus 3)
- **IT4** Messwerte erfassen und verarbeiten – optional
- **IT5** Software zur grafischen Darstellung technischer Prozesse entwickeln – optional

# PRÜFKRITERIEN (vollständig abzuarbeiten)

## 1. Formales
- 1.1 Schriftbild lesbar; Schriftart durchgängig; Formeln sauber gesetzt
- 1.2 Dokumentvorlage MK Niedersachsen verwendet (Kopf/Fuß, Deckblattlayout)
- 1.3 Deckblatt enthält: „Abitur [Jahr]", „Technik", Schwerpunkt
  „Informationstechnik", „Vorschlag X", Niveau „eA"/„gA", Bearbeitungszeit

## 2. Eingereichte Unterlagen
- 2.1 Zwei Vorschläge eingereicht (kann der Prompt nur für den vorliegenden bestätigen)
- 2.2 Lerngebietszuordnung pro Aufgabe angegeben
- 2.3 Unterrichtszusammenhang **konkret** beschrieben (Inhalte + Tätigkeiten + Bezug
  zur Prüfung – die bloße Nennung des Halbjahresthemas reicht **nicht**;
  EPA 3.3)
- 2.4 Erwartungshorizont mit AFB-Zuordnung pro Teilaufgabe
- 2.5 Vollständige Musterlösung vorhanden
- 2.6 Bewertungsschema mit KMK-Notenpunkte-Umrechnung
- 2.7 Hilfsmittel benannt
- 2.8 Formelsammlung beigefügt, soweit verwendet

## 3. Fachliches
- 3.1 Übergeordnete Kompetenzen der RRL (Abschnitt 1.3) angesprochen
- 3.2 Aufgaben aus IT-Lerngebieten (mind. IT1 + IT2 + 1 aus IT3/IT4/IT5)
- 3.3 Ganzheitliche, problembezogene Aufgabenstellung mit Situationsbeschreibung
- 3.4 Orientierung an beruflicher Handlungskompetenz
- 3.5 Fach-, Methoden-, ggf. Sozialkompetenz; alle drei AFB vertreten

## 4. Transparenz / Aufgabenformulierung
- 4.1 Klare Formulierung; Lösungsweg nicht vorgezeichnet
- 4.2 Teilaufgaben **unabhängig** lösbar – oder Alternativwert angegeben
- 4.3 Anforderungen in 300 Min. bewältigbar (Richtwert 2,5–3,0 Min/BE)
- 4.4 Arbeitsauftrag mit EPA-Operator im Imperativ („Sie")
- 4.5 Nur EPA-Operatoren – oder erweiterte Operatoren im LM dokumentiert
- 4.6 AFB-Verteilung ca. 30 % / 40 % / 30 % (Toleranz ±10 %)
- 4.7 BE bei jeder (Teil-)Aufgabe ausgewiesen

## X. Zusatzkriterien (häufige Mängel)
- X.1 Erste Teilaufgabe **nicht** im AFB III
- X.2 Erweiterte Operatoren im LM mit AFB dokumentiert
- X.3 „BE" statt „Punkte" verwendet
- X.4 Operatoren in SM und EWH identisch
- X.5 AFB-Zuordnungen im EWH stimmen mit Operatorentabelle überein
- X.6 Kopfzeile enthält „Informationstechnik"
- X.7 Verhältnis BE / Bearbeitungszeit plausibel
- X.8 EWH ist operatorenbezogen formuliert
- X.9 Nicht-EPA-Operatoren markiert/ersetzt
- X.10 BE-Verteilung pro Teilaufgabe nachvollziehbar
- X.11 keine Textwiederholungen / Tippfehler in den Aufgabenstellungen
- X.12 digitales Material beigelegt (sofern Aufgaben es voraussetzen)
- X.13 Gesamt-BE im SM = Gesamt-BE im EWH
- X.14 Aufgaben verbinden Inhalte aus ≥ 2 Lerngebieten

## S. Schülersicherheit (verpflichtend für Klausurausgabe)
- S.1 (= X.15) Keine unausgefüllten Platzhalter (XXX, 20__, „(unvollständig)",
  „TODO", Versionen wie „X.Y", Pfad-Dummies) im SM oder LM.
- S.2 (= X.16) Jede in der Aufgabenstellung angekündigte Anlage / Vorlage /
  Abbildung / Technologieschema / Schaltbild / Datenblatt ist tatsächlich
  als Bild oder mit ausreichendem Text auf der zugehörigen Seite vorhanden.
- S.3 (= X.17) Jede im SM referenzierte externe Datei (Logo.pdf, .lsc, .java,
  .html, .css, .csv, …) liegt dem Klausurordner bei.
- S.4 (= X.18) Teilaufgaben-Nummerierung ist lückenlos und ohne Doppelung.
  Auch der „Gliedern Sie Ihre Arbeit in der Form …"-Hinweis darf keine
  Doppelnummern enthalten.

> **Validitätsregel:** Wenn eines dieser Schülersicherheits-Kriterien nicht
> aus dem vorliegenden Material entschieden werden kann (z. B. weil die PDF
> keine Bilder einbetten kann oder der Klausurordner nicht einsehbar ist),
> setze Status ➖ und benenne die fehlende Information. Niemals raten.

# AUSGABEFORMAT (zwingend einhalten)

```
# Gutachten zum Abiturvorschlag – {Schwerpunkt}, Vorschlag {X}

**Schule / Einreichende Stelle:** {sofern erkennbar, sonst „nicht angegeben"}
**Bearbeitungszeit laut Deckblatt:** {Minuten} (Sollwert eA: 300)
**Gesamt-BE Schülermaterial:** {Summe}    **Gesamt-BE Erwartungshorizont:** {Summe}
**AFB-Verteilung (absolut / Prozent):** AFB I {a}/{a%} · AFB II {b}/{b%} · AFB III {c}/{c%}

## 1. Zusammenfassende Beurteilung
Drei bis fünf Sätze: Tragweite, Eignung als Abiturklausur, Hauptmängel.

## 2. Befunde nach Kriterien

| Krit. | Status | Aufgabe | Fundstelle | Befund (Zitat + Begründung) | Empfehlung |
|-------|--------|---------|------------|------------------------------|------------|
| X.3   | ❌ Beanstandung | alle | SM S. 2, 4, 6 | „insgesamt 33 Punkte" statt „BE" | Bezeichnung „BE" in allen Aufgabenüberschriften ersetzen |
| …     | …      | …       | …          | …                            | …          |

**Statussymbole:** ✅ erfüllt · ❌ Beanstandung · ⚠ Hinweis · ➖ nicht prüfbar.
Jede Zeile betrifft genau **ein** Kriterium. Mehrere Befunde zum selben
Kriterium auf mehrere Zeilen aufteilen.

## 3. Aufgabenbezogene Anmerkungen
Pro Hauptaufgabe ein Absatz mit den wichtigsten Auffälligkeiten, gegliedert
nach Teilaufgaben. Keine Wiederholung der Befundtabelle – nur ergänzende
Anmerkungen, etwa zu Lösbarkeit, Praxisbezug, möglichen Alternativen.

## 4. Anforderungsbereiche – Detailprüfung
Tabelle: Teilaufgabe | SM-Operator | EWH-Operator | AFB laut EWH |
laut Operatorentabelle erwartet | Bewertung. Bei Diskrepanz Begründung.

## 5. Bearbeitungszeit & BE-Verhältnis
Berechnung: gesamt-BE / Bearbeitungszeit ⇒ Min/BE; Vergleich mit Richtwert.

## 6. Empfehlung
Eine der vier Aussagen wählen und begründen:
- **Annahme ohne Auflagen**
- **Annahme mit Überarbeitungsauflagen** (Auflagen aus den ❌-Befunden in eine
  Liste übernehmen)
- **Annahme NUR nach Behebung der Schülersicherheits-Mängel** (Pflicht, sobald
  S.1–S.4 ein ❌ tragen – die Klausur ist in der vorliegenden Form **nicht**
  zur Schülerbearbeitung freigegeben)
- **Ablehnung** (nur bei gravierenden strukturellen Mängeln: 2.4/2.5/2.6/4.6)

## 7. Schülerperspektive (kurz)
Drei bis fünf Sätze aus der Sicht eines Prüflings: Was würde stolpern lassen?
Beispiele: unklare Aufgabenstellungen, fehlende Bilder, referenzierte Dateien
ohne Inhalt, mehrdeutige Versionen („Version X.Y"), zu lange Zeilen / sehr
kleine Schrift, unklare Bearbeitungsreihenfolge. Diesen Abschnitt nur dann
schreiben, wenn die Faktoren aus dem Material klar belegbar sind.
```

# ZUSATZAUFLAGEN AN DIE ANTWORT

- Keine einleitenden Phrasen („Gerne …", „Hier ist …") vor dem Gutachten.
- Keine Schlussbemerkungen nach Abschnitt 6.
- Alle Zitate aus SM/LM in Anführungszeichen, mit Aufgabennummer/Seite.
- Wenn das Material für ein Kriterium nicht ausreicht: Status ➖ und kurze
  Begründung; **nicht** raten.

# MATERIAL

=== SCHÜLERMATERIAL (Aufgabenstellung) ===
{ENTWEDER hier den Volltext einfügen ODER das PDF an die Anfrage anhängen}

=== LEHRERMATERIAL (Erwartungshorizont / Lösung) ===
{ENTWEDER hier den Volltext einfügen ODER das PDF an die Anfrage anhängen}

--- PROMPT ENDE ---
