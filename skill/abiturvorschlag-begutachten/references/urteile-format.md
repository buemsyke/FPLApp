# Format von `urteile.json`

`vorbereiten` legt die Datei mit allen Einträgen an, die Claude bearbeiten soll. Nur die
Werte füllen – keine Einträge hinzufügen oder löschen, Nummern nicht ändern.

## `kriterien` (Teil A)

| Feld | Werte |
|---|---|
| `ergebnis` | `beanstandung` · `keine_beanstandung` · `nicht_pruefbar` |
| `konfidenz` | 0–100; über 75 nur bei echter Sicherheit |
| `begruendung` | kurz, sachlich, mit Textbelegen; bei Beanstandung die betroffene Aufgabe/Teilaufgabe nennen |
| `fundstellen` | Liste; je Eintrag Dokument, Seite, Stelle und **wörtliches Zitat in „…“** |

Schreibweise der Fundstellen: `Schülermaterial Seite 4, 1.3: „…“`,
`Lehrermaterial Seite 9, EWH 2.1: „…“` – „Seite“ ausschreiben (die Hinweisliste kürzt nach dem
ersten Punkt), „Lehrermaterial“/„EWH“ nennen, damit der Bericht die Spalte SM/LM richtig wählt.

```json
{
  "kriterium_nr": "4.2",
  "kriterium_text": "Teilaufgaben unabhängig lösbar (Vorgabe 4.2)",
  "ergebnis": "beanstandung",
  "konfidenz": 85,
  "begruendung": "Teilaufgabe 2.3 (6 BE) baut auf Teilaufgabe 2.2 auf, ohne Alternativwert.",
  "fundstellen": ["Schülermaterial Seite 5, 2.3: „Erweitern Sie Ihr Programm aus 2.2 …“"]
}
```

Zitatregel (prüft `abschliessen`):
- Groß-/Kleinschreibung, Zeilenumbrüche, Silbentrennung und Anführungszeichen sind egal.
- Auslassungen mit `…` sind erlaubt; jedes Stück muss im Text stehen.
- Wird bei einer Beanstandung kein Zitat gefunden, wird sie zu `nicht_pruefbar`
  („[Zitat nicht im Material gefunden]“). Dann Zitat korrigieren und erneut abschließen.
- Beanstandung mit Konfidenz < 75 → `nicht_pruefbar` (wie in der App).

## `loesbarkeit` (Teil B)

| Feld | Werte |
|---|---|
| `loesbarkeit`, `richtigkeit` | `ja` · `nein` · `unklar` · `nicht_pruefbar` |
| `loesbarkeit_konfidenz`, `richtigkeit_konfidenz` | 0–100; `ja`/`nein` unter 75 wird zu `unklar` |
| `loesbarkeit_begruendung`, `richtigkeit_begruendung` | kurz, mit Bezug zur Aufgabe |
| `fehlende_information` | Liste – Pflicht bei `loesbarkeit: nein` |
| `fehler_in_loesung` | Liste konkreter Fehler – Pflicht bei `richtigkeit: nein` |

```json
{
  "teilaufgabe": "1.4",
  "lerngebiet": "IT2",
  "loesbarkeit": "ja",
  "loesbarkeit_konfidenz": 85,
  "loesbarkeit_begruendung": "IP-Adresse und Präfix stehen in der Situationsbeschreibung.",
  "fehlende_information": [],
  "richtigkeit": "nein",
  "richtigkeit_konfidenz": 90,
  "richtigkeit_begruendung": "Broadcast falsch berechnet: /26 ergibt .63, nicht .64.",
  "fehler_in_loesung": ["Broadcastadresse 192.168.10.64 statt 192.168.10.63"]
}
```

Sonderfälle:
- Musterlösung nur als Bild oder sehr kurz → `richtigkeit: nicht_pruefbar`.
- Aufgabe hängt von einer Abbildung/Anlage ab, deren Inhalt nicht im Text steht →
  `loesbarkeit: nicht_pruefbar`.
- `modell` oben in der Datei bleibt „Claude“ (erscheint in Hinweisliste und Berichten).
