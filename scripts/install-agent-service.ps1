# Registers the VxDesk remote agent as a scheduled task that starts hidden at
# logon (NSSM-free, Task Scheduler based).
#
#   powershell -ExecutionPolicy Bypass -File scripts\install-agent-service.ps1 `
#       -Server ws://192.168.1.10:8765 -Token <minted> [-AgentId shop-pc-01] [-Name "Shop PC"]
#
# Uninstall:
#   powershell -ExecutionPolicy Bypass -File scripts\install-agent-service.ps1 -Uninstall

param(
    [string]$Server,
    [string]$Token,
    [string]$AgentId = "",
    [string]$Name = "",
    [switch]$DryRunDefault,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$TaskName = "VxDeskAgent"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName'."
    exit 0
}

if (-not $Server -or -not $Token) {
    Write-Host "ERROR: -Server and -Token are required."
    Write-Host "Mint a token first: Remote page -> Add agent (or POST /api/remote/agents)."
    exit 1
}

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $RepoRoot "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "ERROR: backend venv not found at $Python — run npm run setup first."
    exit 1
}

$argList = "-m vxdesk.agent --server `"$Server`" --token `"$Token`""
if ($AgentId) { $argList += " --agent-id `"$AgentId`"" }
if ($Name)    { $argList += " --name `"$Name`"" }
if ($DryRunDefault) { $argList += " --dry-run-default" }

# hidden console: run through powershell -WindowStyle Hidden
$actionArgs = "-WindowStyle Hidden -ExecutionPolicy Bypass -Command " +
    "`"Set-Location '$RepoRoot\backend'; & '$Python' $argList`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' (hidden, starts at logon)."
Write-Host "Start it now:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Logs:          backend\logs\agent.log (or %LOCALAPPDATA%\VxDesk\logs when frozen)"
