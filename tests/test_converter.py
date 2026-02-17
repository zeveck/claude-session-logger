"""Tests for log-converter.py and log-converter.js.

Runs both converters against the same fixtures and asserts on output.

Usage:
    python3 tests/test_converter.py           # test both
    python3 tests/test_converter.py --py-only  # python only
    python3 tests/test_converter.py --js-only  # node only
"""

import os
import subprocess
import sys
import tempfile
import unittest

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY_CONVERTER = os.path.join(PKG_DIR, "py", "log-converter.py")
JS_CONVERTER = os.path.join(PKG_DIR, "js", "log-converter.js")
FIXTURES_DIR = os.path.join(PKG_DIR, "tests", "fixtures")

# Determine which runtimes to test based on CLI flags
_PY_ONLY = "--py-only" in sys.argv
_JS_ONLY = "--js-only" in sys.argv
if _PY_ONLY:
    sys.argv.remove("--py-only")
if _JS_ONLY:
    sys.argv.remove("--js-only")


def _runtimes():
    """Yield (label, command_prefix) for each runtime under test."""
    if not _JS_ONLY:
        yield ("py", [sys.executable, PY_CONVERTER])
    if not _PY_ONLY:
        yield ("js", ["node", JS_CONVERTER])


def run_converter(cmd, fixture, session_id="abc12345-test", date="2026-02-16",
                  start_time="2026-02-16T18:56:00", agent_type=None,
                  agent_id=None):
    """Run a converter command and return the output markdown string."""
    fixture_path = os.path.join(FIXTURES_DIR, fixture)
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        output_path = f.name

    try:
        args = cmd + [
            "--transcript", fixture_path,
            "--output", output_path,
            "--session-id", session_id,
            "--date", date,
            "--start-time", start_time,
        ]
        if agent_type:
            args += ["--agent-type", agent_type]
        if agent_id:
            args += ["--agent-id", agent_id]

        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            raise RuntimeError(
                f"Converter failed (exit {result.returncode}):\n"
                f"  stderr: {result.stderr}\n  stdout: {result.stdout}"
            )

        with open(output_path, "r") as f:
            return f.read()
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


class ConverterTestBase:
    """Mixin with test methods. Subclasses set self.label and self.cmd."""

    # --- Header tests ---

    def test_session_header(self):
        md = run_converter(self.cmd, "basic.jsonl")
        self.assertIn("# Session `abc12345` — 2026-02-16 18:56", md)
        self.assertIn("---", md)

    def test_subagent_header(self):
        md = run_converter(
            self.cmd, "basic.jsonl",
            agent_type="Explore", agent_id="aaaa1111-bbbb-cccc"
        )
        self.assertIn("# Subagent: Explore `aaaa1111`", md)
        self.assertIn("*Parent session: `abc12345`*", md)

    # --- Basic rendering ---

    def test_basic_user_assistant(self):
        md = run_converter(self.cmd, "basic.jsonl")
        self.assertIn("**User:**", md)
        self.assertIn("> Hello, how are you?", md)
        self.assertIn("I'm doing well, thanks for asking!", md)
        self.assertIn("> What can you help me with?", md)
        self.assertIn("software engineering tasks", md)

    # --- Tool call rendering ---

    def test_tool_call_inline(self):
        """Short tool results (<=4 lines) render inline with ⎿ prefix."""
        md = run_converter(self.cmd, "tool-calls.jsonl")
        self.assertIn("`Read(/tmp/config.json)`", md)
        self.assertIn('⎿  { "key": "value" }', md)

    def test_tool_call_collapsed(self):
        """Long tool results (>4 lines) render in <details> blocks."""
        md = run_converter(self.cmd, "long-result.jsonl")
        self.assertIn("<details>", md)
        self.assertIn("<summary>", md)
        self.assertIn("Bash(ls -la)", md)
        self.assertIn("</details>", md)
        self.assertIn("<br>", md)

    def test_multi_tool_calls(self):
        """Parallel tool calls each get their own result."""
        md = run_converter(self.cmd, "multi-tool.jsonl")
        self.assertIn("`Read(/tmp/a.txt)`", md)
        self.assertIn("content of a", md)
        self.assertIn("`Read(/tmp/b.txt)`", md)
        self.assertIn("content of b", md)

    # --- Edit diff rendering ---

    def test_edit_diff(self):
        """Edit tool shows a diff block."""
        md = run_converter(self.cmd, "edit-diff.jsonl")
        self.assertIn("`Update(/tmp/test.py)`", md)
        self.assertIn("```diff", md)
        self.assertIn("-def hello_wrold():", md)
        self.assertIn("+def hello_world():", md)
        self.assertIn("```", md)
        self.assertIn("Successfully edited", md)

    # --- Tool header formats ---

    def test_all_tool_headers(self):
        """Each tool type gets the right header format."""
        md = run_converter(self.cmd, "all-tool-types.jsonl")
        self.assertIn("`Bash(echo hello", md)
        self.assertIn("`Read(/tmp/test.txt)`", md)
        self.assertIn("`Write(/tmp/out.txt)`", md)
        self.assertIn("`Update(/tmp/edit.txt)`", md)
        self.assertIn("`Glob(**/*.py)`", md)
        self.assertIn("Searched for `TODO`", md)
        self.assertIn("`WebFetch(https://example.com/", md)
        self.assertIn("`WebSearch(python tutorial)`", md)
        self.assertIn("`Task(Explore: Research something)`", md)
        # Generic fallback
        self.assertIn("CustomTool", md)

    # --- Error results ---

    def test_error_result(self):
        """Tool errors show Error prefix and strip <tool_use_error> tags."""
        md = run_converter(self.cmd, "error-result.jsonl")
        self.assertIn("**Error:**", md)
        self.assertIn("No such file or directory", md)
        # The XML tags should be stripped
        self.assertNotIn("<tool_use_error>", md)
        self.assertNotIn("</tool_use_error>", md)

    # --- Thinking blocks ---

    def test_thinking_blocks_omitted(self):
        """Thinking blocks are not rendered."""
        md = run_converter(self.cmd, "thinking-blocks.jsonl")
        self.assertNotIn("Let me calculate", md)
        self.assertIn("2+2 = 4", md)

    # --- Malformed input ---

    def test_malformed_json_skipped(self):
        """Bad JSON lines are skipped, valid ones render normally."""
        md = run_converter(self.cmd, "malformed.jsonl")
        self.assertIn("> Valid message", md)
        self.assertIn("Valid response", md)

    # --- Null timestamps ---

    def test_null_timestamp_skipped(self):
        """Records with null timestamps (file-history-snapshot) are skipped."""
        md = run_converter(self.cmd, "null-timestamp.jsonl")
        self.assertIn("> Hello", md)
        self.assertIn("Hi there!", md)
        # Should not contain any reference to null
        self.assertNotIn("null", md.lower().split("---", 1)[1] if "---" in md else md)

    # --- Skip types ---

    def test_skip_types_filtered(self):
        """queue-operation, progress, system types don't appear in output."""
        md = run_converter(self.cmd, "skip-types.jsonl")
        self.assertIn("> Only real message", md)
        self.assertIn("Only real response", md)
        # The body should only have the one exchange
        body = md.split("---", 1)[1] if "---" in md else md
        self.assertEqual(body.count("**User:**"), 1)

    # --- Context continuation ---

    def test_context_continuation_collapsed(self):
        """Context continuation messages render in a details block."""
        md = run_converter(self.cmd, "context-continuation.jsonl")
        self.assertIn("**Context restored from previous session", md)
        self.assertIn("<details>", md)
        self.assertIn("<summary>Session summary</summary>", md)
        self.assertIn("Fixed bug in login flow", md)

    # --- Empty input ---

    def test_empty_transcript(self):
        """Empty JSONL file creates an empty output file."""
        with tempfile.NamedTemporaryFile(
            suffix=".jsonl", delete=False, mode="w"
        ) as f:
            f.write("")
            empty_fixture = f.name

        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            output_path = f.name

        try:
            result = subprocess.run(
                self.cmd + [
                    "--transcript", empty_fixture,
                    "--output", output_path,
                ],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0)
            with open(output_path, "r") as f:
                content = f.read()
            self.assertEqual(content, "")
        finally:
            os.unlink(empty_fixture)
            if os.path.exists(output_path):
                os.unlink(output_path)

    # --- Parity check (run both and compare structure) ---

    def test_output_not_empty(self):
        """Sanity check: converter produces non-empty output."""
        md = run_converter(self.cmd, "basic.jsonl")
        self.assertGreater(len(md), 50)


# Dynamically create test classes for each runtime
for label, cmd in _runtimes():
    cls_name = f"TestConverter_{label}"
    cls = type(cls_name, (ConverterTestBase, unittest.TestCase), {
        "label": label,
        "cmd": cmd,
    })
    globals()[cls_name] = cls
del label, cmd, cls_name, cls


class TestConverterParity(unittest.TestCase):
    """Verify Python and JS converters produce equivalent output."""

    def setUp(self):
        runtimes = list(_runtimes())
        if len(runtimes) < 2:
            self.skipTest("Need both runtimes for parity tests")
        self.py_cmd = None
        self.js_cmd = None
        for label, cmd in runtimes:
            if label == "py":
                self.py_cmd = cmd
            elif label == "js":
                self.js_cmd = cmd

    def _compare_fixture(self, fixture):
        """Run both converters and compare structural elements."""
        py_md = run_converter(self.py_cmd, fixture)
        js_md = run_converter(self.js_cmd, fixture)

        # Headers should match exactly
        py_header = py_md.split("---")[0]
        js_header = js_md.split("---")[0]
        self.assertEqual(py_header.strip(), js_header.strip(),
                         f"Header mismatch for {fixture}")

        # Both should have same number of User: blocks
        self.assertEqual(
            py_md.count("**User:**"), js_md.count("**User:**"),
            f"User block count mismatch for {fixture}"
        )

        # Both should have same number of <details> blocks
        self.assertEqual(
            py_md.count("<details>"), js_md.count("<details>"),
            f"Details block count mismatch for {fixture}"
        )

    def test_parity_basic(self):
        self._compare_fixture("basic.jsonl")

    def test_parity_tool_calls(self):
        self._compare_fixture("tool-calls.jsonl")

    def test_parity_long_result(self):
        self._compare_fixture("long-result.jsonl")

    def test_parity_edit_diff(self):
        self._compare_fixture("edit-diff.jsonl")

    def test_parity_error_result(self):
        self._compare_fixture("error-result.jsonl")

    def test_parity_multi_tool(self):
        self._compare_fixture("multi-tool.jsonl")

    def test_parity_all_tool_types(self):
        self._compare_fixture("all-tool-types.jsonl")

    def test_parity_context_continuation(self):
        self._compare_fixture("context-continuation.jsonl")


if __name__ == "__main__":
    unittest.main()
