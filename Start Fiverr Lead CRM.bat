@echo off
setlocal EnableExtensions
title Fiverr Lead Extractor CRM - FT Solutions
cd /d "%~dp0"

if exist "%ProgramFiles%\nodejs\" set "PATH=%ProgramFiles%\nodejs\;%PATH%"
if exist "%LocalAppData%\Programs\node\" set "PATH=%LocalAppData%\Programs\node\;%PATH%"

echo.
echo  ============================================
echo   Fiverr Lead Extractor CRM - FT Solutions
echo  ============================================
echo.
echo  KEEP THIS WINDOW OPEN.
echo  App URL: http://localhost:3000/login
echo  Scraper browser opens when you START a job only.
echo.

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js not installed: https://nodejs.org/
  pause
  exit /b 1
)

if not exist "node_modules\" (
  echo Installing npm packages...
  call npm.cmd install
  if errorlevel 1 ( echo [ERROR] npm install failed. & pause & exit /b 1 )
)

if not exist "venv\Scripts\python.exe" (
  echo [ERROR] Python venv missing. Run setup in README first.
  pause
  exit /b 1
)

echo Freeing port 3000 and browser locks...
call npm.cmd run free:port
call npm.cmd run free:browser

echo.
echo Starting... login page will open automatically.
echo.

start "Open Login" cmd /c "powershell -ExecutionPolicy Bypass -NoProfile -File scripts\open-login.ps1"

call npm.cmd run client:start:fast
set EXITCODE=%ERRORLEVEL%

echo.
if %EXITCODE% NEQ 0 echo [ERROR] Exit code %EXITCODE% — try Repair Start.bat
pause
exit /b %EXITCODE%
