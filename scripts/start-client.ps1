# Start CRM + Python scraper for client use (Windows)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot + "\.."

Write-Host "Starting Fiverr Lead Extractor CRM + scraper..." -ForegroundColor Cyan
Write-Host "Open http://localhost:3000 after the server is ready." -ForegroundColor Gray
Write-Host "Press Ctrl+C to stop both services." -ForegroundColor Gray

npm run client:start
