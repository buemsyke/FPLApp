#!/bin/bash
# Einrichtung für den Skill (macOS/Linux, ohne Administratorrechte):
# Python 3.12, pdftotext und die Prüfpakete im Benutzerordner.
# Dieselbe Umgebung nutzt die App GutachtenAbiturklausur.
source "$(cd "$(dirname "$0")" && pwd)/umgebung.sh" || exit 1
umgebung_einrichten && umgebung_pruefen
