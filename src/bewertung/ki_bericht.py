"""
Prüfbericht der KI-gestützten Prüfung als XLSX – ohne Modellanbindung.

Führt Regelprüfung und KI-Urteile zu einer Liste zusammen und schreibt den
Bericht (Blatt „Alle Prüfpunkte" und „Handlungsbedarf"). Gemeinsam genutzt von
``src.bewertung.ki_gestuetzt`` und vom Skill ``abiturvorschlag-begutachten``.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from src.bewertung.ki_pruefanweisungen import KONFIDENZ_SCHWELLE, KIPruefErgebnis


@dataclass
class KombinierterPruefpunkt:
    """Kombinierter Prüfpunkt: regelbasiertes + KI-Ergebnis in einer Zeile."""
    lfd_nr: int                      # Laufende Nummer 1-basiert
    kriterium_nr: str                # z.B. "1.3", "X.5"
    kriterium_text: str
    # Regelbasiert
    regelbasiert_erfuellt: bool | None  # True / False / None
    regelbasiert_kommentar: str
    # KI (nur wenn manuell geprüft)
    ki_geprueft: bool
    ki_ergebnis: str     # "beanstandung" | "keine_beanstandung" | "nicht_pruefbar" | ""
    konfidenz: int       # 0 wenn nicht KI-geprüft
    ki_begruendung: str
    fundstellen: list


def erstelle_kombinierte_liste(
    regelbasiert: list,
    ki_ergebnisse: list[KIPruefErgebnis],
) -> list[KombinierterPruefpunkt]:
    """Führt regelbasierte und KI-Prüfergebnisse zu einer geordneten Liste zusammen.

    Jedes Kriterium erscheint genau einmal mit fortlaufender Nummer.
    KI-Ergebnisse werden nur für manuell geprüfte Kriterien ergänzt.
    """
    ki_index: dict[str, KIPruefErgebnis] = {e.kriterium_nr: e for e in ki_ergebnisse}
    kombiniert: list[KombinierterPruefpunkt] = []
    for lfd_nr, erg in enumerate(regelbasiert, 1):
        ki = ki_index.get(erg.kriterium_nr)
        kombiniert.append(KombinierterPruefpunkt(
            lfd_nr=lfd_nr,
            kriterium_nr=erg.kriterium_nr,
            kriterium_text=erg.kriterium_text,
            regelbasiert_erfuellt=erg.erfuellt,
            regelbasiert_kommentar=erg.kommentar,
            ki_geprueft=ki is not None,
            ki_ergebnis=ki.ki_ergebnis if ki else "",
            konfidenz=ki.konfidenz if ki else 0,
            ki_begruendung=ki.begruendung if ki else "",
            fundstellen=ki.fundstellen if ki else [],
        ))
    return kombiniert


_LM_SCHLUESSEL = ("EWH", "Lehrermaterial", "Erwartungshorizont", "Musterlösung", "Musterloesung")
_SM_SCHLUESSEL = ("Schülermaterial", "SM:", "Aufgabenstellung", "Arbeitsauftrag", "als Arbeitsauftrag")


def _trenne_sm_lm_fundstellen(fundstellen: list) -> tuple[str, str]:
    sm, lm = [], []
    for f in fundstellen:
        if any(k.lower() in f.lower() for k in _LM_SCHLUESSEL):
            lm.append(f)
        else:
            sm.append(f)
    return "\n".join(sm), "\n".join(lm)


def _trenne_sm_lm_kommentar(kommentar: str) -> tuple[str, str]:
    """Versucht einen regelbasiert_kommentar in SM- und LM-Anteile aufzuteilen."""
    if not kommentar:
        return "", ""
    teile = re.split(r"\s*\|\s*|\n", kommentar)
    sm_teile, lm_teile, keines = [], [], []
    for teil in teile:
        if not teil.strip():
            continue
        ist_lm = any(k.lower() in teil.lower() for k in _LM_SCHLUESSEL)
        ist_sm = any(k.lower() in teil.lower() for k in _SM_SCHLUESSEL)
        if ist_lm and not ist_sm:
            lm_teile.append(teil.strip())
        elif ist_sm and not ist_lm:
            sm_teile.append(teil.strip())
        else:
            # Kein eindeutiges Signal: bei mehreren Teilen neutral lassen,
            # bei nur einem Teil SM zuordnen (häufigster Fall)
            keines.append(teil.strip())
    if not sm_teile and not lm_teile:
        return kommentar, ""
    sm_teile += keines
    return "\n".join(sm_teile), "\n".join(lm_teile)


def _handlungsbedarf_sortkey(p: "KombinierterPruefpunkt") -> tuple[int, int, int]:
    text = " ".join([
        p.regelbasiert_kommentar or "",
        p.ki_begruendung or "",
        " ".join(p.fundstellen or []),
    ])
    m = re.search(r'(?:Aufgabe[n]?|Teilaufgabe[n]?|Aufg\.)\s*(\d+)\.?(\d*)', text, re.IGNORECASE)
    if not m:
        m = re.search(r'\b(\d+)\.(\d+)\b', text)
    if m:
        return (int(m.group(1)), int(m.group(2)) if m.group(2) else 0, p.lfd_nr)
    return (999, 999, p.lfd_nr)


def _erstelle_handlungsbedarf_sheet(wb, kombinierte: list) -> None:
    """Zweites Tabellenblatt: nur Beanstandungen, sortiert nach Aufgabenreihenfolge."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    beanstandungen = [
        p for p in kombinierte
        if p.regelbasiert_erfuellt is False or p.ki_ergebnis == "beanstandung"
    ]
    if not beanstandungen:
        return

    beanstandungen.sort(key=_handlungsbedarf_sortkey)

    ws = wb.create_sheet("Handlungsbedarf")

    header_fill   = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
    titel_fill    = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid")
    fill_fehler   = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    wrap_align    = Alignment(vertical="top", wrap_text=True)
    center_top    = Alignment(horizontal="center", vertical="top")
    thin_border   = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    ws["A1"] = "Handlungsbedarf – Beanstandungen"
    ws["A1"].font = Font(bold=True, size=14, color="FFFFFF")
    ws["A1"].fill = titel_fill

    headers = [
        "Nr.", "Kriterium", "Beschreibung",
        "Beanstandung / Befund",
        "Fundstelle Schülermaterial",
        "Fundstelle Lehrermaterial",
    ]
    col_widths = [6, 12, 38, 60, 45, 45]
    header_row = 3

    for col_idx, (hdr, width) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=header_row, column=col_idx, value=hdr)
        cell.font = Font(bold=True, size=10)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    for nr, p in enumerate(beanstandungen, 1):
        row = header_row + nr

        # Befund-Text zusammenstellen
        befund_teile = []
        if p.regelbasiert_erfuellt is False and p.regelbasiert_kommentar:
            befund_teile.append(p.regelbasiert_kommentar)
        if p.ki_ergebnis == "beanstandung" and p.ki_begruendung:
            if p.regelbasiert_erfuellt is False:
                befund_teile.append(f"KI ({p.konfidenz}%): {p.ki_begruendung}")
            else:
                befund_teile.append(p.ki_begruendung)
        befund_text = "\n\n".join(befund_teile)

        # Fundstellen aufteilen (nur KI-Items haben ein fundstellen-Array)
        sm_text, lm_text = _trenne_sm_lm_fundstellen(p.fundstellen or [])

        ws.cell(row=row, column=1, value=nr).alignment = center_top
        ws.cell(row=row, column=2, value=f"[{p.kriterium_nr}]").alignment = center_top
        ws.cell(row=row, column=3, value=p.kriterium_text).alignment = wrap_align
        ws.cell(row=row, column=4, value=befund_text).alignment = wrap_align
        ws.cell(row=row, column=5, value=sm_text).alignment = wrap_align
        ws.cell(row=row, column=6, value=lm_text).alignment = wrap_align

        for col_idx in range(1, 7):
            cell = ws.cell(row=row, column=col_idx)
            cell.fill = fill_fehler
            cell.border = thin_border

    last_row = header_row + len(beanstandungen)
    ws.auto_filter.ref = f"A{header_row}:F{last_row}"
    ws.freeze_panes = f"A{header_row + 1}"


def schreibe_ki_bericht_xlsx(
    kombinierte: list[KombinierterPruefpunkt],
    output_pfad: str,
    schueler_datei: str,
    lehrer_datei: str,
    schwelle: int | None = None,
):
    """Schreibt alle Prüfpunkte (regelbasiert + KI) als XLSX-Datei.

    Enthält ein Tabellenblatt mit sämtlichen Prüfpunkten, laufend nummeriert.
    Spalten: Nr. | Kriterium | Beschreibung | Regelbasiert | Kommentar |
             KI-Ergebnis | Konfidenz | KI-Begründung | Fundstellen
    """
    if schwelle is None:
        schwelle = KONFIDENZ_SCHWELLE
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Alle Prüfpunkte"

    # Kopfbereich
    ws["A1"] = "Vollständige Prüfung des Abiturvorschlags"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Schülermaterial: {os.path.basename(schueler_datei)}"
    ws["A3"] = f"Lehrermaterial:  {os.path.basename(lehrer_datei)}"
    ws["A4"] = (
        f"Konfidenz-Schwelle: {schwelle}%  |  "
        f"Prüfpunkte gesamt: {len(kombinierte)}"
    )

    # Tabellenkopf
    header_row = 6
    headers = [
        "Nr.", "Kriterium", "Beschreibung",
        "Regelbasiert", "Kommentar (regelbasiert)",
        "KI-Ergebnis", "Konfidenz", "KI-Begründung", "Fundstellen",
    ]
    col_widths = [6, 12, 38, 18, 50, 22, 10, 55, 40]

    header_font = Font(bold=True, size=10)
    header_fill = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    for col_idx, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    # Farbpaletten
    fill_ok     = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    fill_fehler = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    fill_warn   = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
    fill_auto   = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")
    wrap_align  = Alignment(vertical="top", wrap_text=True)
    center_top  = Alignment(horizontal="center", vertical="top")

    # Hilfstexte
    rb_texte = {
        True:  "✅ Erfüllt",
        False: "❌ Beanstandet",
        None:  "⚠️ Manuell prüfen",
    }
    ki_texte = {
        "beanstandung":      "❌ Beanstandung",
        "keine_beanstandung": "✅ Keine Beanstandung",
        "nicht_pruefbar":    "⚠️ Nicht prüfbar",
        "": "",
    }

    for p in kombinierte:
        row_num = header_row + p.lfd_nr

        ws.cell(row=row_num, column=1, value=p.lfd_nr).alignment = center_top
        ws.cell(row=row_num, column=2,
                value=f"[{p.kriterium_nr}]").alignment = center_top
        ws.cell(row=row_num, column=3,
                value=p.kriterium_text).alignment = wrap_align

        # Regelbasiert-Spalte
        rb_text = rb_texte.get(p.regelbasiert_erfuellt, "?")
        rb_cell = ws.cell(row=row_num, column=4, value=rb_text)
        rb_cell.alignment = center_top
        if p.regelbasiert_erfuellt is True:
            rb_cell.fill = fill_ok
        elif p.regelbasiert_erfuellt is False:
            rb_cell.fill = fill_fehler
        else:
            rb_cell.fill = fill_warn

        ws.cell(row=row_num, column=5,
                value=p.regelbasiert_kommentar).alignment = wrap_align

        # KI-Spalten
        if p.ki_geprueft:
            ki_text = ki_texte.get(p.ki_ergebnis, p.ki_ergebnis)
            ki_cell = ws.cell(row=row_num, column=6, value=ki_text)
            ki_cell.alignment = center_top
            if p.ki_ergebnis == "keine_beanstandung":
                ki_cell.fill = fill_ok
            elif p.ki_ergebnis == "beanstandung":
                ki_cell.fill = fill_fehler
            else:
                ki_cell.fill = fill_warn

            ws.cell(row=row_num, column=7,
                    value=f"{p.konfidenz}%").alignment = center_top
            ws.cell(row=row_num, column=8,
                    value=p.ki_begruendung).alignment = wrap_align
            ws.cell(row=row_num, column=9,
                    value="\n".join(p.fundstellen) if p.fundstellen else "").alignment = wrap_align
        else:
            # Automatisch geprüft – KI-Spalten grau lassen
            for col in range(6, 10):
                ws.cell(row=row_num, column=col).fill = fill_auto

        for col_idx in range(1, 10):
            ws.cell(row=row_num, column=col_idx).border = thin_border

    # Autofilter & Fixierung
    last_row = header_row + len(kombinierte)
    ws.auto_filter.ref = f"A{header_row}:I{last_row}"
    ws.freeze_panes = f"A{header_row + 1}"

    # Zweites Tabellenblatt: Handlungsbedarf
    _erstelle_handlungsbedarf_sheet(wb, kombinierte)

    wb.save(output_pfad)
    print(f"\nPrüfbericht (XLSX) gespeichert: {output_pfad}")
