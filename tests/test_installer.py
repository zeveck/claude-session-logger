"""Tests for install.py and install.js installers.

Verifies file installation, settings merge, TZ patching, and overwrite guard.

Usage:
    python3 tests/test_installer.py           # test both
    python3 tests/test_installer.py --py-only
    python3 tests/test_installer.py --js-only
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY_INSTALLER = os.path.join(PKG_DIR, "install.py")
JS_INSTALLER = os.path.join(PKG_DIR, "install.js")

_PY_ONLY = "--py-only" in sys.argv
_JS_ONLY = "--js-only" in sys.argv
if _PY_ONLY:
    sys.argv.remove("--py-only")
if _JS_ONLY:
    sys.argv.remove("--js-only")


def _runtimes():
    if not _JS_ONLY:
        yield "py"
    if not _PY_ONLY:
        yield "js"


class InstallerTestBase:
    """Mixin with installer tests. Subclasses set self.runtime."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Create a fake git repo so the installer doesn't abort
        os.makedirs(os.path.join(self.tmpdir, ".git"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_installer(self, stdin_text):
        """Run the installer in the temp project directory."""
        if self.runtime == "py":
            cmd = [sys.executable, PY_INSTALLER]
        else:
            cmd = ["node", JS_INSTALLER]

        result = subprocess.run(
            cmd, input=stdin_text, capture_output=True,
            text=True, timeout=15, cwd=self.tmpdir,
        )
        return result

    @property
    def _ext(self):
        return "." + self.runtime

    @property
    def _expected_scripts(self):
        ext = self._ext
        return [f"stop-log{ext}", f"subagent-stop-log{ext}", f"log-converter{ext}"]

    @property
    def _runtime_cmd(self):
        return "python3" if self.runtime == "py" else "node"

    # --- Fresh install ---

    def test_fresh_install_creates_files(self):
        """Installer copies all hook scripts to .claude/hooks/."""
        result = self._run_installer("America/New_York\n")

        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")

        hooks_dir = os.path.join(self.tmpdir, ".claude", "hooks")
        self.assertTrue(os.path.isdir(hooks_dir))

        for script in self._expected_scripts:
            path = os.path.join(hooks_dir, script)
            self.assertTrue(os.path.isfile(path), f"Missing: {script}")

    def test_fresh_install_creates_settings(self):
        """Installer creates .claude/settings.json with hook config."""
        self._run_installer("UTC\n")

        settings_path = os.path.join(self.tmpdir, ".claude", "settings.json")
        self.assertTrue(os.path.isfile(settings_path))

        with open(settings_path, "r") as f:
            settings = json.load(f)

        self.assertIn("hooks", settings)
        self.assertIn("Stop", settings["hooks"])
        self.assertIn("SubagentStop", settings["hooks"])

        # Verify the command uses the right runtime
        stop_cmd = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn(self._runtime_cmd, stop_cmd)
        self.assertIn("stop-log", stop_cmd)

    def test_tz_patched_in_scripts(self):
        """Installer replaces __TZ__ with the user's chosen timezone."""
        self._run_installer("America/Chicago\n")

        hooks_dir = os.path.join(self.tmpdir, ".claude", "hooks")
        script = f"stop-log{self._ext}"
        with open(os.path.join(hooks_dir, script), "r") as f:
            content = f.read()

        self.assertIn("America/Chicago", content)
        self.assertNotIn("__TZ__", content)

    def test_default_tz(self):
        """Installer uses America/New_York as default when user just hits enter."""
        # Just press enter (empty input = use default)
        self._run_installer("\n")

        hooks_dir = os.path.join(self.tmpdir, ".claude", "hooks")
        script = f"stop-log{self._ext}"
        with open(os.path.join(hooks_dir, script), "r") as f:
            content = f.read()

        self.assertIn("America/New_York", content)

    # --- Settings merge ---

    def test_settings_merge_preserves_existing(self):
        """Installer merges hooks into existing settings without clobbering."""
        settings_dir = os.path.join(self.tmpdir, ".claude")
        os.makedirs(settings_dir, exist_ok=True)
        settings_path = os.path.join(settings_dir, "settings.json")

        existing = {
            "permissions": {"allow": ["Read", "Glob"]},
            "customKey": True,
        }
        with open(settings_path, "w") as f:
            json.dump(existing, f)

        self._run_installer("UTC\n")

        with open(settings_path, "r") as f:
            settings = json.load(f)

        # Original keys preserved
        self.assertEqual(settings["permissions"]["allow"], ["Read", "Glob"])
        self.assertTrue(settings["customKey"])
        # Hooks added
        self.assertIn("hooks", settings)
        self.assertIn("Stop", settings["hooks"])

    # --- Overwrite guard ---

    def test_overwrite_guard_detects_existing(self):
        """Installer detects existing installation."""
        hooks_dir = os.path.join(self.tmpdir, ".claude", "hooks")
        os.makedirs(hooks_dir, exist_ok=True)
        # Create existing hook to trigger overwrite prompt
        script = f"stop-log{self._ext}"
        with open(os.path.join(hooks_dir, script), "w") as f:
            f.write("existing content with __TZ__ placeholder")

        result = self._run_installer("UTC\n")

        # Output should mention overwrite
        self.assertIn("Overwrite", result.stdout + result.stderr)

    # --- No .git directory ---

    def test_no_git_aborts(self):
        """Installer aborts if not in a git project root."""
        shutil.rmtree(os.path.join(self.tmpdir, ".git"))

        result = self._run_installer("UTC\n")

        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("git", combined.lower())


# Dynamically create test classes for each runtime
for runtime in _runtimes():
    cls_name = f"TestInstaller_{runtime}"
    cls = type(cls_name, (InstallerTestBase, unittest.TestCase), {
        "runtime": runtime,
    })
    globals()[cls_name] = cls
del runtime, cls_name, cls


if __name__ == "__main__":
    unittest.main()
