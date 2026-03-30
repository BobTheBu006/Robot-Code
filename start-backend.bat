@echo off
setlocal

cd /d "%~dp0backend"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
)

echo Installing backend dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Failed to install backend dependencies.
  pause
  exit /b 1
)

echo.
echo Frontend UI: http://127.0.0.1:5173
echo Backend health: http://127.0.0.1:8000/health
echo Backend robot state: http://127.0.0.1:8000/api/robot/state
echo Backend docs: http://127.0.0.1:8000/docs
echo.
echo Starting FastAPI backend...
".venv\Scripts\python.exe" -m uvicorn app.main:app --reload

echo.
echo Backend stopped.
pause
