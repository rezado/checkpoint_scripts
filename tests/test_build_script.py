import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "build.sh"


class BuildScriptTests(unittest.TestCase):
    def _write_fake_command(self, directory: Path, name: str) -> None:
        script_path = directory / name
        script_path.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    f"printf '{name}|%s|%s\\n' \"$PWD\" \"$*\" >> \"$FAKE_LOG\"",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        script_path.chmod(0o755)

    def _prepare_fake_nemu_home(self, root: Path) -> Path:
        nemu_home = root / "custom-nemu"
        (nemu_home / "resource" / "gcpt_restore").mkdir(parents=True)
        (nemu_home / "resource" / "simpoint" / "simpoint_repo").mkdir(
            parents=True
        )
        return nemu_home

    def _run_build_script(self, nemu_home: Path, defconfig: str | None):
        fake_bin = nemu_home.parent / "fake-bin"
        fake_bin.mkdir()
        self._write_fake_command(fake_bin, "make")
        self._write_fake_command(fake_bin, "git")

        log_path = nemu_home.parent / "commands.log"
        env = os.environ.copy()
        env.update(
            {
                "INIT_NEMU": "1",
                "NEMU_HOME": str(nemu_home),
                "FAKE_LOG": str(log_path),
                "PATH": f"{fake_bin}:{env['PATH']}",
            }
        )
        if defconfig is not None:
            env["NEMU_DEFCONFIG"] = defconfig
        else:
            env.pop("NEMU_DEFCONFIG", None)

        completed = subprocess.run(
            ["bash", str(BUILD_SCRIPT)],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        log_lines = []
        if log_path.exists():
            log_lines = log_path.read_text(encoding="utf-8").splitlines()
        return completed, log_lines

    def test_build_nemu_uses_override_home_and_custom_defconfig(self):
        with tempfile.TemporaryDirectory() as tmp:
            nemu_home = self._prepare_fake_nemu_home(Path(tmp))

            completed, log_lines = self._run_build_script(
                nemu_home=nemu_home,
                defconfig="custom_defconfig",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(log_lines[0], f"make|{nemu_home}|custom_defconfig")
            self.assertEqual(log_lines[1], f"make|{nemu_home}|-j")
            self.assertEqual(
                log_lines[2], f"git|{nemu_home}|submodule update --init"
            )

    def test_build_nemu_defaults_to_checkpoint_defconfig(self):
        with tempfile.TemporaryDirectory() as tmp:
            nemu_home = self._prepare_fake_nemu_home(Path(tmp))

            completed, log_lines = self._run_build_script(
                nemu_home=nemu_home,
                defconfig=None,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                log_lines[0], f"make|{nemu_home}|riscv64-xs-cpt_defconfig"
            )


if __name__ == "__main__":
    unittest.main()
