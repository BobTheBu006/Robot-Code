#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_PROJECT_DIR="/home/robot/robot control/Robot-Code"
if [[ -f "$SCRIPT_DIR/start-backend.sh" && -f "$SCRIPT_DIR/start-frontend.sh" ]]; then
  PROJECT_DIR="$SCRIPT_DIR"
else
  PROJECT_DIR="${ROBOT_CODE_DIR:-$DEFAULT_PROJECT_DIR}"
fi
FRONTEND_URL="http://127.0.0.1:5173"
FRONTEND_HOST="127.0.0.1"
FRONTEND_PORT="5173"

if [[ ! -f "$PROJECT_DIR/start-backend.sh" || ! -f "$PROJECT_DIR/start-frontend.sh" ]]; then
  echo "Could not find Robot-Code launch scripts."
  echo "Checked project directory: $PROJECT_DIR"
  exit 1
fi

open_terminal() {
  local title="$1"
  local script_name="$2"

  if command -v x-terminal-emulator >/dev/null 2>&1; then
    x-terminal-emulator -T "$title" -e bash "$PROJECT_DIR/$script_name"
  elif command -v lxterminal >/dev/null 2>&1; then
    lxterminal --title="$title" --command="bash '$PROJECT_DIR/$script_name'"
  elif command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title="$title" -- bash "$PROJECT_DIR/$script_name"
  else
    echo "Could not find a graphical terminal emulator."
    echo "Run '$PROJECT_DIR/start-backend.sh' and '$PROJECT_DIR/start-frontend.sh' in separate terminals."
    exit 1
  fi
}

open_browser() {
  if command -v xdg-open >/dev/null 2>&1; then
    nohup xdg-open "$FRONTEND_URL" >/dev/null 2>&1 &
  elif command -v sensible-browser >/dev/null 2>&1; then
    nohup sensible-browser "$FRONTEND_URL" >/dev/null 2>&1 &
  elif command -v chromium >/dev/null 2>&1; then
    nohup chromium "$FRONTEND_URL" >/dev/null 2>&1 &
  elif command -v firefox >/dev/null 2>&1; then
    nohup firefox "$FRONTEND_URL" >/dev/null 2>&1 &
  else
    echo "Could not find a browser to open automatically."
    echo "Open $FRONTEND_URL manually once the frontend starts."
  fi
}

wait_for_frontend() {
  for _ in $(seq 1 45); do
    if command -v curl >/dev/null 2>&1; then
      if curl --silent --fail "$FRONTEND_URL" >/dev/null 2>&1; then
        return 0
      fi
    elif command -v wget >/dev/null 2>&1; then
      if wget -q --spider "$FRONTEND_URL" >/dev/null 2>&1; then
        return 0
      fi
    elif (echo >/dev/tcp/"$FRONTEND_HOST"/"$FRONTEND_PORT") >/dev/null 2>&1; then
      return 0
    fi

    sleep 1
  done

  return 1
}

echo "Opening backend and frontend launchers..."
open_terminal "Robot Backend" "start-backend.sh"
open_terminal "Robot Frontend" "start-frontend.sh"

(
  if wait_for_frontend; then
    open_browser
  else
    echo "Frontend did not become ready in time for automatic browser launch."
    echo "Open $FRONTEND_URL manually."
  fi
) &
