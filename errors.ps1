#!/usr/bin/env pwsh
Set-StrictMode -Version Latest
$scriptDir = Split-Path -Path $MyInvocation.MyCommand.Path -Parent
Set-Location $scriptDir

$errLog = Join-Path $scriptDir "backend\logs.err.log"
$log = Join-Path $scriptDir "backend\logs.log"

if (Test-Path $errLog) {
  Write-Host "--- tailing backend/logs.err.log for errors (Ctrl+C to stop) ---"
  Get-Content -Path $errLog -Tail 200 -Wait
} elseif (Test-Path $log) {
  Get-Content -Path $log -Tail 200 -Wait | Select-String -Pattern 'error' -SimpleMatch -CaseSensitive:$false
} else {
  Write-Host "No backend/logs.err.log found. Start the app first with .\run.ps1"
}
