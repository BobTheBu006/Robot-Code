"""Loads machine-specific settings from backend/.env into the environment.

The gantry services read wiring facts (for example ROBOT_GPIO_A_DIR_INVERT) from
environment variables. Those describe this one machine, not the code, so they
belong in the gitignored backend/.env rather than in source or in whoever's
shell happened to launch uvicorn. Stdlib-only on purpose: no python-dotenv
dependency for a dozen lines of parsing.

Values already present in the real environment win, so a deliberate
`ROBOT_GPIO_A_DIR_INVERT=0 uvicorn ...` still overrides the file.
"""

import os
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def load_env_file() -> None:
    if not _ENV_PATH.exists():
        return
    try:
        content = _ENV_PATH.read_text(encoding="utf-8")
    except OSError:
        return

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value
