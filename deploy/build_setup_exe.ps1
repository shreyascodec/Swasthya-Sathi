# Build a THIN Setup.exe (launcher only — no torch/OCR wheels inside the exe).
# Run from repo root:
#   powershell -ExecutionPolicy Bypass -File deploy\build_setup_exe.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "Creating venv…"
    py -3 -m venv .venv
}

& $Py -m pip install -q --upgrade pip pyinstaller

$Dist = Join-Path $Root "deploy\_pyinstaller_dist"
$Work = Join-Path $Root "deploy\_pyinstaller_work"
$Entry = Join-Path $Root "deploy\setup_launcher.py"

Remove-Item $Dist, $Work -Recurse -Force -ErrorAction SilentlyContinue

# Exclude ML stacks so the exe stays a small launcher (~10 MB).
& $Py -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --name Setup `
    --distpath $Dist `
    --workpath $Work `
    --specpath (Join-Path $Root "deploy") `
    --exclude-module torch `
    --exclude-module torchvision `
    --exclude-module torchaudio `
    --exclude-module cv2 `
    --exclude-module onnxruntime `
    --exclude-module transformers `
    --exclude-module faster_whisper `
    --exclude-module rapidocr `
    --exclude-module huggingface_hub `
    --exclude-module numpy `
    --exclude-module PIL `
    $Entry

$Built = Join-Path $Dist "Setup.exe"
if (-not (Test-Path $Built)) { throw "Setup.exe was not produced at $Built" }
Copy-Item $Built (Join-Path $Root "Setup.exe") -Force
Write-Host "OK: $Root\Setup.exe"
Write-Host "Keep Setup.exe in the same folder as deploy\, config\, server\, frontend\."
