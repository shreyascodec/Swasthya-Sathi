@echo off
title Swasthya Sathi - KIOSK (single origin, http://localhost:8000)
cd /d "%~dp0"

REM Production launcher: ONE process, ONE origin, no Vite dev server.
REM The backend serves the built SPA from frontend\dist at "/" and the API at
REM "/api" (server\main.py), so the browser never crosses an origin and there is
REM no CORS and no second port to keep alive.
REM
REM Use start_react.bat instead for DEVELOPMENT (hot reload on :5173).

set "PYTHON=C:\Users\shrey\AppData\Local\Programs\Python\Python312\python.exe"

REM --- server configuration (see .env.example for the full list) ---
if not defined SS_ENV set "SS_ENV=dev_4060"
if not defined SS_HOST set "SS_HOST=127.0.0.1"
if not defined SS_PORT set "SS_PORT=8000"
if not defined SS_WARMUP set "SS_WARMUP=1"
if not defined SS_LOG_LEVEL set "SS_LOG_LEVEL=INFO"

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
echo Starting Swasthya Sathi on http://localhost:8000
echo   UI  http://localhost:8000
echo   API http://localhost:8000/api
echo.
echo Requires: Ollama running (summary model) and models\weights\ present.
echo Models warm up at startup (SS_WARMUP=1); the UI shows "Warming up" until ready.
echo Close this window to stop the kiosk.
echo.
"%PYTHON%" -m uvicorn server.main:app --host %SS_HOST% --port %SS_PORT%
pause
