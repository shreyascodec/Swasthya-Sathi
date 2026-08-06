# Build the clinic-ready installer:  dist\SwasthyaSathiSetup.exe
#
#   1) Prebuilt React SPA        -> frontend\dist      (Node required on BUILD PC only)
#   2) Bundled offline installers-> deploy\bundle\     (Python + Ollama, downloaded once)
#   3) Inno Setup compile        -> dist\SwasthyaSathiSetup.exe
#
# Run from repo root:
#   powershell -ExecutionPolicy Bypass -File deploy\build_release.ps1
#
# Requirements on the BUILD PC (not the clinic PC):
#   - Node.js LTS + npm      (https://nodejs.org/)
#   - Inno Setup 6           (https://jrsoftware.org/isdl.php)  -> provides ISCC.exe
#   - Internet (first run downloads the bundled installers)
#
# The single dist\SwasthyaSathiSetup.exe is all you hand to a clinic. It works on
# a PC with NOTHING pre-installed (it bundles Python + Ollama). Internet is used
# only during the first run to download models; the app runs offline afterward.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

# Pin the Python that ships inside the installer (per-user, silent).
$PyVer      = "3.12.7"
$PyUrl      = "https://www.python.org/ftp/python/$PyVer/python-$PyVer-amd64.exe"
# Ollama is NOT bundled (keeps the installer ~1 GB smaller). appliance_setup.py
# installs it via winget / direct download on first run. To ship it offline,
# uncomment the download below and re-add the Source line in installer.iss.
# $OllamaUrl = "https://ollama.com/download/OllamaSetup.exe"

Write-Host "== Swasthya Sathi installer build =="
Write-Host "Root: $Root"

# --- 1) Frontend (prebuilt for the installer) --------------------------------
# Refresh PATH in case Node was installed in this Windows session.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

$npmCmd = $null
$cmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($cmd) { $npmCmd = $cmd.Source }
if (-not $npmCmd) {
    $candidates = @(
        "$env:ProgramFiles\nodejs\npm.cmd",
        "${env:ProgramFiles(x86)}\nodejs\npm.cmd",
        "$env:LOCALAPPDATA\Programs\node\npm.cmd"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $npmCmd = $c; break }
    }
}
if (-not $npmCmd) {
    throw @"
Node.js / npm was not found on this build PC.
Install Node.js LTS from https://nodejs.org/ then open a NEW PowerShell window and re-run:
  powershell -ExecutionPolicy Bypass -File deploy\build_release.ps1
(Clinic kiosks do NOT need Node — only the machine that builds the installer.)
"@
}

$Frontend = Join-Path $Root "frontend"
Write-Host "Building frontend with: $npmCmd"
Push-Location $Frontend
try {
    & $npmCmd ci
    if ($LASTEXITCODE -ne 0) { & $npmCmd install }
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
    & $npmCmd run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
} finally {
    Pop-Location
}

$Index = Join-Path $Frontend "dist\index.html"
if (-not (Test-Path $Index)) {
    throw "frontend\dist\index.html missing after build"
}
Write-Host "OK: frontend\dist ready"

# --- 2) Bundled offline installers ------------------------------------------
$Bundle = Join-Path $Root "deploy\bundle"
New-Item -ItemType Directory -Force $Bundle | Out-Null

function Get-Installer([string]$Url, [string]$Dest, [string]$Label) {
    if ((Test-Path $Dest) -and ((Get-Item $Dest).Length -gt 1MB)) {
        Write-Host "OK: $Label already present ($([math]::Round((Get-Item $Dest).Length/1MB)) MB)"
        return
    }
    Write-Host "Downloading $Label ..."
    $old = $ProgressPreference; $ProgressPreference = "SilentlyContinue"
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing
    } finally {
        $ProgressPreference = $old
    }
    if (-not (Test-Path $Dest) -or ((Get-Item $Dest).Length -le 1MB)) {
        throw "$Label download failed or too small: $Url"
    }
    Write-Host "OK: $Label ($([math]::Round((Get-Item $Dest).Length/1MB)) MB)"
}

Get-Installer $PyUrl (Join-Path $Bundle "python-installer.exe") "Python $PyVer"
# Ollama intentionally not bundled (see note above).

# --- 3) Inno Setup compile ---------------------------------------------------
$Iscc = $null
foreach ($c in @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)) { if (Test-Path $c) { $Iscc = $c; break } }
if (-not $Iscc) {
    $g = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($g) { $Iscc = $g.Source }
}
if (-not $Iscc) {
    throw @"
Inno Setup (ISCC.exe) was not found on this build PC.
Install Inno Setup 6 from https://jrsoftware.org/isdl.php then re-run:
  powershell -ExecutionPolicy Bypass -File deploy\build_release.ps1
"@
}

$Iss = Join-Path $Root "deploy\installer.iss"
Write-Host "Compiling installer with: $Iscc"
& $Iscc $Iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed" }

$Out = Join-Path $Root "dist\SwasthyaSathiSetup.exe"
if (-not (Test-Path $Out)) { throw "Installer was not produced at $Out" }

Write-Host ""
Write-Host "Installer ready:"
Write-Host "  $Out   ($([math]::Round((Get-Item $Out).Length/1MB)) MB)"
Write-Host ""
Write-Host "Hand this single file to the clinic. They double-click it:"
Write-Host "  Next -> Install -> Finish, then wait once while models download."
Write-Host "Every day after: the 'Swasthya Sathi' desktop shortcut."
Write-Host ""
Write-Host "NOTE: unsigned installer -> SmartScreen may show 'Windows protected your PC'."
Write-Host "      Click 'More info' -> 'Run anyway' the first time."
