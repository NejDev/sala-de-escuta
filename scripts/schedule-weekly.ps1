<#
.SYNOPSIS
  Schedules the weekly Tech Radar BR update in Windows Task Scheduler.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\schedule-weekly.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\schedule-weekly.ps1 -Day Friday -Time 18:30
#>
param(
    [ValidateSet('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')]
    [Alias('Dia')]
    [string]$Day = 'Monday',
    [Alias('Hora')]
    [string]$Time = '09:00'
)

$ErrorActionPreference = 'Stop'
$taskName = 'Spotify Assistant - Tech Radar BR'
$projectDir = Split-Path -Parent $PSScriptRoot

$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) { throw 'pythonw.exe not found in PATH.' }

$action = New-ScheduledTaskAction -Execute $pythonw -Argument '-m spotify_assistant weekly' -WorkingDirectory $projectDir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $Time
# StartWhenAvailable: if the PC is off at the scheduled time, it runs as soon as it's turned on.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Updates the Tech Radar BR playlist with the new episodes of the week.' -Force | Out-Null

Write-Host "Task '$taskName' scheduled: $Day at $Time."
Write-Host "Run now:      Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Remove:       Unregister-ScheduledTask -TaskName '$taskName'"
Write-Host "Log:          $projectDir\data\assistant.log"
