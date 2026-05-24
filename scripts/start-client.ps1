# Start CRM + Python scraper for client use (Windows)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "Starting Fiverr Lead Extractor CRM + scraper..." -ForegroundColor Cyan
Write-Host "Open http://localhost:3000 after the server is ready." -ForegroundColor Gray
Write-Host "Press Ctrl+C to stop both services." -ForegroundColor Gray

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "start-local-mongo.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "Local database could not start. Please run app as Administrator once or contact FT Solutions +92307-9670503."
}

npm run client:start
