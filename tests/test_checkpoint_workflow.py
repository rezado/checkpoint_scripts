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
        self.assertIn("output_base", inputs)
        self.assertIn("max_k", inputs)
        self.assertIn("max_workers", inputs)
        self.assertIn("nemu", inputs)
        self.assertIn("resume_after", inputs)
        self.assertEqual(inputs["input_path"]["required"], "true")
        self.assertEqual(inputs["output_base"]["default"], "")
        self.assertEqual(inputs["interval"]["default"], "20000000")
        self.assertEqual(inputs["max_k"]["default"], "")
        self.assertEqual(inputs["max_workers"]["default"], "3")
        self.assertEqual(inputs["nemu"]["default"], "riscv64-xs-cpt_defconfig")
        self.assertEqual(inputs["resume_after"]["default"], "")
        self.assertEqual(job["timeout-minutes"], "40320")
        self.assertEqual(checkout["with"]["clean"], "false")

        run_script = job["steps"][-1]["run"]
        self.assertIn('INPUT_PATH="${{ github.event.inputs.input_path }}"', run_script)
        self.assertIn('WORKLOAD_NAME="${{ github.event.inputs.name }}"', run_script)
        self.assertIn('MAX_WORKERS="${{ github.event.inputs.max_workers }}"', run_script)
        self.assertIn('MAX_K_INPUT="${{ github.event.inputs.max_k }}"', run_script)
        self.assertIn('NEMU_INPUT="${{ github.event.inputs.nemu }}"', run_script)
        self.assertIn('ARCHIVE_ID_INPUT="${{ github.event.inputs.archive_id }}"', run_script)
        self.assertIn('OUTPUT_BASE_INPUT="${{ github.event.inputs.output_base }}"', run_script)
        self.assertIn('RESUME_AFTER="${{ github.event.inputs.resume_after }}"', run_script)
        self.assertIn('RUNNER_USERNAME="$(id -un)"', run_script)
        self.assertIn('if [[ -z "$INPUT_PATH" ]]; then', run_script)
        self.assertIn('if [[ ! -e "$INPUT_PATH" ]]; then', run_script)
        self.assertIn('if [[ -n "$MAX_K_INPUT" ]]', run_script)
        self.assertIn('if [[ -z "$NEMU_INPUT" ]]; then', run_script)
        self.assertIn('if [[ -d "$INPUT_PATH" && -n "$WORKLOAD_NAME" ]]; then', run_script)
        self.assertIn('if [[ -n "$RESUME_AFTER" && -z "$ARCHIVE_ID_INPUT" ]]; then', run_script)
        self.assertIn('validate_nemu_home() {', run_script)
        self.assertIn('if [[ "$NEMU_INPUT" == *_defconfig ]]; then', run_script)
        self.assertIn('NEMU_UPSTREAM_URL="https://github.com/OpenXiangShan/NEMU.git"', run_script)
        self.assertIn('git clone --recursive --branch "$NEMU_UPSTREAM_BRANCH" "$NEMU_UPSTREAM_URL" "$NEMU_HOME"', run_script)
        self.assertIn('make "$NEMU_DEFCONFIG"', run_script)
        self.assertIn('if [[ ! -x "$nemu_bin" ]]; then', run_script)
        self.assertIn('if [[ ! -x "$simpoint_bin" ]]; then', run_script)
        self.assertIn('--input-path "$INPUT_PATH"', run_script)
        self.assertIn('--interval "$INTERVAL"', run_script)
        self.assertIn('--max-k "$MAX_K_INPUT"', run_script)
        self.assertIn('--resume-after "$RESUME_AFTER"', run_script)
        self.assertIn('--archive-id "$ARCHIVE_ID_INPUT"', run_script)
        self.assertIn('--max-workers "$MAX_WORKERS"', run_script)
        self.assertIn('RUN_LOG="$(mktemp)"', run_script)
        self.assertIn("python3 -u generate_checkpoint.py", run_script)
        self.assertIn('| tee "$RUN_LOG"', run_script)
        self.assertIn("- input_path: \\`$INPUT_PATH\\`", run_script)
        self.assertIn("- input_kind: \\`$INPUT_KIND\\`", run_script)
        self.assertIn("- max_k: \\`${MAX_K_INPUT:-auto}\\`", run_script)
        self.assertIn("- nemu: \\`$NEMU_INPUT\\`", run_script)
        self.assertIn("- nemu_mode: \\`$NEMU_MODE\\`", run_script)
        self.assertIn("- nemu_home: \\`$NEMU_HOME\\`", run_script)
        self.assertIn("- archive_id: \\`${ACTUAL_ARCHIVE_ID:-${ARCHIVE_ID_INPUT:-auto}}\\`", run_script)
        self.assertIn("- output_base: \\`${CHECKPOINT_OUTPUT_BASE}\\`", run_script)


if __name__ == "__main__":
    unittest.main()
