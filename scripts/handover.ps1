# Hands the Telegram bot over to the candidate's phone, in one go:
#   1. stops the hunter, 2. forgets the test jobs so the candidate gets every good match fresh,
#   3. waits up to 10 minutes for the candidate to press Start in the bot (your chat becomes the admin chat:
#      errors keep coming to you, jobs go to them), 4. starts the hunter again.
# Usage (PowerShell, in the project folder): .\scripts\handover.ps1 -Who alex
param([Parameter(Mandatory = $true)][string]$Who)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$task = "Job Hunter - $Who"
$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*hunter*--who $Who*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }

& $py -m hunter --who $Who reset --yes
& $py -m hunter --who $Who telegram --wait 600

Start-ScheduledTask -TaskName $task
Write-Host "Hunter running again. Check with: $py -m hunter --who $Who doctor"
