# cc-session-logger

Automatically converts Claude Code JSONL transcripts into readable markdown logs after every turn. Hooks into Claude Code's `Stop` and `SubagentStop` lifecycle events — no manual effort required.

## Install

Clone this repo, then run the installer from your project directory. Pick whichever runtime you prefer:

**Python:**

```
cd your-project
python3 /path/to/cc-session-logger/install.py
```

**Node.js:**

```
cd your-project
node /path/to/cc-session-logger/install.js
```

Both installers:
- Copy hook scripts to `.claude/hooks/`
- Copy serve script to `.claude/serve-sessions.{py,js}`
- Merge hook config into `.claude/settings.json`
- Prompt for your timezone

Restart Claude Code after installing.

### Requirements

One of:
- **python3** (3.9+)
- **node** (18+)

## Output

Logs appear in `.claude/logs/` with chronologically sortable filenames:

```
.claude/logs/2026-02-16-1856-3183b382.md
.claude/logs/2026-02-16-1856-3183b382-subagent-general-purpose-a46cc27f.md
```

Format: `{date}-{HHMM}-{session}[-subagent-{type}-{agent}].md`

Each log starts with a header:

```markdown
# Session `3183b382` — 2026-02-16 18:56

---
```

The body renders user prompts, assistant responses, tool calls with results, and edit diffs. Long tool results collapse into `<details>` blocks.

## Configuration

### Timezone

Set during installation. To change later, edit the `TZ` line in both hook scripts in `.claude/hooks/`:

Python: `stop-log.py` and `subagent-stop-log.py`
```python
TZ = os.environ.get("TZ", "America/New_York")
```

Node.js: `stop-log.js` and `subagent-stop-log.js`
```javascript
const TZ = process.env.TZ || "America/New_York";
```

### Log directory

Logs write to `.claude/logs/` relative to the project root.

## Serve

Browse and share your session logs over HTTPS. The serve script is copied into your project during installation. Start from your project root:

**Python:**

```
python3 .claude/serve-sessions.py
```

**Node.js:**

```
node .claude/serve-sessions.js
```

HTTPS is enabled by default with an auto-generated self-signed certificate (requires `openssl`). Certs are stored in `.claude/certs/`.

Options:

```
--port 8443          # default: 9443
--host 0.0.0.0       # default: 127.0.0.1 (localhost only)
--dir .claude/logs   # default: .claude/logs
--http               # use plain HTTP instead of HTTPS
--cert path/to.pem   # custom TLS certificate
--key path/to-key.pem # custom TLS private key
```

Routes:
- `/` — index of all sessions (with optional labels)
- `/{name}` — rendered HTML (for humans)
- `/{name}.md` — raw markdown (for machines / another Claude via WebFetch)

### Session labels

Add a label to any session by appending it to the header line:

```markdown
# Session `abc12345` — 2026-02-17 09:30 — Auth Feature
```

The label ("Auth Feature") will appear in the index alongside the session entry.

## Tests

Run the full test suite (requires both python3 and node):

```
cd /path/to/cc-session-logger
./tests/run_tests.sh
```

Run individual test modules:

```
python3 tests/test_converter.py     # converter (JSONL → markdown)
python3 tests/test_hooks.py         # hook scripts (stop-log, subagent-stop-log)
python3 tests/test_installer.py     # installers (install.py, install.js)
```

Test a single runtime:

```
python3 tests/test_converter.py --py-only
python3 tests/test_converter.py --js-only
```

Verbose output:

```
python3 tests/test_converter.py -v
```

## Uninstall

Remove the hook scripts from `.claude/hooks/`, the serve script from `.claude/serve-sessions.*`, and the `Stop` and `SubagentStop` entries from `.claude/settings.json`.

## License

MIT
