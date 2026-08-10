"""Writing down what a run actually did.

The point of the journal is being able to answer "what did the machine do"
after the browser tab is gone, so these tests care about durability and about
never letting record-keeping interfere with a run in progress.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.journal import RunJournal, list_runs, prune_old_runs, read_run


class JournalWritingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_records_are_appended_one_per_line(self) -> None:
        journal = RunJournal("run1", self.root)
        journal.write("run_started", node_count=3)
        journal.write("block_finished", node_id="a", ok=True)
        journal.write("run_finished", ok=True)

        lines = journal.path.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 3)
        self.assertEqual([json.loads(line)["kind"] for line in lines],
                         ["run_started", "block_finished", "run_finished"])

    def test_every_record_is_stamped_and_attributed(self) -> None:
        journal = RunJournal("run2", self.root)
        journal.write("block_finished", node_id="a")
        record = read_run("run2", self.root)[0]
        self.assertEqual(record["run_id"], "run2")
        self.assertIn("at", record)

    def test_earlier_records_are_never_rewritten(self) -> None:
        # Append-only is the whole value: a later failure must not be able to
        # erase the entry that explains it.
        journal = RunJournal("run3", self.root)
        journal.write("block_finished", node_id="a", ok=True)
        first = journal.path.read_text(encoding="utf-8")
        journal.write("block_finished", node_id="b", ok=False)
        self.assertTrue(journal.path.read_text(encoding="utf-8").startswith(first))

    def test_values_that_are_not_json_do_not_lose_the_record(self) -> None:
        journal = RunJournal("run4", self.root)
        journal.write("block_finished", result={"when": object()})
        self.assertEqual(len(read_run("run4", self.root)), 1)

    def test_a_write_failure_does_not_raise_into_a_running_machine(self) -> None:
        # Stopping mid-dispense because a log line could not be written would
        # be worse than losing the line.
        journal = RunJournal("run5", self.root / "nope")
        journal._root = Path("/proc/cannot/write/here")
        journal.write("run_started")  # must not raise
        journal.write("run_finished")


class JournalReadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_a_torn_line_does_not_make_the_run_unreadable(self) -> None:
        journal = RunJournal("run6", self.root)
        journal.write("run_started")
        with journal.path.open("a", encoding="utf-8") as handle:
            handle.write('{"kind": "block_fini\n')  # cut off by a power loss
        journal.write("run_finished", ok=True)

        records = read_run("run6", self.root)
        self.assertEqual([r["kind"] for r in records], ["run_started", "run_finished"])

    def test_an_unknown_run_reads_as_empty(self) -> None:
        self.assertEqual(read_run("never-happened", self.root), [])

    def test_runs_are_summarised_newest_first(self) -> None:
        for index, run_id in enumerate(["old", "new"]):
            journal = RunJournal(run_id, self.root)
            journal.write("run_started", node_count=2)
            journal.write("block_finished", node_id="a", ok=True)
            journal.write("run_finished", ok=index == 1)
            # Space the files out so ordering by mtime is deterministic.
            import os
            import time
            stamp = time.time() + index
            os.utime(journal.path, (stamp, stamp))

        summaries = list_runs(self.root)
        self.assertEqual([s["run_id"] for s in summaries], ["new", "old"])
        self.assertEqual(summaries[0]["blocks_run"], 1)
        self.assertTrue(summaries[0]["ok"])
        self.assertFalse(summaries[1]["ok"])

    def test_an_unfinished_run_is_marked_in_progress(self) -> None:
        journal = RunJournal("running", self.root)
        journal.write("run_started")
        summary = list_runs(self.root)[0]
        self.assertTrue(summary["in_progress"])
        self.assertIsNone(summary["finished_at"])


class JournalPruningTests(unittest.TestCase):
    def test_only_the_newest_runs_are_kept(self) -> None:
        import os
        import time

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for index in range(6):
                journal = RunJournal(f"run{index}", root)
                journal.write("run_started")
                stamp = time.time() + index
                os.utime(journal.path, (stamp, stamp))

            removed = prune_old_runs(root, keep=2)
            self.assertEqual(removed, 4)
            remaining = sorted(path.stem for path in root.glob("*.jsonl"))
            self.assertEqual(remaining, ["run4", "run5"])


if __name__ == "__main__":
    unittest.main()
