import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "checkpoint_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_single_bin_checkpoint as single_bin


class SingleBinCheckpointTests(unittest.TestCase):
    def test_build_archive_layout_contains_expected_paths(self):
        layout = single_bin.build_archive_layout("/tmp/archive/demo")
        self.assertEqual(layout["gcpt_bins"], "/tmp/archive/demo/gcpt_bins")
        self.assertEqual(layout["logs"], "/tmp/archive/demo/logs")
        self.assertEqual(layout["metadata"], "/tmp/archive/demo/metadata")

    def test_validate_resume_after_cluster_requires_simpoint_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            archive_root.mkdir()
            with self.assertRaisesRegex(FileNotFoundError, "simpoints0"):
                single_bin.validate_resume_artifacts(
                    archive_root=str(archive_root),
                    workload="demo",
                    resume_after="cluster",
                )

    def test_write_request_metadata_persists_user_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata_dir = Path(tmp) / "metadata"
            metadata_dir.mkdir()
            output = single_bin.write_request_metadata(
                metadata_dir=str(metadata_dir),
                request={
                    "bin": "/tmp/demo.bin",
                    "name": "demo",
                    "archive_id": "archive-demo",
                    "interval": 20000000,
                    "copies": 1,
                    "resume_after": None,
                },
            )
            self.assertTrue(Path(output).is_file())
            text = Path(output).read_text(encoding="utf-8")
            self.assertIn("name: demo", text)
            self.assertIn("interval: 20000000", text)

    def test_parse_args_requires_bin_and_name(self):
        parser = single_bin.build_arg_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_validate_outputs_accepts_zstd_checkpoint_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            (archive_root / "profiling-0" / "demo").mkdir(parents=True)
            (archive_root / "cluster-0-0" / "demo").mkdir(parents=True)
            checkpoint_dir = archive_root / "checkpoint-0-0-0" / "demo" / "0"
            checkpoint_dir.mkdir(parents=True)

            (archive_root / "profiling-0" / "demo" / "simpoint_bbv.gz").write_text(
                "bbv", encoding="utf-8"
            )
            (archive_root / "cluster-0-0" / "demo" / "simpoints0").write_text(
                "0 0", encoding="utf-8"
            )
            (archive_root / "cluster-0-0" / "demo" / "weights0").write_text(
                "1 1.0", encoding="utf-8"
            )
            (checkpoint_dir / "_0_1.0_.zstd").write_text("checkpoint", encoding="utf-8")

            single_bin.validate_outputs(str(archive_root), "demo")

    def test_main_invokes_checkpoint_postprocess_after_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive" / "demo-archive"
            input_bin = Path(tmp) / "demo.bin"
            input_bin.write_text("bin", encoding="utf-8")
            expected_archive_root = str((REPO_ROOT / "archive" / "demo-archive").resolve())

            args = Namespace(
                bin=str(input_bin),
                name="demo",
                archive_id="demo-archive",
                interval=20000000,
                copies=1,
                resume_after=None,
            )

            parser = mock.Mock()
            parser.parse_args.return_value = args

            with mock.patch.object(single_bin, "build_arg_parser", return_value=parser), \
                 mock.patch.object(single_bin, "validate_input_args"), \
                 mock.patch.object(single_bin, "ensure_directories"), \
                 mock.patch.object(single_bin, "write_request_metadata", return_value=str(archive_root / "metadata" / "single_bin_request.yaml")), \
                 mock.patch.object(single_bin, "copy_input_bin", return_value=str(archive_root / "gcpt_bins" / "demo")), \
                 mock.patch.object(single_bin, "validate_resume_artifacts"), \
                 mock.patch.object(single_bin, "ensure_resume_logs"), \
                 mock.patch.object(single_bin, "validate_runtime_tools"), \
                 mock.patch.object(
                     single_bin,
                     "TakeCheckpointConfig",
                     return_value=mock.Mock(get_config=mock.Mock(return_value={"utils": {}})),
                 ), \
                 mock.patch.object(single_bin, "generate_command", return_value=object()), \
                 mock.patch.object(single_bin, "level_first_exec"), \
                 mock.patch.object(single_bin, "validate_outputs"), \
                 mock.patch.object(single_bin, "count_checkpoints", return_value=1), \
                 mock.patch.dict(single_bin.os.environ, {"NEMU_HOME": "/tmp/nemu"}, clear=False), \
                 mock.patch.object(single_bin, "generate_checkpoint_metadata", create=True) as postprocess:
                exit_code = single_bin.main()

            self.assertEqual(exit_code, 0)
            postprocess.assert_called_once_with(
                archive_root=expected_archive_root,
                workloads=["demo"],
                times=[1, 1, 1],
                ids=[0, 0, 0],
            )


if __name__ == "__main__":
    unittest.main()
