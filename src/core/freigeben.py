#!/usr/bin/env python3
"""
Lehrer-Freigabe-Workflow (Phase C).

Geht alle Schüler eines Pakets im Status „vorschlag" durch und bietet
der Lehrkraft eine interaktive Sichtung an:

  [j] Freigeben — Vorschlag wird zur Endbewertung; Status → „freigegeben"
  [e] Editieren — Punkte oder Bemerkungen ändern, automatisch neu berechnen,
                  XLSX / Korrektur-PDF werden neu erzeugt; Status → „editiert"
  [v] Verwerfen — Bewertung als „verworfen" markieren (z.B. nochmal von Hand);
                  vorhandene Dateien bleiben, aber Note ist ungültig
  [s] Sprachabzug setzen (0 / 1 / 2 Notenpunkte)
  [n] Nächster (überspringen)

Jede Aktion wird im audit_log.jsonl als „lehrer_freigabe", „lehrer_edit"
oder „lehrer_verwerfen" festgehalten – mit Diff der vorher/nachher-Werte.

Nicht-interaktive Modi:
  --bulk-freigabe          Alle Vorschläge auf einmal freigeben
  --status                 Übersicht ausgeben (kein Eingriff)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.core.audit import AuditLog
from src.core.korrektur_pdf import KorrekturEintrag, erzeuge_korrektur_pdf
from src.core.paket import Paket, paket_laden
from src.bewertung.schueler import (
    BewertungsErgebnis, SchuelerBewertung, fuelle_xlsx,
    punkte_und_note, schreibe_detailbericht_json,
    schreibe_detailbericht_markdown, waehle_standardsatz,
)
from src.bewertung.gutachten import (
    _paket_teilaufgaben, lese_status, schreibe_status,
)


# ---------------------------------------------------------------------------
# Laden / Speichern einer Schüler-Bewertung
# ---------------------------------------------------------------------------

def _lade_bewertung(schueler_dir: Path) -> SchuelerBewertung:
    j = json.loads((schueler_dir / "bewertung.json").read_text(encoding="utf-8"))
    erg = [BewertungsErgebnis(**e) for e in j.get("ergebnisse", [])]
    return SchuelerBewertung(
        schueler_name=j["schueler_name"],
        quelldatei=j["quelldatei"],
        ergebnisse=erg,
        sprachabzug=j.get("sprachabzug", 0),
        modell=j.get("modell", ""),
        ocr_methode=j.get("ocr_methode", ""),
        erzeugt_am=j.get("erzeugt_am", ""),
    )


def _speichere_bewertung_und_artefakte(
    paket: Paket,
    schueler_dir: Path,
    bewertung: SchuelerBewertung,
    status: str,
) -> None:
    """Schreibt XLSX / Markdown / JSON / Korrektur-PDF + Status neu."""
    teilaufgaben = _paket_teilaufgaben(paket)
    fuelle_xlsx(paket.vorlage_xlsx, schueler_dir / "bewertung.xlsx",
                bewertung, teilaufgaben)
    schreibe_detailbericht_markdown(bewertung, teilaufgaben,
                                    schueler_dir / "detailbericht.md")
    schreibe_detailbericht_json(bewertung, schueler_dir / "bewertung.json")

    gesamt = bewertung.gesamtsummen()
    summen = bewertung.summen_pro_aufgabe()
    max_ges = sum(t.max_punkte_gesamt for t in teilaufgaben)
    prozent = (gesamt["gesamt"] / max_ges * 100) if max_ges else 0.0
    np, kennung, note_text = punkte_und_note(prozent)
    np_final = max(0, np - bewertung.sprachabzug)

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
        for e in bewertung.ergebnisse
    ]
    status_text = {
        "freigegeben": "Freigegeben durch Lehrkraft",
        "editiert": "Editiert + freigegeben durch Lehrkraft",
        "verworfen": "Verworfen – Note ungültig",
    }.get(status, status)
    erzeuge_korrektur_pdf(
        original_pdf=schueler_dir / "original.pdf",
        eintraege=korr_eintraege,
        ausgabe_pdf=schueler_dir / "korrigiert.pdf",
        schueler_anzeige=bewertung.schueler_name,
        klausur_name=paket.name,
        paket_name=paket.name,
        aufgaben_summen=summen,
        gesamt=gesamt,
        max_gesamt=max_ges,
        notenpunkte=np,
        note_kennung=kennung,
        note_text=note_text,
        sprachabzug=bewertung.sprachabzug,
        modell=bewertung.modell,
        erzeugt_am=bewertung.erzeugt_am,
        status=status_text,
    )

    schreibe_status(
        schueler_dir, status,
        pseudonym=schueler_dir.name,
        klarname=bewertung.schueler_name,
        erreichte_punkte=gesamt["gesamt"],
        max_punkte=max_ges,
        notenpunkte=np,
        notenpunkte_final=np_final,
        note=f"{kennung} ({note_text})",
        sprachabzug=bewertung.sprachabzug,
        konfidenz_warnungen=sum(1 for e in bewertung.ergebnisse if e.flags),
    )


# ---------------------------------------------------------------------------
# Lehrer-Aktionen (jede mit Audit)
# ---------------------------------------------------------------------------

def freigeben(paket: Paket, schueler_dir: Path, lehrer: str) -> None:
    bewertung = _lade_bewertung(schueler_dir)
    audit = AuditLog(schueler_dir / "audit_log.jsonl")
    audit.append(
        schritt="lehrer_freigabe",
        pseudonym=schueler_dir.name,
        modell=bewertung.modell,
        payload={
            "lehrer": lehrer,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "punktsumme": bewertung.gesamtsummen()["gesamt"],
            "sprachabzug": bewertung.sprachabzug,
        },
    )
    _speichere_bewertung_und_artefakte(paket, schueler_dir, bewertung, "freigegeben")
    print(f"  ✓ {schueler_dir.name} freigegeben.")


def verwerfen(paket: Paket, schueler_dir: Path, lehrer: str, grund: str) -> None:
    bewertung = _lade_bewertung(schueler_dir)
    audit = AuditLog(schueler_dir / "audit_log.jsonl")
    audit.append(
        schritt="lehrer_verwerfen",
        pseudonym=schueler_dir.name,
        modell=bewertung.modell,
        payload={"lehrer": lehrer, "grund": grund,
                 "ts": time.strftime("%Y-%m-%dT%H:%M:%S")},
    )
    _speichere_bewertung_und_artefakte(paket, schueler_dir, bewertung, "verworfen")
    print(f"  ✗ {schueler_dir.name} verworfen ({grund}).")


def editieren(
    paket: Paket,
    schueler_dir: Path,
    edits: dict[str, dict[str, Any]],
    sprachabzug: int | None,
    lehrer: str,
    grund: str,
) -> None:
    """Wendet Edits auf die Bewertung an und loggt den Diff."""
    bewertung_vorher = _lade_bewertung(schueler_dir)
    bewertung = _lade_bewertung(schueler_dir)
    teilaufgaben = _paket_teilaufgaben(paket)
    diffs: list[dict[str, Any]] = []

    for nr, eintrag in edits.items():
        ta = next((t for t in teilaufgaben if t.nummer == nr), None)
        if not ta:
            continue
        e = next((x for x in bewertung.ergebnisse if x.teilaufgabe == nr), None)
        if not e:
            continue
        vorher = {"i": e.erreicht_i, "ii": e.erreicht_ii, "iii": e.erreicht_iii,
                  "standardsatz": e.standardsatz, "bemerkung": e.bemerkung}
        if "i" in eintrag:
            e.erreicht_i = max(0.0, min(ta.max_punkte_i, float(eintrag["i"])))
        if "ii" in eintrag:
            e.erreicht_ii = max(0.0, min(ta.max_punkte_ii, float(eintrag["ii"])))
        if "iii" in eintrag:
            e.erreicht_iii = max(0.0, min(ta.max_punkte_iii, float(eintrag["iii"])))
        if "bemerkung" in eintrag:
            e.bemerkung = str(eintrag["bemerkung"])
        # Standardsatz automatisch neu wählen
        prozent = (e.erreicht_gesamt / ta.max_punkte_gesamt) if ta.max_punkte_gesamt else 0.0
        e.standardsatz = waehle_standardsatz(prozent)
        nachher = {"i": e.erreicht_i, "ii": e.erreicht_ii, "iii": e.erreicht_iii,
                   "standardsatz": e.standardsatz, "bemerkung": e.bemerkung}
        if vorher != nachher:
            e.flags = [f for f in (e.flags or []) if f != "konfidenz_niedrig"]
            e.flags.append("lehrer_edit")
            diffs.append({"teilaufgabe": nr, "vorher": vorher, "nachher": nachher})

    if sprachabzug is not None and sprachabzug != bewertung.sprachabzug:
        diffs.append({
            "sprachabzug": {"vorher": bewertung.sprachabzug, "nachher": sprachabzug},
        })
        bewertung.sprachabzug = sprachabzug

    if not diffs:
        print(f"  (keine Änderungen für {schueler_dir.name})")
        return

    audit = AuditLog(schueler_dir / "audit_log.jsonl")
    audit.append(
        schritt="lehrer_edit",
        pseudonym=schueler_dir.name,
        modell=bewertung.modell,
        payload={
            "lehrer": lehrer, "grund": grund,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "diffs": diffs,
        },
    )
    _speichere_bewertung_und_artefakte(paket, schueler_dir, bewertung, "editiert")
    print(f"  ✎ {schueler_dir.name}: {len(diffs)} Änderung(en) angewandt + freigegeben.")


# ---------------------------------------------------------------------------
# Interaktiver Review-Loop
# ---------------------------------------------------------------------------

def _kurzfassung(bewertung: SchuelerBewertung, teilaufgaben_max: dict[str, float]) -> str:
    lines: list[str] = []
    gesamt = bewertung.gesamtsummen()
    max_ges = sum(teilaufgaben_max.values())
    prozent = (gesamt["gesamt"] / max_ges * 100) if max_ges else 0.0
    np, kennung, note_text = punkte_und_note(prozent)
    lines.append(f"  Klarname:     {bewertung.schueler_name}")
    lines.append(f"  Punkte:       {gesamt['gesamt']:.1f} / {max_ges:.0f} = {prozent:.1f} %")
    lines.append(f"  Note:         {np} NP ({kennung}, {note_text})")
    if bewertung.sprachabzug:
        lines.append(f"  Sprachabzug:  −{bewertung.sprachabzug} → {max(0, np - bewertung.sprachabzug)} NP")
    lines.append(f"  KI-Modell:    {bewertung.modell}")
    auff = [e for e in bewertung.ergebnisse if e.flags]
    if auff:
        lines.append(f"  Auffällig:    {len(auff)} Teilaufgabe(n) mit Flags:")
        for e in auff:
            lines.append(f"    {e.teilaufgabe}: {e.erreicht_gesamt:.1f}/{teilaufgaben_max[e.teilaufgabe]:.0f} "
                         f"({', '.join(e.flags)})")
    return "\n".join(lines)


def interaktiv(paket: Paket, lehrer: str) -> None:
    teilaufgaben = _paket_teilaufgaben(paket)
    ta_max = {t.nummer: t.max_punkte_gesamt for t in teilaufgaben}
    schueler = sorted(paket.bewertungen_dir.glob("Schueler-*"))
    if not schueler:
        print(f"Keine Bewertungen in {paket.bewertungen_dir}.")
        return

    for s in schueler:
        st = lese_status(s)
        if st.get("status") not in ("vorschlag", "in_bearbeitung"):
            continue
        bewertung = _lade_bewertung(s)
        print("\n" + "=" * 72)
        print(f"  {s.name}")
        print("=" * 72)
        print(_kurzfassung(bewertung, ta_max))
        print(f"  Detailbericht: {s / 'detailbericht.md'}")
        print(f"  Korrektur-PDF: {s / 'korrigiert.pdf'}")
        print()
        while True:
            choice = input("  [j] freigeben  [e] editieren  [v] verwerfen  "
                           "[s] sprachabzug  [n] nächster  [q] beenden: ").strip().lower()
            if choice == "j":
                freigeben(paket, s, lehrer)
                break
            if choice == "v":
                grund = input("    Grund: ").strip() or "(ohne Angabe)"
                verwerfen(paket, s, lehrer, grund)
                break
            if choice == "s":
                try:
                    n = int(input("    Sprachabzug (0/1/2): ").strip())
                except ValueError:
                    continue
                editieren(paket, s, {}, n, lehrer, grund="Sprachabzug gesetzt")
                continue
            if choice == "e":
                edits = _frage_edits(bewertung, ta_max)
                grund = input("    Begründung der Änderung: ").strip() or "(ohne Angabe)"
                editieren(paket, s, edits, None, lehrer, grund)
                break
            if choice == "n":
                print(f"  ⏭  {s.name} übersprungen.")
                break
            if choice == "q":
                return


def _frage_edits(bewertung: SchuelerBewertung,
                 ta_max: dict[str, float]) -> dict[str, dict[str, Any]]:
    """Sehr einfache Edit-Eingabe: TA-Nummer + neue I/II/III/Bemerkung."""
    edits: dict[str, dict[str, Any]] = {}
    print("    Eingabe pro Zeile: <TA>=<i>,<ii>,<iii>[/bemerkung]")
    print("    leere Zeile = fertig. Punkte werden auf Max gekappt.")
    while True:
        line = input("    edit> ").strip()
        if not line:
            break
        try:
            head, _, bem = line.partition("/")
            nr, _, vals = head.partition("=")
            nr = nr.strip()
            werte = [v.strip() for v in vals.split(",")]
            entry: dict[str, Any] = {}
            for key, v in zip(("i", "ii", "iii"), werte):
                if v != "":
                    entry[key] = float(v)
            if bem.strip():
                entry["bemerkung"] = bem.strip()
            edits[nr] = entry
        except Exception as ex:
            print(f"    (Eingabe ignoriert: {ex})")
    return edits


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--paket", type=Path, required=True)
    p.add_argument("--lehrer", default="unbekannt",
                   help="Name der Lehrkraft (im Audit-Log dokumentiert)")
    p.add_argument("--bulk-freigabe", action="store_true",
                   help="Alle Vorschläge ohne Rückfrage freigeben")
    p.add_argument("--status", action="store_true",
                   help="Übersicht anzeigen, kein Eingriff")
    args = p.parse_args(argv)

    paket = paket_laden(args.paket)

    if args.status:
        for s in sorted(paket.bewertungen_dir.glob("Schueler-*")):
            st = lese_status(s)
            print(f"  {s.name:15s}  {st.get('status', '?'):14s}  "
                  f"NP={st.get('notenpunkte', '?'):>3} ({st.get('note', '?')})  "
                  f"⚠={st.get('konfidenz_warnungen', '?')}")
        return 0

    if args.bulk_freigabe:
        n = 0
        for s in sorted(paket.bewertungen_dir.glob("Schueler-*")):
            if lese_status(s).get("status") in ("vorschlag", "in_bearbeitung"):
                freigeben(paket, s, args.lehrer)
                n += 1
        print(f"\n{n} Bewertung(en) freigegeben.")
        return 0

    interaktiv(paket, args.lehrer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
