"""
Prüfanweisungen der KI-gestützten Prüfung (Stufe 2) – ohne Modellanbindung.

Enthält System-Prompt, die kriterienspezifischen Prüfanweisungen, die
Platzhalter-Auflösung und die Ergebnis-Datenklasse. Bewusst ohne Abhängigkeit
von ``openai`` oder ``eduwerkzeuge``: Das Modul wird von
``src.bewertung.ki_gestuetzt`` (App, lokale Modelle) und vom Skill
``abiturvorschlag-begutachten`` (Claude prüft selbst) gemeinsam genutzt.
Änderungen an den Prüfanweisungen wirken daher in beiden Varianten.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.bewertung.regelbasiert import (
    ABITUR_BEARBEITUNGSZEIT_MIN,
    IT_LERNGEBIETE,
    IT_OPTIONAL,
    IT_VERBINDLICH,
    RRL_KOMPETENZEN,
)

# Konfidenz-Schwelle: darunter gilt eine Beanstandung als „nicht sicher prüfbar"
KONFIDENZ_SCHWELLE = 75


SYSTEM_PROMPT = """\
Du bist ein erfahrener Gutachter für Abiturklausuren am Beruflichen Gymnasium \
Technik, Schwerpunkt Informationstechnik (Niedersachsen). Du prüfst \
Abiturvorschläge (Schülermaterial + Lehrermaterial) gegen die amtlichen Kriterien.

WICHTIGE REGELN:
1. Melde NUR eindeutige, belegbare Verstöße. Formuliere sachlich und präzise.
2. Wenn du dir nicht sicher bist, ob ein Verstoß vorliegt, antworte mit \
   „keine Beanstandung erkennbar". Lieber ein Problem übersehen als einen \
   falschen Alarm auslösen.
3. Beziehe dich konkret auf Textstellen aus dem Material.
4. Antworte IMMER im folgenden JSON-Format (kein anderer Text davor/danach):
{
  "ergebnis": "beanstandung" | "keine_beanstandung" | "nicht_pruefbar",
  "konfidenz": <0-100>,
  "begruendung": "<kurze sachliche Begründung mit Textbelegen>",
  "fundstellen": ["<Zitat oder Verweis 1>", "<Zitat oder Verweis 2>"]
}
5. Setze „konfidenz" nur auf >75, wenn du dir wirklich sicher bist.
6. Setze „ergebnis" auf „nicht_pruefbar", wenn der bereitgestellte Text \
   nicht ausreicht, um das Kriterium zu bewerten.

KONSISTENZ-REGELN (UNBEDINGT BEACHTEN):
7. ACHTUNG: Die Kriteriennummer (z.B. [1.3]) bezieht sich auf das \
   PRÜFKRITERIUM im Gutachten, NICHT auf eine Teilaufgabe der Klausur! \
   Verwechsle diese nicht. Lies die PRÜFANWEISUNG, nicht die Aufgabennummer.
8. Lies deine Begründung NOCHMALS, bevor du das Ergebnis setzt: \
   Wenn deine Begründung sagt, das Kriterium sei ERFÜLLT, MUSS das \
   Ergebnis „keine_beanstandung" lauten – und umgekehrt. \
   Begründung und Ergebnis dürfen sich NIEMALS widersprechen.
9. Wenn du feststellst, dass die nötigen Informationen nicht vorhanden \
   sind oder du das Kriterium nicht bewerten kannst, MUSS das Ergebnis \
   „nicht_pruefbar" sein – NICHT „keine_beanstandung" oder „beanstandung".
10. TABELLEN IM PDF: Der Text wurde aus PDF extrahiert. Tabellen können \
    fragmentiert erscheinen (Spalten als separate Textzeilen). Suche gezielt \
    nach Zahlenreihen und ordne sie den Spaltenüberschriften zu. \
    Bei EWH-Tabellen stehen typischerweise die Spalten: \
    Teilaufgabe | Erwartete Schülerleistung | AFB I | AFB II | AFB III | Σ \
    und am Ende eine Zeile „Gesamtsummen".
11. BEANSTANDUNGEN – AUFGABENBEZUG PFLICHT: Wenn du eine Beanstandung \
    meldest, MUSS die Begründung die konkret betroffene Aufgabe und \
    Teilaufgabe benennen (z.B. „Aufgabe 2, Teilaufgabe 2.1" oder \
    „Aufgabe 1, Teilaufgaben 1.2 und 1.4"). \
    Allgemeine Aussagen ohne Aufgabenbezug sind NICHT ausreichend.
12. DOKUMENTRAHMEN: Das Material wird durch die Prüfsoftware mit den \
    Trennzeichen „=== SCHÜLERMATERIAL (Aufgabenstellung) ===" und \
    „=== LEHRERMATERIAL (Erwartungshorizont / Lösung) ===" strukturiert. \
    Diese Zeilen sind KEINE Teile des Klausurinhalts – sie sind nur \
    Software-Markierungen. Das eigentliche Deckblatt, die Aufgaben und \
    der Erwartungshorizont beginnen jeweils NACH dem Trennzeichen.
"""

# ---------------------------------------------------------------------------
# Kriterien-spezifische Prompts
# ---------------------------------------------------------------------------
# Jedes Kriterium, das manuell geprüft werden muss, bekommt einen eigenen
# Prompt.  Kriterien, die physisch/visuell geprüft werden müssen, werden
# übersprungen (KI_NICHT_PRUEFBAR).
#
# → Die Prüftexte sind im Dict KI_PRUEF_PROMPTS definiert (s.u.).
#   Schlüssel = Kriterium-Nummer, Wert = Prüfanweisung für die KI.
#   Platzhalter {rrl_kompetenzen}, {operatoren_tabelle} etc. werden
#   von _baue_prompt() dynamisch aufgelöst.

KI_NICHT_PRUEFBAR = {
    "1.1",  # Schriftbild – visuell
    "2.1",  # Zwei Vorschläge – nur ein Vorschlag wird geprüft
    "2.8",  # Formelsammlung – physisch
    "X.12", # Digitales Material – physisch
}

# ---------------------------------------------------------------------------
# KI_PRUEF_PROMPTS – die 16 Prüfanweisungen für LM Studio
# ---------------------------------------------------------------------------
# Jeder Eintrag enthält die Prüfanweisung, die an das lokale Sprachmodell
# gesendet wird.  Platzhalter in geschweiften Klammern (z.B. {rrl_kompetenzen})
# werden von _baue_prompt() / _baue_batch_prompt() zur Laufzeit ersetzt.
#
# Verfügbare Platzhalter:
#   {rrl_kompetenzen}     – Auflistung der RRL-Kompetenzen
#   {lerngebiete}         – Auflistung der IT-Lerngebiete
#   {verbindlich}         – Verbindliche Lerngebiete
#   {optional}            – Optionale Lerngebiete
#   {operatoren_tabelle}  – Operatoren mit AFB (kurz)
#   {operatoren_detail}   – Operatoren mit AFB + Beschreibung
#   {bearbeitungszeit}    – Bearbeitungszeit in Minuten
KI_PRUEF_PROMPTS: dict[str, str] = {
    "1.3": (
        "HINWEIS ZUR DOKUMENTSTRUKTUR: Der bereitgestellte Text beginnt mit der "
        "Systemmarkierung '=== SCHÜLERMATERIAL (Aufgabenstellung) ==='. "
        "Diese Zeile ist KEIN Deckblatt – sie ist eine Trennmarkierung der Prüfsoftware. "
        "Das eigentliche Deckblatt befindet sich NACH dieser Markierung "
        "als erste Seite des Dokuments.\n\n"
        "Prüfe, ob das Schülermaterial ein Deckblatt nach amtlichem Muster enthält. "
        "Ein normgerechtes Deckblatt enthält:\n"
        "- 'Abiturprüfung', 'Zentralabitur' oder 'Abitur [Jahr/Platzhalter]'\n"
        "- Fach 'Technik'\n"
        "- Schwerpunkt (z.B. 'Informationstechnik' oder 'Mechatronik')\n"
        "- Vorschlag, Aufgabe oder Buchstabe (z.B. 'Vorschlag A')\n"
        "- Anforderungsniveau 'eA' (erhöhtes) oder 'gA' (grundlegendes)\n"
        "- Bearbeitungszeit in Minuten\n\n"
        "VORGEHEN:\n"
        "1. Überspringe die erste Zeile '=== SCHÜLERMATERIAL ==='\n"
        "2. Lies die folgenden 30–40 Zeilen als erste Seite des Dokuments\n"
        "3. Suche nach den 6 Deckblatt-Elementen und zitiere sie wörtlich\n"
        "4. Wenn ≥ 4 Elemente gefunden: keine_beanstandung (mit Zitaten)\n"
        "5. Wenn < 3 Elemente: beanstandung (mit Angabe was fehlt)\n"
        "6. Wenn kein lesbarer Text nach dem Trennzeichen: nicht_pruefbar"
    ),
    "3.1": (
        "Prüfe, ob die Aufgaben übergeordnete Kompetenzen gemäß den Rahmenrichtlinien "
        "(RRL bgtechnik2016.pdf, Abschnitt 1.3) ansprechen.\n\n"
        "Die übergeordneten Kompetenzen sind:\n"
        "{rrl_kompetenzen}\n\n"
        "Es müssen NICHT alle Kompetenzen abgedeckt sein, aber die Aufgaben "
        "sollten erkennbar mehrere dieser Kompetenzen fördern. "
        "Melde nur dann eine Beanstandung, wenn die Aufgaben OFFENSICHTLICH "
        "keine der genannten Kompetenzen ansprechen."
    ),
    "3.2": (
        "Prüfe, ob die Aufgaben aus den Lerngebieten der RRL Informationstechnik stammen.\n\n"
        "Die offiziellen Lerngebiete der RRL BG Technik – Informationstechnik "
        "(bgtechnik2016.pdf) sind:\n"
        "{lerngebiete}\n\n"
        "Verbindlich (beide müssen abgedeckt sein): {verbindlich}.\n"
        "Optional (mind. 1 aus 3 muss abgedeckt sein): {optional}.\n\n"
        "WICHTIG – Schulspezifische Lerngebiete:\n"
        "Die offiziellen RRL enthalten NUR die Lerngebiete IT1–IT5. "
        "Lerngebiete IT6 und höher sind NICHT in der offiziellen RRL enthalten.\n"
        "Falls das Lehrermaterial ein Lerngebiet 'IT6' oder höher ausweist:\n"
        "  → Dies ist ein schulinternes/schulspezifisches Lerngebiet.\n"
        "  → Ohne Vorlage des schulischen Curriculums kann die vollständige Prüfung\n"
        "    NICHT abgeschlossen werden.\n"
        "  → Melde dies als Beanstandung mit dem Hinweis:\n"
        "    'Lerngebiet ITx ist nicht in der offiziellen RRL bgtechnik2016 enthalten.\n"
        "     Ohne schulisches Curriculum ist keine vollständige Prüfung möglich.'\n\n"
        "Prüfe anhand der Aufgabeninhalte (nicht nur Schlüsselwörter), "
        "welche Lerngebiete angesprochen werden. Melde eine Beanstandung, "
        "wenn die Aufgaben offensichtlich nicht aus den genannten Lerngebieten stammen "
        "ODER wenn ein nicht-offizielles Lerngebiet (IT6+) verwendet wird."
    ),
    "3.3": (
        "Prüfe, ob die Aufgabenstellung ganzheitlich und problembezogen ist.\n\n"
        "Kriterien für Ganzheitlichkeit:\n"
        "- Zusammenhängende Situationsbeschreibung / Szenario vorhanden\n"
        "- Aufgaben sind in einen realitätsnahen Kontext eingebettet\n"
        "- Komplexe, nicht-triviale Problemstellungen\n"
        "- Mehrere Lerngebiete / Themenfelder werden verknüpft\n\n"
        "Melde eine Beanstandung NUR, wenn die Aufgaben offensichtlich "
        "zusammenhanglos, trivial oder ohne jeden Praxisbezug sind."
    ),
    "3.4": (
        "Prüfe, ob die Aufgabenstellung an beruflicher Handlungskompetenz orientiert ist.\n\n"
        "Kriterien:\n"
        "- Berufstypische Problemstellungen aus der Informationstechnik\n"
        "- Bezug zu realen Arbeitsaufträgen, Projekten oder betrieblichen Situationen\n"
        "- Handlungsorientierung (Prüfling soll aktiv Lösungen erarbeiten)\n\n"
        "Melde eine Beanstandung NUR, wenn die Aufgaben keinerlei Bezug "
        "zu beruflichen Situationen oder der IT-Praxis erkennen lassen."
    ),
    "3.5": (
        "Prüfe, ob die Aufgaben verschiedene Kompetenzen ansprechen.\n\n"
        "Geprüft werden soll:\n"
        "- Fachkompetenz (Fachwissen anwenden)\n"
        "- Methodenkompetenz (Lösungsverfahren, Analyse, Dokumentation)\n"
        "- ggf. Sozialkompetenz, Selbstkompetenz\n"
        "- Alle drei Anforderungsbereiche (AFB I: Reproduktion, "
        "AFB II: Reorganisation/Transfer, AFB III: Reflexion/Problemlösung)\n\n"
        "Die verwendete Operatorentabelle:\n"
        "{operatoren_tabelle}\n\n"
        "Melde eine Beanstandung NUR, wenn offensichtlich nur ein "
        "Anforderungsbereich oder nur eine Kompetenz abgedeckt wird."
    ),
    "4.1": (
        "Prüfe ob die Aufgaben klar formuliert sind und ob der Lösungsweg NICHT vorgezeichnet ist "
        "(Vorgabe 4.1).\n\n"
        "BEANSTANDUNGSGRÜNDE (mit konkretem Textzitat melden):\n"
        "A) MEHRDEUTIGKEIT:\n"
        "   - 'Welche Typen sollen verglichen werden?' fehlt → unklar was gemeint ist\n"
        "   - Fehlt: Auf welche Abbildung/Anlage soll sich der Schüler beziehen?\n"
        "   - Fehlt: Wie viele Elemente sollen erstellt/genannt/beschrieben werden?\n"
        "   - Formulierung kann zwei verschiedene Aufgabenstellungen meinen\n"
        "B) VORGEZEICHNETER LÖSUNGSWEG:\n"
        "   - Explizite Schritt-für-Schritt-Anleitung ('Schritt 1: ..., Schritt 2: ...')\n"
        "   - 'Gehen Sie wie folgt vor:' mit aufgelisteten Teilschritten\n"
        "   - 'Zunächst ... dann ... abschließend' als verbindliche Reihenfolge\n"
        "C) AUFGABENSTELLUNG IST BESCHREIBUNG, KEIN ARBEITSAUFTRAG:\n"
        "   - Fragen statt Operatoren: 'Was ist ...?' statt 'Beschreiben Sie ...'\n"
        "   - Fehlende Handlungsanweisung (kein Operator im Imperativ)\n"
        "   Hinweis: 'Es ist ... zu erstellen' ist kein Arbeitsauftrag nach EPA!\n\n"
        "KEINE Beanstandung wenn:\n"
        "- Strukturierte Teilaufgaben (1.1, 1.2, ...) ohne Schrittanweisungen verwendet werden\n"
        "- Die Aufgabenstellung konkret genug ist, auch wenn sie knapp formuliert ist\n"
        "- Operatoren korrekt im Imperativ mit 'Sie' verwendet werden\n\n"
        "Melde NUR eindeutige Fälle mit wörtlichem Zitat und Angabe der Teilaufgabe."
    ),
    "4.3": (
        "Prüfe ob die Anforderungen in der angegebenen Bearbeitungszeit angemessen sind "
        "(Vorgabe 4.3).\n\n"
        "Abitur-Sollwert Bearbeitungszeit: {bearbeitungszeit} Minuten.\n"
        "Vorabcheck-Hinweis (regelbasiert): {kommentar}\n\n"
        "PRÜFVORGEHEN (Schritt für Schritt, alle Schritte zwingend durchführen):\n"
        "SCHRITT 1 – BE aus dem SCHÜLERMATERIAL ablesen:\n"
        "  Suche bei jeder Hauptaufgabe die BE-Angabe in eckigen Klammern oder 'insgesamt X BE'.\n"
        "  Zähle ALLE Hauptaufgaben auf: Aufg. 1 = X BE, Aufg. 2 = Y BE, Aufg. 3 = Z BE\n"
        "  Gesamt-SM = X + Y + Z BE\n"
        "  ACHTUNG: Zähle nur die Hauptaufgaben-Summen, NICHT die Teilaufgaben einzeln!\n\n"
        "SCHRITT 2 – Bearbeitungszeit aus SM ablesen:\n"
        "  Suche 'Bearbeitungszeit: X Minuten' auf dem Deckblatt.\n"
        "  Falls nicht gefunden oder abweichend vom Sollwert ({bearbeitungszeit} Min): notieren.\n\n"
        "SCHRITT 3 – Verhältnis berechnen:\n"
        "  Verhältnis = angegebene_Bearbeitungszeit / Gesamt-SM-BE\n"
        "  Richtwert: 2,5–3,0 Minuten pro BE.\n"
        "  Laut Gutachten-Auswertung (Lüneburg): ca. 3 Minuten pro BE als Orientierung.\n\n"
        "SCHRITT 4 – Beurteilung:\n"
        "  - Verhältnis < 1,5 Min/BE → zu wenig Zeit → Beanstandung\n"
        "  - Verhältnis 1,5–4,0 Min/BE → akzeptabel → keine Beanstandung\n"
        "  - Verhältnis > 4,0 Min/BE → zu wenig Aufgaben → Beanstandung\n"
        "  - Bearbeitungszeit weicht vom Sollwert ({bearbeitungszeit} Min) ab → Beanstandung\n\n"
        "Zeige die Berechnung in der Begründung:\n"
        "  'SM: Aufg. 1 = X BE + Aufg. 2 = Y BE → Gesamt = Z BE\n"
        "   Verhältnis: W Min / Z BE = N,N Min/BE (Richtwert: 2,5–3,0)'\n"
        "Im Zweifel: keine Beanstandung."
    ),
    "X.5": (
        "VORVERARBEITETE EWH-TABELLE (automatisch extrahiert – Ausgangspunkt für Prüfung):\n"
        "{ewh_vorverarbeitet}\n"
        "Falls die Tabelle leer oder als [Extraktion fehlgeschlagen] markiert ist:\n"
        "  → Prüfe trotzdem anhand des Rohtexts im LEHRERMATERIAL-Abschnitt unten.\n"
        "  → Vermerke im 'begruendung'-Feld explizit, welche Zeilen nicht auswertbar waren.\n\n"
        "Prüfe die AFB-Zuordnungen im Erwartungshorizont (Lehrermaterial) auf zwei Dinge:\n"
        "A) Stimmen die Operatoren im EWH mit den Operatoren in der Aufgabenstellung (SM) überein?\n"
        "B) Sind die Operatoren dem richtigen Anforderungsbereich zugeordnet?\n\n"
        "Die offizielle Operatorentabelle (EPA + ggf. erweitert):\n"
        "{operatoren_detail}\n\n"
        "Vom Lehrermaterial selbst eingeführte erweiterte Operatoren – "
        "diese müssen exakt mit den dort dokumentierten AFB übereinstimmen, "
        "Abweichungen sind eine Beanstandung:\n"
        "{operatoren_erweitert}\n\n"
        "PRÜFVORGEHEN (Schritt für Schritt):\n"
        "1. Suche im Lehrermaterial den Abschnitt 'Erwartungshorizont'.\n"
        "2. Die EWH-Tabelle hat Spalten: Teilaufgabe | Erwartete Schülerleistung | "
        "AFB I | AFB II | AFB III | Σ\n"
        "3. Für jede Zeile: Welcher Operator im EWH? In welcher AFB-Spalte stehen Punkte?\n"
        "4. Suche den entsprechenden Operator im Schülermaterial für dieselbe Teilaufgabe.\n"
        "5. Prüfe: Sind SM-Operator und EWH-Operator IDENTISCH?\n\n"
        "ZWINGEND ZU PRÜFENDE FEHLZUORDNUNGEN (häufigste Fehler laut Gutachten):\n"
        "- 'Begründen' → NUR AFB II! Punkte in AFB I = FEHLER. "
        "(Häufigster Fehler – Gutachten Hannover, Lüchow)\n"
        "- 'Dokumentieren' → NUR AFB III! Punkte in AFB I oder II = FEHLER. "
        "(Gutachten Hannover, Hildesheim)\n"
        "- 'Skizzieren' → NUR AFB II! Punkte in AFB I = FEHLER. "
        "(Gutachten Lüchow, Lüneburg)\n"
        "- 'Ermitteln' → NUR AFB II! Punkte in AFB I = FEHLER. (Gutachten Hannover)\n"
        "- 'Ableiten' → NUR AFB II! Punkte in AFB I = FEHLER. (Gutachten Hannover)\n"
        "- 'Beurteilen' → NUR AFB II/III! Punkte nur in AFB I = FEHLER. "
        "(Gutachten Hannover, Lüneburg)\n"
        "- 'Beschreiben' → NUR AFB I! Punkte in AFB II/III = FEHLER.\n"
        "- 'Nennen' → NUR AFB I! Punkte in AFB II/III = FEHLER.\n"
        "- 'Entwickeln'/'Entwerfen' → AFB II/III! Punkte nur in AFB I = FEHLER.\n"
        "- Ein Operator darf MAXIMAL ZWEI aufeinanderfolgende AFBs abdecken.\n\n"
        "KONSISTENZ SM ↔ EWH (zwingend prüfen):\n"
        "Wenn die Aufgabenstellung 'Erläutern Sie' sagt, aber der EWH 'Beschreiben' schreibt "
        "→ BEANSTANDUNG. Die Operatoren müssen in SM und EWH identisch sein.\n\n"
        "Melde NUR eindeutige Fehlzuordnungen oder Inkonsistenzen mit konkretem Textzitat.\n"
        "Format: 'Teilaufgabe X.Y: SM-Operator [Zitat] vs. EWH-Operator [Zitat]; "
        "AFB-Zuordnung: ist AFB Z, muss AFB W sein'\n"
        "Wenn die EWH-Tabelle weder automatisch extrahierbar noch im Rohtext lesbar ist: nicht_pruefbar.\n"
        "Vermerke in diesem Fall im 'begruendung'-Feld: "
        "'EWH-Tabelle nicht extrahierbar – manuelle Prüfung erforderlich.'"
    ),
    # --- Bedingt manuelle Kriterien ---
    "2.3": (
        "Prüfe ob die Beschreibung des Unterrichtszusammenhangs im Lehrermaterial "
        "AUSREICHEND KONKRET ist (gemäß EPA 3.3).\n\n"
        "HINTERGRUND: Laut Auswertung der Fachberatung (Hannover 2026) genügt der bloße "
        "Verweis auf das Halbjahresthema NICHT. Gefordert ist: Welche konkreten Unterrichtsinhalte "
        "und Aufgabentypen wurden behandelt? Warum können die Schüler diese Prüfung lösen?\n\n"
        "PRÜFSCHEMA (alle vier Punkte bewerten):\n"
        "1. LERNGEBIETE: Werden konkrete Lerngebietskennungen (IT1–IT5) mit Inhalt genannt?\n"
        "   → Nur 'Lerngebiet IT1 wurde behandelt' ist NICHT ausreichend.\n"
        "   → Ausreichend: 'In IT1 wurden Steuerungsabläufe mit SPS/LOGO! behandelt, "
        "     insbesondere Wertetabellen und Funktionsgleichungen.'\n"
        "2. AUFGABENTYPEN: Welche konkreten Problemstellungen wurden im Unterricht geübt?\n"
        "   → Ausreichend: 'Die Schüler haben ... entworfen / programmiert / analysiert'\n"
        "   → Nicht ausreichend: Nur Themennennung ohne Tätigkeitsbeschreibung\n"
        "3. KOMPETENZBEGRÜNDUNG: Warum können die Schüler diese Prüfungsaufgabe lösen?\n"
        "   → Ausreichend: Begründung dass erworbene Kompetenzen die Prüfungsaufgabe ermöglichen\n"
        "4. BEZUG ZUR PRÜFUNGSAUFGABE: Ist der Zusammenhang zwischen Unterricht und Prüfung klar?\n"
        "   → Nicht ausreichend: Nur das Halbjahresthema nennen\n\n"
        "ERGEBNIS:\n"
        "- 'keine_beanstandung': Alle vier Punkte ausreichend erfüllt (mit Textzitaten)\n"
        "- 'beanstandung': Beschreibung fehlt oder ist auf bloße Themennennung reduziert "
        "(mit genauer Begründung WAS fehlt)\n"
        "- 'nicht_pruefbar': Kein entsprechender Abschnitt im Lehrermaterial vorhanden\n\n"
        "WICHTIG: Zitiere konkret aus dem Lehrermaterial, was vorhanden ist, "
        "und benenne explizit was fehlt."
    ),
    "2.5": (
        "Prüfe, ob im Lehrermaterial eine komplette Lösung / Musterlösung "
        "vorhanden ist.\n\n"
        "Eine Musterlösung sollte alle Teilaufgaben abdecken und "
        "nachvollziehbare Lösungswege zeigen. "
        "Melde nur dann eine Beanstandung, wenn offensichtlich keine "
        "Lösung oder nur sehr bruchstückhafte Hinweise vorhanden sind."
    ),
    "2.6": (
        "Prüfe, ob im Lehrermaterial ein Bewertungsschema vorhanden ist.\n\n"
        "Ein Bewertungsschema enthält typischerweise:\n"
        "- Zuordnung von Bewertungseinheiten (BE) zu KMK-Notenpunkten (0–15)\n"
        "- Oder eine Umrechnungstabelle BE → Note\n"
        "Melde nur dann eine Beanstandung, wenn kein Schema erkennbar ist."
    ),
    "4.2": (
        "Prüfe ob jede Teilaufgabe unabhängig von anderen lösbar ist (Vorgabe 4.2). "
        "Dies ist laut Auswertung der häufigste Mangel in eingereichten Abiturvorschlägen.\n\n"
        "PRÜFVORGEHEN (Schritt für Schritt):\n"
        "1. Liste ALLE Teilaufgaben auf, die du im Schülermaterial findest "
        "(Format: X.Y – BE-Anzahl – Operator).\n"
        "2. Für jede Teilaufgabe: Enthält sie einen EXPLIZITEN Verweis auf "
        "das Ergebnis/die Lösung/das Schaltbild/den Code einer ANDEREN Teilaufgabe?\n"
        "   Typische Formulierungen für Abhängigkeit:\n"
        "   - 'das Schaltbild aus X.Y' / 'Ihr Programm aus Aufgabe X.Y'\n"
        "   - 'Ergänzen Sie das in X.Y erstellte ...' / 'Erweitern Sie Ihre Lösung aus ...'\n"
        "   - 'Auf Basis Ihrer Tabelle aus X.Y ...' / 'Verwenden Sie das Ergebnis aus ...'\n"
        "   - 'Tragen Sie in das Diagramm aus X.Y ein ...'\n"
        "3. Falls eine Abhängigkeit erkannt: Gibt es einen ALTERNATIVWERT oder -HINWEIS?\n"
        "   Typische Absicherungen:\n"
        "   - 'Sollten Sie kein Ergebnis haben, verwenden Sie den Wert ...'\n"
        "   - 'Falls Sie in X.Y keine Lösung erarbeitet haben, nutzen Sie ...'\n"
        "   - 'Alternativwert: ...'\n\n"
        "BEANSTANDUNG nur wenn:\n"
        "a) Eine echte Abhängigkeit besteht (Ergebnis aus TA A wird in TA B ZWINGEND benötigt) UND\n"
        "b) Kein Alternativwert / kein Hinweis für den Fall des Scheiterns angegeben ist UND\n"
        "c) Die abhängige Teilaufgabe mindestens 4 BE hat (signifikantes Gewicht).\n\n"
        "KEINE Beanstandung wenn:\n"
        "- Aufgaben nur THEMATISCH zusammenhängen, aber unabhängig lösbar sind\n"
        "- Ein Alternativwert oder -hinweis gegeben ist\n"
        "- Nur ein gemeinsames Szenario/Kontext geteilt wird (das ist gewünscht!)\n\n"
        "FORMAT der Beanstandung (zwingend mit Zitat):\n"
        "'Teilaufgabe X.Y (Z BE) baut auf Teilaufgabe X.W auf: "
        "[wörtliches Zitat der abhängigen Formulierung]. Kein Alternativwert angegeben.'"
    ),
    "4.4": (
        "Prüfe, ob die Aufgabenstellungen als Arbeitsaufträge / "
        "Handlungsanweisungen formuliert sind.\n\n"
        "Korrekt: Verwendung von Operatoren im Imperativ mit 'Sie' "
        "(z.B. 'Berechnen Sie ...', 'Erläutern Sie ...').\n"
        "Problematisch: Reine Fragen ('Was ist ...?', 'Wie funktioniert ...?') "
        "ohne Operatoren.\n\n"
        "Melde nur dann eine Beanstandung, wenn die Mehrheit der Aufgaben "
        "NICHT als Arbeitsauftrag formuliert ist."
    ),
    "4.6": (
        "Prüfe die Verteilung der Anforderungsbereiche (AFB I, II, III) "
        "im Erwartungshorizont.\n\n"
        "Sollverteilung: AFB I: ca. 30%, AFB II: ca. 40%, AFB III: ca. 30% "
        "(Toleranz jeweils ±10%, d.h. akzeptabel: I: 20–40%, II: 30–50%, III: 20–40%).\n\n"
        "TABELLEN-SUCHE (der Text stammt aus PDF-Extraktion):\n"
        "Die EWH-Tabelle hat Spalten: Teilaufgabe | Erwartete Schülerleistung | "
        "AFB I | AFB II | AFB III | Σ\n"
        "Am Tabellenende steht: 'Gesamtsummen (absolut)' mit den BE-Summen pro Spalte.\n"
        "Da PDF-Text keine Tabellenstruktur erhält, erscheinen die Summen oft als Zahlenfolge:\n"
        "  'Gesamtsummen 30 42 28 100' (= AFB I=30, II=42, III=28, Gesamt=100)\n"
        "ODER mehrzeilig:\n"
        "  'Gesamtsummen'\n"
        "  '30    42    28    100'\n\n"
        "BERECHNUNG:\n"
        "1. Finde die 4 Zahlen nach 'Gesamtsummen' (absolute BE: I, II, III, Gesamt)\n"
        "2. Berechne Prozente: Zeige explizit: 'AFB I: 30/100 = 30%'\n"
        "3. Vergleiche: Liegt jeder Wert im Toleranzbereich?\n\n"
        "Melde eine Beanstandung NUR, wenn ein AFB deutlich außerhalb liegt (< 15% oder > 55%). "
        "Wenn keine 'Gesamtsummen'-Zeile auffindbar: nicht_pruefbar (NICHT beanstandung)."
    ),
    "X.8": (
        "Prüfe, ob der Erwartungshorizont im Lehrermaterial operatorenbezogen "
        "formuliert ist.\n\n"
        "Das bedeutet: Die erwarteten Schülerleistungen im EWH sollten "
        "mit den gleichen EPA-Operatoren beschrieben werden, die in der "
        "Aufgabenstellung verwendet werden.\n"
        "Melde nur dann eine Beanstandung, wenn der EWH offensichtlich "
        "KEINE Operatoren verwendet."
    ),
    "X.10": (
        "Prüfe, ob die Punkteverteilung (BE) im Erwartungshorizont "
        "transparent und nachvollziehbar ist.\n\n"
        "HINWEIS ZUR EWH-TABELLE:\n"
        "Der EWH enthält typischerweise eine Tabelle, in der für jede "
        "Teilaufgabe die BE auf die Anforderungsbereiche (AFB I, II, III) "
        "aufgeteilt sind. Wenn diese Tabelle vorhanden ist und die "
        "BE-Zuordnung pro Teilaufgabe erkennbar ist, gilt die "
        "Punkteverteilung als transparent.\n\n"
        "Bei mehreren Operatoren / Anforderungen pro Teilaufgabe sollte "
        "erkennbar sein, welche Teilleistung wie viele BE ergibt.\n"
        "Melde nur dann eine Beanstandung, wenn die BE-Zuordnung "
        "völlig intransparent ist (keine Tabelle, keine BE-Angaben). "
        "Eine typische EWH-Tabelle mit BE pro Teilaufgabe und AFB "
        "ist AUSREICHEND transparent – das ist Standardformat."
    ),
    "X.13": (
        "Prüfe, ob die Gesamtpunktzahl aus dem Schülermaterial mit der "
        "Gesamtzahl im Erwartungshorizont übereinstimmt.\n\n"
        "Der regelbasierte Vorabcheck hat ermittelt:\n"
        "{kommentar}\n\n"
        "SCHRITT-FÜR-SCHRITT-ANLEITUNG:\n"
        "1. SCHÜLERMATERIAL: Suche nach BE-Angaben bei jeder Hauptaufgabe "
        "   (z.B. 'insgesamt 33 BE', '[50 BE]', '33 Punkte'). "
        "   Liste auf: Aufg. 1 = X BE, Aufg. 2 = Y BE, Aufg. 3 = Z BE → Summe = W BE\n"
        "2. LEHRERMATERIAL (EWH): Suche 'Gesamtsummen' und lies die Gesamt-BE ab "
        "   (letzte Zahl in der Zahlenfolge nach 'Gesamtsummen').\n"
        "3. VERGLEICH: SM-Summe == EWH-Summe?\n\n"
        "ZEIGE die Berechnung in der Begründung:\n"
        "  SM: Aufg. 1 = X BE + Aufg. 2 = Y BE → Summe = W BE\n"
        "  EWH: Gesamtsumme = V BE\n"
        "  W == V → keine_beanstandung / W ≠ V → beanstandung\n\n"
        "Melde NUR eine Beanstandung, wenn die Summen tatsächlich UNTERSCHIEDLICH sind. "
        "Wenn du eine der Summen nicht finden kannst: nicht_pruefbar."
    ),
    "X.14": (
        "Prüfe ob die Aufgabenstellung Inhalte aus mindestens zwei verschiedenen Lerngebieten "
        "abdeckt (laut Vorgabe müssen beide Vorschläge zusammen aus mind. 3 Lerngebieten stammen).\n\n"
        "HINTERGRUND: Laut Auswertung Fachberatung (Zeven 2026): 'Keine Aufgabe verbindet "
        "mehr als ein Lerngebiet.' Dies ist ein qualitativer Hinweis.\n\n"
        "Die Lerngebiete der RRL Informationstechnik:\n"
        "{lerngebiete}\n\n"
        "Verbindlich: {verbindlich}. Optional (1 aus 3): {optional}.\n\n"
        "PRÜFVORGEHEN:\n"
        "1. Identifiziere für jede Hauptaufgabe das primäre Lerngebiet anhand der Inhalte.\n"
        "2. Prüfe ob mindestens IT1 UND IT2 (verbindlich) abgedeckt sind.\n"
        "3. Prüfe ob mindestens ein optionales Lerngebiet (IT3, IT4 oder IT5) abgedeckt ist.\n"
        "4. Prüfe ob mindestens eine Aufgabe Inhalte aus MEHREREN Lerngebieten verbindet "
        "(wünschenswert, aber kein hartes Kriterium).\n\n"
        "BEANSTANDUNG wenn:\n"
        "- Ein verbindliches Lerngebiet (IT1 oder IT2) fehlt vollständig\n"
        "- Alle Aufgaben stammen aus demselben Lerngebiet (kein optionales vertreten)\n\n"
        "HINWEIS (keine Beanstandung, nur Kommentar) wenn:\n"
        "- Alle Aufgaben aus einzelnen Lerngebieten kommen, aber kein Aufgaben-übergreifendes Thema\n\n"
        "Format der Fundstellen: 'Aufgabe X → Lerngebiet IT[N] ([Zitat aus Aufgabenstellung])'"
    ),
}


def _extrahiere_ewh_zeilen(lehrer_text: str) -> tuple[list[dict], str]:
    """Extrahiert EWH-Tabellendaten heuristisch aus dem Lehrermaterial-Text.

    Gibt (zeilen, hinweis) zurück:
    - zeilen: list of {teilaufgabe, operator, afb_i, afb_ii, afb_iii, summe}
    - hinweis: leer wenn OK, sonst Beschreibung des Problems

    Lehrkräfte füllen EWH-Tabellen unterschiedlich aus; die Extraktion ist
    daher heuristisch und kann bei atypischen Layouts scheitern.
    """
    abschnitt_re = re.compile(
        r'(?:erwartungshorizont|bewertungsraster|bewertungsschl(?:ü|ue)ssel)\b',
        re.IGNORECASE,
    )
    m = abschnitt_re.search(lehrer_text)
    if not m:
        return [], "Kein EWH-Abschnitt ('Erwartungshorizont'/'Bewertungsraster') gefunden"

    ewh_text = lehrer_text[m.start(): m.start() + 8000]

    # Zeilenmuster: TEILAUFG  LEISTUNGSTEXT  ZAHL  ZAHL  ZAHL  [ZAHL]
    # Tolerant gegenüber Komma/Punkt als Dezimaltrenner in Teilaufgaben-Nr.
    zre = re.compile(
        r'^\s*(\d+[.,]\d+[a-zA-Z]?)\s+'   # Teilaufgabe: 1.1, 1.2a, 2,1 etc.
        r'(.+?)\s+'                         # Leistungstext (non-greedy)
        r'(\d+)\s+(\d+)\s+(\d+)'          # AFB I, II, III
        r'(?:\s+(\d+))?\s*$',              # optionale Σ-Spalte
        re.MULTILINE,
    )
    zeilen = []
    for zm in zre.finditer(ewh_text):
        ta = zm.group(1).replace(',', '.')
        text = zm.group(2).strip()
        # Ersten Operator-Begriff extrahieren (Großbuchstabe + mind. 3 Folgezeichen)
        op_m = re.match(r'([A-ZÄÖÜ][a-zäöü]{3,})', text)
        operator = op_m.group(1) if op_m else (text.split()[0][:20] if text else "?")
        afb_i = int(zm.group(3))
        afb_ii = int(zm.group(4))
        afb_iii = int(zm.group(5))
        zeilen.append({
            "teilaufgabe": ta,
            "operator": operator,
            "afb_i": afb_i,
            "afb_ii": afb_ii,
            "afb_iii": afb_iii,
            "summe": int(zm.group(6)) if zm.group(6) else afb_i + afb_ii + afb_iii,
        })

    if not zeilen:
        return [], (
            "EWH-Tabelle nicht parsebar – Zeilen mit Muster "
            "'Teilaufg. + Leistungstext + 3 AFB-Zahlen' nicht gefunden. "
            "Häufige Ursache: PDF-Textextraktion verliert Tabellenspalten."
        )
    return zeilen, ""


def _formatiere_ewh_vorverarbeitung(zeilen: list[dict], hinweis: str) -> str:
    """Formatiert extrahierte EWH-Zeilen als strukturierten Text für den KI-Prompt."""
    if hinweis and not zeilen:
        return f"[Extraktion fehlgeschlagen: {hinweis}]"
    teile = [
        "Teilaufg. | Operator             | AFB I | AFB II | AFB III | Σ",
        "-" * 62,
    ]
    for z in zeilen:
        teile.append(
            f"{z['teilaufgabe']:<10} | {z['operator']:<20} | "
            f"{z['afb_i']:>5} | {z['afb_ii']:>6} | {z['afb_iii']:>7} | {z['summe']:>2}"
        )
    if hinweis:
        teile.append(f"\n[Extraktion-Hinweis: {hinweis}]")
    return "\n".join(teile)


def _baue_template_vars(
    kombinierte_ops: dict,
    erweiterte_ops: dict,
    kommentar: str,
) -> dict:
    """Baut das Dict an Platzhaltern für die KI-Prompts.

    `kombinierte_ops` enthält EPA-Operatoren plus die aus dem Lehrermaterial
    geparsten erweiterten Operatoren. `erweiterte_ops` enthält nur letztere
    und wird zusätzlich separat ausgewiesen, damit die KI weiß, welche
    Operatoren *nur* aufgrund der schulinternen Erweiterung gültig sind.
    """
    if erweiterte_ops:
        erweitert_block = "\n".join(
            f"- {op.capitalize()}: AFB {'/'.join(info['afb'])} "
            "(laut Lehrermaterial, Abschnitt 'Operatorenliste wurde ... erweitert')"
            for op, info in sorted(erweiterte_ops.items())
        )
    else:
        erweitert_block = "(keine erweiterten Operatoren im Lehrermaterial dokumentiert)"

    return {
        "rrl_kompetenzen": "\n".join(f"- {k}" for k in RRL_KOMPETENZEN),
        "lerngebiete": "\n".join(f"- {k}: {v}" for k, v in IT_LERNGEBIETE.items()),
        "verbindlich": ", ".join(sorted(IT_VERBINDLICH)),
        "optional": ", ".join(sorted(IT_OPTIONAL)),
        "operatoren_tabelle": "\n".join(
            f"- {op.capitalize()}: AFB {'/'.join(info['afb'])}"
            for op, info in sorted(kombinierte_ops.items())
        ),
        "operatoren_detail": "\n".join(
            f"- {op.capitalize()}: AFB {'/'.join(info['afb'])} – {info['desc']}"
            for op, info in sorted(kombinierte_ops.items())
        ),
        "operatoren_erweitert": erweitert_block,
        "bearbeitungszeit": str(ABITUR_BEARBEITUNGSZEIT_MIN),
        "kommentar": kommentar,
        # Wird für X.5 durch _baue_prompt()/_baue_batch_prompt() überschrieben
        "ewh_vorverarbeitet": "",
    }

@dataclass
class KIPruefErgebnis:
    """Ergebnis einer einzelnen KI-Prüfung."""
    kriterium_nr: str
    kriterium_text: str
    ki_ergebnis: str  # "beanstandung", "keine_beanstandung", "nicht_pruefbar"
    konfidenz: int
    begruendung: str
    fundstellen: list
    original_kommentar: str  # Kommentar aus klausur_regelbasiert.py
