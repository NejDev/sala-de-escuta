<#
Copies the room's data from the server to this PC (data/, .env, playlists.json): one folder per day,
keeping the last 14. If the server is ever lost, a new one plus the latest folder brings the room back.

  .\scripts\backup-from-server.ps1 -Server ubuntu@<ip>             # one backup now
  .\scripts\backup-from-server.ps1 -Server ubuntu@<ip> -Install    # and every day at noon (or as soon as the PC is on)
  .\scripts\backup-from-server.ps1 -Remove                         # stop the daily backup
#>
param(
  [string] $Server,
  [string] $Key = "$env:USERPROFILE\.ssh\sala-oracle",
  [string] $Destination = "$env:USERPROFILE\sala-backup",
  [int] $Keep = 14,
  [switch] $Install,
  [switch] $Remove
)
$TaskName = 'Sala de escuta - backup'
if ($Remove) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  "Daily backup removed."
  return
}
if (-not $Server) { throw "Say which server: -Server ubuntu@<ip>" }
if ($Install) {
  $arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Server $Server -Key `"$Key`" -Destination `"$Destination`" -Keep $Keep"
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
  $trigger = New-ScheduledTaskTrigger -Daily -At 12:00
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
  "Daily backup registered as '$TaskName'."
}

$target = Join-Path $Destination (Get-Date -Format 'yyyy-MM-dd')
New-Item -ItemType Directory -Force $target | Out-Null
$sources = 'data', '.env', 'playlists.json' | ForEach-Object { "${Server}:sala-de-escuta/$_" }
& scp -q -i $Key -o BatchMode=yes -o ConnectTimeout=20 -r @sources $target
$result = if ($LASTEXITCODE -eq 0) { "ok $target" } else { "FAILED (is the server up?)" }
"$(Get-Date -Format 's') $result" | Add-Content (Join-Path $Destination 'backup.log')
if ($LASTEXITCODE -ne 0) { Write-Warning "Backup failed (is the server up?)"; exit 1 }
Get-ChildItem $Destination -Directory | Sort-Object Name -Descending | Select-Object -Skip $Keep | Remove-Item -Recurse -Force
"Backup saved in $target"
