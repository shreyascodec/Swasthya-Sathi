@echo off
title Swasthya Sathi - React UI (API :8000 + web :5173)
cd /d "%~dp0"

set "PYTHON=C:\Users\shrey\AppData\Local\Programs\Python\Python312\python.exe"

echo Starting FastAPI backend on http://localhost:8000 ...
start "Swasthya Sathi API" cmd /k ""%PYTHON%" -m uvicorn server.main:app --port 8000"

echo Starting React frontend on http://localhost:5173 ...
cd frontend
start "Swasthya Sathi Web" cmd /k "npm run dev"

echo.
echo Two windows opened:
echo   - API      http://localhost:8000
echo   - Web UI   http://localhost:5173  ^<-- open this in your browser
echo.
echo Close those windows to stop the servers.
pause >nul
