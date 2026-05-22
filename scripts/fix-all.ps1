# Fix Redis + Admin — run from project root
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "=== 1. Start Redis 5 on port 6380 ===" -ForegroundColor Cyan
& "$PSScriptRoot\start-redis5.ps1"

Write-Host "`n=== 2. Verify Redis version ===" -ForegroundColor Cyan
node -e "require('dotenv').config();const R=require('ioredis');const u=process.env.REDIS_URL||'redis://127.0.0.1:6380';const r=new R(u);r.info('server').then(i=>{const v=(i.match(/redis_version:([^\r\n]+)/)||[])[1];console.log('REDIS_URL',u);console.log('Version',v);if(parseFloat(v)<5)process.exit(1);r.quit()}).catch(e=>{console.error(e.message);process.exit(1)})"
if ($LASTEXITCODE -ne 0) { Write-Host "Redis 5+ required on port 6380" -ForegroundColor Red; exit 1 }

Write-Host "`n=== 3. Seed admin user ===" -ForegroundColor Cyan
npm run seed:admin

Write-Host "`n=== 4. Done ===" -ForegroundColor Green
Write-Host "Now run in separate terminals:"
Write-Host "  npm run dev"
Write-Host "  npm run worker"
Write-Host ""
Write-Host "Login: admin@ftsolutions.local / Admin@FT2024"
