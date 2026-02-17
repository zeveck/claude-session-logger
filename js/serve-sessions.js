#!/usr/bin/env node
/**
 * Serve session logs over HTTPS.
 *
 * Serves .claude/logs/ as browsable, shareable session threads.
 * Raw markdown for machines (another Claude via WebFetch), rendered HTML for humans.
 * HTTPS with auto-generated self-signed cert by default.
 *
 * Usage:
 *   node serve-sessions.js                      # HTTPS on localhost:9443
 *   node serve-sessions.js --http               # plain HTTP
 *   node serve-sessions.js --port 8443          # custom port
 *   node serve-sessions.js --host 0.0.0.0       # expose to network
 *   node serve-sessions.js --cert C --key K     # custom cert
 *   node serve-sessions.js --dir .claude/logs   # custom log directory
 */

const http = require("http");
const https = require("https");
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const DEFAULT_PORT = 9443;
const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_DIR = path.join(".claude", "logs");
const DEFAULT_CERT_DIR = path.join(".claude", "certs");
const CERT_FILE = "localhost.pem";
const KEY_FILE = "localhost-key.pem";

// Strict filename pattern: YYYY-MM-DD-HHMM-{session}[-subagent-{type}-{agent}]
const LOG_NAME_RE =
  /^(\d{4}-\d{2}-\d{2})-(\d{4})-(\w+?)(?:-subagent-(.+)-(\w+))?$/;

// Label regex for first line of log
const LABEL_RE =
  /^#\s+(?:Session|Subagent:\s+\S+)\s+.+?\u2014\s+\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?\s*\u2014\s+(.+)$/;

const HTML_TEMPLATE = `<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TITLE</title>
<link id="md-css" rel="stylesheet" href="https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown-dark.min.css">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"><\/script>
<style>
  html[data-theme="dark"] body {
    background: #0d1117;
    color: #e6edf3;
  }
  html[data-theme="light"] body {
    background: #ffffff;
    color: #1f2328;
  }
  body {
    max-width: 960px;
    margin: 0 auto;
    padding: 2rem 1rem;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    transition: background 0.2s, color 0.2s;
  }
  .markdown-body {
    background: transparent;
  }
  html[data-theme="dark"] .markdown-body pre,
  html[data-theme="dark"] .markdown-body code {
    background: #161b22;
  }
  nav {
    margin-bottom: 1.5rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  nav a { color: #58a6ff; text-decoration: none; }
  nav a:hover { text-decoration: underline; }
  .theme-toggle {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 1.2rem;
    padding: 0.2rem;
    line-height: 1;
  }
  #content { display: none; }
</style>
</head>
<body>
<nav>
  <a href="/">&larr; All sessions</a>
  <button class="theme-toggle" onclick="toggleTheme()" title="Toggle light/dark mode">&#9788;</button>
</nav>
<div id="raw" class="markdown-body"></div>
<pre id="content">CONTENT</pre>
<script>
  const md = document.getElementById('content').textContent;
  document.getElementById('raw').innerHTML = marked.parse(md);
  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('cc-theme', theme);
    document.querySelector('.theme-toggle').textContent = theme === 'dark' ? '\u263c' : '\u263d';
    var css = document.getElementById('md-css');
    css.href = theme === 'dark'
      ? 'https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown-dark.min.css'
      : 'https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown-light.min.css';
  }
  function toggleTheme() {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  }
  setTheme(localStorage.getItem('cc-theme') || 'dark');
<\/script>
</body>
</html>`;

const INDEX_TEMPLATE = `<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>cc-session-logs</title>
<style>
  html[data-theme="dark"] body {
    background: #0d1117;
    color: #e6edf3;
  }
  html[data-theme="light"] body {
    background: #ffffff;
    color: #1f2328;
  }
  body {
    max-width: 960px;
    margin: 0 auto;
    padding: 2rem 1rem;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    transition: background 0.2s, color 0.2s;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 0.5rem;
  }
  html[data-theme="dark"] header { border-bottom: 1px solid #30363d; }
  html[data-theme="light"] header { border-bottom: 1px solid #d0d7de; }
  h1 { margin: 0; }
  .theme-toggle {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 1.2rem;
    padding: 0.2rem;
    line-height: 1;
  }
  a { color: #58a6ff; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .session {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem 0.5rem;
    cursor: pointer;
    border-radius: 6px;
    transition: background 0.15s;
  }
  html[data-theme="dark"] .session { border-bottom: 1px solid #21262d; }
  html[data-theme="light"] .session { border-bottom: 1px solid #d0d7de; }
  html[data-theme="dark"] .session:hover { background: #161b22; }
  html[data-theme="light"] .session:hover { background: #f6f8fa; }
  .session-name {
    font-family: monospace;
    font-size: 0.95rem;
  }
  .session a.row-link {
    color: inherit;
    text-decoration: none;
  }
  .formats { font-size: 0.8rem; opacity: 0.6; }
  .formats a { margin-left: 0.75rem; }
  .subagent { opacity: 0.7; font-size: 0.85rem; margin-left: 0.5rem; }
  .label { margin-left: 0.75rem; font-style: italic; }
  html[data-theme="dark"] .label { color: #8b949e; }
  html[data-theme="light"] .label { color: #656d76; }
  .empty { font-style: italic; }
  html[data-theme="dark"] .empty { color: #8b949e; }
  html[data-theme="light"] .empty { color: #656d76; }
</style>
</head>
<body>
<header>
  <h1>cc-session-logs</h1>
  <button class="theme-toggle" onclick="toggleTheme()" title="Toggle light/dark mode">&#9788;</button>
</header>
ENTRIES
<script>
  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('cc-theme', theme);
    document.querySelector('.theme-toggle').textContent = theme === 'dark' ? '\u263c' : '\u263d';
  }
  function toggleTheme() {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  }
  setTheme(localStorage.getItem('cc-theme') || 'dark');
  document.querySelectorAll('.session').forEach(function(el) {
    el.addEventListener('click', function(e) {
      if (e.target.tagName === 'A') return;
      window.location = el.dataset.href;
    });
  });
<\/script>
</body>
</html>`;

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function parseLogName(filename) {
  const name = filename.replace(".md", "");
  const m = name.match(LOG_NAME_RE);
  if (!m) return null;
  const timePart = m[2];
  return {
    raw: name,
    date: m[1],
    time: `${timePart.slice(0, 2)}:${timePart.slice(2)}`,
    session: m[3],
    agentType: m[4] || null,
    agentId: m[5] || null,
  };
}

function readLabel(filepath) {
  try {
    const content = fs.readFileSync(filepath, "utf-8");
    const firstLine = content.split("\n")[0];
    const m = firstLine.match(LABEL_RE);
    return m ? m[1].trim() : null;
  } catch {
    return null;
  }
}

function buildIndex(logDir) {
  let files;
  try {
    files = fs
      .readdirSync(logDir)
      .filter((f) => f.endsWith(".md") && !f.startsWith("."));
  } catch {
    files = [];
  }

  // Filter to only well-formed filenames
  const entries = [];
  for (const f of files) {
    const meta = parseLogName(f);
    if (meta !== null) {
      entries.push([f, meta]);
    }
  }

  entries.sort((a, b) => b[0].localeCompare(a[0]));

  if (!entries.length) {
    return INDEX_TEMPLATE.replace(
      "ENTRIES",
      '<p class="empty">No session logs found.</p>'
    );
  }

  const parts = entries.map(([f, meta]) => {
    const dateTime = `${meta.date} ${meta.time}`;
    let label = `${dateTime} &mdash; ${meta.session}`;
    if (meta.agentType) {
      label += `<span class="subagent">${meta.agentType} ${meta.agentId || ""}</span>`;
    }

    const fileLabel = readLabel(path.join(logDir, f));
    if (fileLabel) {
      label += `<span class="label">${escapeHtml(fileLabel)}</span>`;
    }

    const slug = f.replace(".md", "");
    return (
      `<div class="session" data-href="/${slug}">` +
      `  <span class="session-name">` +
      `<a class="row-link" href="/${slug}">${label}</a>` +
      `</span>` +
      `  <span class="formats">` +
      `    <a href="/${slug}">html</a>` +
      `    <a href="/${f}">md</a>` +
      `  </span>` +
      `</div>`
    );
  });

  return INDEX_TEMPLATE.replace("ENTRIES", parts.join("\n"));
}

function findOpenssl() {
  try {
    execSync("which openssl", { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

function ensureCert(certDir) {
  const certPath = path.join(certDir, CERT_FILE);
  const keyPath = path.join(certDir, KEY_FILE);

  if (fs.existsSync(certPath) && fs.existsSync(keyPath)) {
    return { certPath, keyPath };
  }

  if (!findOpenssl()) {
    console.error(
      "  [ERROR] No TLS certificate found and openssl is not installed."
    );
    console.error(
      "  Either install openssl, provide --cert and --key, or use --http."
    );
    process.exit(1);
  }

  fs.mkdirSync(certDir, { recursive: true });
  console.log(`  Generating self-signed certificate in ${certDir}/`);

  try {
    execSync(
      `openssl req -x509 -newkey rsa:2048 -keyout "${keyPath}" -out "${certPath}" -days 365 -nodes -subj "/CN=localhost"`,
      { stdio: "pipe" }
    );
  } catch (e) {
    console.error(`  [ERROR] Failed to generate certificate: ${e.message}`);
    process.exit(1);
  }

  return { certPath, keyPath };
}

function parseArgs(argv) {
  const args = {
    port: DEFAULT_PORT,
    host: DEFAULT_HOST,
    dir: DEFAULT_DIR,
    useHttp: false,
    cert: null,
    key: null,
  };
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === "--port" && argv[i + 1]) {
      args.port = parseInt(argv[++i], 10);
    } else if (argv[i] === "--host" && argv[i + 1]) {
      args.host = argv[++i];
    } else if (argv[i] === "--dir" && argv[i + 1]) {
      args.dir = argv[++i];
    } else if (argv[i] === "--http") {
      args.useHttp = true;
    } else if (argv[i] === "--cert" && argv[i + 1]) {
      args.cert = argv[++i];
    } else if (argv[i] === "--key" && argv[i + 1]) {
      args.key = argv[++i];
    }
  }
  return args;
}

function main() {
  const args = parseArgs(process.argv);

  fs.mkdirSync(args.dir, { recursive: true });

  function handler(req, res) {
    const urlPath = decodeURIComponent(req.url || "/").replace(/^\/+/, "");

    function respond(code, body, contentType) {
      const buf = Buffer.from(body, "utf-8");
      res.writeHead(code, {
        "Content-Type": contentType,
        "Content-Length": buf.length,
        "Access-Control-Allow-Origin": "*",
      });
      res.end(buf);
    }

    // Index
    if (!urlPath) {
      respond(200, buildIndex(args.dir), "text/html");
      return;
    }

    // Raw markdown: /filename.md
    if (urlPath.endsWith(".md")) {
      const filePath = path.join(args.dir, path.basename(urlPath));
      try {
        const content = fs.readFileSync(filePath, "utf-8");
        respond(200, content, "text/plain; charset=utf-8");
      } catch {
        respond(404, "Not found", "text/plain");
      }
      return;
    }

    // Rendered HTML: /filename (no .md)
    const mdFile = path.join(args.dir, path.basename(urlPath) + ".md");
    try {
      const content = fs.readFileSync(mdFile, "utf-8");
      const title = escapeHtml(path.basename(urlPath));
      const body = HTML_TEMPLATE.replace("TITLE", title).replace(
        "CONTENT",
        escapeHtml(content)
      );
      respond(200, body, "text/html");
    } catch {
      respond(404, "Not found", "text/plain");
    }
  }

  let server;
  let protocol;

  if (args.useHttp) {
    server = http.createServer(handler);
    protocol = "http";
  } else {
    let certPath, keyPath;
    if (args.cert && args.key) {
      certPath = args.cert;
      keyPath = args.key;
    } else {
      const result = ensureCert(DEFAULT_CERT_DIR);
      certPath = result.certPath;
      keyPath = result.keyPath;
    }

    const options = {
      key: fs.readFileSync(keyPath),
      cert: fs.readFileSync(certPath),
    };
    server = https.createServer(options, handler);
    protocol = "https";
  }

  server.listen(args.port, args.host, () => {
    const hostDisplay = args.host === "127.0.0.1" ? "localhost" : args.host;
    const url = `${protocol}://${hostDisplay}:${args.port}`;
    console.log();
    console.log(`  Serving session logs at ${url}`);
    console.log(`  Log directory: ${args.dir}`);
    console.log("  Press Ctrl+C to stop.");
    console.log();
  });
}

main();
