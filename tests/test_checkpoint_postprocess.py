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


class CheckpointPostprocessTests(unittest.TestCase):
    def test_dump_result_generates_cluster_json_and_worklist(self):
        try:
            postprocess = importlib.import_module("checkpoint_postprocess")
        except ModuleNotFoundError as exc:
            self.fail(f"checkpoint_postprocess module missing: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "logs" / "profiling-0" / "demo").mkdir(parents=True)
            (base / "cluster-0-0" / "demo").mkdir(parents=True)
            (base / "checkpoint-0-0-0" / "demo" / "7").mkdir(parents=True)

            profiling_log = (
                "header line\n"
                "total guest instructions = 12,345\x1b[0m\n"
            )
            (base / "logs" / "profiling-0" / "demo" / "profiling.out.log").write_text(
                profiling_log,
                encoding="utf-8",
            )
            (base / "cluster-0-0" / "demo" / "weights0").write_text(
                "0.8 0\n0.00001 1\n",
                encoding="utf-8",
            )
            (base / "cluster-0-0" / "demo" / "simpoints0").write_text(
                "7 0\n8 1\n",
                encoding="utf-8",
            )

            postprocess.dump_result(str(base), ["demo"], [1, 1, 1], [0, 0, 0])

            json_path = base / "checkpoint-0-0-0" / "cluster-0-0.json"
            list_path = base / "checkpoint-0-0-0" / "checkpoint.lst"
            self.assertTrue(json_path.is_file())
            self.assertTrue(list_path.is_file())

            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["demo"]["insts"], "12345")
            self.assertEqual(payload["demo"]["points"], {"7": "0.8"})

            entries = list_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(entries, ["demo_7 demo/7 0 0 20 20"])

    def test_generate_result_list_uses_profiling_index_for_logs(self):
        try:
            postprocess = importlib.import_module("checkpoint_postprocess")
        except ModuleNotFoundError as exc:
            self.fail(f"checkpoint_postprocess module missing: {exc}")

        result = postprocess.generate_result_list("/tmp/archive", [1, 1, 2], [0, 0, 0])

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["profiling_log"], "/tmp/archive/logs/profiling-0")
        self.assertEqual(result[1]["profiling_log"], "/tmp/archive/logs/profiling-0")
        self.assertEqual(result[1]["json_path"], "/tmp/archive/checkpoint-0-0-1/cluster-0-0.json")

    def test_profiling_instrs_rejects_empty_profiling_log(self):
        try:
            postprocess = importlib.import_module("checkpoint_postprocess")
        except ModuleNotFoundError as exc:
            self.fail(f"checkpoint_postprocess module missing: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "demo").mkdir(parents=True)
            (base / "demo" / "profiling.out.log").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "failed to find instructions"):
                postprocess.profiling_instrs(str(base), "demo", using_new_script=True)


if __name__ == "__main__":
    unittest.main()
