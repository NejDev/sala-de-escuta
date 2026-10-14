<#
.SYNOPSIS
  Agenda a atualizacao semanal da Tech Radar BR no Agendador de Tarefas do Windows.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\agendar-semanal.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\agendar-semanal.ps1 -Dia Friday -Hora 18:30
#>
param(
    [ValidateSet('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')]
    [string]$Dia = 'Monday',
    [string]$Hora = '09:00'
)

$ErrorActionPreference = 'Stop'
$taskName = 'Spotify Assistant - Tech Radar BR'
$projectDir = Split-Path -Parent $PSScriptRoot

$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) { throw 'pythonw.exe nao encontrado no PATH.' }

$action = New-ScheduledTaskAction -Execute $pythonw -Argument '-m spotify_assistant weekly' -WorkingDirectory $projectDir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Dia -At $Hora
# StartWhenAvailable: se o PC estiver desligado no horario, roda assim que ligar.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Atualiza a playlist Tech Radar BR com os episodios novos da semana.' -Force | Out-Null

Write-Host "Tarefa '$taskName' agendada: $Dia as $Hora."
Write-Host "Rodar agora:  Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Remover:      Unregister-ScheduledTask -TaskName '$taskName'"
Write-Host "Log:          $projectDir\data\assistant.log"
