# Open CRM in an app-style browser window. Root URL decides login vs dashboard.
$ports = @(3000, 3001)
$path = "/"

function Open-AppUrl([string]$url) {
    $edge = @(
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

    if ($edge) {
        Start-Process -FilePath $edge -ArgumentList "--app=$url"
        return
    }

    $chrome = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

    if ($chrome) {
        Start-Process -FilePath $chrome -ArgumentList "--app=$url"
        return
    }

    Start-Process $url
}

foreach ($port in $ports) {
    $url = "http://localhost:$port$path"
    Write-Host "Waiting for $url ..."
    for ($i = 0; $i -lt 45; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) {
                Write-Host "Opening $url"
                Open-AppUrl $url
                exit 0
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
}

Write-Host "Server slow - opening http://localhost:3000/ anyway"
Open-AppUrl "http://localhost:3000/"
