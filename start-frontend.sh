#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/frontend"

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is not installed or is not on PATH."
  echo "Install Node.js 20+ and npm, then run this script again."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is not installed or is not on PATH."
  echo "Install npm along with Node.js 20+, then run this script again."
  exit 1
fi

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  cp .env.example .env
fi

if [ ! -d "node_modules" ]; then
  echo "Installing frontend dependencies..."
  npm install
fi

echo
echo "Frontend UI: http://127.0.0.1:5173"
echo "Network UI:  http://<raspberry-pi-ip>:5173"
echo "API mode:    same-origin /api requests proxied to http://127.0.0.1:8000"
echo
echo "Starting frontend..."
npm run dev
