import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "checkpoint-trigger.yml"


class CheckpointWorkflowTests(unittest.TestCase):
    def test_workflow_dispatch_exposes_single_and_batch_inputs(self):
        workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

        dispatch = workflow["on"]["workflow_dispatch"]
        inputs = dispatch["inputs"]
        job = workflow["jobs"]["run-single-bin-checkpoint"]
        self.assertIn("interval", inputs)
        self.assertIn("bin_list", inputs)
        self.assertIn("rebuild_nemu", inputs)
        self.assertIn("nemu_home", inputs)
        self.assertIn("nemu_defconfig", inputs)
        self.assertIn("max_workers", inputs)
        self.assertEqual(inputs["interval"]["default"], "20000000")
        self.assertEqual(inputs["max_workers"]["default"], "3")
        self.assertEqual(job["timeout-minutes"], "2880")

        run_script = job["steps"][-1]["run"]
        self.assertIn('INTERVAL="${{ github.event.inputs.interval }}"', run_script)
        self.assertIn('MAX_WORKERS="${{ github.event.inputs.max_workers }}"', run_script)
        self.assertIn('BIN_LIST_PATH="${{ github.event.inputs.bin_list }}"', run_script)
        self.assertIn('REBUILD_NEMU="${{ github.event.inputs.rebuild_nemu }}"', run_script)
        self.assertIn('NEMU_OVERRIDE_HOME="${{ github.event.inputs.nemu_home }}"', run_script)
        self.assertIn('NEMU_DEFCONFIG="${{ github.event.inputs.nemu_defconfig }}"', run_script)
        self.assertIn('if [[ -n "$NEMU_OVERRIDE_HOME" ]]; then', run_script)
        self.assertIn('if [[ "$REBUILD_NEMU" == "true" ]]; then', run_script)
        self.assertIn('if [[ ! "$MAX_WORKERS" =~ ^[0-9]+$ ]] || [[ "$MAX_WORKERS" -le 0 ]]; then', run_script)
        self.assertIn('make "$NEMU_DEFCONFIG"', run_script)
        self.assertIn('--interval "$INTERVAL"', run_script)
        self.assertIn('--max-workers "$MAX_WORKERS"', run_script)
        self.assertIn('--bin-list "$BIN_LIST_PATH"', run_script)
        self.assertIn("- interval: \\`$INTERVAL\\`", run_script)


if __name__ == "__main__":
    unittest.main()
