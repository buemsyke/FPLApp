#!/usr/bin/env python3
"""
begutachten.py – Vorprüfung eines Abiturvorschlags (BG Technik, Schwerpunkt
Informationstechnik) für den Skill abiturvorschlag-begutachten.

Dieselbe Prüfung wie die App GutachtenAbiturklausur – nur urteilt in den
Stufen 2 (KI-Kriterien) und 3 (Lösbarkeit/Richtigkeit) Claude statt eines
lokalen Modells. Regelprüfung, Prüfanweisungen, Gutachten-Raster,
Hinweisliste und Berichte kommen aus denselben Modulen (scripts/src).

Aufruf:
  python3 begutachten.py umgebung
  python3 begutachten.py vorbereiten SM.pdf LM.pdf [--ausgabe ORDNER]
  python3 begutachten.py abschliessen ORDNER [--modell Claude] [--unvollstaendig]

vorbereiten  → Gutachten-Raster (DOCX), Rückmeldung (XLSX), Texte, Prüfauftrag,
               leere urteile.json
abschliessen → prüft urteile.json (Werte, Konfidenz, Zitate) und schreibt
               Hinweisliste, KI-Prüfbericht, Lösbarkeitsbericht, Bericht.md
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
SKILL = HIER.parent
VERSION = "1.0"


# ---------------------------------------------------------------------------
# Laufzeitumgebung: fehlen Pakete, die Umgebung aus umgebung.sh verwenden
# ---------------------------------------------------------------------------

def _umgebungs_pythons() -> list[Path]:
    basen = []
    if os.environ.get("GUTACHTEN_UMGEBUNG"):
        basen.append(Path(os.environ["GUTACHTEN_UMGEBUNG"]))
    basen.append(Path.home() / "Library/Application Support/GutachtenAbiturklausur")
    basen.append(Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
                 / "gutachten-abiturklausur")
    return [b / "umgebung" / "bin" / "python" for b in basen]


def _pakete_fehlen() -> list[str]:
    import importlib.util
    if sys.version_info < (3, 10):
        return [f"Python ≥ 3.10 (vorhanden: {sys.version.split()[0]})"]
    return [m for m in ("docx", "openpyxl", "pypdf")
            if importlib.util.find_spec(m) is None]


def _sichere_umgebung() -> None:
    fehlend = _pakete_fehlen()
    if fehlend and not os.environ.get("GUTACHTEN_NEUSTART"):
        for py in _umgebungs_pythons():
            if py.is_file() and Path(sys.executable).resolve() != py.resolve():
                os.environ["GUTACHTEN_NEUSTART"] = "1"
                os.execv(str(py), [str(py), str(Path(__file__).resolve()), *sys.argv[1:]])
    if fehlend:
        print("FEHLER: Es fehlen " + ", ".join(fehlend) + ".", file=sys.stderr)
        print("Einrichten ohne Administratorrechte (macOS/Linux, einmalig):\n"
              f"  bash \"{HIER / 'einrichten.sh'}\"\n"
              "oder in einer Umgebung mit pip:\n"
              "  pip install python-docx openpyxl pypdf", file=sys.stderr)
        sys.exit(3)
    # pdftotext der eingerichteten Umgebung bevorzugen
    bin_dir = Path(sys.executable).parent
    if (bin_dir / "pdftotext").exists():
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


def _finde_quelle() -> Path:
    """scripts/src im Skill-Paket, sonst Projektordner (Entwicklung)."""
    for kandidat in (HIER, SKILL.parent.parent):
        if (kandidat / "src" / "bewertung" / "regelbasiert.py").is_file():
            return kandidat
    sys.exit("FEHLER: Prüfmodule (src/bewertung) nicht gefunden.")


def _finde_vorlage() -> Path | None:
    for kandidat in (SKILL / "assets" / "gutachtenvorlage.docx",
                     SKILL.parent.parent / "data" / "material" / "bg-abi_te_gutachten 2026.docx"):
        if kandidat.is_file():
            return kandidat
    return None


_sichere_umgebung()
sys.path.insert(0, str(_finde_quelle()))

# ruff: noqa: E402 – Importe erst nach der Umgebungsprüfung
import argparse
import contextlib
import datetime
import hashlib
import io
import json
import re
import shutil

from src.analysen.rrl import IT_RRL_UEBERGEORDNETE_KOMPETENZEN, kompakter_rrl_block
from src.bewertung.hinweisliste import (
    erkenne_vorschlag, hinweisblock_fuer_vorschlag, schreibe_hinweisliste, zaehle,
)
from src.bewertung.ki_bericht import erstelle_kombinierte_liste, schreibe_ki_bericht_xlsx
from src.bewertung.ki_pruefanweisungen import (
    KI_NICHT_PRUEFBAR, KI_PRUEF_PROMPTS, KONFIDENZ_SCHWELLE, SYSTEM_PROMPT,
    KIPruefErgebnis, _baue_template_vars, _extrahiere_ewh_zeilen,
    _formatiere_ewh_vorverarbeitung,
)
from src.bewertung.loesbarkeit import (
    IT_LERNGEBIET_HINWEISE, MAX_AUFGABE_TEXT, MAX_LOESUNG_TEXT, SYSTEM_PROMPT_LSG,
    LoesbarkeitErgebnis, _validitaetsfilter, _vorbedingung, extrahiere_loesungstext,
    extrahiere_materialhinweise, extrahiere_teilaufgabentext, klassifiziere_lerngebiet,
    schreibe_loesbarkeitsbericht_xlsx,
)
from src.bewertung.regelbasiert import (
    OPERATOREN, begutachte, erstelle_gutachten_docx, erstelle_rueckmeldung_xlsx,
    extract_pages_pdf, extract_text, extract_text_pdf, parse_aufgaben,
    parse_erweiterte_operatoren,
)

KI_WERTE = {"beanstandung", "keine_beanstandung", "nicht_pruefbar"}
LSG_WERTE = {"ja", "nein", "unklar", "nicht_pruefbar"}
SYMBOL_REGEL = {True: "✔", False: "✘", None: "?"}
AUSZUG_AUFGABE = 2500   # Zeichen im Prüfauftrag (Volltext liegt in text/)
AUSZUG_LOESUNG = 5000


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

def _still(fn, *args, **kwargs):
    """Ruft fn ohne Konsolenausgabe auf (Ausgabe geht ins Protokoll)."""
    puffer = io.StringIO()
    with contextlib.redirect_stdout(puffer):
        ergebnis = fn(*args, **kwargs)
    return ergebnis, puffer.getvalue()


def _sha256(pfad: Path) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def _seiten(pfad: Path) -> list[str]:
    if pfad.suffix.lower() == ".pdf":
        return extract_pages_pdf(str(pfad)) or [extract_text(str(pfad))]
    return [extract_text(str(pfad))]


def _mit_seitenmarken(seiten: list[str]) -> str:
    return "\n".join(f"\n=== Seite {i} ===\n{s.strip()}" for i, s in enumerate(seiten, 1))


def _lehrertext_wie_app(lm: Path) -> tuple[str, str, str]:
    """(normal, layout, kombiniert) – kombiniert wie in fuehre_ki_pruefung_durch."""
    normal = extract_text(str(lm))
    layout = extract_text_pdf(str(lm), layout=True) if lm.suffix.lower() == ".pdf" else ""
    if layout and layout != normal:
        kombi = normal + "\n\n=== LEHRERMATERIAL (Layout-Extraktion für Tabellen) ===\n" + layout
    else:
        kombi = normal
    return normal, layout, kombi


def _kurz(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " …"


# --- Zitatprüfung -----------------------------------------------------------

_ANF = re.compile(r"[„“”\"»«‚‘’']")
_ZITAT = re.compile(r"[„\"“»‚']([^„\"“”»«‚‘’']{4,})[“\"”«‘’']")


def _norm(text: str) -> str:
    t = (text or "").replace("\xad", "").replace("ﬁ", "fi").replace("ﬂ", "fl")
    t = _ANF.sub("", t)
    t = re.sub(r"[‐‑‒–—−]", "-", t)
    t = re.sub(r"(\w)-\s+(\w)", r"\1\2", t)        # Silbentrennung am Zeilenende
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def _zitat_belegt(fundstelle: str, korpus: str) -> bool:
    """True, wenn ein wörtliches Zitat der Fundstelle im Material steht.
    Zitate stehen in Anführungszeichen; Auslassungen mit … sind erlaubt."""
    teile = _ZITAT.findall(fundstelle) or [fundstelle]
    for zitat in teile:
        segmente = [s for s in re.split(r"\s*(?:\[…\]|\[\.\.\.\]|…|\.\.\.)\s*", zitat)
                    if len(_norm(s)) >= 4]
        if segmente and all(_norm(s) in korpus for s in segmente):
            return True
    return False


# ---------------------------------------------------------------------------
# umgebung
# ---------------------------------------------------------------------------

def befehl_umgebung(_args) -> int:
    import docx, openpyxl, pypdf  # noqa: F401
    print(f"Skill-Skript:  {VERSION}")
    print(f"Python:        {sys.version.split()[0]} ({sys.executable})")
    print(f"python-docx:   {getattr(docx, '__version__', 'vorhanden')}")
    print(f"openpyxl:      {openpyxl.__version__}")
    print(f"pypdf:         {pypdf.__version__}")
    pdftotext = shutil.which("pdftotext")
    print(f"pdftotext:     {pdftotext or 'FEHLT – Regelprüfung eingeschränkt (z. B. 4.7)'}")
    vorlage = _finde_vorlage()
    print(f"Vorlage:       {vorlage or 'FEHLT – kein Gutachten-Raster'}")
    print(f"Prüfmodule:    {_finde_quelle() / 'src'}")
    return 0 if pdftotext and vorlage else 1


# ---------------------------------------------------------------------------
# vorbereiten
# ---------------------------------------------------------------------------

def _kriterien_auftraege(ergebnisse, lehrer_kombi: str) -> tuple[list[dict], list[dict]]:
    """Offene Kriterien (erfuellt=None) wie in der App: KI_NICHT_PRUEFBAR fest,
    alle übrigen mit aufgelöster Prüfanweisung."""
    erweiterte = parse_erweiterte_operatoren(lehrer_kombi)
    kombiniert = dict(OPERATOREN)
    kombiniert.update(erweiterte)
    fest, offen = [], []
    for e in ergebnisse:
        if e.erfuellt is not None:
            continue
        if e.kriterium_nr in KI_NICHT_PRUEFBAR:
            fest.append({
                "kriterium_nr": e.kriterium_nr, "kriterium_text": e.kriterium_text,
                "ki_ergebnis": "nicht_pruefbar", "konfidenz": 0,
                "begruendung": "Kriterium erfordert visuelle/physische Prüfung – "
                               "nicht durch KI prüfbar.",
                "fundstellen": [], "original_kommentar": e.kommentar,
            })
            continue
        variablen = _baue_template_vars(kombiniert, erweiterte, e.kommentar)
        if e.kriterium_nr == "X.5":
            zeilen, hinweis = _extrahiere_ewh_zeilen(lehrer_kombi)
            variablen["ewh_vorverarbeitet"] = _formatiere_ewh_vorverarbeitung(zeilen, hinweis)
        vorlage = KI_PRUEF_PROMPTS.get(e.kriterium_nr)
        if vorlage is None:
            anweisung = (f"Prüfe das folgende Kriterium:\n[{e.kriterium_nr}] {e.kriterium_text}\n\n"
                         f"Bisheriger Hinweis der automatischen Prüfung:\n{e.kommentar}\n\n"
                         "Melde NUR eindeutige Verstöße. Im Zweifel: keine Beanstandung.")
        else:
            anweisung = vorlage.format_map(variablen)
        offen.append({"kriterium_nr": e.kriterium_nr, "kriterium_text": e.kriterium_text,
                      "kommentar": e.kommentar, "anweisung": anweisung})
    return fest, offen


def _teilaufgaben_auftraege(sm: Path, lm: Path) -> tuple[list[dict], list[dict]]:
    """Teilaufgaben wie in fuehre_loesbarkeitspruefung_durch."""
    sm_text = extract_text(str(sm))
    normal, layout, _ = _lehrertext_wie_app(lm)
    lm_text = layout or normal
    aufgaben = parse_aufgaben(sm_text)
    fest, offen = [], []
    for a in aufgaben:
        material = extrahiere_materialhinweise(sm_text, a.nummer)
        for t in a.teilaufgaben:
            aufg = extrahiere_teilaufgabentext(sm_text, t, aufgaben)
            loes = extrahiere_loesungstext(lm_text, t.nummer)
            lerngebiet, _ = klassifiziere_lerngebiet(aufg, loes)
            hinweis = _vorbedingung(aufg, loes, lerngebiet)
            if hinweis:
                erg = LoesbarkeitErgebnis(teilaufgabe=t.nummer, lerngebiet=lerngebiet,
                                          vorab_hinweis=hinweis,
                                          loesbarkeit_begruendung=hinweis,
                                          richtigkeit_begruendung=hinweis)
                fest.append(erg.__dict__)
                continue
            offen.append({"teilaufgabe": t.nummer, "lerngebiet": lerngebiet,
                          "punkte": t.punkte, "material": material,
                          "aufgabentext": aufg[:MAX_AUFGABE_TEXT],
                          "loesungstext": loes[:MAX_LOESUNG_TEXT]})
    return fest, offen


def _schreibe_pruefauftrag(ziel: Path, lauf: dict, ergebnisse, krit_offen, krit_fest,
                           ta_offen, ta_fest) -> None:
    z = []
    z.append(f"# Prüfauftrag – {lauf['titel']}\n")
    z.append("Erzeugt von `begutachten.py vorbereiten`. **Vertraulich.** Arbeite Teil A und B "
             "vollständig ab und trage jedes Urteil in `urteile.json` ein (Format: "
             "`references/urteile-format.md` des Skills). Danach:\n")
    z.append(f"```\npython3 \"{HIER / 'begutachten.py'}\" abschliessen \"{ziel}\"\n```\n")
    z.append("## Material\n")
    z.append("- `text/schuelermaterial.txt` – Schülermaterial (SM) mit Seitenmarken "
             "`=== Seite N ===`; entspricht dem Abschnitt „=== SCHÜLERMATERIAL ===“ "
             "der Prüfanweisungen.")
    z.append("- `text/lehrermaterial.txt` – Lehrermaterial (LM) mit Seitenmarken; "
             "`text/lehrermaterial_layout.txt` – dasselbe zeilentreu (Tabellen, EWH).")
    z.append(f"- Originale: `{lauf['schuelermaterial']}`, `{lauf['lehrermaterial']}`")
    if not lauf["pdftotext"]:
        z.append("- ⚠ pdftotext fehlte – Textextraktion mit pypdf, Tabellen ggf. zerrissen.")
    z.append("\nAuszüge unten sind automatisch geschnitten und können unvollständig sein: "
             "im Zweifel im Volltext nachsehen. Inhalte, die nur als Bild vorliegen, "
             "bewertest du nicht (→ `nicht_pruefbar`).\n")

    z.append("## Ergebnis der Regelprüfung (fest – nicht ändern)\n")
    z.append("| Nr. | Kriterium | Raster | Kommentar (gekürzt) |\n|---|---|---|---|")
    for e in ergebnisse:
        kom = _kurz(e.kommentar, 160).replace("|", "/").replace("\n", " ")
        z.append(f"| {e.kriterium_nr} | {e.kriterium_text} | {SYMBOL_REGEL[e.erfuellt]} | {kom} |")

    z.append(f"\n## Teil A – Kriterien ({len(krit_offen)})\n")
    z.append("Regeln der App für jedes Kriterium (gelten unverändert; das Antwortformat "
             "ist hier ein Eintrag in `urteile.json` → `kriterien`):\n")
    z.append("```text\n" + SYSTEM_PROMPT.strip() + "\n```\n")
    z.append("Zusätzlich im Skill: Jede `beanstandung` braucht mindestens eine Fundstelle mit "
             "**wörtlichem Zitat in „…“**, z. B. `Schülermaterial Seite 3, 1.2: „Erläutern Sie …“` "
             "oder `Lehrermaterial Seite 7, EWH 2.1: „…“` (\"Seite\" ausschreiben – die "
             "Hinweisliste kürzt nach dem ersten Punkt). `abschliessen` sucht die Zitate im Text; "
             "nicht gefundene Zitate machen aus der Beanstandung „nicht prüfbar“.\n")
    for k in krit_offen:
        z.append(f"### [{k['kriterium_nr']}] {k['kriterium_text']}\n")
        z.append(f"**Vorabcheck (regelbasiert):** {k['kommentar']}\n")
        z.append("**Prüfanweisung:**\n\n```text\n" + k["anweisung"].strip() + "\n```\n")

    z.append(f"\n## Teil B – Lösbarkeit und Richtigkeit je Teilaufgabe ({len(ta_offen)})\n")
    z.append("Regeln der App (Antwort → `urteile.json` → `loesbarkeit`):\n")
    z.append("```text\n" + SYSTEM_PROMPT_LSG.strip() + "\n```\n")
    z.append("Prüffragen je Teilaufgabe:\n"
             "- **A) Lösbarkeit** – Reicht das Schülermaterial inkl. der genannten Anlagen? "
             "Fehlende Werte/Abbildungen, mehrdeutige Formulierungen, fehlende "
             "Zwischenergebnisse aus Voraufgaben (Alternativwert?).\n"
             "- **B) Fachliche Richtigkeit** – Ist die Musterlösung fachlich korrekt "
             "(RRL-Inhalte und Fehlermuster unten)? Rechnungen nachrechnen.\n")
    z.append("### Curriculare Grundlage\n")
    z.append(IT_RRL_UEBERGEORDNETE_KOMPETENZEN.strip() + "\n")
    for lg in sorted({t["lerngebiet"] for t in ta_offen}):
        z.append(f"#### {lg}\n")
        if lg != "unbekannt":
            z.append(kompakter_rrl_block(lg).strip() + "\n")
        z.append("Häufige fachliche Fehlermuster:\n\n" +
                 IT_LERNGEBIET_HINWEISE.get(lg, IT_LERNGEBIET_HINWEISE["unbekannt"]).strip() + "\n")
    for t in ta_offen:
        z.append(f"### Teilaufgabe {t['teilaufgabe']} ({t['lerngebiet']}, {t['punkte']} BE)\n")
        mat = ", ".join(t["material"]) or "keine genannt"
        z.append(f"Referenziertes Material: {mat}\n")
        z.append("Aufgabenstellung (Auszug):\n\n```text\n"
                 + _kurz(t["aufgabentext"], AUSZUG_AUFGABE) + "\n```\n")
        z.append("Musterlösung (Auszug):\n\n```text\n"
                 + (_kurz(t["loesungstext"], AUSZUG_LOESUNG)
                    or "(keine Lösung im Textextrakt gefunden – im LM nachsehen)") + "\n```\n")

    if krit_fest or ta_fest:
        z.append("\n## Bereits festgelegt (nicht in urteile.json)\n")
        for k in krit_fest:
            z.append(f"- [{k['kriterium_nr']}] {k['kriterium_text']}: nicht prüfbar "
                     "(visuell/physisch) – prüft die Fachberatung.")
        for t in ta_fest:
            z.append(f"- Teilaufgabe {t['teilaufgabe']}: {t['vorab_hinweis']}")
    (ziel / "pruefauftrag.md").write_text("\n".join(z) + "\n", encoding="utf-8")


def befehl_vorbereiten(args) -> int:
    sm, lm = Path(args.schuelermaterial).resolve(), Path(args.lehrermaterial).resolve()
    for p in (sm, lm):
        if not p.is_file():
            sys.exit(f"FEHLER: Datei nicht gefunden: {p}")
        if p.suffix.lower() not in (".pdf", ".docx"):
            sys.exit(f"FEHLER: Nur PDF oder DOCX: {p.name}")
    stamm = sm.stem
    ziel = Path(args.ausgabe or f"Gutachten_{stamm}").resolve()
    (ziel / "text").mkdir(parents=True, exist_ok=True)
    protokoll = []

    regel, ausgabe = _still(begutachte, str(sm), str(lm))
    protokoll.append(ausgabe)
    ergebnisse, analyse, aufgaben, sm_seiten, lm_seiten, sm_pages, lm_pages = regel

    vorlage = _finde_vorlage()
    gutachten = ziel / f"Gutachten_{stamm}.docx"
    if vorlage:
        _, ausgabe = _still(erstelle_gutachten_docx, ergebnisse, analyse, str(vorlage),
                            str(gutachten), str(sm), str(lm))
        protokoll.append(ausgabe)
    rueckmeldung = ziel / f"Rueckmeldung_{stamm}.xlsx"
    _, ausgabe = _still(erstelle_rueckmeldung_xlsx, ergebnisse, aufgaben, sm_seiten, lm_seiten,
                        output_pfad=str(rueckmeldung), schueler_datei=str(sm),
                        lehrer_datei=str(lm), sm_pages=sm_pages, lm_pages=lm_pages)
    protokoll.append(ausgabe)

    # Texte für Claude (mit Seitenmarken) und für die Zitatprüfung
    lm_normal, lm_layout, lm_kombi = _lehrertext_wie_app(lm)
    (ziel / "text" / "schuelermaterial.txt").write_text(_mit_seitenmarken(_seiten(sm)), encoding="utf-8")
    (ziel / "text" / "lehrermaterial.txt").write_text(_mit_seitenmarken(_seiten(lm)), encoding="utf-8")
    if lm_layout:
        (ziel / "text" / "lehrermaterial_layout.txt").write_text(
            _mit_seitenmarken(lm_layout.split("\f")), encoding="utf-8")

    krit_fest, krit_offen = _kriterien_auftraege(ergebnisse, lm_kombi)
    ta_fest, ta_offen = _teilaufgaben_auftraege(sm, lm)

    lauf = {
        "skill_version": VERSION,
        "erstellt": datetime.datetime.now().isoformat(timespec="seconds"),
        "titel": erkenne_vorschlag("\n".join(sm_pages[:2]), str(sm)),
        "stamm": stamm,
        "schuelermaterial": str(sm), "lehrermaterial": str(lm),
        "sha256_sm": _sha256(sm), "sha256_lm": _sha256(lm),
        "pdftotext": bool(shutil.which("pdftotext")),
        "vorlage": str(vorlage) if vorlage else "",
        "kriterien_fest": krit_fest,
        "kriterien_offen": [k["kriterium_nr"] for k in krit_offen],
        "loesbarkeit_fest": ta_fest,
        "loesbarkeit_offen": [t["teilaufgabe"] for t in ta_offen],
        "lerngebiete": {t["teilaufgabe"]: t["lerngebiet"] for t in ta_offen},
    }
    (ziel / "lauf.json").write_text(json.dumps(lauf, ensure_ascii=False, indent=2), encoding="utf-8")
    (ziel / "protokoll_regelpruefung.txt").write_text("\n".join(protokoll), encoding="utf-8")
    _schreibe_pruefauftrag(ziel, lauf, ergebnisse, krit_offen, krit_fest, ta_offen, ta_fest)

    urteile = {
        "modell": "Claude",
        "kriterien": [{"kriterium_nr": k["kriterium_nr"], "kriterium_text": k["kriterium_text"],
                       "ergebnis": "", "konfidenz": 0, "begruendung": "", "fundstellen": []}
                      for k in krit_offen],
        "loesbarkeit": [{"teilaufgabe": t["teilaufgabe"], "lerngebiet": t["lerngebiet"],
                         "loesbarkeit": "", "loesbarkeit_konfidenz": 0,
                         "loesbarkeit_begruendung": "", "fehlende_information": [],
                         "richtigkeit": "", "richtigkeit_konfidenz": 0,
                         "richtigkeit_begruendung": "", "fehler_in_loesung": []}
                        for t in ta_offen],
    }
    urteile_pfad = ziel / "urteile.json"
    if urteile_pfad.exists() and not args.neu:
        print(f"Hinweis: {urteile_pfad.name} besteht bereits und bleibt erhalten "
              "(--neu überschreibt).")
    else:
        urteile_pfad.write_text(json.dumps(urteile, ensure_ascii=False, indent=2), encoding="utf-8")

    n = {s: sum(1 for e in ergebnisse if e.erfuellt is s) for s in (True, False, None)}
    print(f"Vorprüfung {lauf['titel']} – {sm.name}")
    print(f"Regelprüfung: ✔ {n[True]}  ✘ {n[False]}  ? {n[None]}  (von {len(ergebnisse)})")
    if not lauf["pdftotext"]:
        print("⚠ pdftotext fehlt – Textextraktion mit pypdf; einzelne Kriterien können "
              "falsch gewertet sein (bash scripts/einrichten.sh).")
    for e in ergebnisse:
        if e.erfuellt is False:
            print(f"  ✘ [{e.kriterium_nr}] {e.kriterium_text}: {_kurz(e.kommentar, 140)}")
    print(f"Für Claude: {len(krit_offen)} Kriterien, {len(ta_offen)} Teilaufgaben "
          f"(fest: {len(krit_fest)} Kriterien, {len(ta_fest)} Teilaufgaben nicht prüfbar)")
    print(f"Ordner:      {ziel}")
    print(f"Prüfauftrag: {ziel / 'pruefauftrag.md'}")
    print(f"Urteile:     {urteile_pfad}")
    if vorlage:
        print(f"Raster:      {gutachten.name}")
    else:
        print("⚠ Gutachten-Vorlage fehlt – kein Raster erzeugt.")
    return 0


# ---------------------------------------------------------------------------
# abschliessen
# ---------------------------------------------------------------------------

def _int(wert) -> int:
    try:
        return max(0, min(100, int(wert)))
    except (TypeError, ValueError):
        return 0


def _liste(wert) -> list:
    if wert is None:
        return []
    return [wert] if isinstance(wert, str) else [str(w) for w in wert if str(w).strip()]


def befehl_abschliessen(args) -> int:
    ziel = Path(args.ordner).resolve()
    try:
        lauf = json.loads((ziel / "lauf.json").read_text(encoding="utf-8"))
        urteile = json.loads((ziel / "urteile.json").read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        sys.exit(f"FEHLER: {e.filename} fehlt – zuerst 'vorbereiten' ausführen.")
    except json.JSONDecodeError as e:
        sys.exit(f"FEHLER: urteile.json ist kein gültiges JSON ({e}).")

    sm, lm = Path(lauf["schuelermaterial"]), Path(lauf["lehrermaterial"])
    warnungen, fehler = [], []
    for pfad, schluessel in ((sm, "sha256_sm"), (lm, "sha256_lm")):
        if not pfad.is_file():
            sys.exit(f"FEHLER: Originaldatei fehlt: {pfad}")
        if _sha256(pfad) != lauf[schluessel]:
            warnungen.append(f"{pfad.name} wurde seit 'vorbereiten' geändert – "
                             "Ergebnisse ggf. neu vorbereiten.")
    modell = (args.modell or urteile.get("modell") or "Claude").strip()

    korpus = _norm(" ".join(
        (ziel / "text" / n).read_text(encoding="utf-8")
        for n in ("schuelermaterial.txt", "lehrermaterial.txt", "lehrermaterial_layout.txt")
        if (ziel / "text" / n).is_file()))

    # --- Kriterien -----------------------------------------------------------
    eingetragen = {str(k.get("kriterium_nr")): k for k in urteile.get("kriterien", [])}
    ki: list[KIPruefErgebnis] = [KIPruefErgebnis(**k) for k in lauf["kriterien_fest"]]
    kommentare = {}
    regel, _ = _still(begutachte, str(sm), str(lm))
    ergebnisse = regel[0]
    for e in ergebnisse:
        kommentare[e.kriterium_nr] = (e.kriterium_text, e.kommentar)
    ohne_beleg = []
    for nr in lauf["kriterien_offen"]:
        text, kommentar = kommentare.get(nr, ("", ""))
        k = eingetragen.get(nr)
        if not k or not (k.get("ergebnis") or "").strip():
            if args.unvollstaendig:
                ki.append(KIPruefErgebnis(nr, text, "nicht_pruefbar", 0,
                                          "Nicht bearbeitet.", [], kommentar))
            else:
                fehler.append(f"Kriterium {nr}: kein Ergebnis eingetragen.")
            continue
        ergebnis = k["ergebnis"].strip().lower()
        if ergebnis not in KI_WERTE:
            fehler.append(f"Kriterium {nr}: ergebnis '{ergebnis}' unzulässig "
                          f"({', '.join(sorted(KI_WERTE))}).")
            continue
        konfidenz = _int(k.get("konfidenz"))
        begruendung = (k.get("begruendung") or "").strip()
        fundstellen = _liste(k.get("fundstellen"))
        if not begruendung:
            fehler.append(f"Kriterium {nr}: Begründung fehlt.")
            continue
        if ergebnis == "beanstandung":
            if konfidenz < KONFIDENZ_SCHWELLE:
                ergebnis = "nicht_pruefbar"
                begruendung = (f"[Konfidenz {konfidenz}% < Schwelle {KONFIDENZ_SCHWELLE}%] "
                               + begruendung)
            elif not any(_zitat_belegt(f, korpus) for f in fundstellen):
                ergebnis = "nicht_pruefbar"
                begruendung = "[Zitat nicht im Material gefunden] " + begruendung
                ohne_beleg.append(nr)
            elif not re.search(r"Aufgabe|Teilaufgabe|\b\d+\.\d+\b", begruendung):
                warnungen.append(f"Kriterium {nr}: Beanstandung ohne Aufgabenbezug.")
        ki.append(KIPruefErgebnis(nr, text, ergebnis, konfidenz, begruendung,
                                  fundstellen, kommentar))
    unbekannt = set(eingetragen) - set(lauf["kriterien_offen"])
    if unbekannt:
        warnungen.append("Nicht angefragte Kriterien ignoriert: " + ", ".join(sorted(unbekannt)))

    # --- Lösbarkeit ----------------------------------------------------------
    eingetragen_t = {str(t.get("teilaufgabe")): t for t in urteile.get("loesbarkeit", [])}
    loesbar: list[LoesbarkeitErgebnis] = [LoesbarkeitErgebnis(**t) for t in lauf["loesbarkeit_fest"]]
    for nr in lauf["loesbarkeit_offen"]:
        t = eingetragen_t.get(nr)
        if not t or not (t.get("loesbarkeit") or "").strip() or not (t.get("richtigkeit") or "").strip():
            if args.unvollstaendig:
                loesbar.append(LoesbarkeitErgebnis(teilaufgabe=nr,
                                                   lerngebiet=lauf.get("lerngebiete", {}).get(nr, ""),
                                                   loesbarkeit_begruendung="Nicht bearbeitet.",
                                                   richtigkeit_begruendung="Nicht bearbeitet."))
            else:
                fehler.append(f"Teilaufgabe {nr}: loesbarkeit/richtigkeit fehlt.")
            continue
        antwort = {
            "loesbarkeit": t["loesbarkeit"].strip().lower(),
            "loesbarkeit_konfidenz": _int(t.get("loesbarkeit_konfidenz")),
            "loesbarkeit_begruendung": (t.get("loesbarkeit_begruendung") or "").strip(),
            "fehlende_information": _liste(t.get("fehlende_information")),
            "richtigkeit": t["richtigkeit"].strip().lower(),
            "richtigkeit_konfidenz": _int(t.get("richtigkeit_konfidenz")),
            "richtigkeit_begruendung": (t.get("richtigkeit_begruendung") or "").strip(),
            "fehler_in_loesung": _liste(t.get("fehler_in_loesung")),
        }
        falsch = [a for a in ("loesbarkeit", "richtigkeit") if antwort[a] not in LSG_WERTE]
        if falsch:
            fehler.append(f"Teilaufgabe {nr}: unzulässiger Wert bei {', '.join(falsch)} "
                          f"({', '.join(sorted(LSG_WERTE))}).")
            continue
        if antwort["loesbarkeit"] == "nein" and not antwort["fehlende_information"]:
            warnungen.append(f"Teilaufgabe {nr}: 'nicht lösbar' ohne fehlende_information.")
        if antwort["richtigkeit"] == "nein" and not antwort["fehler_in_loesung"]:
            warnungen.append(f"Teilaufgabe {nr}: 'Lösung falsch' ohne fehler_in_loesung.")
        antwort = _validitaetsfilter(antwort)
        lerngebiet = lauf.get("lerngebiete", {}).get(nr) or t.get("lerngebiet", "")
        loesbar.append(LoesbarkeitErgebnis(teilaufgabe=nr, lerngebiet=lerngebiet, **antwort))

    if fehler:
        print("urteile.json ist noch nicht vollständig:")
        for f in fehler:
            print(f"  - {f}")
        print("Ergänzen und erneut 'abschliessen' – oder mit --unvollstaendig fehlende "
              "Einträge als „nicht prüfbar“ übernehmen.")
        return 2

    # --- Ausgaben ------------------------------------------------------------
    stamm, kennung = lauf["stamm"], re.sub(r"[^A-Za-z0-9]+", "-", modell).strip("-").lower()
    reihenfolge = {nr: i for i, nr in enumerate(e.kriterium_nr for e in ergebnisse)}
    ki.sort(key=lambda e: reihenfolge.get(e.kriterium_nr, 999))
    block = hinweisblock_fuer_vorschlag(str(sm), str(lm), ki_ergebnisse=ki, loesbarkeit=loesbar,
                                        modell=modell, regel=regel, dateiname=str(sm))
    hinweise_xlsx, hinweise_csv = schreibe_hinweisliste([block], ziel / f"Hinweise_{stamm}_{kennung}")
    ki_xlsx = ziel / f"KI_Pruefung_{stamm}_{kennung}.xlsx"
    _still(schreibe_ki_bericht_xlsx, erstelle_kombinierte_liste(ergebnisse, ki),
           str(ki_xlsx), str(sm), str(lm))
    lsg_xlsx = ziel / f"Loesbarkeit_{stamm}_{kennung}.xlsx"
    _still(schreibe_loesbarkeitsbericht_xlsx, loesbar, str(lsg_xlsx), str(sm), str(lm),
           modell=modell, pruefer=modell)
    (ziel / f"ergebnis_{kennung}.json").write_text(json.dumps({
        "skill_version": VERSION, "modell": modell,
        "abgeschlossen": datetime.datetime.now().isoformat(timespec="seconds"),
        "sha256_sm": lauf["sha256_sm"], "sha256_lm": lauf["sha256_lm"],
        "konfidenz_schwelle": KONFIDENZ_SCHWELLE,
        "kriterien": [e.__dict__ for e in ki], "loesbarkeit": [e.__dict__ for e in loesbar],
        "warnungen": warnungen,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    bericht = _bericht_md(lauf, modell, ergebnisse, ki, loesbar, block, warnungen,
                          [hinweise_xlsx, hinweise_csv, ki_xlsx, lsg_xlsx])
    bericht_pfad = ziel / f"Bericht_{stamm}.md"
    bericht_pfad.write_text(bericht, encoding="utf-8")

    gesamt, ki_h = zaehle([block])
    print(f"Abgeschlossen: {lauf['titel']} ({modell})")
    print(f"Hinweisliste: {gesamt} Hinweise, davon {ki_h} aus der KI-Prüfung (gelb)")
    if ohne_beleg:
        print("Zitat nicht gefunden → „nicht prüfbar“: " + ", ".join(ohne_beleg))
    for w in warnungen:
        print(f"⚠ {w}")
    print(f"Bericht: {bericht_pfad}")
    for p in (ziel / f"Gutachten_{stamm}.docx", hinweise_xlsx, hinweise_csv, ki_xlsx, lsg_xlsx):
        if Path(p).exists():
            print(f"         {p}")
    return 0


def _bericht_md(lauf, modell, ergebnisse, ki, loesbar, block, warnungen, dateien) -> str:
    n = {s: sum(1 for e in ergebnisse if e.erfuellt is s) for s in (True, False, None)}
    ki_n = {w: sum(1 for e in ki if e.ki_ergebnis == w) for w in KI_WERTE}
    z = [f"# Vorprüfung {lauf['titel']}\n",
         f"vertraulich · KI-gestützte Vorprüfung ({modell}) · "
         f"{datetime.date.today().strftime('%d.%m.%Y')}\n",
         f"- Schülermaterial: `{Path(lauf['schuelermaterial']).name}` "
         f"(SHA-256 {lauf['sha256_sm'][:12]}…)",
         f"- Lehrermaterial: `{Path(lauf['lehrermaterial']).name}` "
         f"(SHA-256 {lauf['sha256_lm'][:12]}…)\n",
         "Alle Urteile sind Vorschläge. Das Gutachten verantwortet die Fachberatung; "
         "die „?“-Kriterien im Raster prüft sie selbst.\n",
         "## Überblick\n",
         "| Stufe | Ergebnis |\n|---|---|",
         f"| Regelprüfung (Raster) | ✔ {n[True]} · ✘ {n[False]} · ? {n[None]} |",
         f"| KI-Kriterien ({modell}) | Beanstandung {ki_n['beanstandung']} · keine "
         f"{ki_n['keine_beanstandung']} · nicht prüfbar {ki_n['nicht_pruefbar']} |",
         f"| Teilaufgaben | {len(loesbar)} geprüft · nicht lösbar "
         f"{sum(1 for e in loesbar if e.loesbarkeit == 'nein')} · Lösung fehlerhaft "
         f"{sum(1 for e in loesbar if e.richtigkeit == 'nein')} |",
         f"| Hinweisliste | {len(block.hinweise)} Hinweise |\n"]
    if not lauf.get("pdftotext"):
        z.append("> ⚠ Ohne pdftotext geprüft – einzelne Regelbefunde können falsch sein.\n")

    z.append("## Beanstandungen der Regelprüfung (✘ im Raster)\n")
    z += [f"- **[{e.kriterium_nr}] {e.kriterium_text}** – {_kurz(e.kommentar, 300)}"
          for e in ergebnisse if e.erfuellt is False] or ["- keine"]

    z.append(f"\n## Beanstandungen der KI-Prüfung (Konfidenz ≥ {KONFIDENZ_SCHWELLE} %)\n")
    treffer = [e for e in ki if e.ki_ergebnis == "beanstandung"]
    for e in treffer:
        z.append(f"- **[{e.kriterium_nr}] {e.kriterium_text}** ({e.konfidenz} %) – {e.begruendung}")
        z += [f"  - {f}" for f in e.fundstellen]
    if not treffer:
        z.append("- keine")

    z.append("\n## Lösbarkeit und fachliche Richtigkeit\n")
    z.append("| TA | LG | lösbar | % | richtig | % | Befund |\n|---|---|---|---|---|---|---|")
    for e in loesbar:
        befund = "; ".join(_liste(e.fehlende_information) + _liste(e.fehler_in_loesung)) \
            or _kurz(e.vorab_hinweis or "", 90)
        z.append(f"| {e.teilaufgabe} | {e.lerngebiet} | {e.loesbarkeit} | {e.loesbarkeit_konfidenz} "
                 f"| {e.richtigkeit} | {e.richtigkeit_konfidenz} | {befund.replace('|', '/')} |")

    z.append("\n## Selbst prüfen\n")
    offen = [e for e in ki if e.ki_ergebnis == "nicht_pruefbar"]
    z += [f"- [{e.kriterium_nr}] {e.kriterium_text} – {_kurz(e.begruendung, 160)}" for e in offen]
    z += [f"- Teilaufgabe {e.teilaufgabe}: {e.loesbarkeit}/{e.richtigkeit} – "
          f"{_kurz(e.loesbarkeit_begruendung or e.richtigkeit_begruendung, 140)}"
          for e in loesbar if "unklar" in (e.loesbarkeit, e.richtigkeit)
          or "nicht_pruefbar" in (e.loesbarkeit, e.richtigkeit)]
    if len(z) and z[-1] == "\n## Selbst prüfen\n":
        z.append("- nichts offen")
    if warnungen:
        z.append("\n## Warnungen\n")
        z += [f"- {w}" for w in warnungen]
    z.append("\n## Dateien\n")
    z.append(f"- `Gutachten_{lauf['stamm']}.docx` – Raster der Gutachtenvorlage (✔/✘/?), "
             "ohne Hinweistext")
    z += [f"- `{Path(p).name}`" for p in dateien]
    z.append("\nHinweisliste vor dem Versand prüfen und die Spalte „Herkunft“ löschen; "
             "KI-Hinweise sind gelb markiert.")
    return "\n".join(z) + "\n"


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="befehl", required=True)
    sub.add_parser("umgebung", help="Pakete, pdftotext und Vorlage prüfen")
    v = sub.add_parser("vorbereiten", help="Regelprüfung, Raster, Prüfauftrag")
    v.add_argument("schuelermaterial")
    v.add_argument("lehrermaterial")
    v.add_argument("--ausgabe", help="Zielordner (Standard: ./Gutachten_<SM-Name>)")
    v.add_argument("--neu", action="store_true", help="vorhandene urteile.json überschreiben")
    a = sub.add_parser("abschliessen", help="Urteile prüfen, Hinweisliste und Berichte")
    a.add_argument("ordner")
    a.add_argument("--modell", help="Bezeichnung des prüfenden Modells (Standard: Claude)")
    a.add_argument("--unvollstaendig", action="store_true",
                   help="fehlende Urteile als „nicht prüfbar“ übernehmen")
    args = ap.parse_args()
    return {"umgebung": befehl_umgebung, "vorbereiten": befehl_vorbereiten,
            "abschliessen": befehl_abschliessen}[args.befehl](args)


if __name__ == "__main__":
    sys.exit(main())
