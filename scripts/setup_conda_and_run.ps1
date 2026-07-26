#!/usr/bin/env pwsh
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Path $MyInvocation.MyCommand.Path -Parent
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

$installer = Join-Path $env:TEMP "Miniconda3-latest-Windows-x86_64.exe"
$condaPath = Join-Path $env:USERPROFILE "miniconda3\Scripts\conda.exe"

if (-not (Test-Path $condaPath)) {
  Write-Host "Downloading Miniconda to $installer..."
  Invoke-WebRequest -Uri "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe" -OutFile $installer -UseBasicParsing
  Write-Host "Installing Miniconda (silent)..."
  Start-Process -FilePath $installer -ArgumentList "/InstallationType=JustMe","/RegisterPython=0","/S","/D=$env:USERPROFILE\miniconda3" -Wait
  if (-not (Test-Path $condaPath)) { Write-Error "Conda install failed"; exit 1 }
}

Write-Host "Conda available at $condaPath"

Write-Host "Creating conda env 'ppe' with Python 3.11..."
& $condaPath create -y -n ppe python=3.11 -c conda-forge

Write-Host "Installing binary packages via conda-forge (numpy, opencv, fastapi, uvicorn, python-multipart)..."
& $condaPath install -y -n ppe -c conda-forge numpy=1.26.4 opencv fastapi uvicorn python-multipart

Write-Host "Upgrading pip and installing ultralytics via pip inside env..."
& $condaPath run -n ppe pip install --upgrade pip setuptools wheel
& $condaPath run -n ppe pip install ultralytics

Set-Location $repoRoot
Set-Location (Join-Path $repoRoot "backend")

if (Test-Path "requirements.txt") {
  Write-Host "Installing remaining requirements from requirements.txt..."
  & $condaPath run -n ppe pip install -r requirements.txt || Write-Host "Some pip installs may have been skipped or already satisfied."
}

Write-Host "Starting uvicorn in conda env 'ppe' (Ctrl+C to stop)..."
& $condaPath run -n ppe uvicorn main:app --host 0.0.0.0 --port 8000
