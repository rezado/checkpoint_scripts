import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "checkpoint-trigger.yml"


class CheckpointWorkflowTests(unittest.TestCase):
    def test_workflow_dispatch_exposes_unified_input_path(self):
        workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

        dispatch = workflow["on"]["workflow_dispatch"]
        inputs = dispatch["inputs"]
        job = workflow["jobs"]["run-checkpoint"]
        checkout = job["steps"][0]
        self.assertEqual(job["runs-on"], "self-hosted")
        self.assertIn("input_path", inputs)
        self.assertIn("name", inputs)
        self.assertIn("archive_id", inputs)
        self.assertIn("rebuild_nemu", inputs)
        self.assertIn("nemu_home", inputs)
        self.assertIn("nemu_defconfig", inputs)
        self.assertIn("max_workers", inputs)
        self.assertIn("resume_after", inputs)
        self.assertEqual(inputs["input_path"]["required"], "true")
        self.assertEqual(inputs["interval"]["default"], "20000000")
        self.assertEqual(inputs["max_workers"]["default"], "3")
        self.assertEqual(inputs["resume_after"]["default"], "")
        self.assertEqual(job["timeout-minutes"], "20160")
        self.assertEqual(checkout["with"]["clean"], "false")

        run_script = job["steps"][-1]["run"]
        self.assertIn('INPUT_PATH="${{ github.event.inputs.input_path }}"', run_script)
        self.assertIn('WORKLOAD_NAME="${{ github.event.inputs.name }}"', run_script)
        self.assertIn('MAX_WORKERS="${{ github.event.inputs.max_workers }}"', run_script)
        self.assertIn('ARCHIVE_ID_INPUT="${{ github.event.inputs.archive_id }}"', run_script)
        self.assertIn('RESUME_AFTER="${{ github.event.inputs.resume_after }}"', run_script)
        self.assertIn('if [[ -z "$INPUT_PATH" ]]; then', run_script)
        self.assertIn('if [[ ! -e "$INPUT_PATH" ]]; then', run_script)
        self.assertIn('if [[ -d "$INPUT_PATH" && -n "$WORKLOAD_NAME" ]]; then', run_script)
        self.assertIn('if [[ -n "$RESUME_AFTER" && -z "$ARCHIVE_ID_INPUT" ]]; then', run_script)
        self.assertIn('if [[ "$REBUILD_NEMU" == "true" ]]; then', run_script)
        self.assertIn('make "$NEMU_DEFCONFIG"', run_script)
        self.assertIn('--input-path "$INPUT_PATH"', run_script)
        self.assertIn('--interval "$INTERVAL"', run_script)
        self.assertIn('--resume-after "$RESUME_AFTER"', run_script)
        self.assertIn('--archive-id "$ARCHIVE_ID_INPUT"', run_script)
        self.assertIn('--max-workers "$MAX_WORKERS"', run_script)
        self.assertIn("python3 run_checkpoint.py", run_script)
        self.assertIn("- input_path: \\`$INPUT_PATH\\`", run_script)
        self.assertIn("- input_kind: \\`$INPUT_KIND\\`", run_script)
        self.assertIn("- archive_id: \\`${ARCHIVE_ID_INPUT:-auto}\\`", run_script)


if __name__ == "__main__":
    unittest.main()
