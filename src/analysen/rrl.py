"""
Verbatim-Auszug aus den Rahmenrichtlinien Technik – Beruflich Gymnasium
(„bgtechnik2016.pdf", Niedersachsen) für die Lerngebiete IT1–IT5.

Ziel: lokale Sprachmodelle (z. B. GPT-OSS-20b) müssen die IT-Lerngebiete
nicht „wissen"; sie bekommen den relevanten Abschnitt direkt in den Prompt
geliefert. Damit verkleinert sich das Halluzinationsrisiko erheblich.

Quelle: ``Material/bgtechnik2016.pdf`` (Niedersächsisches Kultusministerium,
2016 – Rahmenrichtlinien für das Fach Technik im Beruflichen Gymnasium).
Die Inhalte sind unverändert übernommen, lediglich Zeilenumbrüche aus der
PDF-Extraktion wurden geglättet.

Verwendung:
    from it_rrl_inhalte import IT_RRL, kompakter_rrl_block

    block = kompakter_rrl_block("IT2")
    # → liefert einen LLM-tauglichen Textblock mit Zielformulierung,
    #   Inhalten und Unterrichtshinweisen.
"""
from __future__ import annotations


# Umbrella-Kompetenzen für das gesamte Fach Technik (RRL Abschnitt 1.3).
# Diese werden mit jeder Teilaufgabe mitgeliefert, weil sie den Rahmen für
# die Bewertung aller Lerngebiete bilden.
IT_RRL_UEBERGEORDNETE_KOMPETENZEN: str = (
    "Übergeordnete Kompetenzen im Fach Technik "
    "(RRL bgtechnik2016, Abschnitt 1.3):\n"
    "- Technische Probleme analysieren, Wirkungszusammenhänge ermitteln, "
    "Lösungen entwickeln und deren Wirksamkeit beurteilen.\n"
    "- Technische Aufgabenstellungen unter Aspekten von Zweckbestimmung, "
    "Funktionalität und Übertragbarkeit analysieren und die Folgen unter "
    "humanen, ökonomischen und ökologischen Aspekten bewerten.\n"
    "- Optimieren von Lösungen durch Strukturieren von Lösungswegen, "
    "Vergleich von Varianten, Auswahl und Darstellen des Kompromisscharakters.\n"
    "- Theorien und Gesetzmäßigkeiten sowie Analyse- und Syntheseverfahren "
    "über Modelldarstellungen anwenden.\n"
    "- Erkenntnismethoden der Technik beschreiben und situationsgerecht nutzen.\n"
    "- Mit technischen Geräten, Maschinen und Anlagen umgehen "
    "(Experimente, Funktionsermittlung).\n"
    "- Informationen selbstständig beschaffen, verarbeiten, präsentieren; "
    "Gültigkeitsbereich von Modellaussagen kritisch abwägen.\n"
    "- Fachbezogene Kommunikationstechniken anwenden; technische Komponenten "
    "planen und konstruieren.\n"
    "- Typische Lösungsverfahren erfassen, auswählen, anwenden und bewerten.\n"
    "- Ergebnisse in Tabellen, Grafiken, Diagrammen und Abbildungen darstellen.\n"
    "- Hypothesen formulieren und überprüfen.\n"
    "- Modellvorstellungen entwickeln, simulieren, darstellen und ggf. "
    "modifizieren."
)


# Verbatim-Auszüge pro Lerngebiet IT1–IT5 aus den RRL bgtechnik2016
# (jeweils: Titel, Zeitrichtwert, Zielformulierung, Inhalte, Unterrichtshinweise).
IT_RRL: dict[str, dict] = {
    "IT1": {
        "titel": "Technische Prozesse steuern",
        "zeitrichtwert": "80 Unterrichtsstunden",
        "zielformulierung": (
            "Die Schülerinnen und Schüler planen, realisieren und "
            "dokumentieren Steuerungen technischer Prozesse. "
            "Sie entwickeln Lösungen für steuerungstechnische "
            "Problemstellungen und erstellen Schalt-, Funktions- und "
            "Ablaufpläne. "
            "Sie realisieren verbindungs- und speicherprogrammierte "
            "Steuerungen unter Berücksichtigung von Standardlösungen, "
            "wählen Sensoren und Aktoren aus und binden diese ein. "
            "Sie berücksichtigen Sicherheitsregeln sowie ökonomische und "
            "ökologische Anforderungen. "
            "Sie analysieren, bewerten und dokumentieren ihre Lösungen."
        ),
        "inhalte": [
            "Steuerkette, Regelkreis",
            "Aktive und passive Sensoren",
            "Prozessorik: digitaltechnische Grundlagen, Zeit- und "
            "Zählfunktionen, Verknüpfungs- und Ablaufsteuerungen",
            "Elektrische und nicht elektrische Aktoren",
            "Darstellungsformen von Steuerungsprogrammen",
            "Systemtest und Inbetriebnahme",
        ],
        "unterrichtshinweise": (
            "Behandlung der Sensoren und Aktoren beschränkt sich auf "
            "grundlegende Funktionsweise (exemplarisch). Einfache "
            "Problemstellungen sollten anhand von Steuerungseinheiten "
            "aufgebaut, programmiert und getestet werden."
        ),
    },
    "IT2": {
        "titel": "Netzwerke analysieren, planen und konfigurieren",
        "zeitrichtwert": "80 Unterrichtsstunden",
        "zielformulierung": (
            "Die Schülerinnen und Schüler analysieren, planen und "
            "konfigurieren Netzwerke. "
            "Sie analysieren Hardwarekomponenten, Struktur, Funktionsweise "
            "und Sicherheit vorgegebener Netzwerke. "
            "Sie erläutern unter Berücksichtigung von Schichtenmodellen "
            "die Funktion und die Einsatzbereiche von Netzwerkgeräten, "
            "Übertragungsmedien, Zugriffsverfahren und Adressierungsarten. "
            "Sie verwenden und konfigurieren Software zur Nutzung von "
            "Serverdiensten und beschreiben die Funktionsweise der "
            "zugehörigen Protokolle. "
            "Sie planen komplexe Netzwerke auf der Basis einschlägiger "
            "Normen und Vorschriften. "
            "Sie realisieren, konfigurieren und dokumentieren einfache "
            "Netzwerke unter Berücksichtigung von Sicherheits- und "
            "Berechtigungsrichtlinien, testen deren Funktionalität "
            "(Diagnosesoftware, Messgeräte) und bewerten die Ergebnisse. "
            "Sie unterscheiden Techniken zur Anbindung lokaler Netze an "
            "öffentliche Netze."
        ),
        "inhalte": [
            "Peer-to-Peer- und Client-Server-Konzepte",
            "Grundlagen der Übertragungstechnik",
            "Strukturierte Verkabelung / anwendungsneutrale "
            "Verkabelungssysteme",
            "Netzwerkbetriebssysteme",
            "Fehlersuche und Fehlerbehebung im Netzwerk",
        ],
        "unterrichtshinweise": (
            "Terminalserver und drahtlose Netzwerke können eingebunden "
            "werden. Sicherheitsaspekte (z. B. VPN, VLAN, "
            "Authentifizierungs- und Verschlüsselungsverfahren) werden "
            "bei allen Hard- und Softwarekomponenten einbezogen. "
            "Aus IT1 erstellte Anlagen können hier weiterverwendet und "
            "z. B. vernetzt werden."
        ),
    },
    "IT3": {
        "titel": "Software zur Prozessdatenverarbeitung entwickeln",
        "zeitrichtwert": "80 Unterrichtsstunden",
        "zielformulierung": (
            "Die Schülerinnen und Schüler planen und realisieren Software "
            "zur Prozessdatenverarbeitung. "
            "Sie entwerfen Algorithmen zur Überwachung und Steuerung "
            "vernetzter technischer Anlagen. "
            "Sie entscheiden, welche Softwarekomponenten aus existierenden "
            "Bibliotheken übernommen oder angepasst werden können; eigene "
            "Komponenten werden in einer Hochsprache entwickelt. "
            "Sie dokumentieren ihre Arbeitsergebnisse, testen ihre "
            "Programme methodisch und führen systematisch "
            "Fehlerkorrekturen durch."
        ),
        "inhalte": [
            "Prozedurale Programmierung",
            "Objektorientierte Programmierung",
            "Sicherheit gegen Fälschung der übertragenen Daten",
            "Sicherstellung der Autorisierung der Daten",
            "Sicherung gegen Übertragungsfehler",
        ],
        "unterrichtshinweise": (
            "Prozessdaten können in eine Datenbank übernommen und im "
            "Netzwerk bereitgestellt werden (z. B. dynamisches "
            "Internetdokument). Beispiele: Verkehrssteuerung "
            "(Ampeln, Schranken), Steuerung einer Produktionsanlage, "
            "Sortieranlagen, Kläranlagen."
        ),
    },
    "IT4": {
        "titel": "Messwerte erfassen und verarbeiten",
        "zeitrichtwert": "80 Unterrichtsstunden",
        "zielformulierung": (
            "Die Schülerinnen und Schüler erfassen und verarbeiten "
            "Messwerte. Sie planen und realisieren rechnergestützte "
            "Systeme zur Messwerterfassung und -verarbeitung. "
            "Sie entwickeln Algorithmen zur Erfassung, Speicherung, "
            "Verarbeitung und Darstellung der Daten. "
            "Sie entscheiden, welche Softwarekomponenten aus "
            "Bibliotheken übernommen oder angepasst werden; eigene "
            "Komponenten werden in einer Hochsprache entwickelt. "
            "Sie dokumentieren ihre Arbeitsergebnisse, testen das "
            "System methodisch, führen systematisch Fehlerkorrekturen "
            "durch. "
            "Sie analysieren die Daten, stellen diese anwendungsbezogen "
            "dar und bewerten ihre Ergebnisse."
        ),
        "inhalte": [
            "Systeme zur Messwerterfassung",
            "Prozedurale Programmierung",
            "Objektorientierte Programmierung",
        ],
        "unterrichtshinweise": (
            "Messhardware (bzw. Teile davon) im Praxisunterricht "
            "herstellen. Beispiele: Messstation für Solar-/Windanlagen, "
            "Gewässeranalyse, Produkttests (Kabel-/Bauteiletester). "
            "Auswertung/Darstellung der Daten kann statistisch erfolgen. "
            "Für die Datenspeicherung kann eine Datenbank verwendet "
            "werden; für die Messhardware können Mikrocontroller "
            "eingesetzt werden."
        ),
    },
    "IT5": {
        "titel": (
            "Software zur grafischen Darstellung technischer Prozesse "
            "entwickeln"
        ),
        "zeitrichtwert": "80 Unterrichtsstunden",
        "zielformulierung": (
            "Die Schülerinnen und Schüler entwickeln Software zur "
            "grafischen Darstellung technischer Prozesse. "
            "Sie reduzieren Prozesse der Realität und bilden sie auf "
            "unterschiedlichem Abstraktionsniveau in Modellprozessen ab. "
            "Sie entwerfen Algorithmen zur dynamischen Darstellung "
            "technischer Prozessabläufe. "
            "Sie entscheiden, welche Softwarekomponenten aus "
            "Bibliotheken übernommen oder angepasst werden können; "
            "eigene Komponenten werden in einer Hochsprache entwickelt. "
            "Sie dokumentieren ihre Arbeitsergebnisse, testen ihre "
            "Programme methodisch und führen systematisch "
            "Fehlerkorrekturen durch."
        ),
        "inhalte": [
            "Prozedurale Programmierung",
            "Objektorientierte Programmierung",
        ],
        "unterrichtshinweise": (
            "Beispiele für dynamische Darstellung von Prozessabläufen: "
            "Solarpanel-Nachführung, Klimasteuerung eines Gewächshauses, "
            "Gebäude-Automatisierung, Wehrsteuerung, Windradsteuerung, "
            "Zisternensteuerung, Verkehrsleitsystem."
        ),
    },
}


def kompakter_rrl_block(lerngebiet: str, max_zeichen: int | None = None) -> str:
    """Liefert einen LLM-tauglichen Textblock mit dem RRL-Inhalt für ein
    konkretes Lerngebiet (IT1–IT5).

    Wird ``max_zeichen`` gesetzt, wird der zurückgegebene Block bei
    Überschreitung am letzten Wort gekürzt (sicheres Hard-Limit).
    """
    daten = IT_RRL.get(lerngebiet)
    if daten is None:
        return (
            f"({lerngebiet}: keine RRL-Daten verfügbar – "
            f"bitte konservativ prüfen.)"
        )
    inhalte_str = "\n".join(f"  - {i}" for i in daten["inhalte"])
    block = (
        f'RRL bgtechnik2016, Lerngebiet {lerngebiet} – '
        f'„{daten["titel"]}" ({daten["zeitrichtwert"]}):\n\n'
        f'Zielformulierung: {daten["zielformulierung"]}\n\n'
        f'Inhalte:\n{inhalte_str}\n\n'
        f'Unterrichtshinweise: {daten["unterrichtshinweise"]}'
    )
    if max_zeichen and len(block) > max_zeichen:
        cut = block[:max_zeichen].rfind(" ")
        if cut < max_zeichen // 2:
            cut = max_zeichen
        block = block[:cut].rstrip() + " […]"
    return block
