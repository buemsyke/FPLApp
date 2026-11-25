@echo off
REM ============================================================================
REM GutachtenAbiturklausur - Windows Einstiegspunkt
REM Doppelklick zum Starten
REM ============================================================================

setlocal enabledelayedexpansion

REM Prüfe Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [FEHLER] Python nicht gefunden.
    echo Bitte Python 3.11+ von python.org installieren.
    pause
    exit /b 1
)

REM Prüfe ob wir im richtigen Verzeichnis sind
if not exist "app.py" (
    echo [FEHLER] app.py nicht gefunden.
    echo Bitte starten.bat aus dem Projekt-Wurzelverzeichnis aus starten.
    pause
    exit /b 1
)

REM Erstelle .env aus .env.example falls nicht vorhanden
if not exist ".env" (
    echo [INFO] .env wird aus .env.example erstellt...
    copy .env.example .env >nul
    echo [INFO] .env erstellt. Bitte API-Keys in .env eintragen, falls nötig.
)

REM Erstelle venv falls nicht vorhanden
if not exist ".venv" (
    echo [INFO] Virtuelle Umgebung wird erstellt...
    python -m venv .venv
)

REM Aktiviere venv
call .venv\Scripts\activate.bat

REM Installiere/Update Packages
echo [INFO] Dependencies werden installiert...
pip install -q --upgrade pip
pip install -q -r requirements.txt

REM Starte Streamlit
echo [INFO] Starte Streamlit-App...
echo [INFO] Browser wird gleich geöffnet unter http://localhost:8501
echo.

streamlit run app.py --server.port=8501 --browser.gatherUsageStats=false

pause
