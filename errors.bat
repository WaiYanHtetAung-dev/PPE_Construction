@echo off
cd /d "%~dp0"

if exist "backend\logs.log" (
  powershell -NoProfile -Command "Get-Content -Path 'backend\\logs.log' -Tail 200 -Wait | Select-String -Pattern 'error' -SimpleMatch"
) else (
  echo No backend\logs.log found.
)
