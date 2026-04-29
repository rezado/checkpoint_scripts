import concurrent.futures
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "checkpoint_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import take_checkpoint as take_checkpoint


class GenerateCommandThreadSafetyTests(unittest.TestCase):
    def test_generate_command_keeps_each_workload_tree_isolated(self):
        class InstrumentedCheckpointTree:
            root_barrier = None
            cluster_barrier = None
            checkpoint_barrier = None

            def __init__(self, value):
                self.value = value
                self.children = []
                if value is not None and value.get("execute_mode") == "profiling":
                    type(self).root_barrier.wait()
                    time.sleep(0.01)

            def add_child(self, child_node):
                mode = child_node.value.get("execute_mode") if child_node.value else None
                if mode == "cluster":
                    type(self).cluster_barrier.wait()
                    time.sleep(0.01)
                elif mode == "checkpoint":
                    type(self).checkpoint_barrier.wait()
                    time.sleep(0.01)
                self.children.append(child_node)

        def build_config():
            return {
                "NEMU": {
                    "NEMU": "/tmp/nemu",
                    "gcpt_restore": "/tmp/gcpt.bin",
                    "simpoint": "/tmp/simpoint",
                },
                "utils": {
                    "workload_folder": "",
                    "compile_format": "zstd",
                    "interval": "20000000",
                    "workload": "",
                    "buffer": "",
                    "bin_suffix": "",
                    "log_folder": "",
                },
                "profiling": {
                    "basename": "profiling",
                    "id": "0",
                    "times": "1",
                    "config": "",
                },
                "cluster": {
                    "basename": "cluster",
                    "id": "0",
                    "times": "1",
                    "config": "",
                },
                "checkpoint": {
                    "basename": "checkpoint",
                    "id": "0",
                    "times": "1",
                    "config": "",
                },
                "profiling_configs": [(0,)],
                "cluster_configs": [(0, 0)],
                "checkpoint_configs": [(0, 0, 0)],
            }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workloads = ["alpha", "beta", "gamma"]
            for workload in workloads:
                (tmp_path / workload).write_text(workload, encoding="utf-8")

            InstrumentedCheckpointTree.root_barrier = threading.Barrier(
                len(workloads)
            )
            InstrumentedCheckpointTree.cluster_barrier = threading.Barrier(
                len(workloads)
            )
            InstrumentedCheckpointTree.checkpoint_barrier = threading.Barrier(
                len(workloads)
            )

            def run_generate_command(workload):
                root = take_checkpoint.generate_command(
                    workload_folder=str(tmp_path),
                    workload=workload,
                    buffer=str(tmp_path / "archive" / workload),
                    bin_suffix="",
                    emu="NEMU",
                    log_folder=str(tmp_path / "logs" / workload),
                    cpu_bind="0",
                    mem_bind="0",
                    copies="1",
                    config=build_config(),
                    all_in_one_workload=True,
                )
                return workload, root

            with mock.patch.object(
                take_checkpoint, "CheckpointTree", InstrumentedCheckpointTree
            ):
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=len(workloads)
                ) as executor:
                    results = dict(executor.map(run_generate_command, workloads))

        for workload, root in results.items():
            self.assertEqual(root.value["utils"]["workload"], workload)
            self.assertEqual(len(root.children), 1)
            cluster = root.children[0]
            self.assertEqual(cluster.value["utils"]["workload"], workload)
            self.assertEqual(len(cluster.children), 1)
            checkpoint = cluster.children[0]
            self.assertEqual(checkpoint.value["utils"]["workload"], workload)


class LevelFirstExecTests(unittest.TestCase):
    def test_level_first_exec_stops_after_failed_level(self):
        events = []

        class FakeNode:
            def __init__(self, name, returncode, children=None):
                self.children = list(children or [])
                self.value = {
                    "execute_mode": name,
                    "utils": {"workload": name},
                    "command": [name],
                }
                self._returncode = returncode

            def execute(self):
                events.append(self.value["execute_mode"])
                return self._returncode

        class InlineExecutor:
            def __init__(self, max_workers=None):
                self.max_workers = max_workers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, fn):
                future = concurrent.futures.Future()
                try:
                    future.set_result(fn())
                except Exception as exc:  # pragma: no cover - test helper
                    future.set_exception(exc)
                return future

        root = FakeNode("profiling", 1, children=[FakeNode("cluster", 0)])

        with mock.patch.object(
            take_checkpoint.concurrent.futures, "ProcessPoolExecutor", InlineExecutor
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                take_checkpoint.level_first_exec(root)

        self.assertEqual(events, ["profiling"])

    def test_level_first_exec_uses_level_size_for_worker_count(self):
        worker_counts = []

        class FakeNode:
            def __init__(self, name, children=None):
                self.children = list(children or [])
                self.value = {
                    "execute_mode": name,
                    "utils": {"workload": name},
                    "command": [name],
                }

            def execute(self):
                return 0

        class RecordingExecutor:
            def __init__(self, max_workers=None):
                worker_counts.append(max_workers)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, fn):
                future = concurrent.futures.Future()
                future.set_result(fn())
                return future

        root = FakeNode("profiling", children=[FakeNode("cluster")])

        with mock.patch.object(
            take_checkpoint.concurrent.futures, "ProcessPoolExecutor", RecordingExecutor
        ):
            take_checkpoint.level_first_exec(root)

        self.assertEqual(worker_counts, [1, 1])


if __name__ == "__main__":
    unittest.main()
