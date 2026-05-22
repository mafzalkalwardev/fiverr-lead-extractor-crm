@echo off
title Fiverr Lead Extractor CRM
cd /d "%~dp0"

echo.
echo  Fiverr Lead Extractor CRM - FT Solutions
echo  Starting app and scraper... Please keep this window open.
echo.

where node >nul 2>&1
if errorlevel 1 (
  echo ERROR: Node.js is not installed. Install from https://nodejs.org/
  pause
  exit /b 1
)

start "" cmd /c "timeout /t 6 /nobreak >nul && start http://localhost:3000/login"
call npm run client:start

pause
