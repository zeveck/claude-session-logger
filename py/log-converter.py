#!/usr/bin/env python3
"""
Converts Claude Code JSONL transcripts into clean, readable markdown conversation logs.

Usage:
    python log-converter.py --transcript PATH --output PATH

Reads a Claude Code JSONL transcript file and produces a markdown document
that mirrors the Claude Code chat UI as closely as possible.
"""

import argparse
import difflib
import json
import os
import re
import sys


# JSONL line types to skip entirely
SKIP_TYPES = frozenset({
    "file-history-snapshot",
    "queue-operation",
    "progress",
    "system",
})

# Max lines for inline result display (longer gets collapsed)
INLINE_RESULT_MAX_LINES = 4


def parse_jsonl(transcript_path):
    """Parse JSONL file. Returns list of records."""
    records = []
    try:
        with open(transcript_path, "r") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    records.append(json.loads(raw_line))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        print(f"Error: Transcript file not found: {transcript_path}", file=sys.stderr)
        sys.exit(1)
    return records


def should_skip(record):
    """Return True if this record should be skipped entirely."""
    if record.get("type", "") in SKIP_TYPES:
        return True
    if record.get("isMeta"):
        return True
    return False


def group_assistant_records(records):
    """
    Group consecutive assistant records that share the same message.id
    into a single logical response. Also preserves user records and
    interleaves them properly.

    Returns a list of items, each being either:
      - ("user", text, timestamp)
      - ("assistant", [content_blocks], timestamp)
    """
    items = []
    assistant_groups = {}  # msg_id -> {"blocks": [], "timestamp": str}
    assistant_order = []  # list of msg_ids in order of first appearance

    for record in records:
        if should_skip(record):
            continue

        rtype = record.get("type", "")
        msg = record.get("message", {})
        if not isinstance(msg, dict):
            continue

        timestamp = record.get("timestamp", "")

        if rtype == "user":
            # Flush any pending assistant groups before this user message
            for mid in assistant_order:
                grp = assistant_groups[mid]
                items.append(("assistant", grp["blocks"], grp["timestamp"]))
            assistant_groups.clear()
            assistant_order.clear()

            content = msg.get("content", "")
            role = msg.get("role", "")

            if role == "user":
                if isinstance(content, str):
                    text = content.strip()
                    if text:
                        items.append(("user", text, timestamp))
                elif isinstance(content, list):
                    text_parts = []
                    tool_results = []
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type", "")
                        if btype == "text":
                            t = block.get("text", "").strip()
                            if t:
                                text_parts.append(t)
                        elif btype == "tool_result":
                            tool_results.append(block)

                    if text_parts:
                        items.append(("user", "\n".join(text_parts), timestamp))
                    for tr in tool_results:
                        items.append(("tool_result", tr, timestamp))

        elif rtype == "assistant":
            msg_id = msg.get("id", "")
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue

            if msg_id and msg_id in assistant_groups:
                assistant_groups[msg_id]["blocks"].extend(content)
            else:
                key = msg_id or id(record)
                assistant_groups[key] = {
                    "blocks": list(content),
                    "timestamp": timestamp,
                }
                assistant_order.append(key)

    # Flush remaining assistant groups
    for mid in assistant_order:
        grp = assistant_groups[mid]
        items.append(("assistant", grp["blocks"], grp["timestamp"]))

    return items


def _clean_result_text(text):
    """Strip internal XML tags like <tool_use_error> from result text."""
    text = re.sub(r'</?tool_use_error>', '', text)
    return text.strip()


def _escape_html(text):
    """Escape HTML entities for use inside HTML tags."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _unescape_html(text):
    """Unescape HTML entities back to literal characters for markdown output."""
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _truncate(text, max_len):
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _tool_header(name, inp):
    """
    Format a one-line tool call header matching the chat UI style.
    Returns a markdown string safe for rendering.
    """
    if not isinstance(inp, dict):
        return f"● {name}"

    if name == "Bash":
        cmd = inp.get("command", "").split("\n")[0]
        return f"● `Bash({_truncate(cmd, 120)})`"

    if name == "Read":
        path = inp.get("file_path", "")
        return f"● `Read({path})`"

    if name == "Write":
        path = inp.get("file_path", "")
        return f"● `Write({path})`"

    if name == "Edit":
        path = inp.get("file_path", "")
        return f"● `Update({path})`"

    if name == "Glob":
        pattern = inp.get("pattern", "")
        return f"● `Glob({pattern})`"

    if name == "Grep":
        pattern = inp.get("pattern", "")
        if pattern:
            return f"● Searched for `{_truncate(pattern, 80)}`"
        return "● Searched codebase"

    if name == "WebFetch":
        url = inp.get("url", "")
        return f"● `WebFetch({_truncate(url, 100)})`"

    if name == "WebSearch":
        query = inp.get("query", "")
        return f"● `WebSearch({query})`"

    if name == "Task":
        desc = inp.get("description", "")
        agent = inp.get("subagent_type", "")
        if agent:
            return f"● `Task({agent}: {_truncate(desc, 100)})`"
        return f"● `Task({_truncate(desc, 100)})`"

    # Generic fallback
    return f"● {name}"


def format_tool_result_content(content):
    """Extract text from a tool_result content field."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "image":
                    parts.append("[image]")
                else:
                    parts.append(str(block))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content) if content else ""


def _render_result_inline(lines, content, is_error=False):
    """Render a short tool result as indented lines under the tool header."""
    result_lines = content.split("\n")
    prefix = "  ⎿  **Error:** " if is_error else "  ⎿  "
    cont_prefix = "     "
    for i, rline in enumerate(result_lines):
        lines.append(f"{prefix}{rline}" if i == 0 else f"{cont_prefix}{rline}")
    lines.append("")


def _render_result_collapsed(lines, content, summary_text, is_error=False):
    """Render a long tool result as a collapsible <details> block."""
    if is_error:
        summary_text = f"<b>Error:</b> {summary_text}"
    lines.append(f"<details>")
    lines.append(f"<summary>{summary_text}</summary>")
    lines.append(f"<pre><code>{_escape_html(content)}</code></pre>")
    lines.append(f"</details>")
    lines.append("<br>")
    lines.append("")


def _render_tool_with_result(lines, header, result_content, is_error=False):
    """
    Render a tool call header paired with its result.
    Short results: header on one line, ⎿ result below.
    Long results: <details> block with header as the summary (no standalone header).
    """
    content = _clean_result_text(result_content) if result_content else ""

    if not content:
        # No result — just the header
        lines.append(header)
        lines.append("")
        return

    result_lines = content.split("\n")

    if len(result_lines) <= INLINE_RESULT_MAX_LINES:
        lines.append(header)
        _render_result_inline(lines, content, is_error)
    else:
        # Collapsed: <details><summary> IS the header — no standalone line
        summary = _escape_html(header)
        _render_result_collapsed(lines, content, summary, is_error)


def render_markdown(items):
    """
    Render grouped items into clean markdown conversation text.

    Uses a two-pass approach: first collects tool results by tool_use_id,
    then renders each tool_use paired with its result. This ensures each
    tool call is visually grouped with its result, even for parallel calls.
    """
    lines = []

    # First pass: collect tool results keyed by tool_use_id
    tool_results_map = {}  # tool_use_id -> (content_str, is_error)
    for item in items:
        if item[0] == "tool_result":
            tr = item[1]
            content = format_tool_result_content(tr.get("content", ""))
            content = content.strip()
            tid = tr.get("tool_use_id", "")
            if tid:
                tool_results_map[tid] = (content, tr.get("is_error", False))

    # Second pass: render
    for item in items:
        kind = item[0]

        if kind == "user":
            text = item[1]

            # Context continuation summary — collapse behind a heading
            if text.startswith(
                "This session is being continued from a previous"
            ):
                lines.append(
                    "**Context restored from previous session "
                    "(ran out of context):**"
                )
                quoted = "\n".join(
                    f"> {line}" for line in text.split("\n")
                )
                lines.append("<details>")
                lines.append("<summary>Session summary</summary>")
                lines.append("")
                lines.append(quoted)
                lines.append("")
                lines.append("</details>")
                lines.append("<br>")
                lines.append("")
            else:
                quoted = "\n".join(
                    f"> {line}" for line in text.split("\n")
                )
                lines.append(f"**User:**\n{quoted}")
                lines.append("")

        elif kind == "tool_result":
            # Already paired with tool_use in the second pass
            continue

        elif kind == "assistant":
            blocks = item[1]
            for block in blocks:
                if not isinstance(block, dict):
                    continue

                btype = block.get("type", "")

                if btype == "thinking":
                    continue

                elif btype == "text":
                    text = _unescape_html(block.get("text", "").strip())
                    if not text:
                        continue
                    if lines and lines[-1] != "":
                        lines.append("")
                    lines.append(text)
                    lines.append("")

                elif btype == "tool_use":
                    tool_name = block.get("name", "unknown")
                    tool_input = block.get("input", {})
                    header = _tool_header(tool_name, tool_input)
                    tool_id = block.get("id", "")

                    # Look up the result for this tool call
                    result = tool_results_map.get(tool_id)
                    result_content = result[0] if result else ""
                    result_is_error = result[1] if result else False

                    # Edit tool: always show header + diff, then inline result
                    if tool_name == "Edit":
                        lines.append(header)
                        old = tool_input.get("old_string", "")
                        new = tool_input.get("new_string", "")
                        if old or new:
                            diff_lines = list(difflib.unified_diff(
                                old.splitlines(),
                                new.splitlines(),
                                lineterm="",
                                n=2,
                            ))
                            diff_body = [l for l in diff_lines
                                         if not l.startswith(("---", "+++"))]
                            if diff_body:
                                lines.append("```diff")
                                lines.extend(diff_body)
                                lines.append("```")
                        if result_content:
                            result_content = _clean_result_text(result_content)
                            _render_result_inline(lines, result_content,
                                                  result_is_error)
                        else:
                            lines.append("")
                    else:
                        # All other tools: header paired with result
                        _render_tool_with_result(lines, header,
                                                 result_content,
                                                 result_is_error)

            # Ensure blank line after assistant block
            if lines and lines[-1] != "":
                lines.append("")

    return "\n".join(lines)


def render_header(session_id=None, date_str=None, start_time=None,
                  agent_type=None, agent_id=None):
    """Render a metadata header for the top of the log."""
    short_session = session_id[:8] if session_id else "unknown"

    date_display = date_str or "unknown date"
    if start_time:
        m = re.search(r'T(\d{2}:\d{2})', start_time)
        if m:
            date_display += f" {m.group(1)}"

    if agent_type:
        short_agent = agent_id[:8] if agent_id else ""
        title = f"# Subagent: {agent_type}"
        if short_agent:
            title += f" `{short_agent}`"
        title += f" — {date_display}"
        meta = f"*Parent session: `{short_session}`*"
    else:
        title = f"# Session `{short_session}` — {date_display}"
        meta = None

    parts = [title, ""]
    if meta:
        parts.append(meta)
        parts.append("")
    parts.append("---")
    parts.append("")
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(
        description="Convert Claude Code JSONL transcript to clean markdown."
    )
    parser.add_argument(
        "--transcript", required=True,
        help="Path to the JSONL transcript file",
    )
    parser.add_argument(
        "--output", required=True,
        help="Path to the output markdown file",
    )
    parser.add_argument(
        "--session-id", default=None,
        help="Session ID for the log header",
    )
    parser.add_argument(
        "--date", default=None,
        help="Date string for the log header (e.g. 2026-02-16)",
    )
    parser.add_argument(
        "--start-time", default=None,
        help="Start timestamp (ISO 8601) for the log header",
    )
    parser.add_argument(
        "--agent-type", default=None,
        help="Subagent type (e.g. Explore, Plan) for subagent logs",
    )
    parser.add_argument(
        "--agent-id", default=None,
        help="Subagent ID for subagent logs",
    )
    args = parser.parse_args()

    records = parse_jsonl(args.transcript)

    if not records:
        if not os.path.exists(args.output):
            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            with open(args.output, "w") as f:
                f.write("")
        return

    items = group_assistant_records(records)
    header = render_header(args.session_id, args.date, args.start_time,
                           args.agent_type, args.agent_id)
    body = render_markdown(items)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        f.write(header + body)


if __name__ == "__main__":
    main()
