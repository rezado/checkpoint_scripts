import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER_SCRIPT = REPO_ROOT / "checkpoint_scripts" / "run_single_bin_checkpoint.sh"


class RunSingleBinWrapperTests(unittest.TestCase):
    def test_wrapper_preserves_existing_nemu_home_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_bin = Path(tmp) / "bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python3"
            fake_python.write_text(
                "\n".join(
                    [
                        "#!/bin/sh",
                        'printf "%s\\n" "${NEMU_HOME:-}"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)

            env = os.environ.copy()
            env["NEMU_HOME"] = "/tmp/custom-nemu"
            env["PATH"] = f"{fake_bin}:{env['PATH']}"

            completed = subprocess.run(
                ["bash", str(WRAPPER_SCRIPT), "--bin", "/tmp/demo.bin", "--name", "demo"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "/tmp/custom-nemu")


if __name__ == "__main__":
    unittest.main()
