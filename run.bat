@echo off
cd /d "%~dp0"

if "%PPE_PORT%"=="" set "PPE_PORT=8000"

if exist ".ppe_platform.pid" (
  set /p OLDPID=<.ppe_platform.pid
  tasklist /FI "PID eq %OLDPID%" 2>nul | findstr /I "%OLDPID%" >nul
  if not errorlevel 1 (
    echo Already running ^(PID %OLDPID%^) at http://localhost:%PPE_PORT%
    goto :eof
  )
)

if not exist ".venv" (
  echo Creating virtual environment...
  python -m venv .venv
)

call .venv\Scripts\activate.bat
pip install --upgrade pip >nul
pip install -r backend\requirements.txt >nul

if not exist "backend" mkdir backend
type nul > backend\logs.log

echo.
echo Starting PPE Detect Platform on http://localhost:%PPE_PORT%
echo Logging to backend\logs.log
echo.

powershell -NoProfile -Command "& {
  $root = '%CD%';
  $log = Join-Path $root 'backend\logs.log';
  $proc = Start-Process -FilePath (Join-Path $root '.venv\Scripts\python.exe') -ArgumentList '-m','uvicorn','main:app','--host','0.0.0.0','--port','%PPE_PORT%' -WorkingDirectory (Join-Path $root 'backend') -RedirectStandardOutput $log -RedirectStandardError (Join-Path $root 'backend\logs.err.log') -WindowStyle Hidden -PassThru;
  $proc.Id | Out-File -FilePath (Join-Path $root '.ppe_platform.pid') -Encoding ascii;
  Write-Host ('Started with PID ' + $proc.Id)
}"

echo   On this machine: http://localhost:%PPE_PORT%
echo   Logs:  logs.bat
echo   Stop:  stop.bat
echo.
