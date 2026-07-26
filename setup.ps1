#!/usr/bin/env pwsh
Set-StrictMode -Version Latest
$scriptDir = Split-Path -Path $MyInvocation.MyCommand.Path -Parent
Set-Location $scriptDir

Write-Host "Creating virtual environment (if missing)..."
if (-not (Test-Path ".venv")) {
  python -m venv .venv
}

$venvPython = Join-Path $scriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { $venvPython = "python" }

Write-Host "Installing backend Python dependencies..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r backend/requirements.txt

if (-not (Test-Path "backend")) { New-Item -ItemType Directory -Path backend | Out-Null }
$log = Join-Path $scriptDir "backend\logs.log"
if (-not (Test-Path $log)) { New-Item -Path $log -ItemType File | Out-Null }

Write-Host "Setup complete. Start the app with .\run.ps1 or ./run.sh"
