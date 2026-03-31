@echo off
setlocal

where node >nul 2>nul
if errorlevel 1 (
  echo Node.js is not installed or is not on PATH.
  echo Install Node.js 20+ and npm, then run this script again.
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo npm is not installed or is not on PATH.
  echo Install npm along with Node.js 20+, then run this script again.
  pause
  exit /b 1
)

cd /d "%~dp0frontend"

if not exist ".env" if exist ".env.example" (
  copy /Y ".env.example" ".env" >nul
)

if not exist "node_modules" (
  echo Installing frontend dependencies...
  npm.cmd install
  if errorlevel 1 (
    echo.
    echo Failed to install frontend dependencies.
    pause
    exit /b 1
  )
)

echo.
echo Frontend UI: http://127.0.0.1:5173
echo.
echo Starting frontend...
npm.cmd run dev

echo.
echo Frontend stopped.
pause
