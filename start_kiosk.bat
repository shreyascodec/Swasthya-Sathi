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
echo Close this window to stop the kiosk.
echo.
"%PYTHON%" -m uvicorn server.main:app --host 127.0.0.1 --port 8000
pause
