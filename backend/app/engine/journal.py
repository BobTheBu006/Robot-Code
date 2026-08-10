"""Write down what actually ran.

A run drives real hardware: it moves a gantry, dispenses volumes, homes an
axis. When something comes out wrong hours later, "what did the machine
actually do" needs an answer that does not depend on a browser tab still being
open. The in-memory run session is gone the moment the run ends; this is not.

Append-only, one JSON object per line, one file per run. Append-only because
the value here is being able to trust it: a record that gets rewritten as the
run progresses can lose exactly the entry that explains a failure. Reading the
whole thing back is never needed during a run, so nothing is held in memory.

Failures to write are swallowed. A full disk or a read-only mount should not
take down a run that is physically in progress - losing the record is bad,
stopping mid-dispense because we could not write a log line is worse.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

# Keep the newest runs and drop the rest, so an unattended machine does not
# slowly fill its card with run logs.
MAX_RETAINED_RUNS = 200


def _journal_root() -> Path:
    override = os.environ.get("ROBOT_RUN_JOURNAL_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "run-journal"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunJournal:
    """One file, appended to as a run progresses."""

    def __init__(self, run_id: str, root: Path | None = None) -> None:
        self.run_id = run_id
        self._root = root or _journal_root()
        self._path = self._root / f"{run_id}.jsonl"
        self._lock = threading.Lock()
        self._disabled = False

    @property
    def path(self) -> Path:
        return self._path

    def write(self, kind: str, **fields) -> None:
        if self._disabled:
            return
        record = {"at": _now(), "run_id": self.run_id, "kind": kind, **fields}
        line = json.dumps(record, default=str, ensure_ascii=False)
        try:
            with self._lock:
                self._root.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except OSError:
            # Never let record-keeping stop a run that is physically underway.
            # One failure means the medium is unavailable, so stop trying.
            self._disabled = True


def prune_old_runs(root: Path | None = None, keep: int = MAX_RETAINED_RUNS) -> int:
    """Delete all but the newest `keep` run files. Returns how many went."""
    directory = root or _journal_root()
    try:
        files = sorted(
            (path for path in directory.glob("*.jsonl") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return 0

    removed = 0
    for path in files[keep:]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def read_run(run_id: str, root: Path | None = None) -> list[dict]:
    """Read one run back. Malformed lines are skipped, not raised.

    A journal is worth more partially readable than not at all: a line torn by
    a power cut should not make the rest of the run unreadable.
    """
    path = (root or _journal_root()) / f"{run_id}.jsonl"
    if not path.exists():
        return []

    records: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def list_runs(root: Path | None = None, limit: int = 50) -> list[dict]:
    """Summarise recent runs, newest first."""
    directory = root or _journal_root()
    try:
        files = sorted(
            (path for path in directory.glob("*.jsonl") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:limit]
    except OSError:
        return []

    summaries: list[dict] = []
    for path in files:
        records = read_run(path.stem, directory)
        if not records:
            continue
        started = records[0]
        finished = next((r for r in reversed(records) if r["kind"] == "run_finished"), None)
        summaries.append({
            "run_id": path.stem,
            "started_at": started.get("at"),
            "finished_at": finished.get("at") if finished else None,
            "ok": finished.get("ok") if finished else None,
            "error": finished.get("error") if finished else None,
            "blocks_run": sum(1 for r in records if r["kind"] == "block_finished"),
            "in_progress": finished is None,
        })
    return summaries
