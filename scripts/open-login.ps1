# Open CRM login — tries port 3000 first, then 3001
$ports = @(3000, 3001)
$path = "/login"

foreach ($port in $ports) {
    $url = "http://localhost:$port$path"
    Write-Host "Waiting for $url ..."
    for ($i = 0; $i -lt 45; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) {
                Write-Host "Opening $url"
                Start-Process $url
                exit 0
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
}

Write-Host "Server slow — opening http://localhost:3000/login anyway"
Start-Process "http://localhost:3000/login"
