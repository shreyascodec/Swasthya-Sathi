@echo off
title Swasthya Sathi - KIOSK (http://localhost:8000)
cd /d "%~dp0"

REM Production launcher: ONE process, ONE origin.
REM Delegates to the appliance bootstrap so Python/Ollama/device config stay automatic.

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY (
  where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo Python was not found. Run setup.bat once, then try again.
  pause
  exit /b 1
)

if not exist "%~dp0runtime\setup_state.json" (
  %PY% "%~dp0deploy\appliance_setup.py" --gui --start
  exit /b %ERRORLEVEL%
)

%PY% "%~dp0deploy\appliance_setup.py" --start-only
exit /b %ERRORLEVEL%
