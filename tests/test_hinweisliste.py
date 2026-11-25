"""Tests für die Hinweisliste – nur erfundene Daten (keine echten Vorschläge)."""

import csv
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bewertung.hinweisliste import (  # noqa: E402
    HinweisBlock,
    aufgabe_anzeige,
    baue_hinweisblock,
    erkenne_vorschlag,
    hinweise_aus_ki,
    hinweise_aus_loesbarkeit,
    hinweise_aus_regelpruefung,
    schreibe_hinweisliste,
)
from src.bewertung.regelbasiert import (  # noqa: E402
    Aufgabe,
    PruefungsErgebnis,
    Teilaufgabe,
)

# Erfundener Vorschlag: zwei Aufgaben auf drei Seiten
SM_SEITEN_TEXT = [
    "Abitur 2027 Technik Vorschlag B\nSituation: Ein Fahrradverleih plant ein Buchungssystem.",
    "1 Buchung\n1.1 Beschreiben Sie den Ablauf einer Buchung. 4 BE\n"
    "1.2 Notieren Sie die Tabellen. 6 BE",
    "2 Netz\n2.1 Planen Sie das Netz. 8 BE\n"
    "2.2 Erweitern Sie das in Aufgabe 2.1 entwickelte Netz um ein WLAN. 6 BE",
]
LM_SEITEN_TEXT = ["Erwartungshorizont", "1.1 Beschreiben 4\n1.2 Nennen 6\n2.1 Planen 8"]
AUFGABEN = [
    Aufgabe(1, "Buchung", 10, [Teilaufgabe("1.1", ""), Teilaufgabe("1.2", "")]),
    Aufgabe(2, "Netz", 14, [Teilaufgabe("2.1", ""), Teilaufgabe("2.2", "")]),
]
SM_SEITEN = {"1": 2, "1.1": 2, "1.2": 2, "2": 3, "2.1": 3, "2.2": 3}
LM_SEITEN = {"1.1": 2, "1.2": 2, "2.1": 2, "2.2": 2}


def _regel(*ergebnisse):
    return (list(ergebnisse), "", AUFGABEN, SM_SEITEN, LM_SEITEN,
            SM_SEITEN_TEXT, LM_SEITEN_TEXT)


def test_aufgabe_anzeige_wie_versendete_listen():
    assert aufgabe_anzeige("1.3") == "1.3."
    assert aufgabe_anzeige("3") == "3"
    assert aufgabe_anzeige("2.1a") == "2.1a"
    assert aufgabe_anzeige("1.5.2") == "1.5.2"
    assert aufgabe_anzeige("Allgemein") == "Allgemein"


@pytest.mark.parametrize("text, datei, erwartet", [
    ("Abitur 2027 Technik Vorschlag B", "", "Vorschlag B"),
    ("", "2027_Technik_Vorschlag_A_Schuelermaterial.pdf", "Vorschlag A"),
    ("", "2027TechnikAufgB.pdf", "Vorschlag B"),
    ("", "entwurf.pdf", "Vorschlag (entwurf)"),
])
def test_erkenne_vorschlag(text, datei, erwartet):
    assert erkenne_vorschlag(text, datei) == erwartet


def test_afb_fehlzuordnung_im_stil_der_fachberatung():
    e = PruefungsErgebnis(
        "X.5b", "AFB-Fehlzuordnung EWH (Zeilenanalyse)", False,
        "WAHRSCHEINLICHE AFB-FEHLZUORDNUNGEN im EWH erkannt: Teilaufgabe 1.2: "
        "Operator 'skizzieren' (korrekt: AFB II) → AFB I = 6 (verboten für 'skizzieren')")
    hinweise = hinweise_aus_regelpruefung([e], AUFGABEN, SM_SEITEN, LM_SEITEN)
    assert len(hinweise) == 1
    h = hinweise[0]
    assert (h.aufgabe, h.text, h.lm_seite) == ("1.2", "Skizzieren ist Anforderungsbereich 2", "S. 2")
    assert h.herkunft == "Regel [X.5b]" and not h.ki


def test_abhaengigkeit_wird_teilaufgabe_zugeordnet():
    e = PruefungsErgebnis(
        "4.2", "Teilaufgaben unabhängig lösbar (Vorgabe 4.2)", None,
        'MANUELL PRÜFEN: 1 mögliche Aufgaben-Abhängigkeit(en) ohne erkennbaren '
        'Alternativwert erkannt. Fundstellen: „Erweitern Sie das in Aufgabe 2.1 entwickelte Netz"')
    hinweise = hinweise_aus_regelpruefung([e], *_regel()[2:])
    assert len(hinweise) == 1
    h = hinweise[0]
    assert h.aufgabe == "2.2"
    assert h.sm_seite == "S. 3"
    assert h.text.startswith("Die Aufgabe baut auf Aufgabe 2.1 auf. Bitte prüfen, ob die Vorgabe 4.2")


def test_offene_pruefragen_bleiben_im_gutachten():
    """„?“ ohne konkreten Befund gehört ins Raster, nicht in die Hinweisliste."""
    ergebnisse = [
        PruefungsErgebnis("3.3", "Ganzheitlichkeit", None, "MANUELL PRÜFEN: Sind die Aufgaben ganzheitlich?"),
        PruefungsErgebnis("1.3", "Deckblatt", None, "Bitte manuell prüfen ob Deckblatt vorhanden ist."),
        PruefungsErgebnis("2.6", "Bewertungsschema", True, "vorhanden"),
    ]
    assert hinweise_aus_regelpruefung(ergebnisse, *_regel()[2:]) == []


def test_je_aufgabe_nicht_epa_und_punkte():
    ergebnisse = [
        PruefungsErgebnis("X.9", "Keine Nicht-EPA-Operatoren", False, "notieren, erweitern"),
        PruefungsErgebnis("X.3", "BE statt Punkte", True, "ok"),
        PruefungsErgebnis("X.13", "Gesamtpunktzahl konsistent", False,
                          "ABWEICHUNG: SM: 24 BE (Aufg. 1: 10 BE + Aufg. 2: 14 BE) ≠ EWH: 25 BE!"),
    ]
    hinweise = hinweise_aus_regelpruefung(ergebnisse, *_regel()[2:])
    texte = {(h.aufgabe, h.text) for h in hinweise}
    # Befund steht auf Seite 2 – zugeordnet wird die Teilaufgabe, nicht „1“
    assert ("1.2", "„Notieren“ ist kein Operator nach EPA. Bitte ersetzen oder im Lehrermaterial "
                   "als erweiterten Operator mit Anforderungsbereich aufführen.") in texte
    assert any(h.aufgabe == "2.2" and "„Erweitern“" in h.text for h in hinweise)
    assert ("Allgemein", "Die Summe der BE stimmt nicht überein: Schülermaterial 24 BE, "
                         "Erwartungshorizont 25 BE.") in texte
    # X.9 ist je Aufgabe aufgeschlüsselt → keine zusätzliche Allgemein-Zeile
    assert not any(h.herkunft == "Regel [X.9]" and h.aufgabe == "Allgemein" for h in hinweise)


def test_ki_nur_beanstandungen_ab_schwelle_und_markiert():
    ki = [
        SimpleNamespace(kriterium_nr="4.1", kriterium_text="Aufgaben klar formuliert",
                        ki_ergebnis="beanstandung", konfidenz=85,
                        begruendung="In Aufgabe 1.2 ist unklar, welche Tabellen gemeint sind. Weiterer Satz. Dritter Satz.",
                        fundstellen=["Aufgabe 1.2: Notieren Sie die Tabellen"]),
        SimpleNamespace(kriterium_nr="3.3", kriterium_text="Ganzheitlichkeit",
                        ki_ergebnis="beanstandung", konfidenz=60, begruendung="unsicher", fundstellen=[]),
        SimpleNamespace(kriterium_nr="3.4", kriterium_text="Handlungskompetenz",
                        ki_ergebnis="keine_beanstandung", konfidenz=95, begruendung="ok", fundstellen=[]),
    ]
    hinweise = hinweise_aus_ki(ki, "gemma-4-12b")
    assert len(hinweise) == 1
    h = hinweise[0]
    assert h.ki and h.aufgabe == "1.2"
    assert h.herkunft == "KI [4.1] gemma-4-12b · 85 %"
    assert "Dritter Satz" not in h.text


def test_loesbarkeit_fehlende_information_und_musterloesung():
    erg = [SimpleNamespace(
        teilaufgabe="2.1", loesbarkeit="nein", loesbarkeit_konfidenz=80,
        loesbarkeit_begruendung="Die Anzahl der Arbeitsplätze fehlt.",
        fehlende_information=["Anzahl der Arbeitsplätze"],
        richtigkeit="nein", richtigkeit_konfidenz=90,
        richtigkeit_begruendung="Subnetzmaske falsch.", fehler_in_loesung=["/23 statt /24"])]
    hinweise = hinweise_aus_loesbarkeit(erg, "bonsai-27b", SM_SEITEN, LM_SEITEN)
    assert [h.aufgabe for h in hinweise] == ["2.1", "2.1"]
    assert "Anzahl der Arbeitsplätze" in hinweise[0].text and hinweise[0].sm_seite == "S. 3"
    assert hinweise[1].text == "Bitte die Musterlösung prüfen: /23 statt /24."
    assert hinweise[1].lm_seite == "S. 2"


def test_csv_und_xlsx_im_format_der_versendeten_listen(tmp_path):
    e = PruefungsErgebnis("X.6", "Schwerpunkt angegeben", False, "fehlt")
    block_a = baue_hinweisblock("Vorschlag A", _regel(e))
    block_b = HinweisBlock("Vorschlag B")
    xlsx, csv_pfad = schreibe_hinweisliste([block_a, block_b], tmp_path / "Hinweise_Test")

    roh = csv_pfad.read_bytes()
    assert roh.startswith(b"\xef\xbb\xbf")          # BOM für Excel
    assert b"\r\n" in roh                           # CRLF wie die versendeten Dateien
    zeilen = list(csv.reader(roh.decode("utf-8-sig").splitlines(), delimiter=";"))
    assert zeilen[0][5] == "Gewählt:"
    assert zeilen[1][:6] == ["Vorschlag A", "", "Schülermaterial", "Lehrermaterial",
                             "Hinweise", "Überarbeitet am"]
    assert zeilen[2][0] == "Allgemein" and "Informationstechnik" in zeilen[2][1]
    assert ["Vorschlag B", "Keine Anmerkungen"] == zeilen[-1][:2]

    from openpyxl import load_workbook
    ws = load_workbook(xlsx).active
    assert ws.title == "Hinweise"
    assert ws["A2"].value == "Vorschlag A"
    assert ws["B3"].value == zeilen[2][1]
