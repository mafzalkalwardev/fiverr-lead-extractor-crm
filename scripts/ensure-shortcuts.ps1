#Requires -Version 5.1
param([string]$AppDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path)

$startBat   = Join-Path $AppDir "Start Fiverr Lead CRM.bat"
$electronExe = Join-Path $AppDir "dist\Fiverr Lead Extractor.exe"
$iconLocation = if (Test-Path $electronExe) { "$electronExe,0" } else { "" }

$wsh = New-Object -ComObject WScript.Shell

function Set-Shortcut([string]$Path) {
    $lnk = $wsh.CreateShortcut($Path)
    $lnk.TargetPath      = $startBat
    $lnk.WorkingDirectory = $AppDir
    $lnk.Description     = "Start Fiverr Lead Extractor CRM"
    if ($iconLocation) { $lnk.IconLocation = $iconLocation }
    $lnk.Save()
}

$startMenuDir = [Environment]::GetFolderPath("Programs")
$startMenuLnk = Join-Path $startMenuDir "Fiverr Lead CRM.lnk"
if (-not (Test-Path $startMenuLnk)) {
    try { Set-Shortcut $startMenuLnk } catch { }
}

$desktopDir = [Environment]::GetFolderPath("Desktop")
$desktopLnk = Join-Path $desktopDir "Fiverr Lead CRM.lnk"
if (-not (Test-Path $desktopLnk)) {
    try { Set-Shortcut $desktopLnk } catch { }
}
