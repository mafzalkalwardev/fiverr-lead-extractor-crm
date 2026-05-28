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
echo  App URL: http://localhost:3000/
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

echo Starting portable local MongoDB...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-local-mongo.ps1
if errorlevel 1 (
  echo Local database could not start. Please run app as Administrator once or contact FT Solutions +92307-9670503.
  pause
  exit /b 1
)

echo Starting portable Redis 5...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-redis5.ps1

for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
  if /i "%%A"=="MONGODB_URI" set "MONGODB_URI=%%B"
)

echo Freeing port 3000 and browser locks...
call npm.cmd run free:port
call npm.cmd run free:browser

set "PYTHON_AUTO_VERIFICATION_MAX_ATTEMPTS=8"
set "ALLOW_OS_MOUSE_AUTOMATION=false"
set "FOCUS_BROWSER_ON_VERIFICATION=true"

echo.
echo Starting... app window will open automatically.
echo.

start "Open Fiverr Lead CRM" cmd /c "powershell -ExecutionPolicy Bypass -NoProfile -File scripts\open-app.ps1"

call npm.cmd run client:start:fast
set EXITCODE=%ERRORLEVEL%

echo.
if %EXITCODE% NEQ 0 echo [ERROR] Exit code %EXITCODE% — try Repair Start.bat
pause
exit /b %EXITCODE%
