#!/usr/bin/env python3
"""
GutachtenAbiturklausur - Streamlit Web-Interface
Automatische Begutachtung von Abiturklausuren (BG Technik IT, Niedersachsen)
"""

import streamlit as st
from dotenv import load_dotenv
import os

# Lade .env wenn vorhanden
load_dotenv()

# Streamlit Page Config
st.set_page_config(
    page_title="Gutachten Abiturklausur",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS für besseres Styling
st.markdown("""
<style>
    [data-testid="stAppViewContainer"] {
        padding-top: 0;
    }
    .stMainBlockContainer {
        padding-top: 2rem;
    }
</style>
""", unsafe_allow_html=True)


def render_home():
    """Startseite mit Übersicht und Anleitung"""
    st.title("📝 Gutachten Abiturklausur")
    st.markdown("Automatisches Begutachtungssystem für Abiturklausuren (BG Technik IT, Niedersachsen)")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("""
        ### Willkommen!

        Dieses System unterstützt Sie bei der automatisierten Begutachtung von Abiturklausurvorschlägen
        und der Bewertung von Schülerergebnissen.

        **2 Hauptfunktionen:**
        1. 🔍 **Vorschlag prüfen** – Neue Klausurvorschläge regelbasiert + KI-gestützt bewerten
        2. 📊 **Schüler bewerten** – Schülerergebnisse automatisch bewerten und freigeben

        Nutze das **Menü oben links** (☰) zur Navigation.
        """)

    with col2:
        # Provider-Status Sidebar
        st.subheader("⚙️ System")

        provider = os.getenv("KI_PROVIDER", "lokal").lower()
        st.info(f"**Provider**: {provider.capitalize()}")

        if provider == "lokal":
            lm_url = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
            st.caption(f"🖥️ LM Studio · {lm_url}")
        elif provider == "ollama":
            st.caption(f"🖥️ Ollama · {os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')}")
        elif provider == "bonsai":
            st.caption(f"🖥️ Bonsai · {os.getenv('BONSAI_BASE_URL', 'http://localhost:8080')}")
        elif provider == "hetzner":
            st.caption("☁️ Hetzner AI (Cloud)")
        elif provider == "gwdg":
            st.caption("🏫 GWDG Göttingen")


# Render home page
render_home()
