#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
TOOLS_DIR="$SCRIPT_DIR/tools/arduino-cli"
ARDUINO_CONFIG_DIR="$SCRIPT_DIR/.arduino-cli"
ARDUINO_CONFIG_FILE="$ARDUINO_CONFIG_DIR/arduino-cli.yaml"
ARDUINO_PACKAGE_INDEX="https://espressif.github.io/arduino-esp32/package_esp32_index.json"

require_command() {
  local command_name="$1"
  local help_message="$2"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "$help_message"
    exit 1
  fi
}

write_arduino_config() {
  mkdir -p \
    "$ARDUINO_CONFIG_DIR" \
    "$ARDUINO_CONFIG_DIR/data" \
    "$ARDUINO_CONFIG_DIR/downloads" \
    "$ARDUINO_CONFIG_DIR/user" \
    "$ARDUINO_CONFIG_DIR/build" \
    "$ARDUINO_CONFIG_DIR/cache"

  cat > "$ARDUINO_CONFIG_FILE" <<EOF
board_manager:
  additional_urls:
    - $ARDUINO_PACKAGE_INDEX
directories:
  data: $ARDUINO_CONFIG_DIR/data
  downloads: $ARDUINO_CONFIG_DIR/downloads
  user: $ARDUINO_CONFIG_DIR/user
library:
  enable_unsafe_install: false
EOF
}

install_backend_dependencies() {
  echo "==> Backend dependencies"
  cd "$BACKEND_DIR"

  if [ ! -x ".venv/bin/python" ]; then
    echo "Creating backend virtual environment..."
    python3 -m venv .venv
  fi

  echo "Installing Python packages..."
  ".venv/bin/python" -m pip install --upgrade pip
  ".venv/bin/python" -m pip install -r requirements.txt
}

install_frontend_dependencies() {
  echo "==> Frontend dependencies"
  cd "$FRONTEND_DIR"

  echo "Installing npm packages..."
  npm install
}

install_arduino_cli() {
  echo "==> Arduino CLI and ESP32 core"
  require_command "curl" "curl is required to install arduino-cli. Install curl, then rerun this script."

  mkdir -p "$TOOLS_DIR"
  write_arduino_config

  if [ ! -x "$TOOLS_DIR/arduino-cli" ]; then
    echo "Installing arduino-cli into $TOOLS_DIR ..."
    curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR="$TOOLS_DIR" sh
  else
    echo "arduino-cli already present."
  fi

  echo "Updating ESP32 board index..."
  "$TOOLS_DIR/arduino-cli" \
    --config-file "$ARDUINO_CONFIG_FILE" \
    --additional-urls "$ARDUINO_PACKAGE_INDEX" \
    core update-index

  echo "Installing ESP32 Arduino core..."
  "$TOOLS_DIR/arduino-cli" \
    --config-file "$ARDUINO_CONFIG_FILE" \
    --additional-urls "$ARDUINO_PACKAGE_INDEX" \
    core install esp32:esp32
}

main() {
  require_command "python3" "python3 is required to install backend dependencies."
  require_command "node" "Node.js 20+ is required to install frontend dependencies."
  require_command "npm" "npm is required to install frontend dependencies."

  echo "Installing project dependencies from $SCRIPT_DIR"
  install_backend_dependencies
  install_frontend_dependencies
  install_arduino_cli

  echo
  echo "Dependency installation complete."
  echo "Backend venv: $BACKEND_DIR/.venv"
  echo "Frontend node_modules: $FRONTEND_DIR/node_modules"
  echo "Arduino CLI: $TOOLS_DIR/arduino-cli"
  echo "Arduino config: $ARDUINO_CONFIG_FILE"
}

main "$@"
