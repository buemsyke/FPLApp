#!/usr/bin/env python3
"""
Append-only Audit-Log für die Bewertungspipeline.

Schreibt JSONL-Zeilen mit verketteten SHA-256-Hashes („tamper-evident").
Jede Zeile enthält:
  ts            – ISO-Zeitstempel
  schritt       – Typ der Aktion (z.B. „ki_aufruf", „lehrer_edit")
  pseudonym     – Pseudonym des Schülers (oder „global")
  modell        – verwendeter Modellname
  parameter     – Dict mit KI-Parametern (T, top_p, seed, …)
  input_sha256  – Hash über Prompt/Input
  output_sha256 – Hash über Antwort/Output
  payload       – beliebige weitere strukturierte Daten
  parent_sha256 – Hash der vorhergehenden Logzeile (Verkettung)
  this_sha256   – Hash dieser Zeile (ohne dieses Feld)

`verify_chain()` rekonstruiert die Kette und meldet Bruch, falls eine
Zeile manipuliert wurde.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64  # Start-Wert der Hash-Kette


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_datei(pfad: Path) -> str:
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class AuditLog:
    """Append-only Log mit verketteten SHA-256."""

    def __init__(self, pfad: Path):
        self.pfad = Path(pfad)
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        self._letzter_hash = self._lese_letzten_hash()

    def _lese_letzten_hash(self) -> str:
        if not self.pfad.exists() or self.pfad.stat().st_size == 0:
            return GENESIS_HASH
        with open(self.pfad, "rb") as f:
            # Letzte Zeile lesen (einfacher Ansatz – Audit-Logs bleiben überschaubar)
            zeilen = f.read().decode("utf-8").splitlines()
        for zeile in reversed(zeilen):
            zeile = zeile.strip()
            if not zeile:
                continue
            try:
                eintrag = json.loads(zeile)
            except json.JSONDecodeError:
                continue
            return eintrag.get("this_sha256", GENESIS_HASH)
        return GENESIS_HASH

    def append(
        self,
        schritt: str,
        pseudonym: str = "global",
        modell: str = "",
        parameter: dict[str, Any] | None = None,
        input_text: str | None = None,
        output_text: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Hängt einen Eintrag an und gibt den Hash dieses Eintrags zurück."""
        eintrag: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime("%Y-%m-%dT%H:%M:%S"),
            "schritt": schritt,
            "pseudonym": pseudonym,
            "modell": modell,
            "parameter": parameter or {},
            "input_sha256": sha256_text(input_text) if input_text is not None else None,
            "output_sha256": sha256_text(output_text) if output_text is not None else None,
            "payload": payload or {},
            "parent_sha256": self._letzter_hash,
        }
        kanonisch = json.dumps(eintrag, sort_keys=True, ensure_ascii=False)
        this_hash = sha256_text(kanonisch)
        eintrag["this_sha256"] = this_hash
        with open(self.pfad, "a", encoding="utf-8") as f:
            f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
        self._letzter_hash = this_hash
        return this_hash

    def lese_alle(self) -> list[dict[str, Any]]:
        if not self.pfad.exists():
            return []
        out = []
        with open(self.pfad, encoding="utf-8") as f:
            for zeile in f:
                zeile = zeile.strip()
                if zeile:
                    out.append(json.loads(zeile))
        return out

    def verify_chain(self) -> tuple[bool, str]:
        """Prüft die Hash-Kette. Liefert (ok, fehlermeldung)."""
        eintraege = self.lese_alle()
        prev = GENESIS_HASH
        for i, e in enumerate(eintraege):
            erwartet_parent = prev
            if e.get("parent_sha256") != erwartet_parent:
                return False, (
                    f"Zeile {i + 1}: parent_sha256 stimmt nicht "
                    f"(erwartet {erwartet_parent[:12]}…, war {e.get('parent_sha256', '')[:12]}…)"
                )
            this = e.pop("this_sha256", None)
            kanonisch = json.dumps(e, sort_keys=True, ensure_ascii=False)
            errechnet = sha256_text(kanonisch)
            if this != errechnet:
                return False, f"Zeile {i + 1}: this_sha256 manipuliert"
            prev = this
        return True, "OK"
