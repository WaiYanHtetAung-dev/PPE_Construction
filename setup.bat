@echo off
cd /d "%~dp0"

if not exist ".venv" (
  echo Creating virtual environment...
  python -m venv .venv
)

call .venv\Scripts\activate.bat
pip install --upgrade pip >nul
pip install -r backend\requirements.txt

if not exist "backend" mkdir backend
if not exist "backend\logs.log" type nul > "backend\logs.log"

echo Setup complete. Start the app with run.bat or run.ps1
