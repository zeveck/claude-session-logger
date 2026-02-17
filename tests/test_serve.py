"""Tests for serve-sessions.py and serve-sessions.js log servers.

Verifies HTTPS default, HTTP fallback, strict filename parsing,
session labels, index, raw markdown, rendered HTML, and 404 handling.

Usage:
    python3 tests/test_serve.py           # test both
    python3 tests/test_serve.py --py-only
    python3 tests/test_serve.py --js-only
"""

import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY_SERVE = os.path.join(PKG_DIR, "py", "serve-sessions.py")
JS_SERVE = os.path.join(PKG_DIR, "js", "serve-sessions.js")

_PY_ONLY = "--py-only" in sys.argv
_JS_ONLY = "--js-only" in sys.argv
if _PY_ONLY:
    sys.argv.remove("--py-only")
if _JS_ONLY:
    sys.argv.remove("--js-only")

# Use different ports per runtime and mode to avoid conflicts
# HTTPS ports
_HTTPS_PORT_MAP = {"py": 14001, "js": 14002}
# HTTP ports
_HTTP_PORT_MAP = {"py": 14003, "js": 14004}
# Custom cert ports
_CERT_PORT_MAP = {"py": 14005, "js": 14006}


def _runtimes():
    if not _JS_ONLY:
        yield "py"
    if not _PY_ONLY:
        yield "js"


def _make_ssl_context():
    """Create an SSL context that accepts self-signed certs."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _fetch(url, use_ssl=False):
    """Fetch a URL and return (status_code, body)."""
    ctx = _make_ssl_context() if use_ssl else None
    try:
        resp = urllib.request.urlopen(url, timeout=5, context=ctx)
        return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def _fetch_headers(url, use_ssl=False):
    """Fetch a URL and return the response headers."""
    ctx = _make_ssl_context() if use_ssl else None
    resp = urllib.request.urlopen(url, timeout=5, context=ctx)
    return resp.headers


def _start_server(runtime, port, log_dir, extra_args=None, cwd=None):
    """Start a serve-sessions process and wait for it to be ready."""
    if runtime == "py":
        cmd = [sys.executable, PY_SERVE]
    else:
        cmd = ["node", JS_SERVE]

    cmd += ["--port", str(port), "--dir", log_dir]
    if extra_args:
        cmd += extra_args

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=cwd,
    )

    # Determine if HTTPS
    use_ssl = "--http" not in (extra_args or [])
    scheme = "https" if use_ssl else "http"
    base_url = f"{scheme}://127.0.0.1:{port}"

    for _ in range(30):
        time.sleep(0.2)
        try:
            _fetch(base_url, use_ssl=use_ssl)
            break
        except Exception:
            if proc.poll() is not None:
                stdout = proc.stdout.read().decode()
                stderr = proc.stderr.read().decode()
                raise RuntimeError(
                    f"Server exited early (rc={proc.returncode})\n"
                    f"stdout: {stdout}\nstderr: {stderr}"
                )
            continue

    return proc


class ServeHTTPSTestBase:
    """Tests for HTTPS mode (default)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_dir = os.path.join(self.tmpdir, "logs")
        os.makedirs(self.log_dir)

        # Create test log files with well-formed names
        with open(os.path.join(self.log_dir, "2026-02-16-1856-abc12345.md"), "w") as f:
            f.write("# Session `abc12345` \u2014 2026-02-16 18:56\n\n---\n\n**User:**\n> Hello\n\nHi there!\n")

        with open(os.path.join(self.log_dir, "2026-02-16-1900-abc12345-subagent-Explore-dddd1111.md"), "w") as f:
            f.write("# Subagent: Explore `dddd1111` \u2014 2026-02-16 19:00\n\n---\n\nResearch results.\n")

        # Malformed filename (no HHMM) — should be ignored
        with open(os.path.join(self.log_dir, "2026-02-16-oldformat.md"), "w") as f:
            f.write("# Old format log\n\nThis should not appear in the index.\n")

        # File with a label in the header
        with open(os.path.join(self.log_dir, "2026-02-17-0930-def67890.md"), "w") as f:
            f.write("# Session `def67890` \u2014 2026-02-17 09:30 \u2014 Auth Feature\n\n---\n\nWorking on auth.\n")

        self.port = _HTTPS_PORT_MAP[self.runtime]
        self.base_url = f"https://127.0.0.1:{self.port}"

        # Run from tmpdir so auto-cert writes to tmpdir/.claude/certs/
        self.server = _start_server(
            self.runtime, self.port, self.log_dir, cwd=self.tmpdir
        )

    def tearDown(self):
        self.server.terminate()
        self.server.wait(timeout=5)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # --- HTTPS works ---

    def test_https_index(self):
        """Server responds over HTTPS by default."""
        status, body = _fetch(self.base_url + "/", use_ssl=True)
        self.assertEqual(status, 200)
        self.assertIn("Session Logs", body)

    # --- Index ---

    def test_index_lists_sessions(self):
        status, body = _fetch(self.base_url + "/", use_ssl=True)
        self.assertIn("abc12345", body)
        self.assertIn("view", body)
        self.assertIn("raw", body)

    def test_index_shows_subagent(self):
        status, body = _fetch(self.base_url + "/", use_ssl=True)
        self.assertIn("Explore", body)
        self.assertIn("dddd1111", body)

    # --- Strict filename parsing ---

    def test_malformed_filename_excluded(self):
        """Files without HHMM in the name are not shown in the index."""
        status, body = _fetch(self.base_url + "/", use_ssl=True)
        self.assertNotIn("oldformat", body)

    # --- Label ---

    def test_label_shown_in_index(self):
        """Session label from header is displayed in the index."""
        status, body = _fetch(self.base_url + "/", use_ssl=True)
        self.assertIn("Auth Feature", body)

    # --- Raw markdown ---

    def test_raw_markdown(self):
        status, body = _fetch(self.base_url + "/2026-02-16-1856-abc12345.md", use_ssl=True)
        self.assertEqual(status, 200)
        self.assertIn("# Session `abc12345`", body)
        self.assertIn("> Hello", body)

    def test_raw_markdown_404(self):
        status, _ = _fetch(self.base_url + "/nonexistent.md", use_ssl=True)
        self.assertEqual(status, 404)

    # --- Rendered HTML ---

    def test_rendered_html(self):
        status, body = _fetch(self.base_url + "/2026-02-16-1856-abc12345", use_ssl=True)
        self.assertEqual(status, 200)
        self.assertIn("<html", body)
        self.assertIn("marked.parse", body)
        self.assertIn("Session", body)

    def test_rendered_404(self):
        status, _ = _fetch(self.base_url + "/nonexistent", use_ssl=True)
        self.assertEqual(status, 404)

    # --- CORS ---

    def test_cors_header(self):
        headers = _fetch_headers(self.base_url + "/", use_ssl=True)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")

    # --- Empty directory ---

    def test_empty_index(self):
        """Server handles empty log directory gracefully."""
        for f in os.listdir(self.log_dir):
            os.remove(os.path.join(self.log_dir, f))

        status, body = _fetch(self.base_url + "/", use_ssl=True)
        self.assertEqual(status, 200)
        self.assertIn("No session logs found", body)


class ServeHTTPTestBase:
    """Tests for --http mode."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_dir = os.path.join(self.tmpdir, "logs")
        os.makedirs(self.log_dir)

        with open(os.path.join(self.log_dir, "2026-02-16-1856-abc12345.md"), "w") as f:
            f.write("# Session `abc12345` \u2014 2026-02-16 18:56\n\n---\n\nHello\n")

        self.port = _HTTP_PORT_MAP[self.runtime]
        self.base_url = f"http://127.0.0.1:{self.port}"

        self.server = _start_server(
            self.runtime, self.port, self.log_dir, extra_args=["--http"]
        )

    def tearDown(self):
        self.server.terminate()
        self.server.wait(timeout=5)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_http_index(self):
        """Server works over plain HTTP with --http flag."""
        status, body = _fetch(self.base_url + "/", use_ssl=False)
        self.assertEqual(status, 200)
        self.assertIn("Session Logs", body)

    def test_http_raw_markdown(self):
        status, body = _fetch(self.base_url + "/2026-02-16-1856-abc12345.md", use_ssl=False)
        self.assertEqual(status, 200)
        self.assertIn("# Session", body)


class ServeCustomCertTestBase:
    """Tests for --cert/--key mode."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_dir = os.path.join(self.tmpdir, "logs")
        os.makedirs(self.log_dir)
        self.cert_dir = os.path.join(self.tmpdir, "custom-certs")
        os.makedirs(self.cert_dir)

        with open(os.path.join(self.log_dir, "2026-02-16-1856-abc12345.md"), "w") as f:
            f.write("# Session `abc12345` \u2014 2026-02-16 18:56\n\n---\n\nHello\n")

        # Generate a custom cert
        self.cert_path = os.path.join(self.cert_dir, "test.pem")
        self.key_path = os.path.join(self.cert_dir, "test-key.pem")
        subprocess.run(
            [
                "openssl", "req", "-x509",
                "-newkey", "rsa:2048",
                "-keyout", self.key_path,
                "-out", self.cert_path,
                "-days", "1",
                "-nodes",
                "-subj", "/CN=localhost",
            ],
            capture_output=True, check=True,
        )

        self.port = _CERT_PORT_MAP[self.runtime]
        self.base_url = f"https://127.0.0.1:{self.port}"

        self.server = _start_server(
            self.runtime, self.port, self.log_dir,
            extra_args=["--cert", self.cert_path, "--key", self.key_path],
        )

    def tearDown(self):
        self.server.terminate()
        self.server.wait(timeout=5)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_custom_cert_works(self):
        """Server uses custom cert/key when provided."""
        status, body = _fetch(self.base_url + "/", use_ssl=True)
        self.assertEqual(status, 200)
        self.assertIn("Session Logs", body)


# Dynamically create test classes for each runtime
for runtime in _runtimes():
    # HTTPS tests
    cls_name = f"TestServeHTTPS_{runtime}"
    cls = type(cls_name, (ServeHTTPSTestBase, unittest.TestCase), {
        "runtime": runtime,
    })
    globals()[cls_name] = cls

    # HTTP tests
    cls_name = f"TestServeHTTP_{runtime}"
    cls = type(cls_name, (ServeHTTPTestBase, unittest.TestCase), {
        "runtime": runtime,
    })
    globals()[cls_name] = cls

    # Custom cert tests
    cls_name = f"TestServeCert_{runtime}"
    cls = type(cls_name, (ServeCustomCertTestBase, unittest.TestCase), {
        "runtime": runtime,
    })
    globals()[cls_name] = cls

del runtime, cls_name, cls


if __name__ == "__main__":
    unittest.main()
