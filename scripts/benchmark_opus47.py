#!/usr/bin/env python3
"""
Benchmark-Gutachten via Claude Opus 4.7 (Anthropic API).

Verwendet die Promptvorlage data/prompte/Prompt_Github.md und schickt
Schüler- und Lehrermaterial in einem einzigen Turn an Claude Opus 4.7.
Das Ergebnis wird als Markdown gespeichert – ein hochwertiger Referenzlauf
als Maßstab für die lokalen Modelle.

Verwendung:
  python scripts/benchmark_opus47.py <schuelermaterial.pdf> <lehrermaterial.pdf>
  python scripts/benchmark_opus47.py <schuelermaterial.pdf> <lehrermaterial.pdf> --ausgabe mein_gutachten.md

Voraussetzung:
  - ANTHROPIC_API_KEY als Umgebungsvariable oder in .env gesetzt
  - pip install anthropic pypdf
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# .env laden, falls vorhanden
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Projekt-Root zum Python-Pfad hinzufügen
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# Prompt-Template
_PROMPT_PFAD = _ROOT / "data" / "prompte" / "Prompt_Github.md"

# Modell
MODELL = "claude-opus-4-7"


def _lese_prompt_template() -> str:
    if not _PROMPT_PFAD.exists():
        raise FileNotFoundError(f"Prompt-Template nicht gefunden: {_PROMPT_PFAD}")
    text = _PROMPT_PFAD.read_text(encoding="utf-8")
    # Alles zwischen --- PROMPT START --- und --- PROMPT ENDE --- extrahieren
    start = text.find("--- PROMPT START ---")
    ende = text.find("--- PROMPT ENDE ---")
    if start == -1 or ende == -1:
        raise ValueError("Marker '--- PROMPT START ---' / '--- PROMPT ENDE ---' nicht gefunden.")
    return text[start + len("--- PROMPT START ---"):ende].strip()


def _extrahiere_pdf_text(pfad: str) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(pfad)
        seiten = [p.extract_text() or "" for p in reader.pages]
        return "\n\n".join(seiten)
    except Exception as e:
        raise RuntimeError(f"PDF-Extraktion fehlgeschlagen ({pfad}): {e}") from e


def _fuelle_prompt(template: str, sm_text: str, lm_text: str) -> str:
    sm_marker = "{ENTWEDER hier den Volltext einfügen ODER das PDF an die Anfrage anhängen}"
    lm_marker = "{ENTWEDER hier den Volltext einfügen ODER das PDF an die Anfrage anhängen}"
    # Erst SM, dann LM (beide haben denselben Platzhalter – nur einmalig ersetzen)
    prompt = template.replace(sm_marker, sm_text, 1)
    prompt = prompt.replace(lm_marker, lm_text, 1)
    return prompt


def _rufe_opus_auf(prompt: str, api_key: str) -> str:
    try:
        import anthropic
    except ImportError:
        print(
            "[FEHLER] Das Paket 'anthropic' ist nicht installiert.\n"
            "         Bitte ausführen: pip install anthropic",
            file=sys.stderr,
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print(f"  Sende Anfrage an {MODELL} …", flush=True)
    start = datetime.now()

    message = client.messages.create(
        model=MODELL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    dauer = (datetime.now() - start).total_seconds()
    print(f"  Antwort erhalten ({dauer:.1f} s, {message.usage.output_tokens} Output-Token).")

    return message.content[0].text


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gutachten-Benchmark via Claude Opus 4.7 (Anthropic API)"
    )
    parser.add_argument("schuelermaterial", help="Pfad zum Schülermaterial-PDF")
    parser.add_argument("lehrermaterial", help="Pfad zum Lehrermaterial-PDF")
    parser.add_argument(
        "--ausgabe", "-o",
        help="Ausgabedatei (Standard: data/auswertungen/Benchmark_Opus47_<datum>_<basis>.md)"
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print(
            "[FEHLER] ANTHROPIC_API_KEY nicht gesetzt.\n"
            "         Setze ihn in der .env-Datei oder als Umgebungsvariable.",
            file=sys.stderr,
        )
        sys.exit(1)

    sm_pfad = args.schuelermaterial
    lm_pfad = args.lehrermaterial

    if not Path(sm_pfad).exists():
        print(f"[FEHLER] Schülermaterial nicht gefunden: {sm_pfad}", file=sys.stderr)
        sys.exit(1)
    if not Path(lm_pfad).exists():
        print(f"[FEHLER] Lehrermaterial nicht gefunden: {lm_pfad}", file=sys.stderr)
        sys.exit(1)

    print("=" * 72)
    print(f"Gutachten-Benchmark  –  Modell: {MODELL}")
    print("=" * 72)
    print(f"  Schülermaterial : {sm_pfad}")
    print(f"  Lehrermaterial  : {lm_pfad}")

    print("\n[1/3] Lese Prompt-Template …")
    template = _lese_prompt_template()

    print("[2/3] Extrahiere PDF-Texte …")
    sm_text = _extrahiere_pdf_text(sm_pfad)
    lm_text = _extrahiere_pdf_text(lm_pfad)
    print(f"      SM: {len(sm_text):,} Zeichen  |  LM: {len(lm_text):,} Zeichen")

    prompt = _fuelle_prompt(template, sm_text, lm_text)

    print(f"[3/3] KI-Anfrage …")
    gutachten_md = _rufe_opus_auf(prompt, api_key)

    # Ausgabepfad bestimmen
    if args.ausgabe:
        ausgabe_pfad = Path(args.ausgabe)
    else:
        basis = Path(sm_pfad).stem
        datum = datetime.now().strftime("%Y%m%d_%H%M")
        ausgabe_pfad = _ROOT / "data" / "auswertungen" / f"Benchmark_Opus47_{datum}_{basis}.md"

    ausgabe_pfad.parent.mkdir(parents=True, exist_ok=True)

    kopf = (
        f"<!-- Benchmark: {MODELL}  |  "
        f"SM: {Path(sm_pfad).name}  |  "
        f"LM: {Path(lm_pfad).name}  |  "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')} -->\n\n"
    )
    ausgabe_pfad.write_text(kopf + gutachten_md, encoding="utf-8")

    print(f"\nGutachten gespeichert: {ausgabe_pfad}")
    print("=" * 72)


if __name__ == "__main__":
    main()
