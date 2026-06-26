#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/backend"

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

echo "Installing backend dependencies..."
".venv/bin/python" -m pip install -r requirements.txt

echo
echo "Frontend UI: http://127.0.0.1:5173"
echo "Backend health: http://127.0.0.1:8000/health"
echo "Backend robot state: http://127.0.0.1:8000/api/robot/state"
echo "Backend docs: http://127.0.0.1:8000/docs"
echo
echo "Starting FastAPI backend..."
".venv/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
