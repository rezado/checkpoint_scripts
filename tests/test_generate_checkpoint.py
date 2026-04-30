import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "checkpoint_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_checkpoint as checkpoint_generator


class GenerateCheckpointTests(unittest.TestCase):
    def test_generate_specapp_assembly_propagates_background_failures(self):
        with mock.patch.object(
            checkpoint_generator,
            "copy_and_get_assembly",
            return_value=("demo", "/tmp/demo"),
        ), mock.patch.object(
            checkpoint_generator,
            "dump_assembly",
            side_effect=RuntimeError("objdump failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "objdump failed"):
                checkpoint_generator.generate_specapp_assembly(
                    ["demo"],
                    "/tmp/src",
                    "/tmp/dst",
                    "/tmp/assembly",
                    1,
                )

    def test_main_propagates_checkpoint_executor_failures_for_existing_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            gcpt_bins = archive_root / "gcpt_bins"
            logs = archive_root / "logs"
            gcpt_bins.mkdir(parents=True)
            logs.mkdir(parents=True)

            config_ctx = mock.Mock()
            config_ctx.get_config.return_value = {
                "base_config": {
                    "archive_id": "existing-archive",
                    "start_id": "0,0,0",
                    "times": "1,1,1",
                    "emulator": "NEMU",
                    "cpu_bind": 0,
                    "mem_bind": 0,
                    "copies": 1,
                    "all_in_one_workload": True,
                    "max_threads": 1,
                    "bootloader": "opensbi",
                },
                "app_list": ["demo"],
                "base_app_list": ["demo"],
                "spec_app_info": {},
                "archive_buffer_layout": {
                    "buffer_path": str(archive_root),
                    "gcpt_bins": str(gcpt_bins),
                    "logs": str(logs),
                },
            }

            class FailingMapExecutor:
                def __init__(self, max_workers=None):
                    self.max_workers = max_workers

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def map(self, fn, iterable):
                    def iterator():
                        raise RuntimeError("checkpoint executor failed")
                        yield from ()

                    return iterator()

            with mock.patch.object(
                checkpoint_generator,
                "TakeCheckpointConfig",
                return_value=mock.Mock(get_config=mock.Mock(return_value={})),
            ), mock.patch.object(
                checkpoint_generator,
                "RootfsBuilder",
                return_value=mock.Mock(),
            ), mock.patch.object(
                checkpoint_generator,
                "generate_command",
                return_value=object(),
            ), mock.patch.object(
                checkpoint_generator,
                "generate_checkpoint_metadata",
            ), mock.patch.object(
                checkpoint_generator.concurrent.futures,
                "ProcessPoolExecutor",
                FailingMapExecutor,
            ):
                with self.assertRaisesRegex(RuntimeError, "checkpoint executor failed"):
                    checkpoint_generator.main(config_ctx)


if __name__ == "__main__":
    unittest.main()
