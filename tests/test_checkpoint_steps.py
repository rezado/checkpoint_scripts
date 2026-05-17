import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "checkpoint_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import step_checkpoint
import step_cluster
import step_profiling


class CheckpointStepTests(unittest.TestCase):
    def test_profiling_command_uses_plain_stage_name(self):
        command = step_profiling.build_profiling_command(
            nemu_bin="/tmp/nemu",
            workload_bin="/tmp/input/demo.bin",
            archive_root="/tmp/archive",
            workload="demo",
            interval=20000000,
            cpu_bind="0",
            mem_bind="1",
        )

        self.assertIn("/tmp/nemu", command)
        self.assertIn("profiling", command)
        self.assertIn("--simpoint-profile", command)
        self.assertIn("/tmp/input/demo.bin", command)

    def test_cluster_command_uses_expected_paths(self):
        command = step_cluster.build_cluster_command(
            simpoint_bin="/tmp/simpoint",
            archive_root="/tmp/archive",
            workload="demo",
            cpu_bind="1",
            mem_bind="0",
            max_k=None,
            seedkm=111111,
            seedproj=222222,
        )

        self.assertIn("/tmp/archive/profiling/demo/simpoint_bbv.gz", command)
        self.assertIn("/tmp/archive/cluster/demo/simpoints0", command)
        self.assertIn("/tmp/archive/cluster/demo/weights0", command)
        self.assertIn("111111", command)
        self.assertIn("222222", command)

    def test_cluster_command_uses_larger_k_for_xalancbmk(self):
        command = step_cluster.build_cluster_command(
            simpoint_bin="/tmp/simpoint",
            archive_root="/tmp/archive",
            workload="xalancbmk",
            cpu_bind="0",
            mem_bind="0",
            max_k=None,
            seedkm=111111,
            seedproj=222222,
        )

        maxk_index = command.index("-maxK")
        self.assertEqual(command[maxk_index + 1], "100")

    def test_cluster_command_uses_requested_max_k_when_larger_than_default(self):
        command = step_cluster.build_cluster_command(
            simpoint_bin="/tmp/simpoint",
            archive_root="/tmp/archive",
            workload="demo",
            cpu_bind="0",
            mem_bind="0",
            max_k=80,
            seedkm=111111,
            seedproj=222222,
        )

        maxk_index = command.index("-maxK")
        self.assertEqual(command[maxk_index + 1], "80")

    def test_cluster_command_preserves_workload_floor_for_requested_max_k(self):
        command = step_cluster.build_cluster_command(
            simpoint_bin="/tmp/simpoint",
            archive_root="/tmp/archive",
            workload="xalancbmk",
            cpu_bind="0",
            mem_bind="0",
            max_k=60,
            seedkm=111111,
            seedproj=222222,
        )

        maxk_index = command.index("-maxK")
        self.assertEqual(command[maxk_index + 1], "100")

    def test_checkpoint_command_uses_cluster_root_and_plain_stage_name(self):
        command = step_checkpoint.build_checkpoint_command(
            nemu_bin="/tmp/nemu",
            workload_bin="/tmp/input/demo.bin",
            archive_root="/tmp/archive",
            workload="demo",
            interval=20000000,
            cpu_bind="0",
            mem_bind="0",
        )

        self.assertIn("checkpoint", command)
        self.assertIn("/tmp/archive/cluster", command)
        self.assertIn("--cpt-interval", command)
        self.assertIn("/tmp/input/demo.bin", command)


if __name__ == "__main__":
    unittest.main()
