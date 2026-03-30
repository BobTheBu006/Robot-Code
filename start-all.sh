#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

open_terminal() {
  local title="$1"
  local script_name="$2"

  if command -v x-terminal-emulator >/dev/null 2>&1; then
    x-terminal-emulator -T "$title" -e bash "$SCRIPT_DIR/$script_name"
  elif command -v lxterminal >/dev/null 2>&1; then
    lxterminal --title="$title" --command="bash '$SCRIPT_DIR/$script_name'"
  elif command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title="$title" -- bash "$SCRIPT_DIR/$script_name"
  else
    echo "Could not find a graphical terminal emulator."
    echo "Run '$SCRIPT_DIR/start-backend.sh' and '$SCRIPT_DIR/start-frontend.sh' in separate terminals."
    exit 1
  fi
}

echo "Opening backend and frontend launchers..."
open_terminal "Robot Backend" "start-backend.sh"
open_terminal "Robot Frontend" "start-frontend.sh"
