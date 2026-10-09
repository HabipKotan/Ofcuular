#!/bin/bash
# Ders Asistani - baslatici (macOS / Linux)
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
if ! cmp -s requirements.txt .venv/kurulum_tamam.txt; then
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt
  cp requirements.txt .venv/kurulum_tamam.txt
fi
[ -f .env ] || cp .env.example .env
exec .venv/bin/python -m streamlit run app.py
