"""Tests for stop-log.py/js and subagent-stop-log.py/js hook scripts.

Tests timestamp extraction, filename generation, and end-to-end log creation.

Usage:
    python3 tests/test_hooks.py           # test both
    python3 tests/test_hooks.py --py-only
    python3 tests/test_hooks.py --js-only
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(PKG_DIR, "tests", "fixtures")

# We need installed copies with __TZ__ replaced for testing
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


class HookTestBase:
    """Mixin with hook tests. Subclasses set self.runtime ('py' or 'js')."""

    def setUp(self):
        """Create a temp project dir with installed hook scripts."""
        self.tmpdir = tempfile.mkdtemp()
        self.hooks_dir = os.path.join(self.tmpdir, ".claude", "hooks")
        self.logs_dir = os.path.join(self.tmpdir, ".claude", "logs")
        os.makedirs(self.hooks_dir)

        # Copy hook scripts with __TZ__ replaced
        ext = self.runtime
        src_dir = os.path.join(PKG_DIR, self.runtime)
        for script in os.listdir(src_dir):
            src = os.path.join(src_dir, script)
            dst = os.path.join(self.hooks_dir, script)
            with open(src, "r") as f:
                content = f.read()
            content = content.replace("__TZ__", "America/New_York")
            with open(dst, "w") as f:
                f.write(content)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_hook(self, script_name, stdin_data):
        """Run a hook script with JSON on stdin, from the temp project dir."""
        script_path = os.path.join(self.hooks_dir, script_name)
        if self.runtime == "py":
            cmd = [sys.executable, script_path]
        else:
            cmd = ["node", script_path]

        result = subprocess.run(
            cmd, input=json.dumps(stdin_data), capture_output=True,
            text=True, timeout=30, cwd=self.tmpdir,
        )
        return result

    # --- Main hook tests ---

    def test_creates_log_file(self):
        """Hook creates a log file with correct naming convention."""
        fixture = os.path.join(FIXTURES_DIR, "basic.jsonl")
        ext = "." + self.runtime
        script = "stop-log" + ext

        result = self._run_hook(script, {
            "transcript_path": fixture,
            "session_id": "abc12345-6789-0000-0000-000000000000",
        })

        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertTrue(os.path.isdir(self.logs_dir),
                        "Logs directory was not created")

        logs = os.listdir(self.logs_dir)
        # Filter out error logs
        md_logs = [f for f in logs if f.endswith(".md")]
        self.assertEqual(len(md_logs), 1,
                         f"Expected 1 log file, got: {md_logs}")

        log_name = md_logs[0]
        # Filename: {date}-{HHMM}-{short_session}.md
        # The timestamp 2026-02-16T23:56:00Z in America/New_York is 2026-02-16 18:56
        self.assertIn("abc12345", log_name)
        self.assertIn("2026-02-16", log_name)
        self.assertIn("1856", log_name)

    def test_log_file_content(self):
        """Hook produces a log with header and body content."""
        fixture = os.path.join(FIXTURES_DIR, "basic.jsonl")
        ext = "." + self.runtime
        script = "stop-log" + ext

        self._run_hook(script, {
            "transcript_path": fixture,
            "session_id": "abc12345-6789-0000-0000-000000000000",
        })

        md_logs = [f for f in os.listdir(self.logs_dir) if f.endswith(".md")]
        with open(os.path.join(self.logs_dir, md_logs[0]), "r") as f:
            content = f.read()

        self.assertIn("# Session `abc12345`", content)
        self.assertIn("Hello, how are you?", content)

    def test_null_timestamp_handling(self):
        """Hook handles transcripts where first records have null timestamps."""
        fixture = os.path.join(FIXTURES_DIR, "null-timestamp.jsonl")
        ext = "." + self.runtime
        script = "stop-log" + ext

        result = self._run_hook(script, {
            "transcript_path": fixture,
            "session_id": "abc12345-6789-0000-0000-000000000000",
        })

        self.assertEqual(result.returncode, 0)
        md_logs = [f for f in os.listdir(self.logs_dir) if f.endswith(".md")]
        self.assertEqual(len(md_logs), 1)

        log_name = md_logs[0]
        # Should use the timestamp from the third record (23:56:30 UTC = 18:56 ET)
        self.assertIn("1856", log_name)
        # Should NOT have 0000 (the fallback for missing timestamps)
        self.assertNotIn("0000", log_name)

    def test_invalid_json_stdin(self):
        """Hook exits 0 on invalid JSON stdin."""
        ext = "." + self.runtime
        script = "stop-log" + ext
        script_path = os.path.join(self.hooks_dir, script)

        if self.runtime == "py":
            cmd = [sys.executable, script_path]
        else:
            cmd = ["node", script_path]

        result = subprocess.run(
            cmd, input="not json at all", capture_output=True,
            text=True, timeout=10, cwd=self.tmpdir,
        )
        self.assertEqual(result.returncode, 0)

    def test_missing_transcript_file(self):
        """Hook exits 0 when transcript file doesn't exist."""
        ext = "." + self.runtime
        script = "stop-log" + ext

        result = self._run_hook(script, {
            "transcript_path": "/nonexistent/path/transcript.jsonl",
            "session_id": "abc12345",
        })
        self.assertEqual(result.returncode, 0)

    def test_empty_stdin(self):
        """Hook exits 0 on empty stdin."""
        ext = "." + self.runtime
        script = "stop-log" + ext
        script_path = os.path.join(self.hooks_dir, script)

        if self.runtime == "py":
            cmd = [sys.executable, script_path]
        else:
            cmd = ["node", script_path]

        result = subprocess.run(
            cmd, input="", capture_output=True,
            text=True, timeout=10, cwd=self.tmpdir,
        )
        self.assertEqual(result.returncode, 0)

    def test_no_error_log_on_success(self):
        """Successful run should not leave a .converter-errors.log file."""
        fixture = os.path.join(FIXTURES_DIR, "basic.jsonl")
        ext = "." + self.runtime
        script = "stop-log" + ext

        self._run_hook(script, {
            "transcript_path": fixture,
            "session_id": "abc12345-6789",
        })

        error_log = os.path.join(self.logs_dir, ".converter-errors.log")
        self.assertFalse(os.path.exists(error_log),
                         "Error log should not exist on success")

    # --- Subagent hook tests ---

    def test_subagent_creates_log(self):
        """Subagent hook creates log with agent type and ID in filename."""
        fixture = os.path.join(FIXTURES_DIR, "basic.jsonl")
        ext = "." + self.runtime
        script = "subagent-stop-log" + ext

        result = self._run_hook(script, {
            "agent_transcript_path": fixture,
            "session_id": "abc12345-6789-0000-0000-000000000000",
            "agent_id": "aaaa1111-bbbb-cccc-dddd-eeeeeeeeeeee",
            "agent_type": "Explore",
        })

        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")

        md_logs = [f for f in os.listdir(self.logs_dir) if f.endswith(".md")]
        self.assertEqual(len(md_logs), 1)

        log_name = md_logs[0]
        self.assertIn("abc12345", log_name)
        self.assertIn("subagent", log_name)
        self.assertIn("Explore", log_name)
        self.assertIn("aaaa1111", log_name)

    def test_subagent_header_content(self):
        """Subagent log contains proper subagent header."""
        fixture = os.path.join(FIXTURES_DIR, "basic.jsonl")
        ext = "." + self.runtime
        script = "subagent-stop-log" + ext

        self._run_hook(script, {
            "agent_transcript_path": fixture,
            "session_id": "abc12345-6789-0000-0000-000000000000",
            "agent_id": "aaaa1111-bbbb-cccc-dddd-eeeeeeeeeeee",
            "agent_type": "Explore",
        })

        md_logs = [f for f in os.listdir(self.logs_dir) if f.endswith(".md")]
        with open(os.path.join(self.logs_dir, md_logs[0]), "r") as f:
            content = f.read()

        self.assertIn("Subagent: Explore", content)
        self.assertIn("Parent session: `abc12345`", content)

    def test_subagent_missing_transcript(self):
        """Subagent hook exits 0 when transcript doesn't exist."""
        ext = "." + self.runtime
        script = "subagent-stop-log" + ext

        result = self._run_hook(script, {
            "agent_transcript_path": "/nonexistent/path.jsonl",
            "session_id": "abc12345",
            "agent_id": "aaaa1111",
            "agent_type": "Explore",
        })
        self.assertEqual(result.returncode, 0)


# Dynamically create test classes for each runtime
for runtime in _runtimes():
    cls_name = f"TestHooks_{runtime}"
    cls = type(cls_name, (HookTestBase, unittest.TestCase), {
        "runtime": runtime,
    })
    globals()[cls_name] = cls
del runtime, cls_name, cls


if __name__ == "__main__":
    unittest.main()
