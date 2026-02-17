# claude-session-logger

Automatically converts Claude Code JSONL transcripts into readable markdown logs after every turn. Hooks into Claude Code's `Stop` and `SubagentStop` lifecycle events — no manual effort required.

## Install

Clone this repo, then run the installer from your project directory:

**Linux / macOS / WSL:**

```bash
cd your-project
bash /path/to/claude-session-logger/install.sh
```

**Windows (PowerShell):**

```powershell
cd your-project
powershell -ExecutionPolicy Bypass -File \path\to\claude-session-logger\install.ps1
```

The installer will:
- Copy hook scripts to `.claude/hooks/`
- Merge hook config into `.claude/settings.json`
- Prompt for your timezone

Restart Claude Code after installing.

### Requirements

- **python3** — runs the JSONL→markdown converter and settings merge
- **jq** — used at runtime by the hook scripts to parse JSON input
- **bash** — hook scripts run in bash (Git Bash or WSL on Windows)

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

Set during installation. To change later, edit the `TZ` line in both `.claude/hooks/stop-log.sh` and `.claude/hooks/subagent-stop-log.sh`:

```bash
export TZ="${TZ:-America/New_York}"
```

### Log directory

Logs write to `.claude/logs/` relative to the project root. This is not configurable without editing the hook scripts.

## Uninstall

```bash
rm .claude/hooks/stop-log.sh .claude/hooks/subagent-stop-log.sh .claude/hooks/log-converter.py
```

Then remove the `Stop` and `SubagentStop` entries from `.claude/settings.json`.

## License

MIT
