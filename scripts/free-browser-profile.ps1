# Stop processes locking the Fiverr scraper browser profile (run before npm run scraper:py)
$root = Split-Path $PSScriptRoot -Parent
$profiles = @(
    (Join-Path $root "browser-profile"),
    (Join-Path $root "browser-profile-py")
)

Write-Host "Stopping Playwright/Chrome processes that may lock the profile..."
Get-Process -Name "chrome", "chromium", "msedge" -ErrorAction SilentlyContinue | ForEach-Object {
    try { $_.CloseMainWindow() | Out-Null } catch {}
}
Start-Sleep -Seconds 2
Get-Process -Name "chrome", "chromium" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

foreach ($dir in $profiles) {
    if (-not (Test-Path $dir)) { continue }
    foreach ($lock in @("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile")) {
        $f = Join-Path $dir $lock
        if (Test-Path $f) {
            Remove-Item $f -Force -ErrorAction SilentlyContinue
            Write-Host "Removed $f"
        }
    }
}
Write-Host "Done. Start: npm run scraper:py"
