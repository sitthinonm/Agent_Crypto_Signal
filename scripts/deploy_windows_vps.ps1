# Agent Signal — Windows VPS one-shot setup (beginner-friendly)
# Run in PowerShell AS ADMINISTRATOR:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#   .\deploy_windows_vps.ps1
#
# What it does:
# - Ensures Python 3.11 (winget if available, else silent installer from python.org)
# - Downloads repo ZIP from GitHub (no git required)
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

function Refresh-PathEnv {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

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
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files (x86)\Python311-32\python.exe"
    )
    foreach ($p in $common) {
        if (Test-Path $p) { return $p }
    }

    return $null
}

function Ensure-Python311 {
    Refresh-PathEnv
    $existing = Resolve-PythonExe
    if ($existing) {
        Write-Host "==> Python already available: $existing" -ForegroundColor Green
        return $existing
    }

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "==> Installing Python 3.11 via winget..." -ForegroundColor Cyan
        winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
        Refresh-PathEnv
        $after = Resolve-PythonExe
        if ($after) { return $after }
    } else {
        Write-Host "==> winget not found (common on Windows Server). Installing Python via python.org silent installer..." -ForegroundColor Yellow
    }

    $pyVer = "3.11.9"
    $installerName = "python-$pyVer-amd64.exe"
    $installerUrl = "https://www.python.org/ftp/python/$pyVer/$installerName"
    $installerPath = Join-Path $env:TEMP $installerName

    Write-Host "==> Downloading $installerUrl ..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing

    Write-Host "==> Running silent Python install (may take 1-3 minutes)..." -ForegroundColor Cyan
    $args = @(
        "/quiet",
        "InstallAllUsers=1",
        "PrependPath=1",
        "Include_test=0",
        "Include_doc=0",
        "Include_launcher=1",
        "Include_pip=1"
    )
    $proc = Start-Process -FilePath $installerPath -ArgumentList $args -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "Python installer exited with code $($proc.ExitCode). Try reboot VPS, then re-run this script."
    }

    Refresh-PathEnv
    $final = Resolve-PythonExe
    if (-not $final) {
        throw "Python installed but not found in PATH yet. Reboot the VPS once, then re-run this script."
    }
    return $final
}

Write-Host "==> Ensuring Python 3.11..." -ForegroundColor Cyan
$pythonExe = Ensure-Python311
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
