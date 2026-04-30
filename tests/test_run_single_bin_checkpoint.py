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

    def test_parse_args_accepts_max_workers(self):
        parser = single_bin.build_arg_parser()
        args = parser.parse_args(
            ["--bin-list", "/tmp/bins.txt", "--max-workers", "3"]
        )
        self.assertEqual(args.max_workers, 3)

    def test_load_bin_list_entries_ignores_comments_and_uses_file_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bins"
            bin_dir.mkdir()
            alpha_bin = bin_dir / "alpha.bin"
            beta_bin = bin_dir / "beta.gcpt"
            alpha_bin.write_text("alpha", encoding="utf-8")
            beta_bin.write_text("beta", encoding="utf-8")

            bin_list = Path(tmp) / "bins.txt"
            bin_list.write_text(
                "\n".join(
                    [
                        "# batch inputs",
                        "",
                        str(alpha_bin),
                        f"  {beta_bin}  ",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            entries = single_bin.load_bin_list_entries(str(bin_list))

            self.assertEqual(
                entries,
                [
                    {"bin": str(alpha_bin), "name": "alpha.bin"},
                    {"bin": str(beta_bin), "name": "beta.gcpt"},
                ],
            )

    def test_validate_input_args_rejects_archive_id_for_bin_list_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_list = Path(tmp) / "bins.txt"
            bin_list.write_text("/tmp/demo.bin\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "archive-id"):
                single_bin.validate_input_args(
                    Namespace(
                        bin=None,
                        bin_list=str(bin_list),
                        name=None,
                        archive_id="shared-archive",
                        interval=20000000,
                        copies=1,
                        resume_after=None,
                        max_workers=3,
                    )
                )

    def test_validate_input_args_rejects_non_positive_max_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_list = Path(tmp) / "bins.txt"
            bin_list.write_text("/tmp/demo.bin\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "max-workers"):
                single_bin.validate_input_args(
                    Namespace(
                        bin=None,
                        bin_list=str(bin_list),
                        name=None,
                        archive_id=None,
                        interval=20000000,
                        copies=1,
                        resume_after=None,
                        max_workers=0,
                    )
                )

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
                "1.0 0", encoding="utf-8"
            )
            (checkpoint_dir / "_0_1.0_.zstd").write_text("checkpoint", encoding="utf-8")

            single_bin.validate_outputs(str(archive_root), "demo")

    def test_validate_outputs_rejects_missing_expected_checkpoint_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            (archive_root / "profiling-0" / "demo").mkdir(parents=True)
            (archive_root / "cluster-0-0" / "demo").mkdir(parents=True)
            present_dir = archive_root / "checkpoint-0-0-0" / "demo" / "55"
            missing_dir = archive_root / "checkpoint-0-0-0" / "demo" / "2444"
            present_dir.mkdir(parents=True)
            missing_dir.mkdir(parents=True)

            (archive_root / "profiling-0" / "demo" / "simpoint_bbv.gz").write_text(
                "bbv", encoding="utf-8"
            )
            (archive_root / "cluster-0-0" / "demo" / "simpoints0").write_text(
                "55 0\n2444 1\n", encoding="utf-8"
            )
            (archive_root / "cluster-0-0" / "demo" / "weights0").write_text(
                "0.081159 0\n0.009262 1\n", encoding="utf-8"
            )
            (present_dir / "_55_0.081159_memory_.zstd").write_text(
                "checkpoint", encoding="utf-8"
            )

            with self.assertRaisesRegex(FileNotFoundError, "2444"):
                single_bin.validate_outputs(str(archive_root), "demo")

    def test_reset_stage_outputs_clears_stale_outputs_for_fresh_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            profiling_dir = archive_root / "profiling-0" / "demo"
            cluster_dir = archive_root / "cluster-0-0" / "demo"
            checkpoint_dir = archive_root / "checkpoint-0-0-0" / "demo" / "55"
            profiling_log_dir = archive_root / "logs" / "profiling-0" / "demo"
            cluster_log_dir = archive_root / "logs" / "cluster-0-0" / "demo"
            checkpoint_log_dir = archive_root / "logs" / "checkpoint-0-0-0" / "demo"
            metadata_dir = archive_root / "metadata"

            for path in [
                profiling_dir,
                cluster_dir,
                checkpoint_dir,
                profiling_log_dir,
                cluster_log_dir,
                checkpoint_log_dir,
                metadata_dir,
            ]:
                path.mkdir(parents=True, exist_ok=True)

            (profiling_dir / "simpoint_bbv.gz").write_text("bbv", encoding="utf-8")
            (cluster_dir / "simpoints0").write_text("55 0", encoding="utf-8")
            (checkpoint_dir / "_55_0.5_memory_.zstd").write_text(
                "checkpoint", encoding="utf-8"
            )
            (archive_root / "checkpoint-0-0-0" / "cluster-0-0.json").write_text(
                "{}", encoding="utf-8"
            )
            (archive_root / "checkpoint-0-0-0" / "checkpoint.lst").write_text(
                "demo_55 demo/55 0 0 20 20\n", encoding="utf-8"
            )

            single_bin.reset_stage_outputs(str(archive_root), "demo", None)

            self.assertFalse(profiling_dir.exists())
            self.assertFalse(cluster_dir.exists())
            self.assertFalse(checkpoint_dir.parent.exists())
            self.assertFalse(profiling_log_dir.exists())
            self.assertFalse(cluster_log_dir.exists())
            self.assertFalse(checkpoint_log_dir.exists())
            self.assertFalse((archive_root / "checkpoint-0-0-0" / "cluster-0-0.json").exists())
            self.assertFalse((archive_root / "checkpoint-0-0-0" / "checkpoint.lst").exists())
            self.assertTrue(metadata_dir.exists())

    def test_reset_stage_outputs_preserves_resume_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            profiling_dir = archive_root / "profiling-0" / "demo"
            cluster_dir = archive_root / "cluster-0-0" / "demo"
            checkpoint_dir = archive_root / "checkpoint-0-0-0" / "demo" / "55"
            profiling_log_dir = archive_root / "logs" / "profiling-0" / "demo"
            cluster_log_dir = archive_root / "logs" / "cluster-0-0" / "demo"
            checkpoint_log_dir = archive_root / "logs" / "checkpoint-0-0-0" / "demo"

            for path in [
                profiling_dir,
                cluster_dir,
                checkpoint_dir,
                profiling_log_dir,
                cluster_log_dir,
                checkpoint_log_dir,
            ]:
                path.mkdir(parents=True, exist_ok=True)

            single_bin.reset_stage_outputs(str(archive_root), "demo", "profiling")
            self.assertTrue(profiling_dir.exists())
            self.assertTrue(profiling_log_dir.exists())
            self.assertFalse(cluster_dir.exists())
            self.assertFalse(cluster_log_dir.exists())
            self.assertFalse(checkpoint_dir.parent.exists())
            self.assertFalse(checkpoint_log_dir.exists())

            cluster_dir.mkdir(parents=True, exist_ok=True)
            checkpoint_dir.mkdir(parents=True, exist_ok=True)
            cluster_log_dir.mkdir(parents=True, exist_ok=True)
            checkpoint_log_dir.mkdir(parents=True, exist_ok=True)

            single_bin.reset_stage_outputs(str(archive_root), "demo", "cluster")
            self.assertTrue(profiling_dir.exists())
            self.assertTrue(cluster_dir.exists())
            self.assertTrue(profiling_log_dir.exists())
            self.assertTrue(cluster_log_dir.exists())
            self.assertFalse(checkpoint_dir.parent.exists())
            self.assertFalse(checkpoint_log_dir.exists())

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
                max_workers=3,
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

    def test_main_processes_each_entry_from_bin_list_in_parallel(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bins"
            bin_dir.mkdir()
            alpha_bin = bin_dir / "alpha.bin"
            beta_bin = bin_dir / "beta.bin"
            alpha_bin.write_text("alpha", encoding="utf-8")
            beta_bin.write_text("beta", encoding="utf-8")

            bin_list = Path(tmp) / "bins.txt"
            bin_list.write_text(f"{alpha_bin}\n{beta_bin}\n", encoding="utf-8")

            args = Namespace(
                bin=None,
                bin_list=str(bin_list),
                name=None,
                archive_id=None,
                interval=20000000,
                copies=2,
                resume_after=None,
                max_workers=3,
            )

            parser = mock.Mock()
            parser.parse_args.return_value = args

            future_alpha = mock.Mock()
            future_alpha.result.return_value = {
                "name": "alpha.bin",
                "archive_id": "archive-alpha",
                "checkpoint_count": 3,
                "checkpoint_dir": "/tmp/archive-alpha/checkpoint-0-0-0/alpha.bin",
            }
            future_beta = mock.Mock()
            future_beta.result.return_value = {
                "name": "beta.bin",
                "archive_id": "archive-beta",
                "checkpoint_count": 5,
                "checkpoint_dir": "/tmp/archive-beta/checkpoint-0-0-0/beta.bin",
            }

            with mock.patch.object(single_bin, "build_arg_parser", return_value=parser), \
                 mock.patch.object(single_bin, "run_single_checkpoint") as run_single, \
                 mock.patch.object(single_bin.concurrent.futures, "ThreadPoolExecutor") as pool_cls, \
                 mock.patch.object(single_bin.concurrent.futures, "as_completed", return_value=[future_alpha, future_beta]):
                pool = pool_cls.return_value.__enter__.return_value
                pool.submit.side_effect = [future_alpha, future_beta]
                exit_code = single_bin.main()

            self.assertEqual(exit_code, 0)
            self.assertEqual(pool.submit.call_count, 2)
            pool.submit.assert_has_calls(
                [
                    mock.call(
                        run_single,
                        bin_path=str(alpha_bin),
                        workload_name="alpha.bin",
                        archive_id=None,
                        interval=20000000,
                        copies=2,
                        resume_after=None,
                        cpu_bind="0",
                        mem_bind="0",
                    ),
                    mock.call(
                        run_single,
                        bin_path=str(beta_bin),
                        workload_name="beta.bin",
                        archive_id=None,
                        interval=20000000,
                        copies=2,
                        resume_after=None,
                        cpu_bind="1",
                        mem_bind="1",
                    ),
                ]
            )


if __name__ == "__main__":
    unittest.main()
