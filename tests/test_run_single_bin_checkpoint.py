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

    def test_parse_args_accepts_auto_resume_for_bin_list(self):
        parser = single_bin.build_arg_parser()
        args = parser.parse_args(
            [
                "--bin-list",
                "/tmp/bins.txt",
                "--resume-after",
                "auto",
                "--allow-new-archives",
            ]
        )
        self.assertEqual(args.resume_after, "auto")
        self.assertTrue(args.allow_new_archives)

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

    def test_validate_input_args_allows_auto_resume_for_bin_list_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_list = Path(tmp) / "bins.txt"
            bin_list.write_text("/tmp/demo.bin\n", encoding="utf-8")

            single_bin.validate_input_args(
                Namespace(
                    bin=None,
                    bin_list=str(bin_list),
                    name=None,
                    archive_id=None,
                    interval=20000000,
                    copies=1,
                    resume_after="auto",
                    max_workers=3,
                    allow_new_archives=False,
                )
            )

    def test_validate_input_args_rejects_stage_resume_for_bin_list_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_list = Path(tmp) / "bins.txt"
            bin_list.write_text("/tmp/demo.bin\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "auto"):
                single_bin.validate_input_args(
                    Namespace(
                        bin=None,
                        bin_list=str(bin_list),
                        name=None,
                        archive_id=None,
                        interval=20000000,
                        copies=1,
                        resume_after="cluster",
                        max_workers=3,
                        allow_new_archives=False,
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

    def test_detect_auto_resume_state_classifies_archive_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"

            fresh = single_bin.detect_auto_resume_state(str(archive_root), "demo")
            self.assertEqual(fresh["state"], "fresh")
            self.assertIsNone(fresh["resume_after"])

            (archive_root / "profiling-0" / "demo").mkdir(parents=True)
            (archive_root / "profiling-0" / "demo" / "simpoint_bbv.gz").write_text(
                "bbv", encoding="utf-8"
            )
            profiling = single_bin.detect_auto_resume_state(str(archive_root), "demo")
            self.assertEqual(profiling["state"], "after_profiling")
            self.assertEqual(profiling["resume_after"], "profiling")

            cluster_dir = archive_root / "cluster-0-0" / "demo"
            cluster_dir.mkdir(parents=True)
            (cluster_dir / "simpoints0").write_text("55 0\n2444 1\n", encoding="utf-8")
            (cluster_dir / "weights0").write_text("0.5 0\n0.5 1\n", encoding="utf-8")
            partial_dir = archive_root / "checkpoint-0-0-0" / "demo" / "55"
            partial_dir.mkdir(parents=True)
            (partial_dir / "_55_0.5_memory_.zstd").write_text(
                "checkpoint", encoding="utf-8"
            )
            checkpoint = single_bin.detect_auto_resume_state(str(archive_root), "demo")
            self.assertEqual(checkpoint["state"], "after_cluster")
            self.assertEqual(checkpoint["resume_after"], "cluster")
            self.assertEqual(checkpoint["missing_points"], ["2444"])

            complete_dir = archive_root / "checkpoint-0-0-0" / "demo" / "2444"
            complete_dir.mkdir(parents=True)
            (complete_dir / "_2444_0.5_memory_.zstd").write_text(
                "checkpoint", encoding="utf-8"
            )
            complete = single_bin.detect_auto_resume_state(str(archive_root), "demo")
            self.assertEqual(complete["state"], "complete")
            self.assertTrue(complete["skip"])

    def test_prepare_auto_resume_preserves_partial_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            profiling_dir = archive_root / "profiling-0" / "demo"
            cluster_dir = archive_root / "cluster-0-0" / "demo"
            checkpoint_root = archive_root / "checkpoint-0-0-0" / "demo"
            profiling_dir.mkdir(parents=True)
            cluster_dir.mkdir(parents=True)
            (checkpoint_root / "55").mkdir(parents=True)

            (profiling_dir / "simpoint_bbv.gz").write_text("bbv", encoding="utf-8")
            (cluster_dir / "simpoints0").write_text("55 0\n2444 1\n", encoding="utf-8")
            (cluster_dir / "weights0").write_text("0.25 0\n0.75 1\n", encoding="utf-8")
            (checkpoint_root / "55" / "_55_0.25_memory_.zstd").write_text(
                "checkpoint", encoding="utf-8"
            )

            state = single_bin.detect_auto_resume_state(str(archive_root), "demo")
            resume_after = single_bin.prepare_auto_resume_artifacts(
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
                (cluster_dir / "simpoints0.auto-resume-full").read_text(encoding="utf-8"),
                "55 0\n2444 1\n",
            )

            filtered_state = single_bin.detect_auto_resume_state(str(archive_root), "demo")
            self.assertEqual(filtered_state["missing_points"], ["2444"])

            single_bin.restore_auto_resume_artifacts(str(archive_root), "demo")
            self.assertEqual(
                (cluster_dir / "simpoints0").read_text(encoding="utf-8"),
                "55 0\n2444 1\n",
            )

    def test_plan_batch_auto_resume_finds_latest_archives_and_skips_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_parent = Path(tmp) / "archive"
            archive_parent.mkdir()
            bin_dir = Path(tmp) / "bins"
            bin_dir.mkdir()
            alpha_bin = bin_dir / "alpha.bin"
            beta_bin = bin_dir / "beta.bin"
            alpha_bin.write_text("alpha", encoding="utf-8")
            beta_bin.write_text("beta", encoding="utf-8")

            old_alpha = archive_parent / "single_bin_nemu_alpha.bin_2026-05-01-00-00-00"
            new_alpha = archive_parent / "single_bin_nemu_alpha.bin_2026-05-02-00-00-00"
            beta = archive_parent / "single_bin_nemu_beta.bin_2026-05-02-00-00-00"
            for path in [old_alpha, new_alpha, beta]:
                path.mkdir()

            (new_alpha / "profiling-0" / "alpha.bin").mkdir(parents=True)
            (new_alpha / "profiling-0" / "alpha.bin" / "simpoint_bbv.gz").write_text(
                "bbv", encoding="utf-8"
            )

            (beta / "profiling-0" / "beta.bin").mkdir(parents=True)
            (beta / "profiling-0" / "beta.bin" / "simpoint_bbv.gz").write_text(
                "bbv", encoding="utf-8"
            )
            (beta / "cluster-0-0" / "beta.bin").mkdir(parents=True)
            (beta / "cluster-0-0" / "beta.bin" / "simpoints0").write_text(
                "7 0\n", encoding="utf-8"
            )
            (beta / "cluster-0-0" / "beta.bin" / "weights0").write_text(
                "1.0 0\n", encoding="utf-8"
            )
            (beta / "checkpoint-0-0-0" / "beta.bin" / "7").mkdir(parents=True)
            (beta / "checkpoint-0-0-0" / "beta.bin" / "7" / "_7_1.0.zstd").write_text(
                "checkpoint", encoding="utf-8"
            )

            planned, skipped = single_bin.plan_batch_auto_resume(
                [
                    {"bin": str(alpha_bin), "name": "alpha.bin"},
                    {"bin": str(beta_bin), "name": "beta.bin"},
                ],
                archive_parent=str(archive_parent),
                allow_new_archives=False,
            )

            self.assertEqual(len(planned), 1)
            self.assertEqual(planned[0]["archive_id"], new_alpha.name)
            self.assertEqual(planned[0]["resume_after"], "profiling")
            self.assertEqual(len(skipped), 1)
            self.assertEqual(skipped[0]["name"], "beta.bin")
            self.assertTrue(skipped[0]["skipped"])

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
                allow_new_archives=False,
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
                allow_new_archives=False,
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

    def test_main_auto_resume_plans_unfinished_bin_list_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bins"
            bin_dir.mkdir()
            alpha_bin = bin_dir / "alpha.bin"
            alpha_bin.write_text("alpha", encoding="utf-8")

            bin_list = Path(tmp) / "bins.txt"
            bin_list.write_text(f"{alpha_bin}\n", encoding="utf-8")

            args = Namespace(
                bin=None,
                bin_list=str(bin_list),
                name=None,
                archive_id=None,
                interval=20000000,
                copies=2,
                resume_after="auto",
                max_workers=3,
                allow_new_archives=False,
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

            with mock.patch.object(single_bin, "build_arg_parser", return_value=parser), \
                 mock.patch.object(
                     single_bin,
                     "plan_batch_auto_resume",
                     return_value=(
                         [
                             {
                                 "bin": str(alpha_bin),
                                 "name": "alpha.bin",
                                 "archive_id": "archive-alpha",
                                 "resume_after": "cluster",
                             }
                         ],
                         [{"name": "beta.bin", "archive_id": "archive-beta", "skipped": True}],
                     ),
                 ) as plan_auto, \
                 mock.patch.object(single_bin, "run_single_checkpoint") as run_single, \
                 mock.patch.object(single_bin.concurrent.futures, "ThreadPoolExecutor") as pool_cls, \
                 mock.patch.object(single_bin.concurrent.futures, "as_completed", return_value=[future_alpha]):
                pool = pool_cls.return_value.__enter__.return_value
                pool.submit.return_value = future_alpha
                exit_code = single_bin.main()

            self.assertEqual(exit_code, 0)
            plan_auto.assert_called_once_with(
                [{"bin": str(alpha_bin), "name": "alpha.bin"}],
                archive_parent="archive",
                allow_new_archives=False,
            )
            pool.submit.assert_called_once_with(
                run_single,
                bin_path=str(alpha_bin),
                workload_name="alpha.bin",
                archive_id="archive-alpha",
                interval=20000000,
                copies=2,
                resume_after="cluster",
                cpu_bind="0",
                mem_bind="0",
            )


if __name__ == "__main__":
    unittest.main()
