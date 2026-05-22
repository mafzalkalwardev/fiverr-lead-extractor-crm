# Remove lock files only (optional -KillProcesses for Playwright Chrome only)
$root = Split-Path $PSScriptRoot -Parent
$profiles = @(
    (Join-Path $root "browser-profile"),
    (Join-Path $root "browser-profile-py"),
    (Join-Path $root "browser-profile-py-fresh")
)

$kill = $args -contains "-KillProcesses"

if ($kill) {
    Write-Host "Stopping Playwright Chromium only..."
    Get-CimInstance Win32_Process -Filter "name='chrome.exe'" -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.CommandLine -match 'browser-profile|ms-playwright|playwright') {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped PID $($_.ProcessId)"
        }
    }
    Start-Sleep -Seconds 1
}

foreach ($dir in $profiles) {
    if (-not (Test-Path $dir)) { continue }
    foreach ($lock in @("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile")) {
        $paths = @(
            (Join-Path $dir $lock),
            (Join-Path (Join-Path $dir "Default") $lock)
        )
        foreach ($f in $paths) {
            if (Test-Path $f) {
                Remove-Item $f -Force -ErrorAction SilentlyContinue
                Write-Host "Removed $f"
            }
        }
    }
}
Write-Host "Profile locks cleared."
