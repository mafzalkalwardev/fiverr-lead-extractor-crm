@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Install Fiverr Lead CRM
cd /d "%~dp0"

net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo Requesting administrator permission...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

if not exist "FiverrLeadCRM-Client-Setup.ps1" (
  echo Downloading latest setup script...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/mafzalkalwardev/fiverr-lead-extractor-crm/main/FiverrLeadCRM-Client-Setup.ps1' -OutFile '%~dp0FiverrLeadCRM-Client-Setup.ps1'"
  if errorlevel 1 (
    echo [ERROR] Could not download FiverrLeadCRM-Client-Setup.ps1.
    pause
    exit /b 1
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0FiverrLeadCRM-Client-Setup.ps1"
set EXITCODE=%ERRORLEVEL%

echo.
if %EXITCODE% EQU 0 (
  echo Installation complete. Use the Fiverr Lead CRM desktop shortcut.
) else (
  echo Installation failed with exit code %EXITCODE%.
)
pause
exit /b %EXITCODE%
