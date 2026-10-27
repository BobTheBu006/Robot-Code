#!/usr/bin/env bash
set -euo pipefail

pause_on_error() {
  local status=$?
  if [[ $status -ne 0 && -t 0 ]]; then
    echo
    echo "Backend launcher failed with exit code $status."
    read -r -p "Press Enter to close this window..." _
  fi
}
trap pause_on_error EXIT

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/backend"

# A backend may already be running (e.g. left over from an earlier launch).
# Starting a second one only fails with "Address already in use", so say
# what is going on instead.
if curl --silent --fail --max-time 3 http://127.0.0.1:8000/health >/dev/null 2>&1; then
  echo "The backend is already running and healthy on port 8000."
  echo "Backend health: http://127.0.0.1:8000/health"
  echo "Nothing to start. (It reloads by itself when code changes.)"
  [[ -t 0 ]] && read -r -p "Press Enter to close this window..." _
  exit 0
fi
if ss -ltn 2>/dev/null | grep -q ':8000 '; then
  echo "Port 8000 is in use but the backend does not answer /health."
  echo "Find the process with:  ss -ltnp | grep :8000"
  exit 1
fi

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
# Step pulse width. The interval between steps is floored at twice this, so
# it sets the machine's top speed: 15 us -> 30 us floor -> ~33k steps/s, which
# at 800 steps/rotation is about 2500 RPM.
#
# It was 100 us, capping this machine at 375 RPM - which is why 400, 800 and
# 1600 RPM all felt identical. A TB6600's opto input needs a few microseconds
# to switch, so this cannot go much lower without the driver starting to miss
# pulses outright.
export ROBOT_GPIO_STEP_PULSE_SECONDS="${ROBOT_GPIO_STEP_PULSE_SECONDS:-0.000015}"

echo "Starting FastAPI backend..."
".venv/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
