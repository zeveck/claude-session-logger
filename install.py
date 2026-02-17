"""claude-session-logger installer.

Copies hook scripts to .claude/hooks/ and merges config into .claude/settings.json.

Usage:
    python3 install.py
"""

import json
import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.join(".claude", "hooks")
SETTINGS_FILE = os.path.join(".claude", "settings.json")

HOOK_SCRIPTS = ["stop-log.py", "subagent-stop-log.py", "log-converter.py"]

HOOKS_CONFIG = {
    "Stop": [{"hooks": [{"type": "command", "command": "python3 .claude/hooks/stop-log.py"}]}],
    "SubagentStop": [{"hooks": [{"type": "command", "command": "python3 .claude/hooks/subagent-stop-log.py"}]}],
}


def info(msg):
    print(f"  {msg}")


def error(msg):
    print(f"  [ERROR] {msg}", file=sys.stderr)
    sys.exit(1)


def prompt(question, default=""):
    hint = f" [{default}]" if default else ""
    answer = input(f"  {question}{hint}: ").strip()
    return answer or default


def prompt_yn(question, default="n"):
    hint = "[Y/n]" if default == "y" else "[y/N]"
    answer = input(f"  {question} {hint} ").strip().lower()
    answer = answer or default
    return answer.startswith("y")


def main():
    print()
    print("claude-session-logger installer")
    print("================================")
    print()

    # --- Preflight checks ---

    if not os.path.isdir(".git"):
        error("Not in a git project root. Run this from your project directory.")

    # --- Timezone ---

    print("Timezone for log timestamps (e.g. America/New_York, America/Chicago, UTC)")
    tz_value = prompt("TZ", "America/New_York")
    print()

    # --- Check for existing installation ---

    if os.path.isfile(os.path.join(HOOKS_DIR, "stop-log.py")):
        if not prompt_yn("Hooks already installed. Overwrite?"):
            print()
            info("Aborted.")
            return
        print()

    # --- Copy scripts ---

    os.makedirs(HOOKS_DIR, exist_ok=True)

    for script in HOOK_SCRIPTS:
        src = os.path.join(SCRIPT_DIR, script)
        dst = os.path.join(HOOKS_DIR, script)

        with open(src, "r") as f:
            content = f.read()

        content = content.replace("__TZ__", tz_value)

        with open(dst, "w") as f:
            f.write(content)

    info(f"Installed scripts to {HOOKS_DIR}/")

    # --- Merge settings ---

    os.makedirs(".claude", exist_ok=True)

    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        settings = {}

    existing_hooks = settings.get("hooks", {})
    existing_hooks.update(HOOKS_CONFIG)
    settings["hooks"] = existing_hooks

    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")

    info(f"Updated {SETTINGS_FILE}")

    # --- Done ---

    print()
    print("Done! Session logs will appear in .claude/logs/ after each turn.")
    print("Restart Claude Code to pick up the new hooks.")
    print()


if __name__ == "__main__":
    main()
