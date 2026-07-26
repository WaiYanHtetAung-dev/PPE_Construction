#!/usr/bin/env pwsh
Set-StrictMode -Version Latest
$scriptDir = Split-Path -Path $MyInvocation.MyCommand.Path -Parent
Set-Location $scriptDir

$pidFile = Join-Path $scriptDir ".ppe_platform.pid"
$stopped = $false

if (Test-Path $pidFile) {
  $savedPid = Get-Content $pidFile -ErrorAction SilentlyContinue
  if ($savedPid -and (Get-Process -Id $savedPid -ErrorAction SilentlyContinue)) {
    Stop-Process -Id $savedPid -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped PPE Detect Platform (PID $savedPid)."
    $stopped = $true
  }
  Remove-Item $pidFile -ErrorAction SilentlyContinue
}

if (-not $stopped) {
  # Fallback: find any uvicorn/main:app process, regardless of port.
  $procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match 'main:app' }
  if ($procs) {
    foreach ($p in $procs) {
      Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
      Write-Host "Stopped PID $($p.ProcessId) ($($p.CommandLine))"
      $stopped = $true
    }
  }
}

if (-not $stopped) { Write-Host "No running PPE Detect Platform process found." }
