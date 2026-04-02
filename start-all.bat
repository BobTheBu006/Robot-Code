@echo off
setlocal

echo Opening backend and frontend launchers...
start "Robot Backend" cmd /k ""%~dp0start-backend.bat""
start "Robot Frontend" cmd /k ""%~dp0start-frontend.bat""
timeout /t 6 /nobreak >nul
start "" "http://127.0.0.1:5173"
