#!/usr/bin/env node
/**
 * cc-session-logger installer (Node.js)
 *
 * Copies hook scripts to .claude/hooks/ and merges config into .claude/settings.json.
 *
 * Usage:
 *   node install.js
 */

const fs = require("fs");
const path = require("path");
const readline = require("readline");

const SCRIPT_DIR = __dirname;
const HOOKS_DIR = path.join(".claude", "hooks");
const SETTINGS_FILE = path.join(".claude", "settings.json");
const HOOK_SCRIPTS = ["stop-log.js", "subagent-stop-log.js", "log-converter.js"];
const SERVE_SCRIPT = "serve-sessions.js";

const HOOKS_CONFIG = {
  Stop: [{ hooks: [{ type: "command", command: "node .claude/hooks/stop-log.js" }] }],
  SubagentStop: [{ hooks: [{ type: "command", command: "node .claude/hooks/subagent-stop-log.js" }] }],
};

function ask(rl, question, defaultVal) {
  const hint = defaultVal ? ` [${defaultVal}]` : "";
  return new Promise((resolve) => {
    rl.question(`  ${question}${hint}: `, (answer) => {
      resolve(answer.trim() || defaultVal || "");
    });
  });
}

function askYn(rl, question, defaultVal = "n") {
  const hint = defaultVal === "y" ? "[Y/n]" : "[y/N]";
  return new Promise((resolve) => {
    rl.question(`  ${question} ${hint} `, (answer) => {
      const a = (answer.trim() || defaultVal).toLowerCase();
      resolve(a.startsWith("y"));
    });
  });
}

async function main() {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

  console.log();
  console.log("cc-session-logger installer");
  console.log("================================");
  console.log();

  // --- Preflight checks ---

  if (!fs.existsSync(".git")) {
    console.error("  [ERROR] Not in a git project root. Run this from your project directory.");
    rl.close();
    process.exit(1);
  }

  // --- Timezone ---

  console.log("Timezone for log timestamps (e.g. America/New_York, America/Chicago, UTC)");
  const tzValue = await ask(rl, "TZ", "America/New_York");
  console.log();

  // --- Check for existing installation ---

  if (fs.existsSync(path.join(HOOKS_DIR, "stop-log.js"))) {
    const overwrite = await askYn(rl, "Hooks already installed. Overwrite?");
    if (!overwrite) {
      console.log();
      console.log("  Aborted.");
      rl.close();
      return;
    }
    console.log();
  }

  // --- Copy scripts ---

  fs.mkdirSync(HOOKS_DIR, { recursive: true });

  for (const script of HOOK_SCRIPTS) {
    const src = path.join(SCRIPT_DIR, "js", script);
    const dst = path.join(HOOKS_DIR, script);
    let content = fs.readFileSync(src, "utf-8");
    content = content.replace(/__TZ__/g, tzValue);
    fs.writeFileSync(dst, content);
  }

  console.log(`  Installed hook scripts to ${HOOKS_DIR}/`);

  // --- Copy serve script to .claude/ ---

  const serveSrc = path.join(SCRIPT_DIR, "js", SERVE_SCRIPT);
  const serveDst = path.join(".claude", SERVE_SCRIPT);
  fs.copyFileSync(serveSrc, serveDst);
  console.log(`  Installed ${SERVE_SCRIPT} to .claude/`);

  // --- Merge settings ---

  fs.mkdirSync(".claude", { recursive: true });

  let settings = {};
  try {
    settings = JSON.parse(fs.readFileSync(SETTINGS_FILE, "utf-8"));
  } catch {}

  const existingHooks = settings.hooks || {};
  Object.assign(existingHooks, HOOKS_CONFIG);
  settings.hooks = existingHooks;

  fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settings, null, 2) + "\n");

  console.log(`  Updated ${SETTINGS_FILE}`);

  // --- Done ---

  console.log();
  console.log("Done! Session logs will appear in .claude/logs/ after each turn.");
  console.log("Restart Claude Code to pick up the new hooks.");
  console.log();
  console.log("To browse logs in a browser:");
  console.log(`  node .claude/${SERVE_SCRIPT}`);
  console.log();

  rl.close();
}

main();
