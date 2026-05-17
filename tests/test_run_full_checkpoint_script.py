import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "checkpoint_scripts" / "run_full_checkpoint.sh"


class RunFullCheckpointScriptTests(unittest.TestCase):
    def test_script_uses_shared_checkpoint_validation_after_qemu(self):
        text = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "from run_single_bin_checkpoint import count_checkpoints, validate_outputs",
            text,
        )
        self.assertIn("validate_outputs(", text)
        self.assertIn("count_checkpoints(", text)
        self.assertIn('BBV="$ARCHIVE/profiling/$app/simpoint_bbv.gz"', text)
        self.assertIn('CLUSTER_DIR="$ARCHIVE/cluster/$app"', text)
        self.assertIn('CPT_LOG_DIR="$ARCHIVE/logs/checkpoint/$app"', text)
        self.assertIn('config-name=checkpoint', text)

    def test_script_parses_spec_apps_with_commas_and_rejects_empty_resolution(self):
        text = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("split(',')", text)
        self.assertIn('if [[ -z "$SPEC_APPS" ]]; then', text)


if __name__ == "__main__":
    unittest.main()
