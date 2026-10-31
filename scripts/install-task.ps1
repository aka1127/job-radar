# Registers a Windows scheduled task that runs the hunter in the background, with no window to close by mistake.
# It starts at logon and every 10 minutes checks it is still running (a second copy is never started).
# Usage (PowerShell): .\scripts\install-task.ps1 -Who alex
# Remove later with: Unregister-ScheduledTask -TaskName "Job Hunter - alex" -Confirm:$false
param([Parameter(Mandatory = $true)][string]$Who)
$root = Split-Path -Parent $PSScriptRoot
# conhost --headless: the console exists but is never shown, so closing a window or Ctrl+C cannot stop it.
$action = New-ScheduledTaskAction -Execute "conhost.exe" -Argument "--headless cmd.exe /c `"$root\scripts\loop.cmd`" $Who" `
    -WorkingDirectory $root
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit (New-TimeSpan -Days 0) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Job Hunter - $Who" -Action $action -Trigger @($atLogon, $watchdog) -Settings $settings `
    -Description "Watches jobs and sends tailored application packs for $Who" -Force | Out-Null
Start-ScheduledTask -TaskName "Job Hunter - $Who"
Write-Host "Started in the background. Logs: $root\data\$Who.log"
