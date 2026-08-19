param(
  [switch]$Background,
  [switch]$InstallStartup,
  [switch]$UninstallStartup
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$taskName = 'GoFly'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$healthUrl = 'http://127.0.0.1:8787/api/health'
$scriptPath = Join-Path $PSScriptRoot 'start.ps1'

function Test-GoFlyUp {
  try {
    $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
    return $resp.StatusCode -eq 200
  } catch {
    return $false
  }
}

if ($UninstallStartup) {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "Uninstalled startup task: $taskName"
  exit 0
}

if ($InstallStartup) {
  $arg = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $scriptPath + '" -Background'
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg -WorkingDirectory $PSScriptRoot
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
  Write-Host "Registered logon startup: $taskName -> http://127.0.0.1:8787"
  exit 0
}

if (Test-GoFlyUp) {
  Write-Host 'GoFly already running -> http://127.0.0.1:8787'
  exit 0
}

if (-not (Test-Path .venv)) {
  uv venv .venv
  uv pip install -r requirements.txt --python .venv
}
if (-not (Test-Path config.yaml)) {
  Copy-Item config.example.yaml config.yaml
}

Write-Host 'GoFly -> http://127.0.0.1:8787'
if ($Background) {
  $logDir = Join-Path $PSScriptRoot 'logs'
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
  $log = Join-Path $logDir 'gofly.log'
  & $python -m app.main *>> $log
} else {
  & $python -m app.main
}
