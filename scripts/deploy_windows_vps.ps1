# Agent Signal — Windows VPS one-shot setup (beginner-friendly)
# Run in PowerShell AS ADMINISTRATOR:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#   .\deploy_windows_vps.ps1
#
# What it does:
# - Installs Python 3.11 + Git via winget (if missing)
# - Downloads repo ZIP from GitHub (no manual git clone)
# - Creates venv, pip install, copies .env.example -> .env
# - Opens Windows Firewall TCP 8080
# - Registers a startup Scheduled Task to keep API running

$ErrorActionPreference = "Stop"

function Test-Administrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Administrator)) {
    Write-Host "ERROR: Run PowerShell as Administrator (right-click -> Run as administrator)." -ForegroundColor Red
    exit 1
}

$RepoZipUrl = "https://github.com/sitthinonm/Agent_Crypto_Signal/archive/refs/heads/main.zip"
$InstallRoot = "C:\apps"
$AppDir = Join-Path $InstallRoot "Agent_Crypto_Signal-main"
$Port = 8080

Write-Host "==> Preparing folders..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

Write-Host "==> Ensuring winget is available..." -ForegroundColor Cyan
$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $winget) {
    Write-Host "ERROR: winget not found. Install 'App Installer' from Microsoft Store, or use Windows 10/11 with updates, then re-run this script." -ForegroundColor Red
    exit 1
}

Write-Host "==> Installing Python 3.11 (if missing)..." -ForegroundColor Cyan
winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements

Write-Host "==> Installing Git (if missing)..." -ForegroundColor Cyan
winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements

# Refresh PATH for this session (best-effort)
$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = "$machinePath;$userPath"

function Resolve-PythonExe {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $out = & py -3.11 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return $out.Trim() }
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) { return $pythonCmd.Source }

    $common = @(
        "$env:LocalAppData\Programs\Python\Python311\python.exe",
        "C:\Program Files\Python311\python.exe"
    )
    foreach ($p in $common) {
        if (Test-Path $p) { return $p }
    }

    throw "Python not found after install. Reboot the VPS once, then re-run this script."
}

Write-Host "==> Resolving python.exe..." -ForegroundColor Cyan
$pythonExe = Resolve-PythonExe
Write-Host "Using: $pythonExe" -ForegroundColor DarkGray

Write-Host "==> Downloading project ZIP (no git required)..." -ForegroundColor Cyan
$zipPath = Join-Path $env:TEMP "Agent_Crypto_Signal-main.zip"
Invoke-WebRequest -Uri $RepoZipUrl -OutFile $zipPath -UseBasicParsing

Write-Host "==> Extracting ZIP..." -ForegroundColor Cyan
if (Test-Path $AppDir) {
    Remove-Item -Recurse -Force $AppDir
}
Expand-Archive -Path $zipPath -DestinationPath $InstallRoot -Force

if (-not (Test-Path $AppDir)) {
    throw "Expected folder not found after extract: $AppDir"
}

Push-Location $AppDir
try {
    Write-Host "==> Creating virtual environment..." -ForegroundColor Cyan
    & $pythonExe -m venv .venv

    $pip = Join-Path $AppDir ".venv\Scripts\pip.exe"
    $pyVenv = Join-Path $AppDir ".venv\Scripts\python.exe"

    Write-Host "==> Installing dependencies..." -ForegroundColor Cyan
    & $pip install --upgrade pip
    & $pip install -r (Join-Path $AppDir "requirements.txt")

    $envFile = Join-Path $AppDir ".env"
    if (-not (Test-Path $envFile)) {
        Copy-Item (Join-Path $AppDir ".env.example") $envFile -Force
    }

    Write-Host "==> Opening Windows Firewall for TCP $Port..." -ForegroundColor Cyan
    $ruleName = "Agent Signal API $Port"
    if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
    }

    $runBat = Join-Path $AppDir "run_api.bat"
    @"
@echo off
cd /d $AppDir
call .\.venv\Scripts\activate.bat
python -m uvicorn analyzer_service.main:app --host 0.0.0.0 --port $Port
"@ | Set-Content -Path $runBat -Encoding ASCII

    Write-Host "==> Registering Scheduled Task (runs at startup)..." -ForegroundColor Cyan
    $taskName = "AgentSignalAPI"
    $action = New-ScheduledTaskAction -Execute $runBat -WorkingDirectory $AppDir
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

    Write-Host "==> Starting task now..." -ForegroundColor Cyan
    Start-ScheduledTask -TaskName $taskName

    Write-Host ""
    Write-Host "DONE." -ForegroundColor Green
    Write-Host "Health check (from your PC browser):" -ForegroundColor Yellow
    Write-Host "  http://YOUR_VPS_PUBLIC_IP:$Port/health"
    Write-Host ""
    Write-Host "GAS Script Property:" -ForegroundColor Yellow
    Write-Host "  ANALYZER_URL=http://YOUR_VPS_PUBLIC_IP:$Port/analyze"
    Write-Host ""
    Write-Host "If Binance still blocks this VPS IP, change BINANCE_FAPI_BASE_URL in .env and restart the scheduled task." -ForegroundColor DarkYellow
}
finally {
    Pop-Location
}
