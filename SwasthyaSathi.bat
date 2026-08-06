@echo off
title Swasthya Sathi
cd /d "%~dp0"

REM Daily launcher. If first-run setup is incomplete, runs setup automatically.

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY (
  where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
REM Fallback to a freshly installed per-user Python (PATH may not be refreshed yet).
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PY (
  echo Python was not found. Please run setup.bat first.
  pause
  exit /b 1
)

if not exist "%~dp0runtime\setup_state.json" (
  echo First time — preparing your computer…
  %PY% "%~dp0deploy\appliance_setup.py" --gui --start
  exit /b %ERRORLEVEL%
)

%PY% "%~dp0deploy\appliance_setup.py" --start-only
if errorlevel 1 (
  echo.
  echo The app could not start. Trying repair setup…
  %PY% "%~dp0deploy\appliance_setup.py" --gui --start --force
)
exit /b %ERRORLEVEL%
