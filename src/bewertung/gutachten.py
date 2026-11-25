#!/usr/bin/env python3
"""
Paket-basiertes Gutachtensystem (Phase B).

Nimmt ein Klausur-Paket (aus src.core.paket) + einen Ordner mit gescannten
Schülerlösungen entgegen und erzeugt pro Schüler:

  - korrigiert.pdf      – Original mit Annotationen + Korrekturblatt
  - bewertung.xlsx      – Lehrer-Vorlage mit eingetragenen Punkten
  - detailbericht.md    – lesbares Gutachten
  - bewertung.json      – maschinenlesbarer Vorschlag
  - audit_log.jsonl     – hash-verkettetes Audit-Log
  - ocr_text.txt        – Roh-OCR-Ausgabe
  - status.json         – „vorschlag" / „freigegeben" / „editiert"

Eigenschaften:
  • Reproduzierbar:  Modell + Parameter sind im Paket fixiert (T=0, seed).
  • Pseudonymisiert: KI bekommt nur „Schueler-013" zu sehen.
  • Nachvollziehbar: jeder KI-Aufruf wird mit Prompt-Hash, Antwort-Hash,
                     Zeitstempel im Audit-Log dokumentiert.
  • Rechtssicher:    Bewertung ist ein VORSCHLAG; erst nach Freigabe durch
                     die Lehrkraft (src.core.freigeben) wird die Note
                     rechtsgültig. Lehrer-Edits werden mit Diff geloggt.

Nutzung:
  python src/bewertung/gutachten.py vorbereiten "BGI3_2025_VorschlagA" \\
      --lehrer Material/...lehrermaterial.pdf \\
      --schueler Material/...schuelermaterial_270min.pdf \\
      --vorlage "Material/BGI3_Abiturbewertung_2025 Vorschlag A.xlsx"

  python src/bewertung/gutachten.py bewerten \\
      --paket Klausurpakete/BGI3_2025_VorschlagA \\
      --scans Klausuren/Schueler-Scans/
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from openai import OpenAI

from src.core.audit import AuditLog, sha256_datei, sha256_text
from src.core.korrektur_pdf import KorrekturEintrag, erzeuge_korrektur_pdf
from src.core.paket import (
    PAKETE_WURZEL, Paket, klarname, paket_erstellen, paket_laden,
    pseudonym_vergeben,
)
from src.bewertung.schueler import (
    BewertungsErgebnis, SchuelerBewertung, SATZ_LEER, STANDARDSAETZE,
    Teilaufgabe, _clamp, _parse_json_robust, _zahl, fuelle_xlsx,
    lese_schuelerarbeit_pdf, punkte_und_note, schreibe_detailbericht_json,
    schreibe_detailbericht_markdown, waehle_standardsatz,
    BEWERTUNGS_SYSTEM_PROMPT,
)

KONFIDENZ_SCHWELLE = 60


# ---------------------------------------------------------------------------
# Helfer: Paket → Teilaufgabe-Objekte (für bestehende Bibliotheksfunktionen)
# ---------------------------------------------------------------------------

def _paket_teilaufgaben(paket: Paket) -> list[Teilaufgabe]:
    """Konvertiert die im Paket gespeicherten Specs in Teilaufgabe-Objekte."""
    return [
        Teilaufgabe(
            nummer=t.nummer, aufgabe=t.aufgabe,
            max_punkte_i=t.max_punkte_i, max_punkte_ii=t.max_punkte_ii,
            max_punkte_iii=t.max_punkte_iii,
            zeile_in_vorlage=t.zeile_in_vorlage,
            erwartungstext=t.erwartungstext,
        )
        for t in paket.teilaufgaben
    ]


# ---------------------------------------------------------------------------
# Antwort-Extraktion mit Seitenzuordnung (für Korrektur-PDF-Annotationen)
# ---------------------------------------------------------------------------

def extrahiere_antworten_mit_seite(
    rohtext: str,
    teilaufgaben: list[Teilaufgabe],
) -> dict[str, tuple[str, int]]:
    """Wie `extrahiere_antworten_pro_teilaufgabe`, liefert zusätzlich die Seite.

    Erkennt `--- SEITE n ---`-Marker im Rohtext (vom OCR-Pre-Processor)
    und ordnet jede Teilaufgabe der Seite zu, auf der ihr Anker zuerst
    auftritt. Default-Seite ist 1.
    """
    # Seitenmarker indexieren: Position → Seitenzahl
    seiten_marker = [(m.start(), int(m.group(1)))
                     for m in re.finditer(r"---\s*SEITE\s+(\d+)\s*---", rohtext)]

    def seite_an_position(pos: int) -> int:
        seite = 1
        for p, s in seiten_marker:
            if p <= pos:
                seite = s
            else:
                break
        return seite

    nummern = sorted({ta.nummer for ta in teilaufgaben},
                     key=lambda n: [int(p) for p in n.split(".")])
    nummern_re = "|".join(re.escape(n) for n in nummern)
    anker_pattern = re.compile(
        rf"(?:^|\n)(?:\s*(?:###\s*TA\s*|Aufg\.?\s*|Aufgabe\s*|zu\s*|Teilaufgabe\s*)?)({nummern_re})\b[):.]?",
        re.IGNORECASE,
    )
    treffer = list(anker_pattern.finditer(rohtext))
    bloecke: dict[str, list[str]] = {n: [] for n in nummern}
    seiten: dict[str, int] = {}
    for i, m in enumerate(treffer):
        nummer = m.group(1)
        if nummer not in seiten:
            seiten[nummer] = seite_an_position(m.start())
        start = m.end()
        end = treffer[i + 1].start() if i + 1 < len(treffer) else len(rohtext)
        block = rohtext[start:end].strip(" \t:)\n")
        if block:
            bloecke[nummer].append(block)
    return {
        n: ("\n\n".join(parts).strip(), seiten.get(n, 1))
        for n, parts in bloecke.items()
    }


# ---------------------------------------------------------------------------
# Deterministischer KI-Aufruf mit Audit-Logging
# ---------------------------------------------------------------------------

def _ki_anfrage_deterministisch(
    client: OpenAI,
    paket: Paket,
    nutzer_prompt: str,
    system_prompt: str = BEWERTUNGS_SYSTEM_PROMPT,
    max_tokens: int = 1500,
) -> str:
    """Streaming-Aufruf mit fixierten Parametern aus dem Paket."""
    extra: dict[str, Any] = {}
    # OpenAI unterstützt seed offiziell; einige lokale Backends (LM Studio)
    # akzeptieren es als extra_body, andere ignorieren es. Wir senden es,
    # ohne darauf zu vertrauen – T=0 ist die Hauptgrundlage der Determinismus.
    if paket.ki.seed:
        extra["seed"] = paket.ki.seed
    stream = client.chat.completions.create(
        model=paket.ki.modell,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": nutzer_prompt},
        ],
        temperature=paket.ki.temperature,
        top_p=paket.ki.top_p,
        max_tokens=max_tokens,
        stream=True,
        **extra,
    )
    out: list[str] = []
    n = 0
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            out.append(chunk.choices[0].delta.content)
            n += 1
            if n % 25 == 0:
                print(".", end="", flush=True)
    if n >= 25:
        print(flush=True)
    return "".join(out).strip()


def bewerte_teilaufgabe_mit_audit(
    client: OpenAI,
    paket: Paket,
    ta: Teilaufgabe,
    schueler_antwort: str,
    seite: int,
    pseudonym: str,
    audit: AuditLog,
) -> BewertungsErgebnis:
    """Bewertet eine Teilaufgabe und schreibt einen Audit-Log-Eintrag.

    KI sieht nur das Pseudonym, niemals den Klarnamen.
    """
    if not schueler_antwort.strip():
        # Keine Antwort → KEIN KI-Aufruf nötig (deterministisch 0)
        ergebnis = BewertungsErgebnis(
            teilaufgabe=ta.nummer,
            standardsatz=SATZ_LEER,
            bemerkung="Im OCR-Text wurde keine Antwort zu dieser Teilaufgabe gefunden.",
            konfidenz=80,
            flags=["keine_antwort"],
        )
        ergebnis.seite = seite  # type: ignore[attr-defined]
        audit.append(
            schritt="bewertung_skip_leer",
            pseudonym=pseudonym, modell=paket.ki.modell,
            payload={"teilaufgabe": ta.nummer, "grund": "keine_antwort"},
        )
        return ergebnis

    nutzer_prompt = (
        f"### KONTEXT\n"
        f"Pseudonym: {pseudonym} (Klarname pseudonymisiert)\n\n"
        f"### TEILAUFGABE {ta.nummer}\n\n"
        f"### ERWARTUNGSHORIZONT\n{ta.erwartungstext or '(nicht verfügbar)'}\n\n"
        f"### MAXIMALE PUNKTE\n"
        f"AFB I = {ta.max_punkte_i}\nAFB II = {ta.max_punkte_ii}\n"
        f"AFB III = {ta.max_punkte_iii}\nSumme = {ta.max_punkte_gesamt}\n\n"
        f"### SCHÜLERANTWORT (aus OCR)\n{schueler_antwort.strip()}\n\n"
        f"### AUFGABE\n"
        f"Bewerte die Schülerantwort gegen den Erwartungshorizont und antworte "
        f"ausschließlich im vorgegebenen JSON-Format."
    )
    raw = _ki_anfrage_deterministisch(client, paket, nutzer_prompt)
    daten = _parse_json_robust(raw)

    audit.append(
        schritt="ki_bewertung",
        pseudonym=pseudonym, modell=paket.ki.modell,
        parameter={
            "temperature": paket.ki.temperature, "top_p": paket.ki.top_p,
            "seed": paket.ki.seed,
        },
        input_text=nutzer_prompt,
        output_text=raw,
        payload={"teilaufgabe": ta.nummer, "antwort_geparst": bool(daten)},
    )

    if not daten:
        e = BewertungsErgebnis(
            teilaufgabe=ta.nummer,
            standardsatz=SATZ_LEER,
            bemerkung=f"KI-Antwort nicht auswertbar. Roh (gekürzt): {raw[:200]}",
            konfidenz=0,
            schueler_antwort=schueler_antwort,
            flags=["ki_parse_fehler"],
        )
        e.seite = seite  # type: ignore[attr-defined]
        return e

    pi = _clamp(_zahl(daten.get("punkte_i")), 0, ta.max_punkte_i)
    pii = _clamp(_zahl(daten.get("punkte_ii")), 0, ta.max_punkte_ii)
    piii = _clamp(_zahl(daten.get("punkte_iii")), 0, ta.max_punkte_iii)
    konfidenz = int(_zahl(daten.get("konfidenz")))
    standardsatz = (daten.get("standardsatz") or "").strip()
    erlaubte = {s for _, s in STANDARDSAETZE} | {
        "Die vorgelegte Lösung ist falsch und entspricht somit nicht den Erwartungen.",
        SATZ_LEER,
    }
    if standardsatz not in erlaubte:
        prozent = ((pi + pii + piii) / ta.max_punkte_gesamt) if ta.max_punkte_gesamt else 0.0
        standardsatz = waehle_standardsatz(prozent)
    flags = ["konfidenz_niedrig"] if konfidenz < KONFIDENZ_SCHWELLE else []

    e = BewertungsErgebnis(
        teilaufgabe=ta.nummer,
        erreicht_i=pi, erreicht_ii=pii, erreicht_iii=piii,
        standardsatz=standardsatz,
        bemerkung=(daten.get("bemerkung") or "").strip(),
        konfidenz=konfidenz,
        schueler_antwort=schueler_antwort,
        flags=flags,
    )
    e.seite = seite  # type: ignore[attr-defined]
    return e


# ---------------------------------------------------------------------------
# Gutachten-Text (qualitativ, basiert auf AFB-Texten aus dem Paket)
# ---------------------------------------------------------------------------

def generiere_gutachten_text(
    paket: Paket,
    summen: dict[int, dict[str, float]],
    gesamt: dict[str, float],
    schueler_anzeige: str,
    notenpunkte: int,
    note_text: str,
) -> str:
    """Erzeugt den vier-AFB-Standardgutachten-Text wie in der Vorlage vorgesehen."""
    # Aufgaben-Maxima
    max_pro_aufg: dict[int, float] = {}
    max_pro_afb: dict[str, float] = {"i": 0.0, "ii": 0.0, "iii": 0.0}
    for t in paket.teilaufgaben:
        max_pro_aufg.setdefault(t.aufgabe, 0)
        max_pro_aufg[t.aufgabe] += t.max_punkte_i + t.max_punkte_ii + t.max_punkte_iii
        max_pro_afb["i"] += t.max_punkte_i
        max_pro_afb["ii"] += t.max_punkte_ii
        max_pro_afb["iii"] += t.max_punkte_iii

    def afb_satz(afb_key: str) -> str:
        eintraege = paket.afb_texte.get(afb_key) or []
        if not eintraege or max_pro_afb[afb_key] == 0:
            return ""
        prozent = (gesamt[afb_key] / max_pro_afb[afb_key]) * 100
        passend = ""
        for e in eintraege:
            if prozent >= e.get("prozent_min", 0):
                passend = e.get("text", "")
        return passend

    lines = [
        f"### Gutachten-Vorschlag für {schueler_anzeige}",
        "",
        afb_satz("i"),
        afb_satz("ii"),
        afb_satz("iii"),
        "",
    ]
    # Pro Aufgabe einen Hinweissatz
    for aufgabe_nr in sorted(summen.keys()):
        d = summen[aufgabe_nr]
        max_a = max_pro_aufg.get(aufgabe_nr, 0)
        if not max_a:
            continue
        p = (d["gesamt"] / max_a * 100)
        lines.append(
            f"Die {aufgabe_nr}. Aufgabe wurde zu {p:.0f} % gelöst "
            f"({d['gesamt']:.1f} / {max_a:.0f} Punkte)."
        )
    lines.append("")
    lines.append(
        f"Die schriftliche Leistung wird mit **{notenpunkte} Notenpunkten** "
        f"({note_text}) bewertet (KI-Vorschlag)."
    )
    return "\n".join(l for l in lines if l is not None)


# ---------------------------------------------------------------------------
# Status-Datei pro Schüler
# ---------------------------------------------------------------------------

def schreibe_status(schueler_dir: Path, status: str, **extra: Any) -> None:
    payload = {
        "status": status,
        "geaendert_am": time.strftime("%Y-%m-%dT%H:%M:%S"),
        **extra,
    }
    (schueler_dir / "status.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def lese_status(schueler_dir: Path) -> dict[str, Any]:
    p = schueler_dir / "status.json"
    if not p.exists():
        return {"status": "unbekannt"}
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Hauptfunktion: einen Schüler bewerten
# ---------------------------------------------------------------------------

def bewerte_einen_schueler(
    paket: Paket,
    schueler_pdf: Path,
    schueler_klarname: str,
    ocr_modus: str = "vision",
) -> Path:
    """Komplette Pipeline für eine Schüler-PDF.

    Liefert den Pfad zum Schüler-Verzeichnis zurück.
    """
    pseudonym = pseudonym_vergeben(paket, schueler_klarname)
    schueler_dir = paket.bewertungen_dir / pseudonym
    schueler_dir.mkdir(parents=True, exist_ok=True)
    audit = AuditLog(schueler_dir / "audit_log.jsonl")

    print(f"\n=== {schueler_klarname}  (Pseudonym: {pseudonym}) ===")
    schreibe_status(schueler_dir, "in_bearbeitung", pseudonym=pseudonym)

    # PDF kopieren + hashen (immutable Audit)
    original_kopie = schueler_dir / "original.pdf"
    shutil.copy2(schueler_pdf, original_kopie)
    original_hash = sha256_datei(original_kopie)
    (schueler_dir / "original.sha256").write_text(
        f"{original_hash}  original.pdf\n", encoding="utf-8")
    audit.append(
        schritt="schueler_eingelesen",
        pseudonym=pseudonym, modell=paket.ki.modell,
        payload={
            "original_sha256": original_hash,
            "original_bytes": original_kopie.stat().st_size,
            "ocr_modus": ocr_modus,
        },
    )

    # KI-Client
    client = OpenAI(base_url=paket.ki.base_url, api_key="lm-studio",
                    timeout=1800.0, max_retries=0)

    # Schritt OCR
    print(f"  [OCR] {ocr_modus} mit {paket.ki.vision_modell or paket.ki.modell} ...")
    rohtext = lese_schuelerarbeit_pdf(
        original_kopie, modus=ocr_modus,
        client=client, modell=paket.ki.vision_modell or paket.ki.modell,
    )
    (schueler_dir / "ocr_text.txt").write_text(rohtext, encoding="utf-8")
    audit.append(
        schritt="ocr_abgeschlossen",
        pseudonym=pseudonym, modell=paket.ki.vision_modell or paket.ki.modell,
        parameter={"modus": ocr_modus, "dpi": paket.ki.vision_dpi},
        output_text=rohtext,
        payload={"zeichen": len(rohtext)},
    )

    # Schritt Antworten zerlegen
    teilaufgaben = _paket_teilaufgaben(paket)
    ant_mit_seite = extrahiere_antworten_mit_seite(rohtext, teilaufgaben)

    # Schritt KI-Bewertung pro Teilaufgabe
    print(f"  [BEWERTUNG] {len(teilaufgaben)} Teilaufgaben ...")
    ergebnisse: list[BewertungsErgebnis] = []
    for i, ta in enumerate(teilaufgaben, 1):
        antwort, seite = ant_mit_seite.get(ta.nummer, ("", 1))
        print(f"    [{i}/{len(teilaufgaben)}] {ta.nummer} (S. {seite}) ...", end="", flush=True)
        e = bewerte_teilaufgabe_mit_audit(
            client, paket, ta, antwort, seite, pseudonym, audit)
        ergebnisse.append(e)
        marker = "⚠" if e.flags else "✓"
        print(f" {marker} {e.erreicht_gesamt:.1f}/{ta.max_punkte_gesamt:.0f}")

    # SchuelerBewertung-Objekt
    bewertung = SchuelerBewertung(
        schueler_name=schueler_klarname,  # Klarname nur für XLSX/Anzeige
        quelldatei=str(original_kopie.name),
        ergebnisse=ergebnisse,
        modell=paket.ki.modell,
        ocr_methode=f"pdf+{ocr_modus}",
        erzeugt_am=time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    # Schritt XLSX füllen
    xlsx_pfad = schueler_dir / "bewertung.xlsx"
    fuelle_xlsx(paket.vorlage_xlsx, xlsx_pfad, bewertung, teilaufgaben)
    # Schritt MD/JSON
    md_pfad = schueler_dir / "detailbericht.md"
    schreibe_detailbericht_markdown(bewertung, teilaufgaben, md_pfad)
    schreibe_detailbericht_json(bewertung, schueler_dir / "bewertung.json")

    # Gutachten-Text anhängen
    gesamt = bewertung.gesamtsummen()
    summen = bewertung.summen_pro_aufgabe()
    max_ges = sum(t.max_punkte_gesamt for t in teilaufgaben)
    prozent = (gesamt["gesamt"] / max_ges * 100) if max_ges else 0.0
    np, kennung, note_text = punkte_und_note(prozent)
    gutachten = generiere_gutachten_text(
        paket, summen, gesamt, schueler_klarname, np, note_text)
    with open(md_pfad, "a", encoding="utf-8") as f:
        f.write("\n\n---\n\n" + gutachten + "\n")
    (schueler_dir / "gutachten.md").write_text(gutachten, encoding="utf-8")

    # Schritt Korrektur-PDF
    print(f"  [KORREKTUR-PDF] erzeuge ...")
    korr_eintraege = [
        KorrekturEintrag(
            teilaufgabe=e.teilaufgabe,
            seite=getattr(e, "seite", 1),
            max_pkt=next(t.max_punkte_gesamt for t in teilaufgaben if t.nummer == e.teilaufgabe),
            erreicht_pkt=e.erreicht_gesamt,
            standardsatz=e.standardsatz,
            bemerkung=e.bemerkung,
            konfidenz=e.konfidenz,
            flags=e.flags or [],
        )
        for e in ergebnisse
    ]
    korrektur_pdf = schueler_dir / "korrigiert.pdf"
    erzeuge_korrektur_pdf(
        original_pdf=original_kopie,
        eintraege=korr_eintraege,
        ausgabe_pdf=korrektur_pdf,
        schueler_anzeige=schueler_klarname,
        klausur_name=paket.name,
        paket_name=paket.name,
        aufgaben_summen=summen,
        gesamt=gesamt,
        max_gesamt=max_ges,
        notenpunkte=np,
        note_kennung=kennung,
        note_text=note_text,
        sprachabzug=0,
        modell=paket.ki.modell,
        erzeugt_am=bewertung.erzeugt_am,
        status="KI-Vorschlag (noch nicht freigegeben)",
    )

    # Status setzen
    schreibe_status(
        schueler_dir, "vorschlag",
        pseudonym=pseudonym,
        klarname=schueler_klarname,
        erreichte_punkte=gesamt["gesamt"],
        max_punkte=max_ges,
        notenpunkte=np,
        note=f"{kennung} ({note_text})",
        konfidenz_warnungen=sum(1 for e in ergebnisse if e.flags),
    )

    audit.append(
        schritt="bewertung_abgeschlossen",
        pseudonym=pseudonym, modell=paket.ki.modell,
        payload={
            "erreichte_punkte": gesamt["gesamt"],
            "max_punkte": max_ges,
            "prozent": prozent,
            "notenpunkte_vorschlag": np,
            "note": f"{kennung} ({note_text})",
            "konfidenz_warnungen": sum(1 for e in ergebnisse if e.flags),
        },
    )

    print(f"  ✓ {gesamt['gesamt']:.1f}/{max_ges:.0f} = {prozent:.1f} %  →  {np} NP "
          f"({kennung}, {note_text})  [VORSCHLAG]")
    return schueler_dir


# ---------------------------------------------------------------------------
# Batch: kompletter Scan-Ordner
# ---------------------------------------------------------------------------

def bewerte_scan_ordner(
    paket: Paket,
    scan_ordner: Path,
    ocr_modus: str = "vision",
    nur_dateien: list[str] | None = None,
) -> dict[str, Path]:
    """Bewertet alle PDFs im Scan-Ordner und liefert {klarname: ausgabedir}."""
    pdfs = sorted(scan_ordner.glob("*.pdf"))
    if nur_dateien:
        pdfs = [p for p in pdfs if p.name in nur_dateien]
    if not pdfs:
        print(f"Keine PDFs in {scan_ordner} gefunden.")
        return {}

    print(f"\nBewerte {len(pdfs)} Klausur(en) aus {scan_ordner}\n")
    out: dict[str, Path] = {}
    for pdf in pdfs:
        klarname_raw = pdf.stem.replace("_", " ").strip()
        try:
            d = bewerte_einen_schueler(paket, pdf, klarname_raw, ocr_modus=ocr_modus)
            out[klarname_raw] = d
        except Exception as e:
            print(f"  ✗ Fehler bei {pdf.name}: {e}")
    return out


# ---------------------------------------------------------------------------
# Klassenübersicht
# ---------------------------------------------------------------------------

def erzeuge_klassenuebersicht(paket: Paket) -> Path:
    """Markdown-Übersicht: alle Schüler mit Status, Note, Auffälligkeiten."""
    out_pfad = paket.paket_dir / "klassenuebersicht.md"
    schueler = sorted(paket.bewertungen_dir.glob("Schueler-*"))
    lines = [f"# Klassenübersicht – {paket.name}", "",
             f"Stand: {time.strftime('%Y-%m-%d %H:%M:%S')}", "",
             "| Pseudonym | Klarname | Status | Punkte | NP | Note | Konfidenz-Warnungen |",
             "|---|---|---|---|---|---|---|"]
    summe_np = 0
    n = 0
    for s in schueler:
        st = lese_status(s)
        lines.append(
            f"| {st.get('pseudonym', s.name)} "
            f"| {st.get('klarname', '?')} "
            f"| {st.get('status', '?')} "
            f"| {st.get('erreichte_punkte', '?')}/{st.get('max_punkte', '?')} "
            f"| {st.get('notenpunkte', '?')} "
            f"| {st.get('note', '?')} "
            f"| {st.get('konfidenz_warnungen', '?')} |"
        )
        if isinstance(st.get("notenpunkte"), (int, float)):
            summe_np += st["notenpunkte"]
            n += 1
    if n:
        lines.append("")
        lines.append(f"Durchschnitt (Notenpunkte): **{summe_np / n:.1f}** (n={n})")
    out_pfad.write_text("\n".join(lines), encoding="utf-8")
    return out_pfad


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("vorbereiten", help="Klausur-Paket erstellen (Phase A)")
    pp.add_argument("name")
    pp.add_argument("--lehrer", type=Path, required=True)
    pp.add_argument("--schueler", type=Path, required=True)
    pp.add_argument("--vorlage", type=Path, required=True)
    pp.add_argument("--ausgabe", type=Path, default=PAKETE_WURZEL)
    pp.add_argument("--modell", default="")
    pp.add_argument("--provider", default="lokal", choices=["lokal", "hetzner", "gwdg"])
    pp.add_argument("--vision-modell", default="")

    pb = sub.add_parser("bewerten", help="Schüler-Scans gegen Paket bewerten (Phase B)")
    pb.add_argument("--paket", type=Path, required=True)
    pb.add_argument("--scans", type=Path, required=True,
                    help="Ordner mit Schüler-PDFs (Dateiname = Klarname)")
    pb.add_argument("--ocr", choices=["vision", "tesseract"], default="vision")
    pb.add_argument("--datei", action="append", default=[],
                    help="Nur diese Dateinamen verarbeiten (mehrfach möglich)")

    pu = sub.add_parser("uebersicht", help="Klassenübersicht ausgeben")
    pu.add_argument("--paket", type=Path, required=True)

    args = p.parse_args(argv)

    if args.cmd == "vorbereiten":
        paket = paket_erstellen(
            name=args.name, lehrer_pdf=args.lehrer,
            schueler_pdf=args.schueler, vorlage_xlsx=args.vorlage,
            ausgabe_wurzel=args.ausgabe, ki_modell=args.modell,
            ki_provider=args.provider, ki_vision_modell=args.vision_modell,
        )
        print(f"\n✓ Paket erstellt: {paket.paket_dir}")
        print(f"  Nächster Schritt:")
        print(f"    python src/bewertung/gutachten.py bewerten "
              f"--paket {paket.paket_dir} --scans Klausuren/Schueler-Scans/")
        return 0

    if args.cmd == "bewerten":
        paket = paket_laden(args.paket)
        ergebnisse = bewerte_scan_ordner(
            paket, args.scans, ocr_modus=args.ocr,
            nur_dateien=args.datei or None,
        )
        u = erzeuge_klassenuebersicht(paket)
        print(f"\nFertig. {len(ergebnisse)} Bewertung(en) erzeugt.")
        print(f"Klassenübersicht: {u}")
        print(f"Lehrer-Freigabe:  python src/core/freigeben.py --paket {args.paket}")
        return 0

    if args.cmd == "uebersicht":
        paket = paket_laden(args.paket)
        u = erzeuge_klassenuebersicht(paket)
        print(f"Klassenübersicht: {u}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
