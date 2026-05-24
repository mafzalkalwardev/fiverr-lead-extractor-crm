# Quick health check for portable MongoDB and Redis
$ok = $true

Write-Host "Portable MongoDB..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "start-local-mongo.ps1")
if ($LASTEXITCODE -ne 0) { $ok = $false }

Write-Host "MongoDB connection..." -NoNewline
try {
  $envFile = Join-Path $PSScriptRoot "..\.env"
  if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
      if ($_ -match "^MONGODB_URI=(.+)$") { $env:MONGODB_URI = $matches[1] }
    }
  }
  node -e "const m=require('mongoose');m.connect(process.env.MONGODB_URI||'mongodb://127.0.0.1:27017/fiverr-lead-extractor-crm',{serverSelectionTimeoutMS:5000}).then(()=>{console.log(' OK');return m.disconnect()}).catch(e=>{console.log(' FAIL');process.exit(1)})"
  if ($LASTEXITCODE -ne 0) { $ok = $false }
} catch { Write-Host " FAIL"; $ok = $false }

Write-Host "Redis (from .env REDIS_URL)..." -NoNewline
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    if ($_ -match "^REDIS_URL=(.+)$") { $env:REDIS_URL = $matches[1] }
  }
}
if (-not $env:REDIS_URL) { $env:REDIS_URL = "redis://127.0.0.1:6380" }
$url = $env:REDIS_URL
try {
  node -e "const R=require('ioredis');const r=new R(process.env.REDIS_URL||'$url',{connectTimeout:5000});r.info('server').then(i=>{const v=(i.match(/redis_version:([^\r\n]+)/)||[])[1];console.log(' OK v'+v);if(parseInt(v)<5){console.log(' WARN: BullMQ needs Redis 5+');process.exit(1)}r.quit()}).catch(e=>{console.log(' FAIL',e.message);process.exit(1)})"
  if ($LASTEXITCODE -ne 0) { $ok = $false }
} catch { Write-Host " FAIL"; $ok = $false }

if ($ok) { Write-Host "`nAll services OK." -ForegroundColor Green } else { Write-Host "`nFix services before npm run dev / npm run worker." -ForegroundColor Red; exit 1 }
