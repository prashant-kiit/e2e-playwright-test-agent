#!/usr/bin/env bash
# Gracefully close Playwright test browsers left open by the playwright-test MCP server.
#
# The MCP server sets up each agent's page by running the seed test and pausing it at the
# end, so the browser stays open until that paused test worker goes away. This sends SIGTERM
# to those workers, which makes Playwright close its browsers cleanly (well under a second).
# A paused worker never exits by itself even after its browser is gone, so once the browser
# has closed (or the grace period runs out) the now-empty worker is stopped with SIGKILL.
# The MCP server itself keeps running and starts a fresh worker on the next *_setup_page call.
#
# Only runners under the Claude Code session that fired the hook are touched, so other
# sessions' browsers are left alone.
#
# Used by the SubagentStop (playwright-test-* agents only) and SessionEnd hooks.

set -u
GRACE_SECONDS=5
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
LOG="$PROJECT_DIR/.playwright-mcp/close-test-browsers.log"
mkdir -p "$(dirname "$LOG")"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

payload="$(cat 2>/dev/null || true)"
event="$(printf '%s' "$payload" | sed -n 's/.*"hook_event_name" *: *"\([^"]*\)".*/\1/p')"
agent="$(printf '%s' "$payload" | sed -n 's/.*"agent_type" *: *"\([^"]*\)".*/\1/p')"

# On SubagentStop, only act for the Playwright agents; another subagent finishing must not
# close a browser the main session is still using.
if [ "$event" = "SubagentStop" ] && [ -n "$agent" ] && [[ "$agent" != playwright-test-* ]]; then
  exit 0
fi

# Walk up from this hook to the claude process that fired it.
claude_pid=""
pid=$$
while [ -n "$pid" ] && [ "$pid" -gt 1 ]; do
  case "$(ps -o comm= -p "$pid" 2>/dev/null)" in
    *claude*) claude_pid=$pid; break ;;
  esac
  pid="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')"
done
[ -z "$claude_pid" ] && { log "[$event] no parent claude process found; nothing to do"; exit 0; }

is_descendant_of() { # $1=pid $2=ancestor
  local p=$1
  while [ -n "$p" ] && [ "$p" -gt 1 ]; do
    [ "$p" = "$2" ] && return 0
    p="$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')"
  done
  return 1
}

# Paused test runners are the direct children of this session's run-test-mcp-server node process.
runners=()
for server in $(pgrep -f "node .*playwright run-test-mcp-server"); do
  is_descendant_of "$server" "$claude_pid" || continue
  for child in $(pgrep -P "$server"); do
    runners+=("$child")
  done
done

if [ ${#runners[@]} -eq 0 ]; then
  log "[$event${agent:+ $agent}] no open test browsers"
  exit 0
fi

# Browsers launched by the workers (their direct children).
browsers=()
for r in "${runners[@]}"; do
  for b in $(pgrep -P "$r"); do browsers+=("$b"); done
done

log "[$event${agent:+ $agent}] closing test worker(s) ${runners[*]} with browser(s) ${browsers[*]:-none}"
kill -TERM "${runners[@]}" 2>/dev/null

# Wait for Playwright to close the browsers itself.
open=("${browsers[@]}")
for _ in $(seq $((GRACE_SECONDS * 10))); do
  open=()
  for b in "${browsers[@]}"; do kill -0 "$b" 2>/dev/null && open+=("$b"); done
  [ ${#open[@]} -eq 0 ] && break
  sleep 0.1
done

if [ ${#open[@]} -eq 0 ]; then
  log "  browser(s) closed gracefully"
else
  log "  browser(s) still open after ${GRACE_SECONDS}s, forcing: ${open[*]}"
  kill -KILL "${open[@]}" 2>/dev/null
fi

# The paused workers hold nothing now but never exit on their own.
kill -KILL "${runners[@]}" 2>/dev/null
log "  worker(s) stopped"
exit 0
