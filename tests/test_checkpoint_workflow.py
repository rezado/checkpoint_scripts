import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "checkpoint-trigger.yml"


class CheckpointWorkflowTests(unittest.TestCase):
    def test_workflow_dispatch_exposes_interval_input_and_forwards_it(self):
        workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

        dispatch = workflow["on"]["workflow_dispatch"]
        inputs = dispatch["inputs"]
        self.assertIn("interval", inputs)
        self.assertEqual(inputs["interval"]["default"], "20000000")

        run_script = workflow["jobs"]["run-single-bin-checkpoint"]["steps"][-1]["run"]
        self.assertIn('INTERVAL="${{ github.event.inputs.interval }}"', run_script)
        self.assertIn('--interval "$INTERVAL"', run_script)
        self.assertIn("- interval: \\`$INTERVAL\\`", run_script)


if __name__ == "__main__":
    unittest.main()
