FROM python:3.11-slim

WORKDIR /app

# Installiere System-Dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Kopiere requirements und installiere Python-Packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiere Quellcode
COPY . .

# Port für Streamlit
EXPOSE 8501

# Healthcheck
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Streamlit-Konfiguration und Start
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false", \
     "--logger.level=info"]
