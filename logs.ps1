#!/usr/bin/env pwsh
Set-StrictMode -Version Latest
$scriptDir = Split-Path -Path $MyInvocation.MyCommand.Path -Parent
Set-Location $scriptDir

$log = Join-Path $scriptDir "backend\logs.log"
$errLog = Join-Path $scriptDir "backend\logs.err.log"

if (Test-Path $log) {
  Write-Host "--- tailing backend/logs.log (Ctrl+C to stop) ---"
  Get-Content -Path $log -Tail 200 -Wait
} elseif (Test-Path $errLog) {
  Get-Content -Path $errLog -Tail 200 -Wait
} else {
  Write-Host "No backend/logs.log found yet. Start the app first with .\run.ps1"
}
