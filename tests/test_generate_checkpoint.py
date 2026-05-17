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

import generate_checkpoint as checkpoint_runner


class RunCheckpointTests(unittest.TestCase):
    def test_build_archive_layout_contains_expected_paths(self):
        layout = checkpoint_runner.build_archive_layout("/tmp/archive/demo")
        self.assertEqual(layout["logs"], "/tmp/archive/demo/logs")
        self.assertEqual(layout["metadata"], "/tmp/archive/demo/metadata")
        self.assertEqual(layout["json"], "/tmp/archive/demo/json")

    def test_write_request_metadata_persists_user_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata_dir = Path(tmp) / "metadata"
            metadata_dir.mkdir()
            output = checkpoint_runner.write_request_metadata(
                metadata_dir=str(metadata_dir),
                request={
                    "bin": "/tmp/demo.bin",
                    "name": "demo",
                    "archive_id": "archive-demo",
                    "interval": 20000000,
                    "resume_after": None,
                },
            )
            self.assertTrue(Path(output).is_file())
            text = Path(output).read_text(encoding="utf-8")
            self.assertIn("name: demo", text)
            self.assertIn("interval: 20000000", text)

    def test_parse_args_requires_input_path(self):
        parser = checkpoint_runner.build_arg_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_parse_args_accepts_max_workers(self):
        parser = checkpoint_runner.build_arg_parser()
        args = parser.parse_args(
            ["--input-path", "/tmp/bins", "--max-workers", "3"]
        )
        self.assertEqual(args.max_workers, 3)

    def test_resolve_output_base_dir_defaults_to_local_archive(self):
        with mock.patch.dict(
            checkpoint_runner.os.environ,
            {},
            clear=True,
        ):
            self.assertEqual(
                checkpoint_runner.resolve_output_base_dir(),
                str((REPO_ROOT / "archive").resolve()),
            )

    def test_build_archive_root_joins_archive_under_local_archive_directory(self):
        with mock.patch.dict(
            checkpoint_runner.os.environ,
            {},
            clear=True,
        ):
            self.assertEqual(
                checkpoint_runner.build_archive_root("2026-05-17-12-00-00_demo"),
                str((REPO_ROOT / "archive" / "2026-05-17-12-00-00_demo").resolve()),
            )

    def test_generate_archive_id_for_file_puts_timestamp_before_workload(self):
        fake_now = mock.Mock()
        fake_now.strftime.return_value = "2026-05-17-12-00-00"
        with mock.patch.object(checkpoint_runner, "datetime") as mock_datetime:
            mock_datetime.now.return_value = fake_now
            archive_id = checkpoint_runner.generate_archive_id("file", "demo")

        self.assertEqual(archive_id, "2026-05-17-12-00-00_demo")

    def test_generate_archive_id_for_directory_uses_input_dir_name(self):
        fake_now = mock.Mock()
        fake_now.strftime.return_value = "2026-05-17-12-00-00"
        with mock.patch.object(checkpoint_runner, "datetime") as mock_datetime:
            mock_datetime.now.return_value = fake_now
            archive_id = checkpoint_runner.generate_archive_id(
                "directory",
                input_path="/tmp/spec-bins",
            )

        self.assertEqual(archive_id, "2026-05-17-12-00-00_spec-bins")

    def test_load_input_entries_for_directory_uses_common_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bins"
            bin_dir.mkdir()
            alpha_bin = bin_dir / "alpha.fw_payload.bin"
            beta_bin = bin_dir / "beta.fw_payload.bin"
            alpha_bin.write_text("alpha", encoding="utf-8")
            beta_bin.write_text("beta", encoding="utf-8")

            mode, entries, common_suffix = checkpoint_runner.load_input_entries(
                str(bin_dir)
            )

            self.assertEqual(mode, "directory")
            self.assertEqual(common_suffix, ".fw_payload.bin")
            self.assertEqual(
                entries,
                [
                    {"bin": str(alpha_bin), "name": "alpha"},
                    {"bin": str(beta_bin), "name": "beta"},
                ],
            )

    def test_load_input_entries_for_single_file_uses_name_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_bin = Path(tmp) / "demo.fw_payload.bin"
            input_bin.write_text("demo", encoding="utf-8")

            mode, entries, common_suffix = checkpoint_runner.load_input_entries(
                str(input_bin),
                name_override="custom-demo",
            )

            self.assertEqual(mode, "file")
            self.assertIsNone(common_suffix)
            self.assertEqual(entries, [{"bin": str(input_bin), "name": "custom-demo"}])

    def test_validate_input_args_rejects_name_for_directory_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "bins"
            input_dir.mkdir()

            with self.assertRaisesRegex(ValueError, "--name"):
                checkpoint_runner.validate_input_args(
                    Namespace(
                        input_path=str(input_dir),
                        name="demo",
                        archive_id=None,
                        interval=20000000,
                        resume_after=None,
                        max_workers=3,
                    )
                )

    def test_validate_input_args_requires_archive_for_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_bin = Path(tmp) / "demo.bin"
            input_bin.write_text("demo", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "archive-id"):
                checkpoint_runner.validate_input_args(
                    Namespace(
                        input_path=str(input_bin),
                        name=None,
                        archive_id=None,
                        interval=20000000,
                        resume_after="cluster",
                        max_workers=3,
                    )
                )

    def test_validate_input_args_rejects_non_positive_max_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_bin = Path(tmp) / "demo.bin"
            input_bin.write_text("demo", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "max-workers"):
                checkpoint_runner.validate_input_args(
                    Namespace(
                        input_path=str(input_bin),
                        name=None,
                        archive_id=None,
                        interval=20000000,
                        resume_after=None,
                        max_workers=0,
                    )
                )

    def test_validate_outputs_accepts_zstd_checkpoint_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            (archive_root / "profiling" / "demo").mkdir(parents=True)
            (archive_root / "cluster" / "demo").mkdir(parents=True)
            workload_checkpoint_dir = archive_root / "checkpoint" / "demo" / "0"
            workload_checkpoint_dir.mkdir(parents=True)

            (archive_root / "profiling" / "demo" / "simpoint_bbv.gz").write_text(
                "bbv", encoding="utf-8"
            )
            (archive_root / "cluster" / "demo" / "simpoints0").write_text(
                "0 0", encoding="utf-8"
            )
            (archive_root / "cluster" / "demo" / "weights0").write_text(
                "1.0 0", encoding="utf-8"
            )
            (workload_checkpoint_dir / "_0_1.0_.zstd").write_text(
                "checkpoint", encoding="utf-8"
            )

            checkpoint_runner.validate_outputs(str(archive_root), "demo")

    def test_validate_outputs_rejects_missing_expected_checkpoint_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            (archive_root / "profiling" / "demo").mkdir(parents=True)
            (archive_root / "cluster" / "demo").mkdir(parents=True)
            present_dir = archive_root / "checkpoint" / "demo" / "55"
            missing_dir = archive_root / "checkpoint" / "demo" / "2444"
            present_dir.mkdir(parents=True)
            missing_dir.mkdir(parents=True)

            (archive_root / "profiling" / "demo" / "simpoint_bbv.gz").write_text(
                "bbv", encoding="utf-8"
            )
            (archive_root / "cluster" / "demo" / "simpoints0").write_text(
                "55 0\n2444 1\n", encoding="utf-8"
            )
            (archive_root / "cluster" / "demo" / "weights0").write_text(
                "0.081159 0\n0.009262 1\n", encoding="utf-8"
            )
            (present_dir / "_55_0.081159_memory_.zstd").write_text(
                "checkpoint", encoding="utf-8"
            )

            with self.assertRaisesRegex(FileNotFoundError, "2444"):
                checkpoint_runner.validate_outputs(str(archive_root), "demo")

    def test_detect_auto_resume_state_classifies_archive_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"

            fresh = checkpoint_runner.detect_auto_resume_state(str(archive_root), "demo")
            self.assertEqual(fresh["state"], "fresh")
            self.assertIsNone(fresh["resume_after"])

            (archive_root / "profiling" / "demo").mkdir(parents=True)
            (archive_root / "profiling" / "demo" / "simpoint_bbv.gz").write_text(
                "bbv", encoding="utf-8"
            )
            profiling = checkpoint_runner.detect_auto_resume_state(
                str(archive_root), "demo"
            )
            self.assertEqual(profiling["state"], "after_profiling")
            self.assertEqual(profiling["resume_after"], "profiling")

            cluster_dir = archive_root / "cluster" / "demo"
            cluster_dir.mkdir(parents=True)
            (cluster_dir / "simpoints0").write_text("55 0\n2444 1\n", encoding="utf-8")
            (cluster_dir / "weights0").write_text("0.5 0\n0.5 1\n", encoding="utf-8")
            partial_dir = archive_root / "checkpoint" / "demo" / "55"
            partial_dir.mkdir(parents=True)
            (partial_dir / "_55_0.5_memory_.zstd").write_text(
                "checkpoint", encoding="utf-8"
            )
            checkpoint = checkpoint_runner.detect_auto_resume_state(
                str(archive_root), "demo"
            )
            self.assertEqual(checkpoint["state"], "after_cluster")
            self.assertEqual(checkpoint["resume_after"], "cluster")
            self.assertEqual(checkpoint["missing_points"], ["2444"])

            complete_dir = archive_root / "checkpoint" / "demo" / "2444"
            complete_dir.mkdir(parents=True)
            (complete_dir / "_2444_0.5_memory_.zstd").write_text(
                "checkpoint", encoding="utf-8"
            )
            complete = checkpoint_runner.detect_auto_resume_state(
                str(archive_root), "demo"
            )
            self.assertEqual(complete["state"], "complete")
            self.assertTrue(complete["skip"])

    def test_prepare_auto_resume_preserves_partial_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            profiling_dir = archive_root / "profiling" / "demo"
            cluster_dir = archive_root / "cluster" / "demo"
            checkpoint_root = archive_root / "checkpoint" / "demo"
            profiling_dir.mkdir(parents=True)
            cluster_dir.mkdir(parents=True)
            (checkpoint_root / "55").mkdir(parents=True)

            (profiling_dir / "simpoint_bbv.gz").write_text("bbv", encoding="utf-8")
            (cluster_dir / "simpoints0").write_text("55 0\n2444 1\n", encoding="utf-8")
            (cluster_dir / "weights0").write_text("0.25 0\n0.75 1\n", encoding="utf-8")
            (checkpoint_root / "55" / "_55_0.25_memory_.zstd").write_text(
                "checkpoint", encoding="utf-8"
            )

            state = checkpoint_runner.detect_auto_resume_state(str(archive_root), "demo")
            resume_after = checkpoint_runner.prepare_auto_resume_artifacts(
                str(archive_root), "demo", state
            )

            self.assertEqual(resume_after, "cluster")
            self.assertTrue((checkpoint_root / "55" / "_55_0.25_memory_.zstd").exists())
            self.assertEqual(
                (cluster_dir / "simpoints0").read_text(encoding="utf-8"),
                "2444 0\n",
            )
            self.assertEqual(
                (cluster_dir / "weights0").read_text(encoding="utf-8"),
                "0.75 0\n",
            )
            self.assertEqual(
                (cluster_dir / "simpoints0.auto-resume-full").read_text(
                    encoding="utf-8"
                ),
                "55 0\n2444 1\n",
            )

            filtered_state = checkpoint_runner.detect_auto_resume_state(
                str(archive_root), "demo"
            )
            self.assertEqual(filtered_state["missing_points"], ["2444"])

            checkpoint_runner.restore_auto_resume_artifacts(str(archive_root), "demo")
            self.assertEqual(
                (cluster_dir / "simpoints0").read_text(encoding="utf-8"),
                "55 0\n2444 1\n",
            )

    def test_reset_stage_outputs_clears_stale_outputs_for_fresh_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            profiling_dir = archive_root / "profiling" / "demo"
            cluster_dir = archive_root / "cluster" / "demo"
            workload_checkpoint_dir = archive_root / "checkpoint" / "demo" / "55"
            profiling_log_dir = archive_root / "logs" / "profiling" / "demo"
            cluster_log_dir = archive_root / "logs" / "cluster" / "demo"
            checkpoint_log_dir = archive_root / "logs" / "checkpoint" / "demo"
            metadata_dir = archive_root / "metadata"
            json_dir = archive_root / "json"

            for path in [
                profiling_dir,
                cluster_dir,
                workload_checkpoint_dir,
                profiling_log_dir,
                cluster_log_dir,
                checkpoint_log_dir,
                metadata_dir,
                json_dir,
            ]:
                path.mkdir(parents=True, exist_ok=True)

            (profiling_dir / "simpoint_bbv.gz").write_text("bbv", encoding="utf-8")
            (cluster_dir / "simpoints0").write_text("55 0", encoding="utf-8")
            (workload_checkpoint_dir / "_55_0.5_memory_.zstd").write_text(
                "checkpoint", encoding="utf-8"
            )
            (json_dir / "demo.json").write_text("{}", encoding="utf-8")

            checkpoint_runner.reset_stage_outputs(str(archive_root), "demo", None)

            self.assertFalse(profiling_dir.exists())
            self.assertFalse(cluster_dir.exists())
            self.assertFalse(workload_checkpoint_dir.parent.exists())
            self.assertFalse(profiling_log_dir.exists())
            self.assertFalse(cluster_log_dir.exists())
            self.assertFalse(checkpoint_log_dir.exists())
            self.assertFalse((json_dir / "demo.json").exists())
            self.assertTrue(metadata_dir.exists())

    def test_reset_stage_outputs_preserves_resume_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            profiling_dir = archive_root / "profiling" / "demo"
            cluster_dir = archive_root / "cluster" / "demo"
            workload_checkpoint_dir = archive_root / "checkpoint" / "demo" / "55"
            profiling_log_dir = archive_root / "logs" / "profiling" / "demo"
            cluster_log_dir = archive_root / "logs" / "cluster" / "demo"
            checkpoint_log_dir = archive_root / "logs" / "checkpoint" / "demo"

            for path in [
                profiling_dir,
                cluster_dir,
                workload_checkpoint_dir,
                profiling_log_dir,
                cluster_log_dir,
                checkpoint_log_dir,
            ]:
                path.mkdir(parents=True, exist_ok=True)

            checkpoint_runner.reset_stage_outputs(str(archive_root), "demo", "profiling")
            self.assertTrue(profiling_dir.exists())
            self.assertTrue(profiling_log_dir.exists())
            self.assertFalse(cluster_dir.exists())
            self.assertFalse(cluster_log_dir.exists())
            self.assertFalse(workload_checkpoint_dir.parent.exists())
            self.assertFalse(checkpoint_log_dir.exists())

            cluster_dir.mkdir(parents=True, exist_ok=True)
            workload_checkpoint_dir.mkdir(parents=True, exist_ok=True)
            cluster_log_dir.mkdir(parents=True, exist_ok=True)
            checkpoint_log_dir.mkdir(parents=True, exist_ok=True)

            checkpoint_runner.reset_stage_outputs(str(archive_root), "demo", "cluster")
            self.assertTrue(profiling_dir.exists())
            self.assertTrue(cluster_dir.exists())
            self.assertTrue(profiling_log_dir.exists())
            self.assertTrue(cluster_log_dir.exists())
            self.assertFalse(workload_checkpoint_dir.parent.exists())
            self.assertFalse(checkpoint_log_dir.exists())

    def test_main_invokes_workload_runner_for_single_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_bin = Path(tmp) / "demo.bin"
            input_bin.write_text("bin", encoding="utf-8")
            expected_archive_root = str((REPO_ROOT / "archive" / "demo-archive").resolve())

            args = Namespace(
                input_path=str(input_bin),
                name="demo",
                archive_id="demo-archive",
                interval=20000000,
                resume_after=None,
                max_workers=3,
            )

            parser = mock.Mock()
            parser.parse_args.return_value = args

            with mock.patch.object(
                checkpoint_runner, "build_arg_parser", return_value=parser
            ), mock.patch.object(
                checkpoint_runner, "validate_input_args"
            ), mock.patch.object(
                checkpoint_runner,
                "load_input_entries",
                return_value=("file", [{"bin": str(input_bin), "name": "demo"}], None),
            ), mock.patch.object(
                checkpoint_runner, "ensure_directories"
            ), mock.patch.object(
                checkpoint_runner, "write_request_metadata"
            ), mock.patch.object(
                checkpoint_runner, "clear_aggregate_metadata"
            ), mock.patch.object(
                checkpoint_runner, "build_archive_root", return_value=expected_archive_root
            ), mock.patch.object(
                checkpoint_runner, "run_workload"
            ) as run_workload:
                exit_code = checkpoint_runner.main()

            self.assertEqual(exit_code, 0)
            run_workload.assert_called_once_with(
                bin_path=str(input_bin),
                workload_name="demo",
                archive_root=expected_archive_root,
                interval=20000000,
                resume_after=None,
            )

    def test_main_processes_directory_entries_in_parallel_into_shared_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "bins"
            input_dir.mkdir()
            alpha_bin = input_dir / "alpha.bin"
            beta_bin = input_dir / "beta.bin"
            alpha_bin.write_text("alpha", encoding="utf-8")
            beta_bin.write_text("beta", encoding="utf-8")

            args = Namespace(
                input_path=str(input_dir),
                name=None,
                archive_id="shared-archive",
                interval=20000000,
                resume_after=None,
                max_workers=3,
            )

            parser = mock.Mock()
            parser.parse_args.return_value = args
            expected_archive_root = str((REPO_ROOT / "archive" / "shared-archive").resolve())

            future_alpha = mock.Mock()
            future_alpha.result.return_value = {
                "name": "alpha",
                "archive_id": "shared-archive",
                "checkpoint_count": 3,
                "checkpoint_dir": "/tmp/shared/checkpoint/alpha",
            }
            future_beta = mock.Mock()
            future_beta.result.return_value = {
                "name": "beta",
                "archive_id": "shared-archive",
                "checkpoint_count": 5,
                "checkpoint_dir": "/tmp/shared/checkpoint/beta",
            }

            with mock.patch.object(
                checkpoint_runner, "build_arg_parser", return_value=parser
            ), mock.patch.object(
                checkpoint_runner, "validate_input_args"
            ), mock.patch.object(
                checkpoint_runner,
                "load_input_entries",
                return_value=(
                    "directory",
                    [{"bin": str(alpha_bin), "name": "alpha"},
                     {"bin": str(beta_bin), "name": "beta"}],
                    ".bin",
                ),
            ), mock.patch.object(
                checkpoint_runner, "write_request_metadata"
            ), mock.patch.object(
                checkpoint_runner, "ensure_directories"
            ), mock.patch.object(
                checkpoint_runner, "clear_aggregate_metadata"
            ), mock.patch.object(
                checkpoint_runner, "generate_checkpoint_metadata"
            ) as generate_metadata, mock.patch.object(
                checkpoint_runner, "build_archive_root", return_value=expected_archive_root
            ), mock.patch.object(
                checkpoint_runner.os, "makedirs"
            ), mock.patch.object(
                checkpoint_runner, "run_workload"
            ) as run_workload, mock.patch.object(
                checkpoint_runner.concurrent.futures, "ThreadPoolExecutor"
            ) as pool_cls, mock.patch.object(
                checkpoint_runner.concurrent.futures,
                "as_completed",
                return_value=[future_alpha, future_beta],
            ):
                pool = pool_cls.return_value.__enter__.return_value
                pool.submit.side_effect = [future_alpha, future_beta]
                exit_code = checkpoint_runner.main()

            self.assertEqual(exit_code, 0)
            self.assertEqual(pool.submit.call_count, 2)
            pool.submit.assert_has_calls(
                [
                    mock.call(
                        run_workload,
                        bin_path=str(alpha_bin),
                        workload_name="alpha",
                        archive_root=expected_archive_root,
                        interval=20000000,
                        resume_after=None,
                        cpu_bind="0",
                        mem_bind="0",
                        metadata_dir=mock.ANY,
                        generate_metadata=False,
                    ),
                    mock.call(
                        run_workload,
                        bin_path=str(beta_bin),
                        workload_name="beta",
                        archive_root=expected_archive_root,
                        interval=20000000,
                        resume_after=None,
                        cpu_bind="1",
                        mem_bind="1",
                        metadata_dir=mock.ANY,
                        generate_metadata=False,
                    ),
                ]
            )
            generate_metadata.assert_called_once_with(
                archive_root=expected_archive_root,
                workloads=["alpha", "beta"],
                times=[1, 1, 1],
                ids=[0, 0, 0],
            )


if __name__ == "__main__":
    unittest.main()
