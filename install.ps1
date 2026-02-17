# claude-session-logger installer (Windows)
# Copies hook scripts and merges config into .claude/settings.json

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$HooksDir = ".claude\hooks"
$SettingsFile = ".claude\settings.json"

# --- Preflight checks ---

Write-Host ""
Write-Host "claude-session-logger installer"
Write-Host "================================"
Write-Host ""

if (-not (Test-Path ".git")) {
    Write-Host "  [ERROR] Not in a git project root. Run this from your project directory." -ForegroundColor Red
    exit 1
}

try {
    python3 --version | Out-Null
} catch {
    try {
        python --version | Out-Null
    } catch {
        Write-Host "  [ERROR] python3 is required but not found." -ForegroundColor Red
        exit 1
    }
}

# --- Timezone ---

Write-Host "Timezone for log timestamps (e.g. America/New_York, America/Chicago, UTC)"
$TzInput = Read-Host "  TZ [America/New_York]"
$TzValue = if ($TzInput) { $TzInput } else { "America/New_York" }
Write-Host ""

# --- Check for existing installation ---

if (Test-Path "$HooksDir\stop-log.sh") {
    $answer = Read-Host "  Hooks already installed. Overwrite? [y/N]"
    if ($answer -notmatch "^[Yy]") {
        Write-Host "  Aborted."
        exit 0
    }
    Write-Host ""
}

# --- Copy scripts ---

New-Item -ItemType Directory -Path $HooksDir -Force | Out-Null

foreach ($script in @("stop-log.sh", "subagent-stop-log.sh")) {
    $content = Get-Content "$ScriptDir\$script" -Raw
    $content = $content -replace "__TZ__", $TzValue
    Set-Content -Path "$HooksDir\$script" -Value $content -NoNewline
}

Copy-Item "$ScriptDir\log-converter.py" "$HooksDir\log-converter.py" -Force

Write-Host "  Installed scripts to $HooksDir\"

# --- Merge settings ---

New-Item -ItemType Directory -Path ".claude" -Force | Out-Null

$hooksConfig = @{
    Stop = @(@{hooks = @(@{type = "command"; command = ".claude/hooks/stop-log.sh"})})
    SubagentStop = @(@{hooks = @(@{type = "command"; command = ".claude/hooks/subagent-stop-log.sh"})})
}

if (Test-Path $SettingsFile) {
    $settings = Get-Content $SettingsFile -Raw | ConvertFrom-Json -AsHashtable
} else {
    $settings = @{}
}

if (-not $settings.ContainsKey("hooks")) {
    $settings["hooks"] = @{}
}
$settings["hooks"]["Stop"] = $hooksConfig["Stop"]
$settings["hooks"]["SubagentStop"] = $hooksConfig["SubagentStop"]

$settings | ConvertTo-Json -Depth 10 | Set-Content $SettingsFile

Write-Host "  Updated $SettingsFile"

# --- Done ---

Write-Host ""
Write-Host "Done! Session logs will appear in .claude/logs/ after each turn."
Write-Host "Restart Claude Code to pick up the new hooks."
Write-Host ""
