"""Session logger hook for subagents. Runs on the SubagentStop event.

Parallel to stop-log.py but reads subagent-specific fields. Exits 0 always.
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = os.environ.get("TZ", "__TZ__")


def main():
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    transcript_path = hook_input.get("agent_transcript_path", "")
    session_id = hook_input.get("session_id", "unknown")
    agent_id = hook_input.get("agent_id", "unknown")
    agent_type = hook_input.get("agent_type", "subagent")

    if not transcript_path or not os.path.isfile(transcript_path):
        return

    # Wait for transcript to finish flushing (file size stabilizes)
    prev_size = -1
    for _ in range(10):
        try:
            curr_size = os.path.getsize(transcript_path)
        except OSError:
            curr_size = 0
        if curr_size == prev_size:
            break
        prev_size = curr_size
        time.sleep(0.2)

    # Extract start timestamp from first record that has one
    start_ts = None
    try:
        with open(transcript_path, "r") as f:
            for line in f:
                try:
                    ts = json.loads(line).get("timestamp")
                    if ts:
                        start_ts = ts
                        break
                except (json.JSONDecodeError, AttributeError):
                    continue
    except OSError:
        pass

    # Convert UTC timestamp to local time
    if start_ts:
        try:
            m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})", start_ts)
            if m:
                utc_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
                local_dt = utc_dt.astimezone(ZoneInfo(TZ))
                date_str = local_dt.strftime("%Y-%m-%d")
                time_part = local_dt.strftime("%H%M")
                local_ts = local_dt.isoformat()
            else:
                raise ValueError("no match")
        except Exception:
            date_str = datetime.now().strftime("%Y-%m-%d")
            time_part = "0000"
            local_ts = start_ts or ""
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_part = "0000"
        local_ts = ""

    os.makedirs(".claude/logs", exist_ok=True)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    short_session = session_id[:8]
    short_agent = agent_id[:8]
    log_file = f".claude/logs/{date_str}-{time_part}-{short_session}-subagent-{agent_type}-{short_agent}.md"
    error_log = ".claude/logs/.converter-errors.log"

    with open(error_log, "a") as err_f:
        subprocess.run(
            [
                sys.executable, os.path.join(script_dir, "log-converter.py"),
                "--transcript", transcript_path,
                "--output", log_file,
                "--session-id", session_id,
                "--date", date_str,
                "--start-time", local_ts,
                "--agent-type", agent_type,
                "--agent-id", agent_id,
            ],
            stdout=subprocess.DEVNULL,
            stderr=err_f,
        )

    # Remove error log if empty — its presence is the signal
    try:
        if os.path.isfile(error_log) and os.path.getsize(error_log) == 0:
            os.remove(error_log)
    except OSError:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
