@echo off
title Swasthya Sathi - KIOSK (single origin, http://localhost:8000)
cd /d "%~dp0"

REM Production launcher: ONE process, ONE origin, no Vite dev server.
REM The backend serves the built SPA from frontend\dist at "/" and the API at
REM "/api" (server\main.py), so the browser never crosses an origin and there is
REM no CORS and no second port to keep alive.
REM
REM This launcher also (1) makes sure Ollama is up (the summary stage needs it)
REM and (2) opens Chrome at the kiosk URL once the server answers, so a single
REM double-click brings the whole appliance up on screen.
REM
REM Use start_react.bat instead for DEVELOPMENT (hot reload on :5173).

set "PYTHON=C:\Users\shrey\AppData\Local\Programs\Python\Python312\python.exe"
set "OLLAMA=C:\Users\shrey\AppData\Local\Programs\Ollama\ollama.exe"

REM --- server configuration (see .env.example for the full list) ---
if not defined SS_ENV set "SS_ENV=dev_4060"
if not defined SS_HOST set "SS_HOST=127.0.0.1"
if not defined SS_PORT set "SS_PORT=8000"
if not defined SS_WARMUP set "SS_WARMUP=1"
if not defined SS_LOG_LEVEL set "SS_LOG_LEVEL=INFO"
set "KIOSK_URL=http://localhost:%SS_PORT%"

REM --- locate Chrome (Program Files, then x86) ---
set "CHROME="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"

REM --- ensure Ollama (summary LLM) is running; start it if the API is down ---
curl -s -m 2 http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
  echo Ollama not responding - starting it ...
  if exist "%OLLAMA%" (
    start "Ollama" /min "%OLLAMA%" serve
  ) else (
    start "Ollama" /min ollama serve
  )
)

if not exist "frontend\dist\index.html" goto build
echo Found an existing frontend build.
choice /C YN /T 8 /D N /M "Rebuild the UI first"
if errorlevel 2 goto serve

:build
echo.
echo Building the kiosk UI (frontend\dist) ...
cd frontend
call npm ci
if errorlevel 1 call npm install
call npm run build
if errorlevel 1 (
  echo.
  echo BUILD FAILED - not starting. Fix the error above and re-run.
  pause
  exit /b 1
)
cd ..

:serve
echo.
echo Starting Swasthya Sathi on %KIOSK_URL%
echo   UI  %KIOSK_URL%
echo   API %KIOSK_URL%/api
echo.
echo Requires: Ollama running (summary model) and models\weights\ present.
echo Models warm up at startup (SS_WARMUP=1); the UI shows "Warming up" until ready.
echo Close this window to stop the kiosk.
echo.

REM --- open Chrome once the server answers, without blocking uvicorn ---
REM A hidden PowerShell child polls /api/health (200 as soon as the process is
REM up, even while models warm) then opens Chrome in app mode on an isolated
REM profile so the flags are honoured and the user's normal Chrome is untouched.
REM The poll uses curl.exe against 127.0.0.1 on purpose: uvicorn binds
REM 127.0.0.1 only, and Windows resolves "localhost" to IPv6 ::1 first, which a
REM PowerShell Invoke-WebRequest would stall on (and "curl" is aliased to it in
REM PS 5.1 - hence the explicit .exe). For a locked, full-screen appliance swap
REM '--app=' for '--kiosk' below.
if defined CHROME (
  start "" /b powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 90;$i++){ & curl.exe -s -m 2 -o NUL http://127.0.0.1:%SS_PORT%/api/health; if($LASTEXITCODE -eq 0){break}; Start-Sleep 1 }; Start-Process '%CHROME%' -ArgumentList '--app=%KIOSK_URL%','--user-data-dir=%TEMP%\ss_kiosk_chrome','--start-maximized','--no-first-run','--no-default-browser-check'"
) else (
  echo Chrome not found - open %KIOSK_URL% in a browser manually.
)

"%PYTHON%" -m uvicorn server.main:app --host %SS_HOST% --port %SS_PORT%
pause
