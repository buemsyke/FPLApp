#!/usr/bin/env python3
"""
Baut den Skill abiturvorschlag-begutachten aus den Projektquellen.

  python3 scripts/skill_bauen.py               # → dist/abiturvorschlag-begutachten.skill
  python3 scripts/skill_bauen.py --installieren # zusätzlich nach ~/.claude/skills (Claude Code)

Quelle der Wahrheit bleibt das Projekt: skill/abiturvorschlag-begutachten (SKILL.md,
Skript, Referenz) + src/ (Prüfmodule) + scripts/umgebung.sh + Gutachtenvorlage.
Im Skill-Paket nie von Hand ändern – nach jeder Änderung an src/ neu bauen.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PROJEKT = Path(__file__).resolve().parent.parent
NAME = "abiturvorschlag-begutachten"
QUELLE = PROJEKT / "skill" / NAME
DIST = PROJEKT / "dist"
VORLAGE = PROJEKT / "data" / "material" / "bg-abi_te_gutachten 2026.docx"

# Prüfmodule, die der Skill braucht (ohne openai/eduwerkzeuge/streamlit)
MODULE = [
    "src/__init__.py",
    "src/analysen/__init__.py",
    "src/analysen/rrl.py",
    "src/bewertung/__init__.py",
    "src/bewertung/regelbasiert.py",
    "src/bewertung/hinweisliste.py",
    "src/bewertung/ki_pruefanweisungen.py",
    "src/bewertung/ki_bericht.py",
    "src/bewertung/loesbarkeit.py",
]


def pruefe_frontmatter(skill_md: Path) -> None:
    text = skill_md.read_text(encoding="utf-8")
    m = re.search(r'^description:\s*"(.*?)"\s*$', text, re.MULTILINE)
    if not m:
        sys.exit("SKILL.md: description fehlt oder ist nicht in Anführungszeichen.")
    beschreibung = m.group(1)
    if len(beschreibung) > 1024:
        sys.exit(f"SKILL.md: description hat {len(beschreibung)} Zeichen (max. 1024).")
    if "<" in beschreibung or ">" in beschreibung:
        sys.exit("SKILL.md: description enthält spitze Klammern.")
    if not re.search(rf"^name:\s*{NAME}\s*$", text, re.MULTILINE):
        sys.exit(f"SKILL.md: name muss {NAME} sein.")


def baue() -> Path:
    pruefe_frontmatter(QUELLE / "SKILL.md")
    if not VORLAGE.is_file():
        sys.exit(f"Gutachtenvorlage fehlt: {VORLAGE}")
    ziel = DIST / NAME
    if ziel.exists():
        shutil.rmtree(ziel)
    shutil.copytree(QUELLE, ziel, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for rel in MODULE:
        (ziel / "scripts" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJEKT / rel, ziel / "scripts" / rel)
    shutil.copy2(PROJEKT / "scripts" / "umgebung.sh", ziel / "scripts" / "umgebung.sh")
    (ziel / "assets").mkdir(exist_ok=True)
    shutil.copy2(VORLAGE, ziel / "assets" / "gutachtenvorlage.docx")
    for sh in ("einrichten.sh", "umgebung.sh", "begutachten.py"):
        (ziel / "scripts" / sh).chmod(0o755)

    # Rauchtest: Paket importierbar ohne openai/eduwerkzeuge/streamlit
    test = (
        "import sys, importlib.abc\n"
        "class S(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, n, p, t=None):\n"
        "        if n.split('.')[0] in ('openai','eduwerkzeuge','streamlit','dotenv'):\n"
        "            raise ImportError(n)\n"
        "sys.meta_path.insert(0, S())\n"
        f"sys.path.insert(0, {str(ziel / 'scripts')!r})\n"
        "import src.bewertung.regelbasiert, src.bewertung.hinweisliste, "
        "src.bewertung.ki_pruefanweisungen, src.bewertung.ki_bericht, src.bewertung.loesbarkeit\n"
    )
    r = subprocess.run([sys.executable, "-c", test], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("Rauchtest fehlgeschlagen:\n" + r.stderr)

    paket = DIST / f"{NAME}.skill"
    with zipfile.ZipFile(paket, "w", zipfile.ZIP_DEFLATED) as z:
        for datei in sorted(ziel.rglob("*")):
            if datei.is_file() and "__pycache__" not in datei.parts:
                info = zipfile.ZipInfo.from_file(datei, f"{NAME}/{datei.relative_to(ziel)}")
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, datei.read_bytes())   # Rechte (x-Bit) bleiben erhalten
    return paket


def installiere(paket_ordner: Path) -> Path:
    ziel = Path.home() / ".claude" / "skills" / NAME
    if ziel.exists():
        shutil.rmtree(ziel)
    shutil.copytree(paket_ordner, ziel)
    return ziel


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--installieren", action="store_true",
                    help="nach ~/.claude/skills kopieren (Claude Code, nur dieser Benutzer)")
    args = ap.parse_args()
    paket = baue()
    print(f"Skill gebaut: {paket} ({paket.stat().st_size // 1024} KB)")
    if args.installieren:
        print(f"Installiert:  {installiere(DIST / NAME)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
