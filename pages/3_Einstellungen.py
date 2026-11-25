#!/usr/bin/env python3
"""
Streamlit-Seite: Einstellungen
"""

import streamlit as st
from dotenv import load_dotenv
import os

load_dotenv()

st.set_page_config(
    page_title="Einstellungen",
    page_icon="⚙️",
    layout="wide"
)

st.title("⚙️ Einstellungen")

# Aktuelle Konfiguration anzeigen
st.subheader("📋 Aktuelle Konfiguration")

current_provider = os.getenv("KI_PROVIDER", "lokal").lower()
col1, col2 = st.columns(2)

with col1:
    st.write(f"**KI-Provider**: {current_provider.capitalize()}")
    
with col2:
    if current_provider == "lokal":
        url = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
        st.write(f"**URL**: {url}")

st.divider()

# Provider-Informationen
st.subheader("🔐 Provider-Optionen")

col1, col2, col3 = st.columns(3)

with col1:
    st.write("**🖥️ Lokal (LM Studio)**")
    st.caption("""
    - Keine Datenübertragung
    - Kostenlos
    - Offline möglich
    - Benötigt lokale Installation
    """)

with col2:
    st.write("**☁️ Hetzner**")
    st.caption("""
    - DSGVO-konform
    - Server in Deutschland
    - Kostenpflichtig
    - Cloud-basiert
    """)

with col3:
    st.write("**🏫 GWDG**")
    st.caption("""
    - Universität Göttingen
    - Kostenlos (DFN-Mitglieder)
    - Datenschutz-zertifiziert
    - Cloud-basiert
    """)

st.divider()

st.info("""
✅ **System läuft!**

Konfiguration erfolgt über `.env`-Datei:
```
KI_PROVIDER=lokal
LMSTUDIO_BASE_URL=http://localhost:1234/v1
HETZNER_AI_API_KEY=...
GWDG_API_KEY=...
```

Nach Änderungen: App neu starten.
""")
