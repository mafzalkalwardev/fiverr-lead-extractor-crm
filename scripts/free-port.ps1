# Free port 3000 so Next.js always starts on http://localhost:3000
$port = 3000
if ($args.Count -gt 0) { $port = [int]$args[0] }

Write-Host "Checking port $port..."
try {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $procId = $c.OwningProcess
        if ($procId -and $procId -gt 0) {
            $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
            $name = if ($p) { $p.ProcessName } else { "?" }
            Write-Host "Stopping $name (PID $procId) on port $port"
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
} catch {
    $line = netstat -ano | Select-String ":$port\s" | Select-String "LISTENING" | Select-Object -First 1
    if ($line -match '\s+(\d+)\s*$') {
        $procId = $Matches[1]
        Write-Host "Stopping PID $procId on port $port"
        taskkill /F /PID $procId 2>$null
    }
}
Start-Sleep -Seconds 1
Write-Host "Port $port ready."
