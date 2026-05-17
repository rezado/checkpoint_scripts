import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "checkpoint_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


class StepMetadataTests(unittest.TestCase):
    def test_generate_metadata_creates_json_directory_and_worklist(self):
        try:
            metadata = importlib.import_module("step_metadata")
        except ModuleNotFoundError as exc:
            self.fail(f"step_metadata module missing: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "logs" / "profiling" / "demo").mkdir(parents=True)
            (base / "cluster" / "demo").mkdir(parents=True)
            (base / "checkpoint" / "demo" / "7").mkdir(parents=True)

            profiling_log = (
                "header line\n"
                "total guest instructions = 12,345\x1b[0m\n"
            )
            (base / "logs" / "profiling" / "demo" / "profiling.out.log").write_text(
                profiling_log,
                encoding="utf-8",
            )
            (base / "cluster" / "demo" / "weights0").write_text(
                "0.8 0\n0.00001 1\n",
                encoding="utf-8",
            )
            (base / "cluster" / "demo" / "simpoints0").write_text(
                "7 0\n8 1\n",
                encoding="utf-8",
            )

            metadata.generate_metadata(str(base), ["demo"], [1, 1, 1], [0, 0, 0])

            workload_json_path = base / "json" / "demo.json"
            all_json_path = base / "json" / "checkpoints_all.json"
            cov_json_path = base / "json" / "checkpoints_cov0.3.json"
            list_path = base / "checkpoint" / "checkpoint.lst"
            self.assertTrue(workload_json_path.is_file())
            self.assertTrue(all_json_path.is_file())
            self.assertTrue(cov_json_path.is_file())
            self.assertTrue(list_path.is_file())

            payload = json.loads(workload_json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["demo"]["insts"], "12345")
            self.assertEqual(payload["demo"]["points"], {"7": "0.8"})

            aggregated_all = json.loads(all_json_path.read_text(encoding="utf-8"))
            aggregated_cov = json.loads(cov_json_path.read_text(encoding="utf-8"))
            self.assertEqual(aggregated_all["demo"]["points"], {"7": "0.8"})
            self.assertEqual(aggregated_cov["demo"]["points"], {"7": "0.8"})

            entries = list_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(entries, ["demo_7 demo/7 0 0 20 20"])

    def test_generate_result_list_uses_plain_stage_names_for_default_ids(self):
        try:
            metadata = importlib.import_module("step_metadata")
        except ModuleNotFoundError as exc:
            self.fail(f"step_metadata module missing: {exc}")

        result = metadata.generate_result_list("/tmp/archive", [1, 1, 2], [0, 0, 0])

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["profiling_log"], "/tmp/archive/logs/profiling")
        self.assertEqual(result[1]["profiling_log"], "/tmp/archive/logs/profiling")
        self.assertEqual(result[1]["json_dir"], "/tmp/archive/json/checkpoint-0-0-1")

    def test_profiling_instrs_rejects_empty_profiling_log(self):
        try:
            metadata = importlib.import_module("step_metadata")
        except ModuleNotFoundError as exc:
            self.fail(f"step_metadata module missing: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "demo").mkdir(parents=True)
            (base / "demo" / "profiling.out.log").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "failed to find instructions"):
                metadata.profiling_instrs(str(base), "demo", using_step_layout=True)


if __name__ == "__main__":
    unittest.main()
