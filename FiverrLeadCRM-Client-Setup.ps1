#Requires -Version 5.1
param(
    [string]$InstallDir = "$env:USERPROFILE\Fiverr Lead Extractor CRM",
    [string]$RepoZipUrl = "https://github.com/mafzalkalwardev/fiverr-lead-extractor-crm/archive/refs/heads/main.zip",
    [switch]$SkipMongoInstall,
    [switch]$SkipRedisInstall,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$NodeMsiUrl = "https://nodejs.org/dist/v20.18.3/node-v20.18.3-x64.msi"
$PythonInstallerUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
$MongoZipUrl = "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-7.0.15.zip"
$RedisZipUrl = "https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip"
$LocalMongoUri = "mongodb://127.0.0.1:27017/fiverr-lead-extractor-crm"
$LocalRedisUrl = "redis://127.0.0.1:6380"
$LocalDatabaseError = "Local database could not start. Please run app as Administrator once or contact FT Solutions +92307-9670503."

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

function Invoke-DownloadFile([string]$Uri, [string]$OutFile, [string]$Name) {
    Write-Host "Downloading $Name (may take several minutes for large files)..."
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("User-Agent", "Mozilla/5.0 FiverrLeadCRM-Setup")
    try {
        $wc.DownloadFile($Uri, $OutFile)
    } catch {
        throw "Download failed for $Name from $Uri - $($_.Exception.Message)"
    } finally {
        $wc.Dispose()
    }
    if (-not (Test-Path -LiteralPath $OutFile) -or (Get-Item -LiteralPath $OutFile).Length -eq 0) {
        throw "Download produced empty file for $Name."
    }
    $sizeMB = [math]::Round((Get-Item -LiteralPath $OutFile).Length / 1MB, 1)
    Write-Host "Downloaded $Name ($sizeMB MB)" -ForegroundColor Green
}

function Install-Msi([string]$MsiPath, [string]$Name) {
    Write-Host "Installing $Name..."
    $p = Start-Process -FilePath "msiexec.exe" -ArgumentList @("/i", "`"$MsiPath`"", "/qn", "/norestart") -Wait -PassThru
    if ($p.ExitCode -notin @(0, 3010)) {
        throw "$Name installer failed with exit code $($p.ExitCode)."
    }
}

function Install-Exe([string]$ExePath, [string[]]$Arguments, [string]$Name) {
    Write-Host "Installing $Name..."
    $p = Start-Process -FilePath $ExePath -ArgumentList $Arguments -Wait -PassThru
    if ($p.ExitCode -notin @(0, 3010)) {
        throw "$Name installer failed with exit code $($p.ExitCode)."
    }
}

function Ensure-Node {
    Add-PathIfExists "$env:ProgramFiles\nodejs"
    Add-PathIfExists "$env:LocalAppData\Programs\node"
    if (-not (Test-Command "node")) {
        $nodeMsi = Join-Path $env:TEMP "fiverr-crm-node-lts.msi"
        Invoke-DownloadFile -Uri $NodeMsiUrl -OutFile $nodeMsi -Name "Node.js LTS"
        Install-Msi -MsiPath $nodeMsi -Name "Node.js LTS"
        Add-PathIfExists "$env:ProgramFiles\nodejs"
        Add-PathIfExists "$env:LocalAppData\Programs\node"
    }
    node --version
}

function Ensure-Python {
    Add-PathIfExists "$env:ProgramFiles\Python312"
    Add-PathIfExists "$env:ProgramFiles\Python312\Scripts"
    Add-PathIfExists "$env:LocalAppData\Programs\Python\Python312"
    Add-PathIfExists "$env:LocalAppData\Programs\Python\Python312\Scripts"
    if ((Test-Command "py") -or (Test-Command "python")) {
        return
    }

    $pythonExe = Join-Path $env:TEMP "fiverr-crm-python-3.12.exe"
    Invoke-DownloadFile -Uri $PythonInstallerUrl -OutFile $pythonExe -Name "Python 3.12"
    Install-Exe -ExePath $pythonExe -Arguments @(
        "/quiet",
        "InstallAllUsers=1",
        "PrependPath=1",
        "Include_launcher=1",
        "Include_test=0"
    ) -Name "Python 3.12"
    Add-PathIfExists "$env:ProgramFiles\Python312"
    Add-PathIfExists "$env:ProgramFiles\Python312\Scripts"
    Add-PathIfExists "$env:LocalAppData\Programs\Python\Python312"
    Add-PathIfExists "$env:LocalAppData\Programs\Python\Python312\Scripts"
}

function Ensure-VCRuntime {
    $sys32 = "$env:SystemRoot\System32"
    $dll1 = Join-Path $sys32 "vcruntime140.dll"
    $dll2 = Join-Path $sys32 "vcruntime140_1.dll"
    if ((Test-Path $dll1) -and (Test-Path $dll2)) {
        Write-Host "Visual C++ Runtime already present." -ForegroundColor Green
        return
    }
    $vcExe = Join-Path $env:TEMP "fiverr-crm-vcredist.exe"
    Invoke-DownloadFile -Uri "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $vcExe -Name "Visual C++ 2022 Runtime"
    Write-Host "Installing Visual C++ 2022 Runtime..."
    $p = Start-Process -FilePath $vcExe -ArgumentList "/install", "/quiet", "/norestart" -Wait -PassThru
    if ($p.ExitCode -notin @(0, 3010, 1638)) {
        Write-Host "Warning: VC++ Runtime installer returned exit code $($p.ExitCode). MongoDB may fail to start." -ForegroundColor Yellow
    } else {
        Write-Host "Visual C++ 2022 Runtime installed." -ForegroundColor Green
    }
}

function Get-PortableMongodPath {
    $candidates = @(
        (Join-Path $InstallDir "tools\mongodb\bin\mongod.exe"),
        (Join-Path $InstallDir "mongodb\bin\mongod.exe"),
        (Join-Path $InstallDir "vendor\mongodb\bin\mongod.exe"),
        (Join-Path $InstallDir "resources\mongodb\bin\mongod.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Get-SystemMongodPath {
    $cmd = Get-Command "mongod" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($ver in @("8.0","7.0","6.0","5.0","4.4")) {
        $p = "C:\Program Files\MongoDB\Server\$ver\bin\mongod.exe"
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Test-PortOpen([int]$Port) {
    $tc = New-Object Net.Sockets.TcpClient
    try {
        $iar = $tc.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(600, $false)
        if ($ok) { $tc.EndConnect($iar) }
        return $ok
    } catch { return $false } finally { $tc.Close() }
}

function Ensure-PortableMongoDb {
    if (Get-PortableMongodPath) {
        Write-Host "Portable MongoDB already bundled." -ForegroundColor Green
        return
    }

    if ($SkipMongoInstall) {
        Write-Host "Skipping portable MongoDB download by request." -ForegroundColor Yellow
        return
    }

    $mongoTemp = Join-Path $env:TEMP ("fiverr-crm-mongodb-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $mongoTemp -Force | Out-Null
    try {
        $zipPath = Join-Path $mongoTemp "mongodb.zip"
        $extractDir = Join-Path $mongoTemp "extract"
        Invoke-DownloadFile -Uri $MongoZipUrl -OutFile $zipPath -Name "portable MongoDB"
        Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

        $mongod = Get-ChildItem -Path $extractDir -Recurse -Filter "mongod.exe" | Select-Object -First 1
        if (-not $mongod) {
            throw "MongoDB ZIP did not contain mongod.exe."
        }

        $sourceRoot = Split-Path -Parent (Split-Path -Parent $mongod.FullName)
        $targetRoot = Join-Path $InstallDir "tools\mongodb"
        $resolvedInstall = (Resolve-Path -LiteralPath $InstallDir).Path.TrimEnd("\")
        $targetParent = Split-Path -Parent $targetRoot
        if (-not (Test-Path -LiteralPath $targetParent)) {
            New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
        }
        if ((Test-Path -LiteralPath $targetRoot) -and ((Resolve-Path -LiteralPath $targetRoot).Path -notlike "$resolvedInstall*")) {
            throw "Refusing to replace unexpected MongoDB folder: $targetRoot"
        }
        if (Test-Path -LiteralPath $targetRoot) {
            Remove-Item -LiteralPath $targetRoot -Recurse -Force
        }
        New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null
        Copy-Item -Path (Join-Path $sourceRoot "*") -Destination $targetRoot -Recurse -Force
        Write-Host "Portable MongoDB bundled at $targetRoot" -ForegroundColor Green
    } finally {
        if (Test-Path -LiteralPath $mongoTemp) {
            Remove-Item -LiteralPath $mongoTemp -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Ensure-PortableRedis {
    $redisDir = Join-Path $InstallDir "tools\redis5"
    $redisExe = Join-Path $redisDir "redis-server.exe"

    if (Test-Path -LiteralPath $redisExe) {
        Write-Host "Portable Redis already bundled." -ForegroundColor Green
        return
    }

    if ($SkipRedisInstall) {
        Write-Host "Skipping portable Redis download by request." -ForegroundColor Yellow
        return
    }

    $redisTemp = Join-Path $env:TEMP ("fiverr-crm-redis-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $redisTemp -Force | Out-Null
    try {
        $zipPath = Join-Path $redisTemp "redis.zip"
        $extractDir = Join-Path $redisTemp "extract"
        Invoke-DownloadFile -Uri $RedisZipUrl -OutFile $zipPath -Name "portable Redis 5"
        Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

        $redisServer = Get-ChildItem -Path $extractDir -Recurse -Filter "redis-server.exe" | Select-Object -First 1
        if (-not $redisServer) {
            throw "Redis ZIP did not contain redis-server.exe."
        }

        $sourceDir = Split-Path -Parent $redisServer.FullName
        if (-not (Test-Path -LiteralPath $redisDir)) {
            New-Item -ItemType Directory -Path $redisDir -Force | Out-Null
        }
        Copy-Item -Path (Join-Path $sourceDir "*") -Destination $redisDir -Recurse -Force
        Write-Host "Portable Redis bundled at $redisDir" -ForegroundColor Green
    } finally {
        if (Test-Path -LiteralPath $redisTemp) {
            Remove-Item -LiteralPath $redisTemp -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Start-PortableRedis {
    $scriptPath = Join-Path $InstallDir "scripts\start-redis5.ps1"
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        Write-Host "Warning: scripts\start-redis5.ps1 not found; skipping Redis start." -ForegroundColor Yellow
        return
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $scriptPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Warning: Redis could not start. The app may run but job stop may fail." -ForegroundColor Yellow
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

function Set-EnvFileValue([string]$EnvFile, [string]$Key, [string]$Value) {
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        "$Key=$Value" | Set-Content -LiteralPath $EnvFile -Encoding UTF8
        return
    }

    $lines = [Collections.Generic.List[string]]::new()
    $found = $false
    foreach ($line in [IO.File]::ReadAllLines($EnvFile)) {
        if ($line -match "^\s*$([regex]::Escape($Key))=") {
            $lines.Add("$Key=$Value")
            $found = $true
        } else {
            $lines.Add($line)
        }
    }
    if (-not $found) {
        $lines.Add("$Key=$Value")
    }
    [IO.File]::WriteAllLines($EnvFile, $lines, [Text.UTF8Encoding]::new($false))
}

function Get-EnvFileValue([string]$EnvFile, [string]$Key) {
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        return $null
    }

    foreach ($line in [IO.File]::ReadAllLines($EnvFile)) {
        $index = $line.IndexOf("=")
        if ($index -le 0) {
            continue
        }
        if ($line.Substring(0, $index).Trim().ToUpperInvariant() -eq $Key.ToUpperInvariant()) {
            return $line.Substring($index + 1).Trim()
        }
    }
    return $null
}

function Start-PortableMongoDb {
    $scriptPath = Join-Path $InstallDir "scripts\start-local-mongo.ps1"
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        throw "Missing scripts\start-local-mongo.ps1."
    }

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $scriptPath -RootDir $InstallDir
    if ($LASTEXITCODE -ne 0) {
        throw $LocalDatabaseError
    }

    $envFile = Join-Path $InstallDir ".env"
    $uri = Get-EnvFileValue -EnvFile $envFile -Key "MONGODB_URI"
    if ($uri) {
        $env:MONGODB_URI = $uri
    }
}

function Ensure-EnvFile {
    $envFile = Join-Path $InstallDir ".env"
    if (-not (Test-Path $envFile)) {
        $bytes = New-Object byte[] 32
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $secret = [Convert]::ToBase64String($bytes)
        @"
NEXT_PUBLIC_APP_URL=http://localhost:3000
NODE_ENV=development
MONGODB_URI=mongodb://127.0.0.1:27017/fiverr-lead-extractor-crm
REDIS_URL=redis://127.0.0.1:6380
JWT_SECRET=$secret
SCRAPER_ENGINE=python
SCRAPER_MODE=playwright
NEXT_PUBLIC_CLIENT_MODE=true
PLAYWRIGHT_HEADLESS=false
KEEP_BROWSER_PROFILE=true
FOCUS_BROWSER_ON_VERIFICATION=true
PYTHON_AUTO_VERIFICATION_MAX_ATTEMPTS=0
PYTHON_VERIFICATION_TIMEOUT_SEC=900
DEFAULT_DELAY_SECONDS=1
MAX_RETRIES=3
BROWSER_WINDOW_WIDTH=1440
BROWSER_WINDOW_HEIGHT=900
"@ | Set-Content -LiteralPath $envFile -Encoding UTF8
        return
    }

    $text = Get-Content -LiteralPath $envFile -Raw
    $required = @{
        "MONGODB_URI" = $LocalMongoUri
        "REDIS_URL" = $LocalRedisUrl
        "NEXT_PUBLIC_APP_URL" = "http://localhost:3000"
        "NODE_ENV" = "development"
        "SCRAPER_ENGINE" = "python"
        "SCRAPER_MODE" = "playwright"
        "NEXT_PUBLIC_CLIENT_MODE" = "true"
        "PLAYWRIGHT_HEADLESS" = "false"
        "KEEP_BROWSER_PROFILE" = "true"
        "FOCUS_BROWSER_ON_VERIFICATION" = "true"
        "PYTHON_AUTO_VERIFICATION_MAX_ATTEMPTS" = "0"
        "PYTHON_VERIFICATION_TIMEOUT_SEC" = "900"
        "DEFAULT_DELAY_SECONDS" = "1"
        "MAX_RETRIES" = "3"
        "BROWSER_WINDOW_WIDTH" = "1440"
        "BROWSER_WINDOW_HEIGHT" = "900"
    }
    foreach ($key in $required.Keys) {
        if ($key -in @("MONGODB_URI", "REDIS_URL", "NEXT_PUBLIC_APP_URL", "NODE_ENV")) {
            Set-EnvFileValue -EnvFile $envFile -Key $key -Value $required[$key]
        } elseif ($text -notmatch "(?m)^$([regex]::Escape($key))=") {
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
    if (Test-Path (Join-Path $InstallDir "node_modules\next")) {
        Write-Host "node_modules already installed, skipping npm install." -ForegroundColor Green
    } else {
        Invoke-Checked { npm install } "npm install"
    }

    Write-Step "Installing Python packages"
    if (-not (Test-Path (Join-Path $InstallDir "venv\Scripts\python.exe"))) {
        if (Test-Command "py") {
            Invoke-Checked { py -3 -m venv venv } "python venv"
        } else {
            Invoke-Checked { python -m venv venv } "python venv"
        }
    }
    $venvPython = Join-Path $InstallDir "venv\Scripts\python.exe"
    $playwrightInstalled = Test-Path (Join-Path $InstallDir "venv\Lib\site-packages\playwright")
    if (-not $playwrightInstalled) {
        Invoke-Checked { & $venvPython -m pip install --upgrade pip } "pip upgrade"
        Invoke-Checked { & $venvPython -m pip install -r "python_scraper\requirements.txt" } "pip install"
        Invoke-Checked { & $venvPython -m playwright install chromium } "playwright browser install"
    } else {
        Write-Host "Python packages already installed, skipping pip install." -ForegroundColor Green
    }

    Write-Step "Setting up MongoDB"
    $mongodPortable = Get-PortableMongodPath
    $mongodSystem = Get-SystemMongodPath

    if ($mongodPortable) {
        Write-Host "Portable MongoDB already bundled: $mongodPortable" -ForegroundColor Green
    } elseif ($mongodSystem) {
        Write-Host "Found system MongoDB: $mongodSystem" -ForegroundColor Green
        $env:FIVERR_MONGOD_EXE = $mongodSystem
    } elseif (Test-PortOpen -Port 27017) {
        Write-Host "MongoDB already listening on port 27017, skipping install." -ForegroundColor Green
    } else {
        $wingetOk = $false
        if (Get-Command "winget" -ErrorAction SilentlyContinue) {
            Write-Host "Trying winget install MongoDB.Server (fast, no VC++ worries)..."
            winget install -e --id MongoDB.Server --silent --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "MongoDB installed via winget." -ForegroundColor Green
                foreach ($ver in @("8.0","7.0","6.0")) {
                    Add-PathIfExists "C:\Program Files\MongoDB\Server\$ver\bin"
                }
                $found = Get-SystemMongodPath
                if ($found) { $env:FIVERR_MONGOD_EXE = $found }
                $wingetOk = $true
            } else {
                Write-Host "winget install failed, falling back to portable ZIP download." -ForegroundColor Yellow
            }
        }
        if (-not $wingetOk) {
            Write-Step "Installing Visual C++ 2022 Runtime (required by MongoDB)"
            Ensure-VCRuntime
            Write-Step "Downloading portable MongoDB (large download, please wait)"
            Ensure-PortableMongoDb
        }
    }

    $resolvedMongod = if ($env:FIVERR_MONGOD_EXE) { $env:FIVERR_MONGOD_EXE } else { Get-PortableMongodPath }
    if ($resolvedMongod -and (Test-Path -LiteralPath $resolvedMongod)) {
        $mongodVersion = & $resolvedMongod --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "mongod OK: $($mongodVersion | Select-Object -First 1)" -ForegroundColor Green
        } else {
            Write-Host "Warning: mongod.exe self-test returned non-zero (possible missing VC++ runtime). Will attempt to start anyway." -ForegroundColor Yellow
        }
    } elseif (-not (Test-PortOpen -Port 27017)) {
        Write-Host "Warning: mongod.exe not found and port 27017 not open. MongoDB may fail to start." -ForegroundColor Yellow
    }

    if (-not (Test-PortOpen -Port 27017)) {
        Start-PortableMongoDb
    } else {
        Write-Host "MongoDB already running, skipping start." -ForegroundColor Green
    }

    Write-Step "Preparing portable Redis 5"
    Ensure-PortableRedis
    Start-PortableRedis

    Write-Step "Preparing admin account"
    Invoke-Checked { npm run seed:admin } "admin seed"
    Write-Host "[mongo] admin seeded" -ForegroundColor Green

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
