@echo off
title Swasthya Sathi — Setup
cd /d "%~dp0"

REM One-click setup for non-technical users. No questions.
REM Prefer Setup.exe when present; otherwise run the Python bootstrap.

if exist "%~dp0Setup.exe" (
  start "" "%~dp0Setup.exe"
  exit /b 0
)

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
  echo Python was not found. Please install Python 3.12 from python.org and try again.
  pause
  exit /b 1
)

echo Preparing Swasthya Sathi — please wait. This can take several minutes the first time.
echo.
%PY% "%~dp0deploy\appliance_setup.py" --gui --start
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
  echo.
  echo Setup could not finish. See logs\setup.log
  pause
)
exit /b %EC%
