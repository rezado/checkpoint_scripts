import concurrent.futures
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


if __name__ == "__main__":
    unittest.main()
