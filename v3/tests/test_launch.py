import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TABLET = Path(__file__).resolve().parents[1] / "tablet"


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        shutil.copyfile(TABLET / "launch.sh", self.root / "launch.sh")
        binary = self.root / "rpp-dashboard"
        binary.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$BASE_URL" "$STATE_DIR" "$TARGET_PATH" '
            '"$UPDATER_PATH" "$PATH" "$@"\n'
        )
        binary.chmod(0o755)
        self.config = self.root / "config.env"
        self.updater = self.root / "update.sh"
        self.updater.write_text("#!/bin/sh\n")
        self.config.write_text(f"BASE_URL=https://example.test\nUPDATER_PATH={self.updater}\n")

    def launch(self, *arguments):
        return subprocess.run(
            ["/bin/sh", str(self.root / "launch.sh"), *arguments],
            env={**os.environ, "CONFIG_PATH": str(self.config)},
            capture_output=True, text=True,
        )

    def test_exports_shared_defaults_and_passes_arguments(self):
        result = self.launch("--configure-sleep-screen")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[:4], [
            "https://example.test", "/home/root/rpp-sleep-screen-v2/state",
            "/usr/share/remarkable/suspended.png", str(self.updater),
        ])
        self.assertTrue(lines[4].startswith("/home/root/.vellum/bin:"))
        self.assertEqual(lines[5], "--configure-sleep-screen")

    def test_exports_custom_v2_state_and_target(self):
        with self.config.open("a") as config:
            config.write("STATE_DIR=/home/root/shared-state\nTARGET_PATH=/home/root/custom.png\n")
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[1:3],
                         ["/home/root/shared-state", "/home/root/custom.png"])

    def test_missing_configuration_and_updater_are_errors(self):
        self.config.unlink()
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing v2 configuration", result.stderr)
        self.config.write_text(f"BASE_URL=https://example.test\nUPDATER_PATH={self.updater}\n")
        self.updater.unlink()
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing updater", result.stderr)

    def test_registration_uses_oxide_compositor_and_no_preload(self):
        registration = json.loads((TABLET / "dashboard.oxide").read_text())
        self.assertEqual(registration["bin"], "/home/root/rpp-dashboard-v3/launch.sh")
        self.assertEqual(registration["type"], "foreground")
        self.assertEqual(registration["environment"]["QT_QPA_PLATFORM"], "oxide")
        self.assertEqual(registration["environment"]["QT_QUICK_BACKEND"], "software")
        self.assertIn("nopreload", registration["flags"])


if __name__ == "__main__":
    unittest.main()
