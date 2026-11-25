#!/usr/bin/env python3
"""
Klausur-Paket: Vorbereitungs-Phase des Gutachtensystems.

Ein Paket konserviert alles, was für eine reproduzierbare, rechtssichere
Bewertung gebraucht wird:
  - Quelldateien (Lehrermaterial-PDF, Schülermaterial-PDF, Bewertungsvorlage-XLSX)
    + SHA-256-Hashes (für Audit: niemand kann nachträglich die Grundlage ändern)
  - Aufgabenstruktur (Teilaufgaben mit max. Punkten pro AFB)
  - Erwartungshorizont pro Teilaufgabe
  - Fixierte KI-Konfiguration (Modell, Provider, Parameter)
  - AFB-Texte und Standardsätze (aus der Bewertungsvorlage)

Nutzung:
  python klausur_paket.py erstellen "BGI3_2025_VorschlagA" \\
      --lehrer Material/...lehrermaterial.pdf \\
      --schueler Material/...schuelermaterial_270min.pdf \\
      --vorlage Material/BGI3_Abiturbewertung_2025\\ Vorschlag\\ A.xlsx
  python klausur_paket.py info Klausurpakete/BGI3_2025_VorschlagA
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.core.audit import AuditLog, sha256_datei

PROJEKT_WURZEL = Path(__file__).resolve().parent.parent.parent
PAKETE_WURZEL = PROJEKT_WURZEL / "Klausurpakete"
PAKET_VERSION = "1.0"


# Datenmodelle (sind kompatibel zur bestehenden klausur_schueler_bewerten-API)
@dataclass
class TeilaufgabeSpec:
    nummer: str
    aufgabe: int
    max_punkte_i: float
    max_punkte_ii: float
    max_punkte_iii: float
    zeile_in_vorlage: int
    erwartungstext: str = ""


@dataclass
class KIParameter:
    """Fixierte Modellparameter für Reproduzierbarkeit."""
    modell: str = ""
    provider: str = "lokal"
    base_url: str = "http://localhost:1234/v1"
    temperature: float = 0.0
    top_p: float = 1.0
    seed: int = 42
    vision_modell: str = ""
    vision_dpi: int = 200


@dataclass
class Paket:
    name: str
    version: str = PAKET_VERSION
    erzeugt_am: str = ""
    paket_dir: Path = field(default_factory=lambda: Path("."))
    quellen: dict[str, dict[str, str]] = field(default_factory=dict)
    teilaufgaben: list[TeilaufgabeSpec] = field(default_factory=list)
    ki: KIParameter = field(default_factory=KIParameter)
    afb_texte: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    standardsaetze: list[dict[str, Any]] = field(default_factory=list)
    notenschluessel: list[dict[str, Any]] = field(default_factory=list)
    pseudonyme: dict[str, str] = field(default_factory=dict)  # pseudonym → klarname

    @property
    def quellen_dir(self) -> Path:
        return self.paket_dir / "quellen"

    @property
    def bewertungen_dir(self) -> Path:
        return self.paket_dir / "bewertungen"

    @property
    def lehrer_pdf(self) -> Path | None:
        e = self.quellen.get("lehrermaterial")
        return self.quellen_dir / e["dateiname"] if e else None

    @property
    def schueler_pdf(self) -> Path | None:
        e = self.quellen.get("schuelermaterial")
        return self.quellen_dir / e["dateiname"] if e else None

    @property
    def vorlage_xlsx(self) -> Path | None:
        e = self.quellen.get("bewertungsvorlage")
        return self.quellen_dir / e["dateiname"] if e else None


# ---------------------------------------------------------------------------
# Erstellen
# ---------------------------------------------------------------------------

def paket_erstellen(
    name: str,
    lehrer_pdf: Path,
    schueler_pdf: Path,
    vorlage_xlsx: Path,
    ausgabe_wurzel: Path = PAKETE_WURZEL,
    ki_modell: str = "",
    ki_provider: str = "lokal",
    ki_vision_modell: str = "",
) -> Paket:
    """Erzeugt ein neues Klausur-Paket auf der Platte."""
    # Importe spät, um zirkuläre Importe zu vermeiden
    from src.bewertung.schueler import (
        lade_bewertungsschema, lade_erwartungshorizont,
        STANDARDSAETZE, NOTENSCHLUESSEL,
    )

    paket_dir = ausgabe_wurzel / name
    quellen_dir = paket_dir / "quellen"
    bewertungen_dir = paket_dir / "bewertungen"
    for d in (paket_dir, quellen_dir, bewertungen_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Quelldateien kopieren + hashen
    quellen: dict[str, dict[str, str]] = {}
    for rolle, src in [
        ("lehrermaterial", lehrer_pdf),
        ("schuelermaterial", schueler_pdf),
        ("bewertungsvorlage", vorlage_xlsx),
    ]:
        if not src.exists():
            raise FileNotFoundError(f"{rolle}: {src}")
        ziel = quellen_dir / src.name
        shutil.copy2(src, ziel)
        quellen[rolle] = {
            "dateiname": src.name,
            "sha256": sha256_datei(ziel),
            "bytes": str(ziel.stat().st_size),
        }

    # Aufgabenstruktur + Erwartungshorizont
    tas_raw = lade_bewertungsschema(quellen_dir / vorlage_xlsx.name)
    eh = lade_erwartungshorizont(quellen_dir / lehrer_pdf.name)
    tas: list[TeilaufgabeSpec] = []
    for ta in tas_raw:
        tas.append(TeilaufgabeSpec(
            nummer=ta.nummer, aufgabe=ta.aufgabe,
            max_punkte_i=ta.max_punkte_i,
            max_punkte_ii=ta.max_punkte_ii,
            max_punkte_iii=ta.max_punkte_iii,
            zeile_in_vorlage=ta.zeile_in_vorlage,
            erwartungstext=eh.get(ta.nummer, ""),
        ))

    # AFB-Texte aus Vorlage extrahieren (Sheets „Anforderungsbereich I/II/III")
    afb_texte = _lese_afb_texte(quellen_dir / vorlage_xlsx.name)

    # KI-Modell: wenn nicht angegeben, derzeit geladenes Modell verwenden
    if not ki_modell:
        ki_modell = _aktuelles_lmstudio_modell() or "auto"
    ki = KIParameter(
        modell=ki_modell,
        provider=ki_provider,
        vision_modell=ki_vision_modell or ki_modell,
    )

    paket = Paket(
        name=name,
        erzeugt_am=time.strftime("%Y-%m-%dT%H:%M:%S"),
        paket_dir=paket_dir,
        quellen=quellen,
        teilaufgaben=tas,
        ki=ki,
        afb_texte=afb_texte,
        standardsaetze=[{"prozent": p, "satz": s} for p, s in STANDARDSAETZE],
        notenschluessel=[
            {"prozent_min": p, "punkte": pkt, "kennung": k, "text": t}
            for p, pkt, k, t in NOTENSCHLUESSEL
        ],
    )

    _schreibe_paket_json(paket)

    # Audit-Log starten
    log = AuditLog(paket_dir / "audit_log.jsonl")
    log.append(
        schritt="paket_erstellt",
        pseudonym="global",
        modell=ki.modell,
        parameter=asdict(ki),
        payload={
            "name": name,
            "quellen": quellen,
            "anzahl_teilaufgaben": len(tas),
            "max_punkte_gesamt": sum(t.max_punkte_i + t.max_punkte_ii + t.max_punkte_iii
                                     for t in tas),
            "erwartungshorizont_abgedeckt": sum(1 for t in tas if t.erwartungstext),
        },
    )

    _schreibe_readme(paket)
    return paket


def _aktuelles_lmstudio_modell() -> str:
    """Liest das aktuell geladene Modell von LM Studio (ohne Fehler hochzuwerfen)."""
    try:
        from openai import OpenAI
        client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")
        ms = client.models.list()
        if ms.data:
            return ms.data[0].id
    except Exception:
        pass
    return ""


def _lese_afb_texte(vorlage: Path) -> dict[str, list[dict[str, Any]]]:
    """Liest die AFB I/II/III-Standardtexte aus den entsprechenden Sheets."""
    import openpyxl
    import re
    wb = openpyxl.load_workbook(vorlage, data_only=True)
    out: dict[str, list[dict[str, Any]]] = {}
    for sheet_name, key in [
        ("Anforderungsbereich I", "i"),
        ("Anforderungsbereich II", "ii"),
        ("Anforderungsbereich III", "iii"),
    ]:
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        rows = []
        for r in ws.iter_rows(min_row=2, values_only=True):
            if not r or r[0] is None:
                continue
            prozent_text = str(r[0])
            schwelle = r[1]
            text = r[2] or ""
            # Untergrenze aus „X % bis …" extrahieren
            m = re.match(r"\s*(\d+(?:[.,]\d+)?)\s*%", prozent_text)
            untergrenze = float(m.group(1)) if m else 0.0
            rows.append({
                "prozent_min": untergrenze,
                "faktor": float(schwelle) if isinstance(schwelle, (int, float)) else 0.0,
                "text": str(text).strip(),
            })
        out[key] = rows
    return out


def _schreibe_paket_json(paket: Paket) -> None:
    daten = {
        "name": paket.name,
        "version": paket.version,
        "erzeugt_am": paket.erzeugt_am,
        "quellen": paket.quellen,
        "ki": asdict(paket.ki),
        "teilaufgaben": [asdict(t) for t in paket.teilaufgaben],
        "afb_texte": paket.afb_texte,
        "standardsaetze": paket.standardsaetze,
        "notenschluessel": paket.notenschluessel,
    }
    (paket.paket_dir / "paket.json").write_text(
        json.dumps(daten, indent=2, ensure_ascii=False), encoding="utf-8")
    # Pseudonyme-Datei (initial leer); enthält den Mapping pseudonym→klarname.
    pseu = paket.paket_dir / "pseudonyme.json"
    if not pseu.exists():
        pseu.write_text(json.dumps({}, indent=2, ensure_ascii=False), encoding="utf-8")


def _schreibe_readme(paket: Paket) -> None:
    max_ges = sum(t.max_punkte_i + t.max_punkte_ii + t.max_punkte_iii
                  for t in paket.teilaufgaben)
    eh_voll = sum(1 for t in paket.teilaufgaben if t.erwartungstext)
    lines = [
        f"# Klausurpaket: {paket.name}",
        "",
        f"Erzeugt am: {paket.erzeugt_am}",
        "",
        "## Quellen (immutable – SHA-256 in `paket.json`)",
        "",
    ]
    for rolle, e in paket.quellen.items():
        lines.append(f"- **{rolle}**: `{e['dateiname']}`  ·  "
                     f"{int(e['bytes']):,} B  ·  `{e['sha256'][:16]}…`")
    lines += [
        "",
        f"## Aufgabenstruktur: {len(paket.teilaufgaben)} Teilaufgaben "
        f"(max. {max_ges:.0f} Punkte)",
        "",
        f"- Erwartungshorizont vorhanden für: **{eh_voll}/{len(paket.teilaufgaben)}** Teilaufgaben",
        "",
        "## Fixierte KI-Konfiguration",
        "",
        f"- Modell: `{paket.ki.modell}`",
        f"- Vision-Modell: `{paket.ki.vision_modell}`",
        f"- Provider: `{paket.ki.provider}` ({paket.ki.base_url})",
        f"- Temperature: {paket.ki.temperature}  ·  Seed: {paket.ki.seed}",
        "",
        "## Bewertung starten",
        "",
        "```",
        f"python klausur_schueler_bewerten.py --paket Klausurpakete/{paket.name} --scans ORDNER",
        "```",
        "",
        "## Freigabe durch Lehrkraft",
        "",
        "```",
        f"python klausur_freigeben.py --paket Klausurpakete/{paket.name}",
        "```",
        "",
        "## Audit",
        "",
        "Alle KI-Aufrufe und Lehrer-Edits werden in `audit_log.jsonl` mit",
        "verketteten SHA-256-Hashes geloggt. Verifikation:",
        "",
        "```",
        f"python klausur_audit.py verify Klausurpakete/{paket.name}/audit_log.jsonl",
        "```",
    ]
    (paket.paket_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Laden
# ---------------------------------------------------------------------------

def paket_laden(paket_dir: Path) -> Paket:
    """Lädt ein bestehendes Paket aus paket.json + pseudonyme.json."""
    paket_dir = Path(paket_dir)
    p = paket_dir / "paket.json"
    if not p.exists():
        raise FileNotFoundError(f"Kein Paket in {paket_dir} (paket.json fehlt)")
    data = json.loads(p.read_text(encoding="utf-8"))

    ki = KIParameter(**data.get("ki", {}))
    tas = [TeilaufgabeSpec(**t) for t in data.get("teilaufgaben", [])]
    pseu_p = paket_dir / "pseudonyme.json"
    pseudonyme = json.loads(pseu_p.read_text(encoding="utf-8")) if pseu_p.exists() else {}

    return Paket(
        name=data["name"],
        version=data.get("version", PAKET_VERSION),
        erzeugt_am=data.get("erzeugt_am", ""),
        paket_dir=paket_dir,
        quellen=data.get("quellen", {}),
        teilaufgaben=tas,
        ki=ki,
        afb_texte=data.get("afb_texte", {}),
        standardsaetze=data.get("standardsaetze", []),
        notenschluessel=data.get("notenschluessel", []),
        pseudonyme=pseudonyme,
    )


# ---------------------------------------------------------------------------
# Pseudonymisierung
# ---------------------------------------------------------------------------

def pseudonym_vergeben(paket: Paket, klarname: str) -> str:
    """Gibt ein bestehendes oder neues Pseudonym für den Klarnamen zurück.

    Speichert die Zuordnung sofort in pseudonyme.json. Pseudonyme sind
    durchnummeriert: „Schueler-001", „Schueler-002", …
    """
    # Schon vorhanden?
    for pseu, klar in paket.pseudonyme.items():
        if klar.strip().lower() == klarname.strip().lower():
            return pseu
    n = len(paket.pseudonyme) + 1
    pseu = f"Schueler-{n:03d}"
    paket.pseudonyme[pseu] = klarname
    (paket.paket_dir / "pseudonyme.json").write_text(
        json.dumps(paket.pseudonyme, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return pseu


def klarname(paket: Paket, pseudonym: str) -> str:
    return paket.pseudonyme.get(pseudonym, pseudonym)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("erstellen", help="Neues Klausur-Paket erzeugen")
    pe.add_argument("name", help="Paket-Name (z.B. BGI3_2025_VorschlagA)")
    pe.add_argument("--lehrer", type=Path, required=True, help="Lehrermaterial-PDF")
    pe.add_argument("--schueler", type=Path, required=True, help="Schülermaterial-PDF")
    pe.add_argument("--vorlage", type=Path, required=True, help="Bewertungsvorlage-XLSX")
    pe.add_argument("--ausgabe", type=Path, default=PAKETE_WURZEL,
                    help=f"Wurzel-Verzeichnis (Standard: {PAKETE_WURZEL})")
    pe.add_argument("--modell", default="", help="KI-Modell fixieren (sonst LM-Studio-aktuelles)")
    pe.add_argument("--provider", default="lokal", choices=["lokal", "hetzner", "gwdg"])
    pe.add_argument("--vision-modell", default="", help="Separates Vision-Modell (sonst = --modell)")

    pi = sub.add_parser("info", help="Paket-Übersicht ausgeben")
    pi.add_argument("paket_dir", type=Path)

    pv = sub.add_parser("verify", help="Audit-Kette des Pakets prüfen")
    pv.add_argument("paket_dir", type=Path)

    args = p.parse_args(argv)

    if args.cmd == "erstellen":
        paket = paket_erstellen(
            name=args.name,
            lehrer_pdf=args.lehrer,
            schueler_pdf=args.schueler,
            vorlage_xlsx=args.vorlage,
            ausgabe_wurzel=args.ausgabe,
            ki_modell=args.modell,
            ki_provider=args.provider,
            ki_vision_modell=args.vision_modell,
        )
        print(f"\n✓ Paket erstellt: {paket.paket_dir}")
        print(f"  Teilaufgaben: {len(paket.teilaufgaben)}")
        print(f"  Modell:       {paket.ki.modell}")
        return 0

    if args.cmd == "info":
        paket = paket_laden(args.paket_dir)
        print(f"Paket: {paket.name} (v{paket.version})")
        print(f"  Erzeugt: {paket.erzeugt_am}")
        print(f"  Quellen: {len(paket.quellen)} Dateien")
        for rolle, e in paket.quellen.items():
            print(f"    {rolle}: {e['dateiname']}  ({e['sha256'][:16]}…)")
        print(f"  Teilaufgaben: {len(paket.teilaufgaben)}")
        print(f"  Modell:       {paket.ki.modell} ({paket.ki.provider})")
        print(f"  Pseudonyme:   {len(paket.pseudonyme)}")
        return 0

    if args.cmd == "verify":
        log = AuditLog(args.paket_dir / "audit_log.jsonl")
        ok, msg = log.verify_chain()
        print(f"Audit-Kette: {'OK ✓' if ok else 'GEBROCHEN ✗'} – {msg}")
        return 0 if ok else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
