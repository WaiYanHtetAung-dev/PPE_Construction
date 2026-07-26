#!/usr/bin/env pwsh
# Starts the PPE Detect platform in the background on a fixed port (default
# 8000, override with $env:PPE_PORT) and hands the terminal back immediately.
# Use .\logs.ps1 to watch logs and .\stop.ps1 to stop it.
Set-StrictMode -Version Latest
$scriptDir = Split-Path -Path $MyInvocation.MyCommand.Path -Parent
Set-Location $scriptDir

$port = if ($env:PPE_PORT) { $env:PPE_PORT } else { 8000 }
$pidFile = Join-Path $scriptDir ".ppe_platform.pid"
$logFile = Join-Path $scriptDir "backend\logs.log"

if (Test-Path $pidFile) {
  $existingPid = Get-Content $pidFile -ErrorAction SilentlyContinue
  if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
    Write-Host "Already running (PID $existingPid) at http://localhost:$port"
    exit 0
  }
}

if (-not (Test-Path ".venv")) {
  Write-Host "Creating virtual environment..."
  python -m venv .venv
}

$venvPython = Join-Path $scriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { $venvPython = "python" }

& $venvPython -m pip install --upgrade pip | Out-Null
& $venvPython -m pip install -r backend/requirements.txt | Out-Null

if (-not (Test-Path "backend")) { New-Item -ItemType Directory -Path backend | Out-Null }
"" | Set-Content -Path $logFile   # start each run with a clean log file

$proc = Start-Process -FilePath $venvPython `
  -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "$port" `
  -WorkingDirectory (Join-Path $scriptDir "backend") `
  -RedirectStandardOutput $logFile `
  -RedirectStandardError (Join-Path $scriptDir "backend\logs.err.log") `
  -WindowStyle Hidden `
  -PassThru

$proc.Id | Out-File -FilePath $pidFile -Encoding ascii

Start-Sleep -Seconds 2
if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
  Write-Host "Failed to start -- check backend/logs.log and backend/logs.err.log (or run .\errors.ps1)."
  Remove-Item $pidFile -ErrorAction SilentlyContinue
  exit 1
}

$lanIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  Where-Object { $_.InterfaceAlias -notmatch 'Loopback' -and $_.IPAddress -notlike '169.254*' } |
  Select-Object -First 1 -ExpandProperty IPAddress)

Write-Host ""
Write-Host "PPE Detect Platform is running (PID $($proc.Id))"
Write-Host "  On this machine: http://localhost:$port"
if ($lanIp) {
  Write-Host "  On your LAN:     http://$($lanIp):$port"
}
Write-Host "  Logs:  .\logs.ps1"
Write-Host "  Stop:  .\stop.ps1"
Write-Host ""
