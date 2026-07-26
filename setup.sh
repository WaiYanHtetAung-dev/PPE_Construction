#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "Creating virtual environment (if missing)..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

echo "Installing backend Python dependencies..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r backend/requirements.txt

mkdir -p backend
touch backend/logs.log

echo "Setup complete. Start the app with ./run.sh or ./run.ps1"
