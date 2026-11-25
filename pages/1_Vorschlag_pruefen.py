#!/usr/bin/env python3
"""
Streamlit-Seite: Klausurvorschlag prüfen
Regelbasierte + KI-gestützte + Lösbarkeits-Prüfung
"""

import streamlit as st
from dotenv import load_dotenv
import hashlib
import os
import sys
from pathlib import Path
from datetime import datetime

load_dotenv()

PROJEKT_WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJEKT_WURZEL))

from src.bewertung.regelbasiert import begutachte, extract_text_pdf, erstelle_gutachten_docx
from src.bewertung.hinweisliste import (
    aufgabe_anzeige,
    hinweisblock_fuer_vorschlag,
    schreibe_hinweisliste,
    zaehle,
)
from src.bewertung.ki_gestuetzt import (
    PROVIDER,
    aktiver_provider,
    setze_provider,
    liste_modelle,
    fuehre_ki_pruefung_durch,
    erstelle_kombinierte_liste,
    schreibe_ki_bericht_xlsx,
    _checkpoint_pfad as _ki_checkpoint_pfad,
    _loesche_checkpoint as _loesche_ki_checkpoint,
)
from src.bewertung.loesbarkeit import (
    fuehre_loesbarkeitspruefung_durch,
    schreibe_loesbarkeitsbericht_xlsx,
    _loesbar_checkpoint_pfad,
    _loesche_loesbar_checkpoint,
)


@st.cache_data(show_spinner=False, max_entries=8)
def _cached_extract_text_pdf(pfad: str, content_hash: str, layout: bool = False) -> str:
    # content_hash ist der eigentliche Cache-Schlüssel – pfad bleibt zwar identisch
    # (siehe SESSION_WORKDIR/<hash>_<hash>/), aber explizit zu hashen ist robuster.
    return extract_text_pdf(pfad, layout=layout)


# Persistente Ablage der hochgeladenen PDFs (statt /tmp/tmpXXX/).
# Ein wechselndes tmpdir machte Checkpoints früher unbrauchbar.
SESSION_WORKDIR = PROJEKT_WURZEL / "data" / "_streamlit_session"
SESSION_WORKDIR.mkdir(parents=True, exist_ok=True)

GUTACHTEN_VORLAGE = PROJEKT_WURZEL / "data" / "material" / "bg-abi_te_gutachten 2026.docx"

st.set_page_config(
    page_title="Klausurvorschlag prüfen",
    page_icon="🔍",
    layout="wide"
)

st.title("🔍 Klausurvorschlag prüfen")
st.markdown("Klausurvorschläge regelbasiert, KI-gestützt und auf Lösbarkeit prüfen")

# ============================================================================
# Sidebar: Konfiguration
# ============================================================================
with st.sidebar:
    st.subheader("⚙️ Konfiguration")

    # Provider und Modell wählen (Vorbelegung aus .env: KI_PROVIDER, KI_MODELL).
    # Lokal = LM Studio, Ollama, Bonsai: Daten verlassen den Rechner nicht.
    provider_namen = list(PROVIDER.keys())
    env_provider = os.getenv("KI_PROVIDER", "lokal").lower()
    provider = st.selectbox(
        "KI-Provider",
        provider_namen,
        index=provider_namen.index(env_provider) if env_provider in provider_namen else 0,
        format_func=lambda k: PROVIDER[k].name,
    )
    ki_bereit = True
    try:
        cfg = setze_provider(provider)
    except ValueError as e:
        st.error(str(e))
        ki_bereit = False
        cfg = None

    if cfg is not None and cfg.is_lokal:
        st.caption(f"🖥️ lokal · {cfg.base_url}")
        modelle = liste_modelle()
        if modelle:
            env_modell = os.getenv("KI_MODELL", "").strip()
            optionen = ["auto"] + modelle
            vorwahl = next((i for i, m in enumerate(optionen)
                            if env_modell and env_modell.lower() in m.lower()), 0)
            modell_wahl = st.selectbox(
                "Modell", optionen, index=vorwahl,
                help="auto = erstes Modell aus der Präferenzliste "
                     "(Gemma 4 12B, Bonsai, …)",
            )
            cfg = setze_provider(provider, modell_wahl)
        else:
            st.warning(f"{cfg.name} antwortet nicht unter {cfg.base_url}. "
                       "Server starten, dann Seite neu laden.")
    elif cfg is not None:
        st.caption(f"☁️ Cloud · Modell {cfg.model}")
        st.warning("Cloud-Provider: Klausurentwürfe verlassen den Rechner.")

    do_regelbasiert = st.checkbox("✓ Regelbasierte Prüfung", value=True)
    do_ki = st.checkbox("✓ KI-gestützte Prüfung", value=False, disabled=not ki_bereit)
    do_loesbarkeit = st.checkbox("✓ Lösbarkeit prüfen", value=False, disabled=not ki_bereit)

    st.divider()
    neu_starten = st.checkbox(
        "🔄 Bestehende Checkpoints ignorieren",
        value=False,
        help="Beim nächsten Start wird die KI-/Lösbarkeits-Prüfung "
             "von vorne ausgeführt, statt aus dem Checkpoint fortzusetzen.",
    )

# ============================================================================
# Datei-Upload
# ============================================================================
st.subheader("📤 Dateien hochladen")

col1, col2 = st.columns(2)

with col1:
    schueler_file = st.file_uploader(
        "Schülermaterial (PDF)",
        type="pdf",
        key="schueler_pdf"
    )

with col2:
    lehrer_file = st.file_uploader(
        "Lehrermaterial (PDF)",
        type="pdf",
        key="lehrer_pdf"
    )

# ============================================================================
# Hauptlogik
# ============================================================================
laeuft = st.session_state.get("pruefung_laeuft", False)
start_clicked = st.button(
    "🚀 Prüfung starten",
    use_container_width=True,
    type="primary",
    disabled=laeuft,
)

if start_clicked:

    if not schueler_file or not lehrer_file:
        st.error("❌ Beide Dateien müssen hochgeladen werden!")
        st.stop()

    zeitstempel = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Persistente Pfade pro PDF-Inhalt (statt /tmp/tmpXXX/).
    # Identische PDFs landen wieder am gleichen Pfad → Checkpoints greifen.
    schueler_bytes = schueler_file.getvalue()
    lehrer_bytes = lehrer_file.getvalue()
    sm_hash = hashlib.sha256(schueler_bytes).hexdigest()[:16]
    lm_hash = hashlib.sha256(lehrer_bytes).hexdigest()[:16]
    arbeitsverzeichnis = SESSION_WORKDIR / f"{sm_hash}_{lm_hash}"
    arbeitsverzeichnis.mkdir(parents=True, exist_ok=True)
    schueler_path = arbeitsverzeichnis / "schueler.pdf"
    lehrer_path = arbeitsverzeichnis / "lehrer.pdf"
    if not schueler_path.exists() or schueler_path.read_bytes() != schueler_bytes:
        schueler_path.write_bytes(schueler_bytes)
    if not lehrer_path.exists() or lehrer_path.read_bytes() != lehrer_bytes:
        lehrer_path.write_bytes(lehrer_bytes)

    # Run-Lock setzen
    st.session_state["pruefung_laeuft"] = True

    # Optional: Checkpoints zurücksetzen
    if neu_starten:
        _loesche_ki_checkpoint(str(schueler_path), str(lehrer_path))
        _loesche_loesbar_checkpoint(str(schueler_path), str(lehrer_path))

    try:
        tmpdir = arbeitsverzeichnis

        downloads: dict[str, tuple[bytes, str, str]] = {}  # label → (bytes, filename, mime)
        # Quellen für die Hinweisliste (am Ende zusammengeführt)
        regel_ergebnis = None
        ki_fuer_hinweise = None
        loesbar_fuer_hinweise = None

        # ====================================================================
        # Regelbasierte Prüfung
        # ====================================================================
        if do_regelbasiert:
            st.subheader("📋 Regelbasierte Prüfung")
            progress = st.progress(0)
            status = st.status("Analysiere PDF-Dateien...")

            try:
                with status:
                    st.write("Extrahiere Texte...")
                    schueler_text = _cached_extract_text_pdf(str(schueler_path), sm_hash)
                    lehrer_text = _cached_extract_text_pdf(str(lehrer_path), lm_hash)
                    st.write(f"Schülermaterial: {len(schueler_text)} Zeichen")
                    st.write(f"Lehrermaterial:  {len(lehrer_text)} Zeichen")

                    st.write("Führe regelbasierte Prüfung durch...")
                    # Rückgabe: (Ergebnisse, Operatoren-Analyse, Aufgaben,
                    #            SM-/LM-Seitenmap, SM-/LM-Seitentexte)
                    regel_ergebnis = begutachte(str(schueler_path), str(lehrer_path))
                    ergebnisse, analyse_text, aufgaben, *_ = regel_ergebnis
                    warnungen: list[str] = []
                    fehler: list[str] = []
                    gutachten_path = None
                    if GUTACHTEN_VORLAGE.exists():
                        st.write("Fülle Gutachten-Vorlage aus...")
                        gutachten_path = tmpdir / "Gutachten.docx"
                        try:
                            erstelle_gutachten_docx(
                                ergebnisse, analyse_text, str(GUTACHTEN_VORLAGE),
                                str(gutachten_path), schueler_file.name, lehrer_file.name,
                            )
                        except Exception as e:  # Gutachten optional – Prüfung bleibt gültig
                            warnungen.append(f"Gutachten-DOCX konnte nicht erstellt werden: {e}")
                            gutachten_path = None
                    else:
                        warnungen.append(f"Gutachten-Vorlage fehlt: {GUTACHTEN_VORLAGE}")

                progress.progress(100)
                st.success("✅ Regelbasierte Prüfung abgeschlossen!")

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("✅ Erfüllt", sum(1 for e in ergebnisse if e.erfuellt is True))
                with col2:
                    st.metric("❌ Nicht erfüllt", sum(1 for e in ergebnisse if e.erfuellt is False))
                with col3:
                    st.metric("❓ Unklar (→ KI)", sum(1 for e in ergebnisse if e.erfuellt is None))

                st.subheader("📝 Detaillierte Prüfung")
                for res in ergebnisse:
                    if res.erfuellt is True:
                        st.success(f"✅ {res.kriterium_nr}: {res.kriterium_text}")
                    elif res.erfuellt is False:
                        st.error(f"❌ {res.kriterium_nr}: {res.kriterium_text}")
                    else:
                        st.warning(f"❓ {res.kriterium_nr}: {res.kriterium_text} (KI-Prüfung nötig)")
                    if res.kommentar:
                        st.caption(f"Kommentar: {res.kommentar}")

                if analyse_text:
                    with st.expander("🔎 Operatoren-Analyse"):
                        st.text(analyse_text)

                if warnungen:
                    st.subheader("⚠️ Warnungen")
                    for w in warnungen:
                        st.warning(w)
                if fehler:
                    st.subheader("🔴 Fehler")
                    for f in fehler:
                        st.error(f)

                if gutachten_path and Path(gutachten_path).exists():
                    downloads["📄 Gutachten (DOCX)"] = (
                        Path(gutachten_path).read_bytes(),
                        f"Gutachten_{zeitstempel}.docx",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )

            except Exception as e:
                st.error(f"❌ Fehler bei der Prüfung: {e}")
                st.code(str(e))

        # ====================================================================
        # KI-gestützte Prüfung
        # ====================================================================
        if do_ki:
            st.subheader("🤖 KI-gestützte Prüfung")
            ki_progress = st.progress(0)
            ki_status = st.status("Starte KI-Prüfung – das kann einige Minuten dauern …")
            ki_log_platzhalter = st.empty()
            ki_log_zeilen: list[str] = []

            def ki_callback(ev: dict) -> None:
                stufe = ev.get("stufe", "")
                aktuell = int(ev.get("aktuell", 0))
                gesamt = max(1, int(ev.get("gesamt", 1)))
                label = ev.get("label", "")
                if stufe == "ki_start":
                    aus_cp = ev.get("aus_checkpoint", 0)
                    nachricht = f"Starte KI-Prüfung: {gesamt} Kriterien"
                    if aus_cp:
                        nachricht += f" (davon {aus_cp} aus Checkpoint)"
                    ki_log_zeilen.append(nachricht)
                elif stufe == "ki_aufruf":
                    ki_log_zeilen.append(f"⏳ {label} …")
                elif stufe == "ki":
                    erg = ev.get("ergebnis")
                    symbol = "?"
                    if erg is not None:
                        symbol = {
                            "beanstandung": "❌",
                            "keine_beanstandung": "✅",
                            "nicht_pruefbar": "⚠️",
                        }.get(erg.ki_ergebnis, "?")
                    if ki_log_zeilen and ki_log_zeilen[-1].startswith("⏳"):
                        ki_log_zeilen[-1] = ki_log_zeilen[-1].replace("⏳", symbol) + f" ({aktuell}/{gesamt})"
                    else:
                        ki_log_zeilen.append(f"{symbol} {label} ({aktuell}/{gesamt})")
                ki_progress.progress(min(100, int(aktuell / gesamt * 100)))
                ki_log_platzhalter.markdown("\n".join(f"- {z}" for z in ki_log_zeilen[-25:]))

            try:
                with ki_status:
                    st.write("Bereite KI-Provider vor …")
                    ki_progress.progress(5)

                    ki_ergebnisse, regelbasiert_liste = fuehre_ki_pruefung_durch(
                        str(schueler_path), str(lehrer_path),
                        verbose=False, progress_callback=ki_callback,
                    )
                    ki_progress.progress(90)

                    kombinierte = erstelle_kombinierte_liste(regelbasiert_liste, ki_ergebnisse)
                    ki_fuer_hinweise = ki_ergebnisse

                    xlsx_pfad = tmpdir / "KI_Pruefung.xlsx"
                    schreibe_ki_bericht_xlsx(
                        kombinierte, str(xlsx_pfad),
                        str(schueler_path), str(lehrer_path)
                    )
                    ki_progress.progress(100)

                    if xlsx_pfad.exists():
                        downloads["📊 KI-Prüfbericht (XLSX)"] = (
                            xlsx_pfad.read_bytes(),
                            f"KI_Pruefung_{zeitstempel}.xlsx",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )

                st.success("✅ KI-Prüfung abgeschlossen!")

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("❌ Beanstandungen",
                              sum(1 for e in ki_ergebnisse if e.ki_ergebnis == "beanstandung"))
                with col2:
                    st.metric("✅ Keine Beanstandung",
                              sum(1 for e in ki_ergebnisse if e.ki_ergebnis == "keine_beanstandung"))
                with col3:
                    st.metric("❓ Nicht prüfbar",
                              sum(1 for e in ki_ergebnisse if e.ki_ergebnis == "nicht_pruefbar"))

                st.subheader("📝 KI-Ergebnisse")
                for e in ki_ergebnisse:
                    if e.ki_ergebnis == "beanstandung":
                        st.error(f"❌ {e.kriterium_nr}: {e.kriterium_text} (Konfidenz: {e.konfidenz} %)")
                    elif e.ki_ergebnis == "keine_beanstandung":
                        st.success(f"✅ {e.kriterium_nr}: {e.kriterium_text} (Konfidenz: {e.konfidenz} %)")
                    else:
                        st.info(f"❓ {e.kriterium_nr}: {e.kriterium_text}")
                    if e.begruendung:
                        st.caption(e.begruendung)

            except (Exception, SystemExit) as e:
                ki_progress.progress(0)
                st.error(f"❌ KI-Prüfung fehlgeschlagen: {e}")
                st.caption(f"Läuft der Server ({PROVIDER[provider].name}) mit Modell? Auswahl links in der Seitenleiste, Vorbelegung in .env → KI_PROVIDER / KI_MODELL")
                st.code(str(e))

        # ====================================================================
        # Lösbarkeit-Prüfung
        # ====================================================================
        if do_loesbarkeit:
            st.subheader("🎯 Lösbarkeit-Prüfung")
            l_progress = st.progress(0)
            l_status = st.status("Starte Lösbarkeits-Prüfung – das kann einige Minuten dauern …")
            l_log_platzhalter = st.empty()
            l_log_zeilen: list[str] = []

            def l_callback(ev: dict) -> None:
                stufe = ev.get("stufe", "")
                aktuell = int(ev.get("aktuell", 0))
                gesamt = max(1, int(ev.get("gesamt", 1)))
                label = ev.get("label", "")
                if stufe == "loesbarkeit_start":
                    aus_cp = ev.get("aus_checkpoint", 0)
                    nachricht = f"Starte Lösbarkeits-Prüfung: {gesamt} Teilaufgaben"
                    if aus_cp:
                        nachricht += f" (davon {aus_cp} aus Checkpoint)"
                    l_log_zeilen.append(nachricht)
                elif stufe == "loesbarkeit_aufruf":
                    l_log_zeilen.append(f"⏳ {label} …")
                elif stufe == "loesbarkeit":
                    erg = ev.get("ergebnis")
                    symbol = "?"
                    if erg is not None:
                        symbol = {
                            "ja": "✅",
                            "nein": "❌",
                            "unklar": "⚠️",
                            "nicht_pruefbar": "⬜",
                        }.get(erg.loesbarkeit, "?")
                    suffix = " (Checkpoint)" if ev.get("aus_checkpoint") else ""
                    if l_log_zeilen and l_log_zeilen[-1].startswith("⏳"):
                        l_log_zeilen[-1] = l_log_zeilen[-1].replace("⏳", symbol) + f" ({aktuell}/{gesamt}){suffix}"
                    else:
                        l_log_zeilen.append(f"{symbol} {label} ({aktuell}/{gesamt}){suffix}")
                l_progress.progress(min(100, int(aktuell / gesamt * 100)))
                l_log_platzhalter.markdown("\n".join(f"- {z}" for z in l_log_zeilen[-25:]))

            try:
                with l_status:
                    st.write("Bereite KI-Provider vor …")
                    l_progress.progress(5)

                    loesbarkeitsergebnisse = fuehre_loesbarkeitspruefung_durch(
                        str(schueler_path), str(lehrer_path),
                        verbose=False, progress_callback=l_callback,
                    )
                    l_progress.progress(90)
                    loesbar_fuer_hinweise = loesbarkeitsergebnisse

                    xlsx_pfad = tmpdir / "Loesbarkeit.xlsx"
                    schreibe_loesbarkeitsbericht_xlsx(
                        loesbarkeitsergebnisse, str(xlsx_pfad),
                        str(schueler_path), str(lehrer_path)
                    )
                    l_progress.progress(100)

                    if xlsx_pfad.exists():
                        downloads["🎯 Lösbarkeits-Bericht (XLSX)"] = (
                            xlsx_pfad.read_bytes(),
                            f"Loesbarkeit_{zeitstempel}.xlsx",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )

                st.success("✅ Lösbarkeits-Prüfung abgeschlossen!")

                loesbar = sum(1 for e in loesbarkeitsergebnisse if e.loesbarkeit == "ja")
                nicht_loesbar = sum(1 for e in loesbarkeitsergebnisse if e.loesbarkeit == "nein")
                unklar_l = sum(1 for e in loesbarkeitsergebnisse if e.loesbarkeit == "unklar")
                nicht_pruefbar_l = sum(1 for e in loesbarkeitsergebnisse if e.loesbarkeit == "nicht_pruefbar")

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("✅ Lösbar", loesbar)
                with col2:
                    st.metric("❌ Nicht lösbar", nicht_loesbar)
                with col3:
                    st.metric("❓ Unklar", unklar_l)
                with col4:
                    st.metric("⬜ Nicht prüfbar", nicht_pruefbar_l)

                st.subheader("📝 Lösbarkeits-Ergebnisse")
                for e in loesbarkeitsergebnisse:
                    header = f"Aufgabe {e.teilaufgabe} ({e.lerngebiet})"
                    if e.loesbarkeit == "ja":
                        st.success(f"✅ {header} – lösbar (Konfidenz: {e.loesbarkeit_konfidenz} %)")
                    elif e.loesbarkeit == "nein":
                        st.error(f"❌ {header} – nicht lösbar (Konfidenz: {e.loesbarkeit_konfidenz} %)")
                    elif e.loesbarkeit == "nicht_pruefbar":
                        st.info(f"⬜ {header} – nicht prüfbar")
                    else:
                        st.warning(f"❓ {header}")
                    if e.loesbarkeit_begruendung:
                        st.caption(f"Lösbarkeit: {e.loesbarkeit_begruendung}")
                    if e.fehlende_information:
                        st.caption(f"Fehlende Info: {e.fehlende_information}")
                    if e.richtigkeit and e.richtigkeit != "nicht_pruefbar":
                        richt_icon = {"ja": "✅", "nein": "❌"}.get(e.richtigkeit, "❓")
                        st.caption(f"{richt_icon} Musterlösung: {e.richtigkeit} – {e.richtigkeit_begruendung}")

            except (Exception, SystemExit) as e:
                l_progress.progress(0)
                st.error(f"❌ Lösbarkeits-Prüfung fehlgeschlagen: {e}")
                st.caption(f"Läuft der Server ({PROVIDER[provider].name}) mit Modell? Auswahl links in der Seitenleiste, Vorbelegung in .env → KI_PROVIDER / KI_MODELL")
                st.code(str(e))

        # ====================================================================
        # Hinweisliste für die Schule (nicht im Gutachten, sondern XLSX/CSV)
        # ====================================================================
        if do_regelbasiert or do_ki or do_loesbarkeit:
            try:
                modell_name = ""
                if ki_fuer_hinweise is not None or loesbar_fuer_hinweise is not None:
                    modell_name = aktiver_provider().model or ""
                block = hinweisblock_fuer_vorschlag(
                    str(schueler_path), str(lehrer_path),
                    ki_ergebnisse=ki_fuer_hinweise,
                    loesbarkeit=loesbar_fuer_hinweise,
                    modell=modell_name,
                    regel=regel_ergebnis,
                    dateiname=schueler_file.name,
                )
                xlsx_h, csv_h = schreibe_hinweisliste([block], tmpdir / "Hinweise")
                gesamt_h, ki_h = zaehle([block])
                st.subheader(f"📝 Hinweisliste – {block.titel}")
                st.caption(
                    f"{gesamt_h} Hinweise, davon {ki_h} von der KI (gelb in der XLSX). "
                    "KI-Hinweise hängen stark vom Modell ab – vor dem Versand prüfen und "
                    "die Spalte „Herkunft“ löschen. Offene Kriterien („?“) stehen nicht "
                    "hier, sondern im Gutachten-Raster."
                )
                if block.hinweise:
                    st.dataframe(
                        [{"Aufgabe": aufgabe_anzeige(h.aufgabe), "Hinweis": h.text,
                          "SM": h.sm_seite, "LM": h.lm_seite, "Hinweise": h.zusatz,
                          "Herkunft": h.herkunft} for h in block.hinweise],
                        use_container_width=True, hide_index=True,
                    )
                stamm = Path(schueler_file.name).stem
                downloads["📝 Hinweisliste (XLSX)"] = (
                    xlsx_h.read_bytes(), f"Hinweise_{stamm}_{zeitstempel}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                downloads["📝 Hinweisliste (CSV)"] = (
                    csv_h.read_bytes(), f"Hinweise_{stamm}_{zeitstempel}.csv", "text/csv",
                )
            except Exception as e:
                st.warning(f"Hinweisliste konnte nicht erstellt werden: {e}")

        # ====================================================================
        # Downloads (gesammelt am Ende)
        # ====================================================================
        if downloads:
            st.divider()
            st.subheader("📥 Downloads")
            for label, (data, filename, mime) in downloads.items():
                st.download_button(
                    label=label,
                    data=data,
                    file_name=filename,
                    mime=mime,
                )
    finally:
        # Run-Lock wieder freigeben (egal ob Erfolg oder Exception)
        st.session_state["pruefung_laeuft"] = False

# ============================================================================
# Info-Box
# ============================================================================
with st.expander("ℹ️ Hilfe"):
    st.markdown(f"""
    ### Wie funktioniert die Prüfung?

    1. **Laden Sie beide Dateien hoch** (Schüler- und Lehrermaterial als PDF)
    2. **Wählen Sie Prüfungsarten** aus den Optionen in der Sidebar
    3. **Klicken Sie "Prüfung starten"**
    4. **Ergebnisse werden angezeigt** und können heruntergeladen werden

    ### Was wird überprüft?

    - **Regelbasiert**: Format, Struktur, AFB-Verteilung, Operatoren (~40 Kriterien) → Gutachten-Raster (DOCX, ✔/✘/?)
    - **KI-gestützt**: Borderline-Kriterien, Interpretation → XLSX-Download
    - **Lösbarkeit**: Kann jede Teilaufgabe gelöst werden? Ist die Musterlösung korrekt? → XLSX-Download
    - **Hinweisliste** (XLSX + CSV): Hinweise an die Schule im Format der Fachberatung
      (Aufgabe · Hinweis · Schüler-/Lehrermaterial · Hinweise · Überarbeitet am).
      Sie stehen nicht im Gutachten. KI-Hinweise sind gelb markiert und vor dem Versand zu prüfen.

    ### Provider (aktuell: **{provider.capitalize()}**)

    - `lokal` → LM Studio, Port 1234 (Modell wird bei Bedarf per `lms` geladen)
    - `ollama` → Ollama, Port 11434 – vorher `OLLAMA_CONTEXT_LENGTH=32768 ollama serve`
    - `bonsai` → Bonsai-Laufzeit, Adresse in `.env` unter `BONSAI_BASE_URL`
    - `hetzner` / `gwdg` → Cloud – für Klausurentwürfe nicht verwenden

    Vorbelegung in `.env` → `KI_PROVIDER=lokal|ollama|bonsai|hetzner|gwdg`, `KI_MODELL=…`
    """)
