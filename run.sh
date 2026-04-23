#!/bin/bash
set -e

cd "$(dirname "$0")"

PYTHON=/usr/local/bin/python3.13

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment with $PYTHON..."
  $PYTHON -m venv .venv
fi

echo "Installing dependencies..."
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet
.venv/bin/playwright install chromium

.venv/bin/python3 main.py "$@"
