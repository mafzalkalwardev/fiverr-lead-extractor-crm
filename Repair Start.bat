@echo off
setlocal EnableExtensions
title Fiverr CRM - Repair Start
cd /d "%~dp0"

if exist "%ProgramFiles%\nodejs\" set "PATH=%ProgramFiles%\nodejs\;%PATH%"

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

start "Open Login" cmd /c "powershell -ExecutionPolicy Bypass -NoProfile -File scripts\open-login.ps1"

call npm.cmd run client:repair

pause
