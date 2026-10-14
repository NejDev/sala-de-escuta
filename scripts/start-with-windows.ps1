<#
.SYNOPSIS
  Opens the Sala de escuta panel hidden (no window) every time you sign in to Windows.
  Friends can only get in while the panel is open; this way you don't have to remember.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\start-with-windows.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\start-with-windows.ps1 -Remove
#>
param(
    [Alias('Remover')]
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$taskName = 'Sala de escuta - painel'

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Task '$taskName' removed. The panel no longer opens on its own."
    return
}

$projectDir = Split-Path -Parent $PSScriptRoot
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) { throw 'pythonw.exe not found in PATH.' }

$action = New-ScheduledTaskAction -Execute $pythonw -Argument '-m spotify_assistant ui --no-browser' -WorkingDirectory $projectDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
# No time limit (it's a server); if it crashes, retry every minute (up to 5 times).
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Opens the Sala de escuta panel (port 8888) when you sign in to Windows, so friends can access it.' -Force | Out-Null

Write-Host "Task '$taskName' created: the panel opens on its own, hidden, when you sign in to Windows."
Write-Host "Open now:       Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Close now:      Stop-ScheduledTask -TaskName '$taskName'"
Write-Host "Undo:           powershell -ExecutionPolicy Bypass -File .\scripts\start-with-windows.ps1 -Remove"
