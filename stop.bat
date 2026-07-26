@echo off
cd /d "%~dp0"

set "STOPPED=0"

if exist ".ppe_platform.pid" (
  set /p SAVEDPID=<.ppe_platform.pid
  tasklist /FI "PID eq %SAVEDPID%" 2>nul | findstr /I "%SAVEDPID%" >nul
  if not errorlevel 1 (
    echo Stopping PPE Detect Platform ^(PID %SAVEDPID%^)...
    taskkill /PID %SAVEDPID% /F >nul 2>&1
    set "STOPPED=1"
  )
  del /f /q ".ppe_platform.pid" >nul 2>&1
)

if "%STOPPED%"=="0" (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr LISTENING ^| findstr /I ":800"') do (
    echo Stopping process listening on a PPE-range port ^(PID %%a^)
    taskkill /PID %%a /F >nul 2>&1
    set "STOPPED=1"
  )
)

if "%STOPPED%"=="0" echo No running PPE Detect Platform process found.
