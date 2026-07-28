# Swasthya Sathi — Windows kiosk autostart installer.
#
# Registers a Scheduled Task that launches start_kiosk.bat at logon, so the kiosk
# comes back up after a reboot. This is the Windows counterpart to the systemd
# unit used on the Orin. Run from an elevated PowerShell:
#
#   powershell -ExecutionPolicy Bypass -File deploy\install_windows_startup.ps1
#
# Uninstall:
#   Unregister-ScheduledTask -TaskName "SwasthyaSathiKiosk" -Confirm:$false

param(
    [string]$TaskName = "SwasthyaSathiKiosk"
)

$ErrorActionPreference = "Stop"

# Repo root = parent of this script's folder.
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Bat = Join-Path $RepoRoot "start_kiosk.bat"

if (-not (Test-Path $Bat)) {
    throw "start_kiosk.bat not found at $Bat"
}

Write-Host "Repo root : $RepoRoot"
Write-Host "Launcher  : $Bat"

$action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Bat`"" -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
# Keep it alive; relaunch if it stops.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Task '$TaskName' exists — replacing."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Swasthya Sathi kiosk (relaunch at logon)" | Out-Null

Write-Host "Installed scheduled task '$TaskName'. It will start the kiosk at next logon."
Write-Host "Start it now with:  Start-ScheduledTask -TaskName $TaskName"
