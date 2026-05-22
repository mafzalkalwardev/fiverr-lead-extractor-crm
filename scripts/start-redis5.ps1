# Start Redis 5+ on port 6380 (BullMQ requires Redis >= 5; winget Redis.Redis is 3.x)
$redisDir = Join-Path $PSScriptRoot "..\tools\redis5"
$exe = Join-Path $redisDir "redis-server.exe"
if (-not (Test-Path $exe)) {
  Write-Host "Redis 5 not found. Download from:"
  Write-Host "https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip"
  Write-Host "Extract to: $redisDir"
  exit 1
}
$existing = Get-NetTCPConnection -LocalPort 6380 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
  Write-Host "Redis already listening on port 6380"
  exit 0
}
Start-Process -FilePath $exe -ArgumentList "redis.windows.conf", "--port", "6380" -WorkingDirectory $redisDir -WindowStyle Hidden
Start-Sleep 2
Write-Host "Redis 5 started on port 6380. Set REDIS_URL=redis://127.0.0.1:6380 in .env"
