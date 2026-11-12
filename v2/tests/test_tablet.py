import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

UPDATER = Path(__file__).resolve().parents[1] / "tablet" / "update.sh"
FAKE_TOOL = '''#!PYTHON
import fcntl
import hashlib
import os
import shutil
import sys
from pathlib import Path
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path(os.environ["FIXTURE"])
with (root / "calls").open("a") as log:
    log.write(tool + " " + " ".join(args) + "\\n")
if tool == "curl":
    if os.environ.get("FAIL_FETCH"):
        sys.exit(22)
    url = args[-1]
    source = root / ("manifest" if "/latest.sha256?" in url else "image.png")
    shutil.copyfile(source, args[args.index("--output") + 1])
elif tool == "sha256sum":
    print(hashlib.sha256(Path(args[0]).read_bytes()).hexdigest() + "  " + args[0])
elif tool == "awk":
    print(os.environ.get("ROOT_OPTIONS", "ro,relatime"))
elif tool == "mount":
    if os.environ.get("FAIL_MOUNT") == args[1]:
        sys.exit(1)
elif tool == "flock":
    try:
        fcntl.flock(int(args[-1]), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(1)
elif tool == "cp":
    if os.environ.get("FAIL_COPY") and args[-1].endswith(".dashboard-v2.new"):
        sys.exit(1)
    shutil.copyfile(args[0], args[1])
'''


class TabletTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("curl", "sha256sum", "awk", "mount", "flock", "cp"):
            tool = self.bin / name
            tool.write_text(FAKE_TOOL.replace("PYTHON", sys.executable))
            tool.chmod(0o755)
        self.target = self.root / "suspended.png"
        self.target.write_bytes(b"original v1 image")
        Image.new("RGB", (1620, 2160), "green").save(self.root / "image.png")
        self.write_manifest()
        self.environ = {
            **os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
            "FIXTURE": str(self.root), "BASE_URL": "https://example.test/dashboard",
            "STATE_DIR": str(self.root / "state"), "TARGET_PATH": str(self.target),
        }

    def write_manifest(self):
        self.checksum = hashlib.sha256((self.root / "image.png").read_bytes()).hexdigest()
        (self.root / "manifest").write_text(f"{self.checksum}  images/{self.checksum}.png\n")

    def run_updater(self, **environ):
        return subprocess.run(["/bin/sh", str(UPDATER)], env={**self.environ, **environ},
                              capture_output=True, text=True)

    def calls(self):
        return (self.root / "calls").read_text()

    def test_success_preserves_original_and_restores_read_only(self):
        result = self.run_updater()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target.read_bytes(), (self.root / "image.png").read_bytes())
        self.assertEqual((self.root / "state" / "original-suspended.png").read_bytes(), b"original v1 image")
        self.assertIn("mount -o remount,rw /", self.calls())
        self.assertIn("mount -o remount,ro /", self.calls())
        self.assertFalse(list((self.root / "state").glob("download.*")))

    def test_unchanged_image_skips_download_and_mount(self):
        self.target.write_bytes((self.root / "image.png").read_bytes())
        result = self.run_updater()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls().count("curl "), 1)
        self.assertNotIn("mount ", self.calls())

    def test_offline_bad_checksum_bad_header_and_traversal_preserve_target(self):
        original_image = (self.root / "image.png").read_bytes()
        original_manifest = (self.root / "manifest").read_text()
        for failure in ("offline", "checksum", "header", "path"):
            with self.subTest(failure=failure):
                (self.root / "image.png").write_bytes(original_image)
                (self.root / "manifest").write_text(original_manifest)
                if failure == "checksum":
                    (self.root / "image.png").write_bytes(b"truncated")
                elif failure == "header":
                    Image.new("RGBA", (1620, 2160)).save(self.root / "image.png")
                    self.write_manifest()
                elif failure == "path":
                    (self.root / "manifest").write_text(f"{self.checksum}  ../../suspended.png\n")
                result = self.run_updater(**({"FAIL_FETCH": "1"} if failure == "offline" else {}))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.target.read_bytes(), b"original v1 image")
                self.assertNotIn("mount ", self.calls())

    def test_copy_failure_keeps_old_target_and_restores_read_only(self):
        result = self.run_updater(FAIL_COPY="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.target.read_bytes(), b"original v1 image")
        self.assertIn("mount -o remount,ro /", self.calls())
        self.assertFalse((self.root / ".dashboard-v2.new").exists())

    def test_mount_failure_keeps_old_target(self):
        result = self.run_updater(FAIL_MOUNT="remount,rw")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.target.read_bytes(), b"original v1 image")

    def test_read_only_restore_failure_is_reported(self):
        result = self.run_updater(FAIL_MOUNT="remount,ro")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CRITICAL", result.stderr)

    def test_originally_writable_root_is_not_remounted(self):
        result = self.run_updater(ROOT_OPTIONS="rw,relatime")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("mount ", self.calls())

    def test_insecure_endpoint_is_rejected(self):
        result = self.run_updater(BASE_URL="http://example.test")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.target.read_bytes(), b"original v1 image")


if __name__ == "__main__":
    unittest.main()