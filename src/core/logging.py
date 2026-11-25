#!/usr/bin/env python3
"""
Zentrales Logging-Setup für GutachtenAbiturklausur.

Bietet einen konfigurierbaren Logger mit:
- RotatingFileHandler → logs/gutachten.log (5 MB, 3 Backups)
- StreamHandler → stderr (nur WARNING+)
- Umgebungsvariable LOG_LEVEL (default INFO)
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


def setup_logging(name: str = "gutachten") -> logging.Logger:
    """Initialisiert und gibt einen Logger zurück (idempotent).

    Args:
        name: Logger-Name (Standard: "gutachten")

    Returns:
        Konfigurierter Logger mit File + StreamHandler
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # bereits konfiguriert

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.setLevel(level)

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    # File-Handler: alles ab LOG_LEVEL in Datei
    fh = RotatingFileHandler(
        _LOG_DIR / "gutachten.log",
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s:%(funcName)s:%(lineno)d %(message)s"
    ))
    fh.setLevel(level)

    # Stream-Handler: nur WARNING+ auf stderr (für Streamlit-UI sichtbar)
    sh = logging.StreamHandler()
    sh.setLevel(logging.WARNING)
    sh.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    logger.addHandler(fh)
    logger.addHandler(sh)
    logger.propagate = False

    return logger
