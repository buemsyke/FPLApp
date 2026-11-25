#!/usr/bin/env python3
"""
PDF-Korrektur: Annotationen auf der Original-Klausur + Korrekturblatt am Ende.

Erzeugt eine „Korrigiert"-Variante des Schüler-PDFs:
  - Auf der jeweiligen Seite wird je erkannter Teilaufgabe ein farbiger
    Stempel oben rechts gesetzt: „TA 1.1  →  2,0 / 3 Pkt   (zum Teil)".
    Farbcode: grün ≥ 80 %, gelb ≥ 40 %, rot < 40 %, grau = keine Lösung.
  - Am Ende wird ein Korrekturblatt angehängt mit:
        Aufgabenliste (Punkte, Standardsatz, KI-Bemerkung, Konfidenz)
        Aufgabensummen
        Endbewertung (Notenpunkte / Sprachabzug / Endnote)
        Hinweis: „KI-Vorschlag – noch nicht freigegeben"

Abhängigkeiten: pypdf (Lesen/Schreiben), reportlab (Overlays).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject
from reportlab.lib.colors import Color, black, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)
from reportlab.lib import colors as rl_colors

# ---------------------------------------------------------------------------
# Datentyp – wird vom Bewertungsmodul befüllt
# ---------------------------------------------------------------------------

@dataclass
class KorrekturEintrag:
    teilaufgabe: str
    seite: int                  # 1-basiert, Seite im Original-PDF wo Antwort steht
    max_pkt: float
    erreicht_pkt: float
    standardsatz: str
    bemerkung: str = ""
    konfidenz: int = 0
    flags: list[str] | None = None


# ---------------------------------------------------------------------------
# Farbcodierung
# ---------------------------------------------------------------------------

def _farbe_fuer_quote(erreicht: float, max_pkt: float) -> Color:
    if max_pkt <= 0:
        return Color(0.6, 0.6, 0.6)  # grau
    q = erreicht / max_pkt
    if q >= 0.8:
        return Color(0.18, 0.55, 0.20)  # grün
    if q >= 0.4:
        return Color(0.85, 0.65, 0.10)  # gelb-orange
    return Color(0.78, 0.18, 0.18)      # rot


# ---------------------------------------------------------------------------
# Overlay-PDF mit Stempeln pro Seite erzeugen
# ---------------------------------------------------------------------------

def _erzeuge_overlay(
    seitenformat: tuple[float, float],
    eintraege_pro_seite: dict[int, list[KorrekturEintrag]],
    ausgabe_pdf: Path,
    max_seiten: int,
) -> None:
    """Schreibt ein PDF mit denselben Maßen wie das Original; pro Seite die
    Stempel der zugehörigen Korrektureinträge oben rechts gestapelt.
    """
    c = canvas.Canvas(str(ausgabe_pdf), pagesize=seitenformat)
    breite, hoehe = seitenformat
    for seite_idx in range(1, max_seiten + 1):
        eintraege = eintraege_pro_seite.get(seite_idx, [])
        # Stempel oben rechts, untereinander
        y = hoehe - 12 * mm
        for e in eintraege:
            farbe = _farbe_fuer_quote(e.erreicht_pkt, e.max_pkt)
            text = f"TA {e.teilaufgabe}  {e.erreicht_pkt:g} / {e.max_pkt:g}"
            quote = e.erreicht_pkt / e.max_pkt if e.max_pkt > 0 else 0
            zusatz = f"  ({quote*100:.0f} %)" if e.max_pkt > 0 else "  (n/a)"
            full = text + zusatz
            # Kasten
            textbreite = c.stringWidth(full, "Helvetica-Bold", 9)
            box_breite = textbreite + 8
            box_hoehe = 6 * mm
            x = breite - box_breite - 8 * mm
            c.setFillColor(farbe)
            c.setStrokeColor(farbe)
            c.roundRect(x, y - box_hoehe + 2, box_breite, box_hoehe, 2, fill=1, stroke=0)
            c.setFillColor(white)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(x + 4, y - 2.5 * mm, full)
            y -= box_hoehe + 1.5 * mm
            if y < 20 * mm:
                break
        # Fußzeile auf jeder Seite: „KI-Vorschlag, noch nicht freigegeben"
        c.setFont("Helvetica-Oblique", 7)
        c.setFillColor(Color(0.5, 0.5, 0.5))
        c.drawString(10 * mm, 6 * mm,
                     "KI-Vorschlag — noch nicht durch Lehrkraft freigegeben.")
        c.showPage()
    c.save()


# ---------------------------------------------------------------------------
# Original + Overlay zusammenführen
# ---------------------------------------------------------------------------

def _kombiniere_mit_overlay(
    original_pdf: Path,
    overlay_pdf: Path,
    ausgabe_pdf: Path,
) -> None:
    """Legt jede Seite des Overlay-PDFs auf die entsprechende Seite des Originals."""
    orig = PdfReader(str(original_pdf))
    over = PdfReader(str(overlay_pdf))
    writer = PdfWriter()
    for i, page in enumerate(orig.pages):
        if i < len(over.pages):
            page.merge_page(over.pages[i])
        writer.add_page(page)
    with open(ausgabe_pdf, "wb") as f:
        writer.write(f)


# ---------------------------------------------------------------------------
# Korrekturblatt am Ende
# ---------------------------------------------------------------------------

def _erzeuge_korrekturblatt(
    pfad: Path,
    schueler_anzeige: str,
    klausur_name: str,
    eintraege: list[KorrekturEintrag],
    aufgaben_summen: dict[int, dict[str, float]],
    gesamt: dict[str, float],
    max_gesamt: float,
    notenpunkte: int,
    note_kennung: str,
    note_text: str,
    sprachabzug: int,
    modell: str,
    erzeugt_am: str,
    paket_name: str,
    status: str = "Vorschlag (noch nicht freigegeben)",
) -> None:
    """Erzeugt ein eigenständiges Korrekturblatt-PDF als A4-Dokument."""
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Klein", fontName="Helvetica", fontSize=8,
                              textColor=Color(0.35, 0.35, 0.35)))
    styles.add(ParagraphStyle(name="Bemerkung", fontName="Helvetica", fontSize=8,
                              leading=10))

    doc = SimpleDocTemplate(
        str(pfad), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Korrekturblatt {schueler_anzeige}",
    )

    story: list[Any] = []
    story.append(Paragraph(f"<b>Korrekturblatt</b> — {schueler_anzeige}", styles["Title"]))
    story.append(Paragraph(f"Klausur: <b>{klausur_name}</b>  ·  Status: <b>{status}</b>",
                           styles["Normal"]))
    story.append(Paragraph(
        f"Erzeugt am {erzeugt_am} mit Modell <font face='Courier'>{modell}</font>. "
        f"Paket: {paket_name}.", styles["Klein"]))
    story.append(Spacer(1, 4 * mm))

    # Endbewertung-Kasten
    prozent = (gesamt["gesamt"] / max_gesamt * 100) if max_gesamt else 0.0
    end_punkte = max(0, notenpunkte - sprachabzug)
    daten = [
        ["Erreichte Punkte (KI-Vorschlag)", f"{gesamt['gesamt']:.1f} / {max_gesamt:.0f} ({prozent:.1f} %)"],
        ["Notenpunkte (vor Sprachabzug)", f"{notenpunkte} – {note_kennung} ({note_text})"],
    ]
    if sprachabzug:
        daten.append(["Sprachabzug", f"−{sprachabzug} Notenpunkte"])
        daten.append(["Endnote (Vorschlag)", f"{end_punkte}"])
    end_tab = Table(daten, colWidths=[60 * mm, 110 * mm])
    end_tab.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), Color(0.97, 0.97, 0.97)),
        ("BOX", (0, 0), (-1, -1), 0.5, black),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, Color(0.7, 0.7, 0.7)),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(end_tab)
    story.append(Spacer(1, 6 * mm))

    # Aufgaben-Summen
    story.append(Paragraph("<b>Summen pro Aufgabe</b>", styles["Heading3"]))
    sum_header = ["Aufgabe", "AFB I", "AFB II", "AFB III", "Σ erreicht", "Σ max"]
    rows = [sum_header]
    for nr in sorted(aufgaben_summen.keys()):
        d = aufgaben_summen[nr]
        max_a = sum(e.max_pkt for e in eintraege if int(e.teilaufgabe.split(".")[0]) == nr)
        rows.append([f"Aufg. {nr}", f"{d['i']:.1f}", f"{d['ii']:.1f}",
                     f"{d['iii']:.1f}", f"{d['gesamt']:.1f}", f"{max_a:.0f}"])
    rows.append(["Gesamt", f"{gesamt['i']:.1f}", f"{gesamt['ii']:.1f}",
                 f"{gesamt['iii']:.1f}", f"{gesamt['gesamt']:.1f}", f"{max_gesamt:.0f}"])
    tab = Table(rows, colWidths=[22 * mm, 22 * mm, 22 * mm, 22 * mm, 32 * mm, 22 * mm])
    tab.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), Color(0.85, 0.88, 0.95)),
        ("BACKGROUND", (0, -1), (-1, -1), Color(0.95, 0.95, 0.85)),
        ("BOX", (0, 0), (-1, -1), 0.5, black),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, Color(0.7, 0.7, 0.7)),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("PADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tab)
    story.append(Spacer(1, 6 * mm))

    # Detail-Tabelle pro Teilaufgabe
    story.append(Paragraph("<b>Detail pro Teilaufgabe</b>", styles["Heading3"]))
    rows = [["TA", "Max", "Erreicht", "Standardsatz / Bemerkung", "Konf."]]
    for e in eintraege:
        bem = e.standardsatz
        if e.bemerkung and e.standardsatz not in ("o.K.",):
            bem = f"{e.standardsatz} {e.bemerkung}"
        flags = ", ".join(e.flags or [])
        if flags:
            bem += f"   [⚠ {flags}]"
        # Konfidenz-Spalte zeigt nichts bei „n/a"
        konf = f"{e.konfidenz}%" if e.konfidenz else "—"
        rows.append([
            e.teilaufgabe,
            f"{e.max_pkt:g}",
            f"{e.erreicht_pkt:g}",
            Paragraph(bem, styles["Bemerkung"]),
            konf,
        ])
    tab = Table(rows, colWidths=[18 * mm, 12 * mm, 18 * mm, 110 * mm, 14 * mm],
                repeatRows=1)
    tab.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), Color(0.85, 0.88, 0.95)),
        ("BOX", (0, 0), (-1, -1), 0.5, black),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, Color(0.75, 0.75, 0.75)),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 1), (2, -1), "RIGHT"),
        ("ALIGN", (4, 1), (4, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tab)

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        "<i>Hinweis: Dieses Korrekturblatt ist ein KI-Vorschlag. Die Endbewertung "
        "wird erst nach Sichtung und Freigabe durch die Lehrkraft rechtsgültig. "
        "Jede Änderung wird im Audit-Log mit Zeitstempel dokumentiert.</i>",
        styles["Klein"],
    ))

    doc.build(story)


# ---------------------------------------------------------------------------
# Haupteinstieg
# ---------------------------------------------------------------------------

def erzeuge_korrektur_pdf(
    original_pdf: Path,
    eintraege: list[KorrekturEintrag],
    ausgabe_pdf: Path,
    *,
    schueler_anzeige: str,
    klausur_name: str,
    paket_name: str,
    aufgaben_summen: dict[int, dict[str, float]],
    gesamt: dict[str, float],
    max_gesamt: float,
    notenpunkte: int,
    note_kennung: str,
    note_text: str,
    sprachabzug: int,
    modell: str,
    erzeugt_am: str,
    status: str = "Vorschlag (noch nicht freigegeben)",
) -> None:
    """Erzeugt die finale Korrektur-PDF (Original + Stempel + Korrekturblatt)."""
    if not original_pdf.exists():
        raise FileNotFoundError(f"Original-PDF nicht gefunden: {original_pdf}")

    # Originale Seitengröße bestimmen
    orig = PdfReader(str(original_pdf))
    n_seiten = len(orig.pages)
    if n_seiten == 0:
        raise ValueError("Original-PDF hat keine Seiten.")
    box = orig.pages[0].mediabox
    seitenformat = (float(box.width), float(box.height))

    # Einträge nach Seite gruppieren
    pro_seite: dict[int, list[KorrekturEintrag]] = {}
    for e in eintraege:
        seite = max(1, min(n_seiten, e.seite or 1))
        pro_seite.setdefault(seite, []).append(e)

    ausgabe_pdf.parent.mkdir(parents=True, exist_ok=True)
    tmp_overlay = ausgabe_pdf.with_suffix(".overlay.pdf")
    tmp_annotiert = ausgabe_pdf.with_suffix(".annotiert.pdf")
    tmp_korrblatt = ausgabe_pdf.with_suffix(".korrblatt.pdf")

    try:
        _erzeuge_overlay(seitenformat, pro_seite, tmp_overlay, n_seiten)
        _kombiniere_mit_overlay(original_pdf, tmp_overlay, tmp_annotiert)
        _erzeuge_korrekturblatt(
            tmp_korrblatt, schueler_anzeige=schueler_anzeige,
            klausur_name=klausur_name, paket_name=paket_name,
            eintraege=eintraege, aufgaben_summen=aufgaben_summen,
            gesamt=gesamt, max_gesamt=max_gesamt,
            notenpunkte=notenpunkte, note_kennung=note_kennung,
            note_text=note_text, sprachabzug=sprachabzug,
            modell=modell, erzeugt_am=erzeugt_am, status=status,
        )

        # Anhängen: annotiertes Original + Korrekturblatt
        writer = PdfWriter()
        for p in PdfReader(str(tmp_annotiert)).pages:
            writer.add_page(p)
        for p in PdfReader(str(tmp_korrblatt)).pages:
            writer.add_page(p)
        with open(ausgabe_pdf, "wb") as f:
            writer.write(f)
    finally:
        for t in (tmp_overlay, tmp_annotiert, tmp_korrblatt):
            try:
                t.unlink()
            except FileNotFoundError:
                pass
