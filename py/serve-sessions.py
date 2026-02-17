#!/usr/bin/env python3
"""Serve session logs over HTTPS.

Serves .claude/logs/ as browsable, shareable session threads.
Raw markdown for machines (another Claude via WebFetch), rendered HTML for humans.
HTTPS with auto-generated self-signed cert by default.

Usage:
    python3 serve-sessions.py                      # HTTPS on localhost:9443
    python3 serve-sessions.py --http               # plain HTTP
    python3 serve-sessions.py --port 8443          # custom port
    python3 serve-sessions.py --host 0.0.0.0       # expose to network
    python3 serve-sessions.py --cert C --key K     # custom cert
    python3 serve-sessions.py --dir .claude/logs   # custom log directory
"""

import argparse
import html
import os
import re
import shutil
import ssl
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote

DEFAULT_PORT = 9443
DEFAULT_HOST = "127.0.0.1"
DEFAULT_DIR = os.path.join(".claude", "logs")
DEFAULT_CERT_DIR = os.path.join(".claude", "certs")
CERT_FILE = "localhost.pem"
KEY_FILE = "localhost-key.pem"

# Strict filename pattern: YYYY-MM-DD-HHMM-{session}[-subagent-{type}-{agent}]
LOG_NAME_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})-(\d{4})-(\w+?)(?:-subagent-(.+)-(\w+))?$"
)

# Label regex for first line of log:
# # Session `abc123` — 2026-02-17 18:56 — My Label
# # Subagent: Explore `dddd1111` — 2026-02-17 19:00 — My Label
LABEL_RE = re.compile(
    r"^#\s+(?:Session|Subagent:\s+\S+)\s+.+?\u2014\s+\d{4}-\d{2}-\d{2}"
    r"(?:\s+\d{2}:\d{2})?\s*\u2014\s+(.+)$"
)

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link id="md-css" rel="stylesheet" href="https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown-dark.min.css">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  html[data-theme="dark"] body {{
    background: #0d1117;
    color: #e6edf3;
  }}
  html[data-theme="light"] body {{
    background: #ffffff;
    color: #1f2328;
  }}
  body {{
    max-width: 960px;
    margin: 0 auto;
    padding: 2rem 1rem;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    transition: background 0.2s, color 0.2s;
  }}
  .markdown-body {{
    background: transparent;
  }}
  html[data-theme="dark"] .markdown-body pre,
  html[data-theme="dark"] .markdown-body code {{
    background: #161b22;
  }}
  nav {{
    margin-bottom: 1.5rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  nav a {{ color: #58a6ff; text-decoration: none; }}
  nav a:hover {{ text-decoration: underline; }}
  .theme-toggle {{
    background: none;
    border: none;
    cursor: pointer;
    font-size: 1.2rem;
    padding: 0.2rem;
    line-height: 1;
  }}
  #content {{ display: none; }}
</style>
</head>
<body>
<nav>
  <a href="/">&larr; All sessions</a>
  <button class="theme-toggle" onclick="toggleTheme()" title="Toggle light/dark mode">&#9788;</button>
</nav>
<div id="raw" class="markdown-body"></div>
<pre id="content">{content}</pre>
<script>
  const md = document.getElementById('content').textContent;
  document.getElementById('raw').innerHTML = marked.parse(md);
  function setTheme(theme) {{
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('cc-theme', theme);
    document.querySelector('.theme-toggle').textContent = theme === 'dark' ? '\u263c' : '\u263d';
    var css = document.getElementById('md-css');
    css.href = theme === 'dark'
      ? 'https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown-dark.min.css'
      : 'https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown-light.min.css';
  }}
  function toggleTheme() {{
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  }}
  setTheme(localStorage.getItem('cc-theme') || 'dark');
</script>
</body>
</html>
"""

INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>cc-session-logs</title>
<style>
  html[data-theme="dark"] body {{
    background: #0d1117;
    color: #e6edf3;
  }}
  html[data-theme="light"] body {{
    background: #ffffff;
    color: #1f2328;
  }}
  body {{
    max-width: 960px;
    margin: 0 auto;
    padding: 2rem 1rem;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    transition: background 0.2s, color 0.2s;
  }}
  header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 0.5rem;
  }}
  html[data-theme="dark"] header {{ border-bottom: 1px solid #30363d; }}
  html[data-theme="light"] header {{ border-bottom: 1px solid #d0d7de; }}
  h1 {{ margin: 0; }}
  .theme-toggle {{
    background: none;
    border: none;
    cursor: pointer;
    font-size: 1.2rem;
    padding: 0.2rem;
    line-height: 1;
  }}
  a {{ color: #58a6ff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .session {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem 0.5rem;
    cursor: pointer;
    border-radius: 6px;
    transition: background 0.15s;
  }}
  html[data-theme="dark"] .session {{ border-bottom: 1px solid #21262d; }}
  html[data-theme="light"] .session {{ border-bottom: 1px solid #d0d7de; }}
  html[data-theme="dark"] .session:hover {{ background: #161b22; }}
  html[data-theme="light"] .session:hover {{ background: #f6f8fa; }}
  .session-name {{
    font-family: monospace;
    font-size: 0.95rem;
  }}
  .session a.row-link {{
    color: inherit;
    text-decoration: none;
  }}
  .formats {{ font-size: 0.8rem; opacity: 0.6; }}
  .formats a {{ margin-left: 0.75rem; }}
  .subagent {{ opacity: 0.7; font-size: 0.85rem; margin-left: 0.5rem; }}
  .label {{ margin-left: 0.75rem; font-style: italic; }}
  html[data-theme="dark"] .label {{ color: #8b949e; }}
  html[data-theme="light"] .label {{ color: #656d76; }}
  .empty {{ font-style: italic; }}
  html[data-theme="dark"] .empty {{ color: #8b949e; }}
  html[data-theme="light"] .empty {{ color: #656d76; }}
</style>
</head>
<body>
<header>
  <h1>cc-session-logs</h1>
  <button class="theme-toggle" onclick="toggleTheme()" title="Toggle light/dark mode">&#9788;</button>
</header>
{entries}
<script>
  function setTheme(theme) {{
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('cc-theme', theme);
    document.querySelector('.theme-toggle').textContent = theme === 'dark' ? '\u263c' : '\u263d';
  }}
  function toggleTheme() {{
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  }}
  setTheme(localStorage.getItem('cc-theme') || 'dark');
  document.querySelectorAll('.session').forEach(function(el) {{
    el.addEventListener('click', function(e) {{
      if (e.target.tagName === 'A') return;
      window.location = el.dataset.href;
    }});
  }});
</script>
</body>
</html>
"""


def parse_log_name(filename):
    """Extract metadata from a log filename. Returns None if name doesn't match."""
    name = filename.replace(".md", "")
    m = LOG_NAME_RE.match(name)
    if not m:
        return None
    time_part = m.group(2)
    return {
        "raw": name,
        "date": m.group(1),
        "time": f"{time_part[:2]}:{time_part[2:]}",
        "session": m.group(3),
        "agent_type": m.group(4),
        "agent_id": m.group(5),
    }


def read_label(filepath):
    """Read the first line of a log file and extract an optional label."""
    try:
        with open(filepath, "r") as f:
            first_line = f.readline().rstrip()
        m = LABEL_RE.match(first_line)
        return m.group(1).strip() if m else None
    except (OSError, UnicodeDecodeError):
        return None


def build_index(log_dir):
    """Build the index HTML page."""
    try:
        files = [f for f in os.listdir(log_dir)
                 if f.endswith(".md") and not f.startswith(".")]
    except FileNotFoundError:
        files = []

    # Filter to only well-formed filenames
    entries = []
    for f in files:
        meta = parse_log_name(f)
        if meta is not None:
            entries.append((f, meta))

    entries.sort(key=lambda x: x[0], reverse=True)

    if not entries:
        html_entries = '<p class="empty">No session logs found.</p>'
    else:
        parts = []
        for f, meta in entries:
            date_time = f'{meta["date"]} {meta["time"]}'
            label_text = f'{date_time} &mdash; {meta["session"]}'
            if meta["agent_type"]:
                label_text += (f'<span class="subagent">'
                               f'{meta["agent_type"]} {meta["agent_id"] or ""}'
                               f'</span>')

            # Check for label in file header
            file_label = read_label(os.path.join(log_dir, f))
            if file_label:
                label_text += (f'<span class="label">'
                               f'{html.escape(file_label)}'
                               f'</span>')

            slug = f.replace(".md", "")
            parts.append(
                f'<div class="session" data-href="/{slug}">'
                f'  <span class="session-name">'
                f'<a class="row-link" href="/{slug}">{label_text}</a>'
                f'</span>'
                f'  <span class="formats">'
                f'    <a href="/{slug}">html</a>'
                f'    <a href="/{f}">md</a>'
                f'  </span>'
                f'</div>'
            )
        html_entries = "\n".join(parts)

    return INDEX_TEMPLATE.format(entries=html_entries)


class LogHandler(BaseHTTPRequestHandler):
    """HTTP(S) request handler for session logs."""

    log_dir = DEFAULT_DIR

    def do_GET(self):
        path = unquote(self.path).lstrip("/")

        # Index
        if not path:
            body = build_index(self.log_dir)
            self._respond(200, body, "text/html")
            return

        # Raw markdown: /filename.md
        if path.endswith(".md"):
            file_path = os.path.join(self.log_dir, os.path.basename(path))
            if os.path.isfile(file_path):
                with open(file_path, "r") as f:
                    content = f.read()
                self._respond(200, content, "text/plain; charset=utf-8")
            else:
                self._respond(404, "Not found", "text/plain")
            return

        # Rendered HTML: /filename (no .md)
        md_file = os.path.join(self.log_dir, os.path.basename(path) + ".md")
        if os.path.isfile(md_file):
            with open(md_file, "r") as f:
                content = f.read()
            title = os.path.basename(path)
            body = HTML_TEMPLATE.format(
                title=html.escape(title),
                content=html.escape(content),
            )
            self._respond(200, body, "text/html")
            return

        self._respond(404, "Not found", "text/plain")

    def _respond(self, code, body, content_type):
        encoded = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"  {args[0]} {args[1]}\n")


def ensure_cert(cert_dir):
    """Ensure a self-signed cert exists, generating one if needed.

    Returns (cert_path, key_path) or raises SystemExit on failure.
    """
    cert_path = os.path.join(cert_dir, CERT_FILE)
    key_path = os.path.join(cert_dir, KEY_FILE)

    if os.path.isfile(cert_path) and os.path.isfile(key_path):
        return cert_path, key_path

    # Try to generate with openssl
    if not shutil.which("openssl"):
        print("  [ERROR] No TLS certificate found and openssl is not installed.")
        print(f"  Either install openssl, provide --cert and --key, or use --http.")
        sys.exit(1)

    os.makedirs(cert_dir, exist_ok=True)
    print(f"  Generating self-signed certificate in {cert_dir}/", flush=True)

    try:
        subprocess.run(
            [
                "openssl", "req", "-x509",
                "-newkey", "rsa:2048",
                "-keyout", key_path,
                "-out", cert_path,
                "-days", "365",
                "-nodes",
                "-subj", "/CN=localhost",
            ],
            capture_output=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"  [ERROR] Failed to generate certificate: {e.stderr.decode()}")
        sys.exit(1)

    return cert_path, key_path


def main():
    parser = argparse.ArgumentParser(
        description="Serve session logs over HTTPS.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--dir", default=DEFAULT_DIR,
                        help="Log directory (default: .claude/logs)")
    parser.add_argument("--http", action="store_true", dest="use_http",
                        help="Use plain HTTP instead of HTTPS")
    parser.add_argument("--cert", default=None,
                        help="Path to TLS certificate file")
    parser.add_argument("--key", default=None,
                        help="Path to TLS private key file")
    args = parser.parse_args()

    os.makedirs(args.dir, exist_ok=True)

    LogHandler.log_dir = args.dir

    server = HTTPServer((args.host, args.port), LogHandler)

    protocol = "http"
    if not args.use_http:
        # Set up HTTPS
        if args.cert and args.key:
            cert_path, key_path = args.cert, args.key
        else:
            cert_path, key_path = ensure_cert(DEFAULT_CERT_DIR)

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        protocol = "https"

    host_display = "localhost" if args.host == "127.0.0.1" else args.host
    url = f"{protocol}://{host_display}:{args.port}"

    print(flush=True)
    print(f"  Serving session logs at {url}", flush=True)
    print(f"  Log directory: {args.dir}", flush=True)
    print(f"  Press Ctrl+C to stop.", flush=True)
    print(flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
