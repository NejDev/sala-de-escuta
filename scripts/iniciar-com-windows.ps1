<#
.SYNOPSIS
  Abre o painel da Sala de escuta escondido (sem janela) toda vez que voce entra no Windows.
  Os amigos so conseguem entrar com o painel aberto; assim voce nao precisa lembrar.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\iniciar-com-windows.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\iniciar-com-windows.ps1 -Remover
#>
param(
    [switch]$Remover
)

$ErrorActionPreference = 'Stop'
$taskName = 'Sala de escuta - painel'

if ($Remover) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Tarefa '$taskName' removida. O painel nao abre mais sozinho."
    return
}

$projectDir = Split-Path -Parent $PSScriptRoot
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) { throw 'pythonw.exe nao encontrado no PATH.' }

$action = New-ScheduledTaskAction -Execute $pythonw -Argument '-m spotify_assistant ui --no-browser' -WorkingDirectory $projectDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
# Sem limite de tempo (e um servidor); se cair por erro, tenta de novo a cada minuto (ate 5 vezes).
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Abre o painel da Sala de escuta (porta 8888) ao entrar no Windows, para os amigos acessarem.' -Force | Out-Null

Write-Host "Tarefa '$taskName' criada: o painel abre sozinho, escondido, quando voce entrar no Windows."
Write-Host "Abrir agora:    Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Fechar agora:   Stop-ScheduledTask -TaskName '$taskName'"
Write-Host "Desfazer:       powershell -ExecutionPolicy Bypass -File .\scripts\iniciar-com-windows.ps1 -Remover"
