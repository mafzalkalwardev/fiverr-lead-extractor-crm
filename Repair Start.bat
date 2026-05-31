@echo off
setlocal EnableExtensions
title Fiverr CRM - Repair Start
cd /d "%~dp0"

if exist "%ProgramFiles%\nodejs\" set "PATH=%ProgramFiles%\nodejs\;%PATH%"

if not exist "tools\mongodb\bin\mongod.exe" (
  if exist "%USERPROFILE%\Fiverr Lead Extractor CRM\tools\mongodb\bin\mongod.exe" (
    set "FIVERR_MONGOD_EXE=%USERPROFILE%\Fiverr Lead Extractor CRM\tools\mongodb\bin\mongod.exe"
  )
)

echo.
echo  REPAIR MODE
echo  - Free port 3000
echo  - Clear browser locks
echo  - Clean Next.js cache
echo  - Start app on http://localhost:3000
echo.

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Install Node.js from https://nodejs.org/
  pause
  exit /b 1
)

echo Starting portable local MongoDB...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-local-mongo.ps1
if errorlevel 1 (
  echo Local database could not start. Please run app as Administrator once or contact FT Solutions +92307-9670503.
  pause
  exit /b 1
)

echo Starting portable Redis 5...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-redis5.ps1

set "PYTHON_AUTO_VERIFICATION_MAX_ATTEMPTS=8"
set "ALLOW_OS_MOUSE_AUTOMATION=false"
set "FOCUS_BROWSER_ON_VERIFICATION=true"

start "Open Login" cmd /c "powershell -ExecutionPolicy Bypass -NoProfile -File scripts\open-login.ps1"

call npm.cmd run client:repair

pause
