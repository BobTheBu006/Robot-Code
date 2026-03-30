@echo off
setlocal

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
