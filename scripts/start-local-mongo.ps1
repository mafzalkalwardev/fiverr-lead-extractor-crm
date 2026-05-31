#Requires -Version 5.1
param(
    [string]$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [int]$PrimaryPort = 27017,
    [int]$FallbackPort = 27018,
    [int]$ReadyTimeoutSec = 45
)

$ErrorActionPreference = "Stop"

$SupportMessage = "Local database could not start. Please run app as Administrator once or contact FT Solutions +92307-9670503."
$AppDataRoot = Join-Path $env:LOCALAPPDATA "FiverrLeadCRM"
$DbPath = Join-Path $AppDataRoot "data\db"
$LogDir = Join-Path $AppDataRoot "logs"
$LogFile = Join-Path $LogDir "mongod.log"
$PidFile = Join-Path $AppDataRoot "mongod.pid"
$EnvFile = Join-Path $RootDir ".env"
$DatabaseName = "fiverr-lead-extractor-crm"

function Write-Info([string]$Message) {
    Write-Host "[mongo] $Message"
}

function Test-PortOpen([int]$Port) {
    $client = New-Object Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne(600, $false)) {
            return $false
        }
        $client.EndConnect($iar)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-BundledMongodPath {
    $candidates = @()
    if ($env:FIVERR_MONGOD_EXE) {
        $candidates += $env:FIVERR_MONGOD_EXE
    }
    $candidates += @(
        (Join-Path $RootDir "tools\mongodb\bin\mongod.exe"),
        (Join-Path $RootDir "mongodb\bin\mongod.exe"),
        (Join-Path $RootDir "vendor\mongodb\bin\mongod.exe"),
        (Join-Path $RootDir "resources\mongodb\bin\mongod.exe"),
        (Join-Path $RootDir "tools\mongodb\mongod.exe")
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    return $null
}

function Get-PortableMongoProcess {
    $escapedDbPath = [regex]::Escape($DbPath)
    Get-CimInstance Win32_Process -Filter "Name = 'mongod.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match $escapedDbPath) } |
        Select-Object -First 1
}

function Get-PortFromCommandLine([string]$CommandLine) {
    if ($CommandLine -match "--port(?:=|\s+)(\d+)") {
        return [int]$matches[1]
    }
    return $PrimaryPort
}

function Set-EnvValue([string]$Key, [string]$Value) {
    $parent = Split-Path -Parent $EnvFile
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

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

function Set-SelectedMongoUri([int]$Port) {
    $uri = "mongodb://127.0.0.1:$Port/$DatabaseName"
    Set-EnvValue -Key "MONGODB_URI" -Value $uri
    $env:MONGODB_URI = $uri
    Write-Info "port used: $Port"
    Write-Info "database path: $DbPath"
    Write-Info "log path: $LogFile"
}

function Wait-ForMongo([int]$Port, $Process) {
    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if ($Process -and $Process.HasExited) {
            $logTail = if (Test-Path $LogFile) { (Get-Content $LogFile -Tail 5) -join " | " } else { "no log" }
            throw "mongod.exe exited early. Log: $logTail`nIf you see VCRUNTIME140.dll errors run the VC++ 2022 installer from Microsoft."
        }
        if (Test-PortOpen -Port $Port) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Timed out waiting for MongoDB on 127.0.0.1:$Port. See $LogFile"
}

function Start-PortableMongo([int]$Port) {
    $mongod = Get-BundledMongodPath
    if (-not $mongod) {
        throw "Bundled mongod.exe not found. Expected tools\mongodb\bin\mongod.exe inside the app folder."
    }

    New-Item -ItemType Directory -Path $DbPath -Force | Out-Null
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

    $mongodArgs = "--dbpath `"$DbPath`" --logpath `"$LogFile`" --logappend --bind_ip 127.0.0.1 --port $Port"

    Write-Info "starting bundled mongod.exe"
    $process = Start-Process -FilePath $mongod -ArgumentList $mongodArgs -WorkingDirectory (Split-Path -Parent $mongod) -WindowStyle Hidden -PassThru
    $process.Id | Set-Content -LiteralPath $PidFile -Encoding ASCII
    Write-Info "MongoDB portable started"
    return $process
}

try {
    New-Item -ItemType Directory -Path $AppDataRoot -Force | Out-Null

    # ── Step 1: If MongoDB is already accepting connections on any candidate port,
    #    reuse it immediately. This handles admin-elevated processes whose CommandLine
    #    is hidden from WMI, and avoids starting a second instance that would fail
    #    with a data-directory lock conflict.
    foreach ($candidatePort in @($PrimaryPort, $FallbackPort)) {
        if (Test-PortOpen -Port $candidatePort) {
            Write-Info "MongoDB already accepting connections on port $candidatePort"
            Set-SelectedMongoUri -Port $candidatePort
            Write-Info "MongoDB ready"
            exit 0
        }
    }

    # ── Step 2: Nothing is responding. Choose a start port.
    #    If the primary port is bound but not yet accepting connections (very rare
    #    race), fall back to the secondary port.
    $selectedPort = $PrimaryPort

    # ── Step 3: Remove a stale lock file left by a previously crashed mongod.
    #    Without this, the fresh mongod process will exit immediately because it
    #    cannot acquire the WiredTiger data-directory lock.
    $lockFile = Join-Path $DbPath "mongod.lock"
    if (Test-Path $lockFile) {
        $lockPid = (Get-Content $lockFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
        $lockHolder = if ($lockPid -and $lockPid -ne '0') {
            Get-Process -Id ([int]$lockPid) -ErrorAction SilentlyContinue
        } else { $null }
        if (-not $lockHolder) {
            Write-Info "Removing stale lock file (pid $lockPid is not running)..."
            Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
        }
    }

    # ── Step 4: Start MongoDB on the selected port.
    $proc = Start-PortableMongo -Port $selectedPort
    Wait-ForMongo -Port $selectedPort -Process $proc
    Set-SelectedMongoUri -Port $selectedPort
    Write-Info "MongoDB ready"
    exit 0
} catch {
    Write-Host $SupportMessage -ForegroundColor Red
    Write-Host "[mongo] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
