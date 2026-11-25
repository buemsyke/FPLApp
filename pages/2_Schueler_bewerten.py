#!/usr/bin/env python3
"""
Streamlit-Seite: Schülerarbeiten bewerten
"""

import streamlit as st

st.set_page_config(
    page_title="Schüler bewerten",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Schülerarbeiten bewerten")
st.markdown(
    "Automatische Bewertung von Schülerergebnissen in 3 Phasen"
)

tab1, tab2, tab3 = st.tabs(["📦 Paket vorbereiten", "🎓 Schüler bewerten", "✅ Freigabe"])

with tab1:
    st.subheader("1️⃣ Paket vorbereiten")
    st.info("""
    **Status**: Entwicklung läuft

    Hier werden Sie später:
    - Klausurname eingeben
    - Lehrermaterial (PDF) hochladen
    - Bewertungsvorlage (XLSX) hochladen
    - KI-Provider wählen
    - Paket erstellen
    """)

with tab2:
    st.subheader("2️⃣ Schüler bewerten")
    st.info("""
    **Status**: Entwicklung läuft

    Hier werden Sie später:
    - Schüler-PDFs hochladen
    - KI extrahiert automatisch Antworten
    - Bewertet gegen Erwartungshorizont
    - Erzeugt XLSX + Detailbericht
    """)

with tab3:
    st.subheader("3️⃣ Freigabe")
    st.info("""
    **Status**: Entwicklung läuft

    Hier werden Sie später:
    - Alle Schülerergebnisse reviewen
    - Manuelle Anpassungen vornehmen
    - Abfinal geben oder zurück zur Bearbeitung
    - Export als XLSX + PDF
    """)

st.success("✅ Struktur ist ready - Logik kommt in nächster Phase!")
