#Requires -Version 5.1
param(
    [string]$InstallDir = "$env:USERPROFILE\Fiverr Lead Extractor CRM",
    [string]$RepoZipUrl = "https://github.com/mafzalkalwardev/fiverr-lead-extractor-crm/archive/refs/heads/main.zip",
    [switch]$SkipMongoInstall,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Add-PathIfExists([string]$Path) {
    if ((Test-Path $Path) -and ($env:Path -notlike "*$Path*")) {
        $env:Path = "$Path;$env:Path"
    }
}

function Ensure-WingetPackage([string]$Id, [string]$Name) {
    if (-not (Test-Command "winget")) {
        throw "winget is required to install $Name automatically. Install App Installer from Microsoft Store, then run setup again."
    }

    Write-Step "Checking $Name"
    $installed = winget list --exact --id $Id --accept-source-agreements 2>$null
    if ($LASTEXITCODE -eq 0 -and ($installed -match [regex]::Escape($Id))) {
        Write-Host "$Name already installed." -ForegroundColor Green
        return
    }

    Write-Host "Installing $Name..."
    winget install --exact --id $Id --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install $Name with winget package id $Id."
    }
}

function Ensure-Node {
    Add-PathIfExists "$env:ProgramFiles\nodejs"
    Add-PathIfExists "$env:LocalAppData\Programs\node"
    if (-not (Test-Command "node")) {
        Ensure-WingetPackage "OpenJS.NodeJS.LTS" "Node.js LTS"
        Add-PathIfExists "$env:ProgramFiles\nodejs"
        Add-PathIfExists "$env:LocalAppData\Programs\node"
    }
    node --version
}

function Ensure-Python {
    if ((Test-Command "py") -or (Test-Command "python")) {
        return
    }
    Ensure-WingetPackage "Python.Python.3.12" "Python 3.12"
    Add-PathIfExists "$env:LocalAppData\Programs\Python\Python312"
    Add-PathIfExists "$env:LocalAppData\Programs\Python\Python312\Scripts"
}

function Ensure-MongoDb {
    if ($SkipMongoInstall) {
        Write-Host "Skipping MongoDB install by request." -ForegroundColor Yellow
        return
    }

    $svc = Get-Service -Name "MongoDB" -ErrorAction SilentlyContinue
    if (-not $svc) {
        try {
            Ensure-WingetPackage "MongoDB.Server" "MongoDB Community Server"
            $svc = Get-Service -Name "MongoDB" -ErrorAction SilentlyContinue
        } catch {
            Write-Host "MongoDB auto-install failed: $($_.Exception.Message)" -ForegroundColor Yellow
            Write-Host "If you use MongoDB Atlas, put that URI in $InstallDir\.env after setup." -ForegroundColor Yellow
            return
        }
    }

    if ($svc -and $svc.Status -ne "Running") {
        Write-Host "Starting MongoDB service..."
        Start-Service -Name "MongoDB"
    }
}

function Get-PythonExe {
    $venvPython = Join-Path $InstallDir "venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    if (Test-Command "py") {
        return "py"
    }
    return "python"
}

function Invoke-Checked([scriptblock]$Block, [string]$Name) {
    & $Block
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE."
    }
}

function Copy-AppSource([string]$SourceDir, [string]$TargetDir) {
    if (-not (Test-Path $TargetDir)) {
        New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    }

    $excludedDirs = @(
        "node_modules",
        ".next",
        ".git",
        "venv",
        "browser-profile",
        "browser-profile-py",
        "browser-profile-py-fresh",
        "data",
        "test-results"
    )

    $args = @($SourceDir, $TargetDir, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/XF", ".env", "/XD") + $excludedDirs
    robocopy @args | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "Copying app source failed with robocopy exit code $LASTEXITCODE."
    }
    $global:LASTEXITCODE = 0
}

function Ensure-EnvFile {
    $envFile = Join-Path $InstallDir ".env"
    if (-not (Test-Path $envFile)) {
        $bytes = New-Object byte[] 32
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $secret = [Convert]::ToBase64String($bytes)
        @"
MONGODB_URI=mongodb://127.0.0.1:27017/fiverr-lead-extractor-crm
JWT_SECRET=$secret
SCRAPER_ENGINE=python
NEXT_PUBLIC_CLIENT_MODE=true
PLAYWRIGHT_HEADLESS=false
KEEP_BROWSER_PROFILE=true
FOCUS_BROWSER_ON_VERIFICATION=true
PYTHON_AUTO_VERIFICATION_MAX_ATTEMPTS=0
PYTHON_VERIFICATION_TIMEOUT_SEC=900
"@ | Set-Content -LiteralPath $envFile -Encoding UTF8
        return
    }

    $text = Get-Content -LiteralPath $envFile -Raw
    $required = @{
        "SCRAPER_ENGINE" = "python"
        "NEXT_PUBLIC_CLIENT_MODE" = "true"
        "PLAYWRIGHT_HEADLESS" = "false"
        "KEEP_BROWSER_PROFILE" = "true"
        "FOCUS_BROWSER_ON_VERIFICATION" = "true"
        "PYTHON_AUTO_VERIFICATION_MAX_ATTEMPTS" = "0"
        "PYTHON_VERIFICATION_TIMEOUT_SEC" = "900"
    }
    foreach ($key in $required.Keys) {
        if ($text -notmatch "(?m)^$([regex]::Escape($key))=") {
            Add-Content -LiteralPath $envFile -Value "$key=$($required[$key])"
        }
    }
}

function Ensure-ShortcutAndStartup {
    $startBat = Join-Path $InstallDir "Start Fiverr Lead CRM.bat"
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "Fiverr Lead CRM.lnk"

    if (Test-Path $startBat) {
        $wsh = New-Object -ComObject WScript.Shell
        $shortcut = $wsh.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $startBat
        $shortcut.WorkingDirectory = $InstallDir
        $shortcut.Description = "Start Fiverr Lead Extractor CRM"
        $shortcut.Save()

        try {
            $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$startBat`"" -WorkingDirectory $InstallDir
            $trigger = New-ScheduledTaskTrigger -AtLogOn
            Register-ScheduledTask -TaskName "Fiverr Lead Extractor CRM" -Action $action -Trigger $trigger -Description "Starts the Fiverr Lead Extractor CRM at login." -Force | Out-Null
        } catch {
            Write-Host "Startup task was not created: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}

try {
    Write-Step "Installing prerequisites"
    Ensure-Node
    Ensure-Python
    Ensure-MongoDb

    Write-Step "Downloading latest app"
    $tempRoot = Join-Path $env:TEMP ("fiverr-crm-setup-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    $zipPath = Join-Path $tempRoot "source.zip"
    $extractDir = Join-Path $tempRoot "extract"
    Invoke-WebRequest -Uri $RepoZipUrl -OutFile $zipPath
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force
    $source = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
    if (-not $source) {
        throw "Downloaded archive did not contain an app folder."
    }
    Copy-AppSource -SourceDir $source.FullName -TargetDir $InstallDir

    Write-Step "Writing client environment"
    Ensure-EnvFile

    Write-Step "Installing Node packages"
    Set-Location $InstallDir
    Invoke-Checked { npm install } "npm install"

    Write-Step "Installing Python packages"
    if (-not (Test-Path (Join-Path $InstallDir "venv\Scripts\python.exe"))) {
        if (Test-Command "py") {
            Invoke-Checked { py -3 -m venv venv } "python venv"
        } else {
            Invoke-Checked { python -m venv venv } "python venv"
        }
    }
    $venvPython = Join-Path $InstallDir "venv\Scripts\python.exe"
    Invoke-Checked { & $venvPython -m pip install --upgrade pip } "pip upgrade"
    Invoke-Checked { & $venvPython -m pip install -r "python_scraper\requirements.txt" } "pip install"
    Invoke-Checked { & $venvPython -m playwright install chromium } "playwright browser install"

    Write-Step "Preparing admin account"
    try {
        Invoke-Checked { npm run seed:admin } "admin seed"
    } catch {
        Write-Host "Admin seed failed. Start MongoDB, then run npm run seed:admin in $InstallDir." -ForegroundColor Yellow
    }

    Write-Step "Creating shortcut and startup task"
    Ensure-ShortcutAndStartup

    if (-not $NoStart) {
        Write-Step "Starting app"
        Start-Process -FilePath (Join-Path $InstallDir "Start Fiverr Lead CRM.bat") -WorkingDirectory $InstallDir
    }

    Write-Host ""
    Write-Host "Setup complete." -ForegroundColor Green
    Write-Host "Install folder: $InstallDir"
    Write-Host "App URL: http://localhost:3000/"
    Write-Host "Default admin: admin@ftsolutions.local / Admin@FT2024"
} catch {
    Write-Host ""
    Write-Host "Setup failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Install folder: $InstallDir"
    exit 1
} finally {
    if ($tempRoot -and (Test-Path $tempRoot)) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
