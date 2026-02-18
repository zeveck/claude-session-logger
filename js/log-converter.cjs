#!/usr/bin/env node
/**
 * Converts Claude Code JSONL transcripts into clean, readable markdown.
 *
 * Usage:
 *   node log-converter.js --transcript PATH --output PATH
 */

const fs = require("fs");
const path = require("path");

// JSONL line types to skip entirely
const SKIP_TYPES = new Set([
  "file-history-snapshot",
  "queue-operation",
  "progress",
  "system",
]);

// Max lines for inline result display (longer gets collapsed)
const INLINE_RESULT_MAX_LINES = 4;

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, "");
    args[key] = argv[i + 1] || null;
  }
  return args;
}

function parseJsonl(transcriptPath) {
  const records = [];
  let content;
  try {
    content = fs.readFileSync(transcriptPath, "utf-8");
  } catch {
    process.stderr.write(`Error: Transcript file not found: ${transcriptPath}\n`);
    process.exit(1);
  }
  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      records.push(JSON.parse(trimmed));
    } catch {
      continue;
    }
  }
  return records;
}

function shouldSkip(record) {
  if (SKIP_TYPES.has(record.type || "")) return true;
  if (record.isMeta) return true;
  return false;
}

function groupAssistantRecords(records) {
  const items = [];
  const assistantGroups = new Map();
  const assistantOrder = [];

  for (const record of records) {
    if (shouldSkip(record)) continue;

    const rtype = record.type || "";
    const msg = typeof record.message === "object" && record.message ? record.message : {};
    const timestamp = record.timestamp || "";

    if (rtype === "user") {
      for (const mid of assistantOrder) {
        const grp = assistantGroups.get(mid);
        items.push(["assistant", grp.blocks, grp.timestamp]);
      }
      assistantGroups.clear();
      assistantOrder.length = 0;

      const content = msg.content;
      const role = msg.role || "";

      if (role === "user") {
        if (typeof content === "string") {
          const text = content.trim();
          if (text) items.push(["user", text, timestamp]);
        } else if (Array.isArray(content)) {
          const textParts = [];
          const toolResults = [];
          for (const block of content) {
            if (typeof block !== "object" || !block) continue;
            const btype = block.type || "";
            if (btype === "text") {
              const t = (block.text || "").trim();
              if (t) textParts.push(t);
            } else if (btype === "tool_result") {
              toolResults.push(block);
            }
          }
          if (textParts.length) items.push(["user", textParts.join("\n"), timestamp]);
          for (const tr of toolResults) items.push(["tool_result", tr, timestamp]);
        }
      }
    } else if (rtype === "assistant") {
      const msgId = msg.id || "";
      const content = Array.isArray(msg.content) ? msg.content : [];

      if (msgId && assistantGroups.has(msgId)) {
        assistantGroups.get(msgId).blocks.push(...content);
      } else {
        const key = msgId || `_${items.length}_${assistantOrder.length}`;
        assistantGroups.set(key, { blocks: [...content], timestamp });
        assistantOrder.push(key);
      }
    }
  }

  for (const mid of assistantOrder) {
    const grp = assistantGroups.get(mid);
    items.push(["assistant", grp.blocks, grp.timestamp]);
  }

  return items;
}

function cleanResultText(text) {
  return text.replace(/<\/?tool_use_error>/g, "").trim();
}

function escapeHtml(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function unescapeHtml(text) {
  return text.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}

function truncate(text, maxLen) {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + "...";
}

function toolHeader(name, inp) {
  if (typeof inp !== "object" || !inp) return `● ${name}`;

  if (name === "Bash") {
    const cmd = (inp.command || "").split("\n")[0];
    return `● \`Bash(${truncate(cmd, 120)})\``;
  }
  if (name === "Read") return `● \`Read(${inp.file_path || ""})\``;
  if (name === "Write") return `● \`Write(${inp.file_path || ""})\``;
  if (name === "Edit") return `● \`Update(${inp.file_path || ""})\``;
  if (name === "Glob") return `● \`Glob(${inp.pattern || ""})\``;
  if (name === "Grep") {
    const pattern = inp.pattern || "";
    return pattern ? `● Searched for \`${truncate(pattern, 80)}\`` : "● Searched codebase";
  }
  if (name === "WebFetch") return `● \`WebFetch(${truncate(inp.url || "", 100)})\``;
  if (name === "WebSearch") return `● \`WebSearch(${inp.query || ""})\``;
  if (name === "Task") {
    const desc = inp.description || "";
    const agent = inp.subagent_type || "";
    return agent
      ? `● \`Task(${agent}: ${truncate(desc, 100)})\``
      : `● \`Task(${truncate(desc, 100)})\``;
  }
  return `● ${name}`;
}

function formatToolResultContent(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((block) => {
        if (typeof block === "object" && block) {
          if (block.type === "text") return block.text || "";
          if (block.type === "image") return "[image]";
          return String(block);
        }
        return typeof block === "string" ? block : String(block);
      })
      .join("\n");
  }
  return content ? String(content) : "";
}

function renderResultInline(lines, content, isError) {
  const resultLines = content.split("\n");
  const prefix = isError ? "  ⎿  **Error:** " : "  ⎿  ";
  const contPrefix = "     ";
  for (let i = 0; i < resultLines.length; i++) {
    lines.push(i === 0 ? `${prefix}${resultLines[i]}` : `${contPrefix}${resultLines[i]}`);
  }
  lines.push("");
}

function renderResultCollapsed(lines, content, summaryText, isError) {
  if (isError) summaryText = `<b>Error:</b> ${summaryText}`;
  lines.push("<details>");
  lines.push(`<summary>${summaryText}</summary>`);
  lines.push(`<pre><code>${escapeHtml(content)}</code></pre>`);
  lines.push("</details>");
  lines.push("<br>");
  lines.push("");
}

function renderToolWithResult(lines, header, resultContent, isError) {
  const content = resultContent ? cleanResultText(resultContent) : "";
  if (!content) {
    lines.push(header);
    lines.push("");
    return;
  }
  const resultLines = content.split("\n");
  if (resultLines.length <= INLINE_RESULT_MAX_LINES) {
    lines.push(header);
    renderResultInline(lines, content, isError);
  } else {
    renderResultCollapsed(lines, content, escapeHtml(header), isError);
  }
}

/** Simple unified diff between two strings. */
function unifiedDiff(oldStr, newStr, contextLines = 2) {
  const oldLines = oldStr.split("\n");
  const newLines = newStr.split("\n");
  const result = [];

  // Simple LCS-based diff
  const m = oldLines.length;
  const n = newLines.length;

  // Build edit script using Myers-like approach (simplified)
  const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      if (oldLines[i] === newLines[j]) {
        dp[i][j] = dp[i + 1][j + 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
  }

  const ops = []; // {type: '=', '-', '+', line}
  let i = 0, j = 0;
  while (i < m || j < n) {
    if (i < m && j < n && oldLines[i] === newLines[j]) {
      ops.push({ type: "=", line: oldLines[i] });
      i++; j++;
    } else if (j < n && (i >= m || dp[i][j + 1] >= dp[i + 1][j])) {
      ops.push({ type: "+", line: newLines[j] });
      j++;
    } else {
      ops.push({ type: "-", line: oldLines[i] });
      i++;
    }
  }

  // Generate hunks with context
  for (let k = 0; k < ops.length; k++) {
    const op = ops[k];
    if (op.type === "=") {
      // Include context lines around changes
      const nearChange = ops.slice(Math.max(0, k - contextLines), Math.min(ops.length, k + contextLines + 1))
        .some((o) => o.type !== "=");
      if (nearChange) result.push(` ${op.line}`);
    } else if (op.type === "-") {
      result.push(`-${op.line}`);
    } else {
      result.push(`+${op.line}`);
    }
  }

  return result;
}

function renderMarkdown(items) {
  const lines = [];

  // First pass: collect tool results keyed by tool_use_id
  const toolResultsMap = new Map();
  for (const item of items) {
    if (item[0] === "tool_result") {
      const tr = item[1];
      const content = formatToolResultContent(tr.content || "").trim();
      const tid = tr.tool_use_id || "";
      if (tid) toolResultsMap.set(tid, [content, !!tr.is_error]);
    }
  }

  // Second pass: render
  for (const item of items) {
    const kind = item[0];

    if (kind === "user") {
      const text = item[1];
      if (text.startsWith("This session is being continued from a previous")) {
        lines.push("**Context restored from previous session (ran out of context):**");
        const quoted = text.split("\n").map((l) => `> ${l}`).join("\n");
        lines.push("<details>");
        lines.push("<summary>Session summary</summary>");
        lines.push("");
        lines.push(quoted);
        lines.push("");
        lines.push("</details>");
        lines.push("<br>");
        lines.push("");
      } else {
        const quoted = text.split("\n").map((l) => `> ${l}`).join("\n");
        lines.push(`**User:**\n${quoted}`);
        lines.push("");
      }
    } else if (kind === "tool_result") {
      continue;
    } else if (kind === "assistant") {
      const blocks = item[1];
      for (const block of blocks) {
        if (typeof block !== "object" || !block) continue;
        const btype = block.type || "";

        if (btype === "thinking") continue;

        if (btype === "text") {
          const text = unescapeHtml((block.text || "").trim());
          if (!text) continue;
          if (lines.length && lines[lines.length - 1] !== "") lines.push("");
          lines.push(text);
          lines.push("");
        } else if (btype === "tool_use") {
          const toolName = block.name || "unknown";
          const toolInput = block.input || {};
          const header = toolHeader(toolName, toolInput);
          const toolId = block.id || "";

          const result = toolResultsMap.get(toolId);
          const resultContent = result ? result[0] : "";
          const resultIsError = result ? result[1] : false;

          if (toolName === "Edit") {
            lines.push(header);
            const oldStr = toolInput.old_string || "";
            const newStr = toolInput.new_string || "";
            if (oldStr || newStr) {
              const diffBody = unifiedDiff(oldStr, newStr, 2);
              if (diffBody.length) {
                lines.push("```diff");
                lines.push(...diffBody);
                lines.push("```");
              }
            }
            if (resultContent) {
              renderResultInline(lines, cleanResultText(resultContent), resultIsError);
            } else {
              lines.push("");
            }
          } else {
            renderToolWithResult(lines, header, resultContent, resultIsError);
          }
        }
      }
      if (lines.length && lines[lines.length - 1] !== "") lines.push("");
    }
  }

  return lines.join("\n");
}

function renderHeader(sessionId, dateStr, startTime, agentType, agentId) {
  const shortSession = sessionId ? sessionId.slice(0, 8) : "unknown";
  let dateDisplay = dateStr || "unknown date";

  if (startTime) {
    const m = startTime.match(/T(\d{2}:\d{2})/);
    if (m) dateDisplay += ` ${m[1]}`;
  }

  let title, meta;
  if (agentType) {
    const shortAgent = agentId ? agentId.slice(0, 8) : "";
    title = `# Subagent: ${agentType}`;
    if (shortAgent) title += ` \`${shortAgent}\``;
    title += ` — ${dateDisplay}`;
    meta = `*Parent session: \`${shortSession}\`*`;
  } else {
    title = `# Session \`${shortSession}\` — ${dateDisplay}`;
    meta = null;
  }

  const parts = [title, ""];
  if (meta) {
    parts.push(meta);
    parts.push("");
  }
  parts.push("---");
  parts.push("");
  return parts.join("\n");
}

function main() {
  const args = parseArgs(process.argv);
  if (!args.transcript || !args.output) {
    process.stderr.write("Usage: node log-converter.js --transcript PATH --output PATH\n");
    process.exit(1);
  }

  const records = parseJsonl(args.transcript);

  if (!records.length) {
    if (!fs.existsSync(args.output)) {
      const dir = path.dirname(path.resolve(args.output));
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(args.output, "");
    }
    return;
  }

  const items = groupAssistantRecords(records);
  const header = renderHeader(
    args["session-id"],
    args.date,
    args["start-time"],
    args["agent-type"],
    args["agent-id"]
  );
  const body = renderMarkdown(items);

  const dir = path.dirname(path.resolve(args.output));
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(args.output, header + body);
}

main();
