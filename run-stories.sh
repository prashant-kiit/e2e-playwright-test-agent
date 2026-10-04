#!/usr/bin/env bash
# Run the QA workflow for several stories of ONE app at once: one headless Claude Code session per story.
# All stories in a batch must belong to the same app; a batch that mixes apps is refused.
#
#   ./run-stories.sh SCRUM-201 SCRUM-202 SCRUM-205     # specific stories of one app
#   ./run-stories.sh practice-target                   # every story of an app
#   ./run-stories.sh -j 2 -w 1 saucedemo               # 2 sessions at a time, 1 Playwright worker each
#   ./run-stories.sh --dry-run practice-target         # show what would run, start nothing
#
# Each session gets the kick-off prompt from qa_user_prompt.md with its own "Active story:" line
# and "Mode: unattended" (see "Unattended (batch) runs" in qa_system_prompt.md). Sessions share
# this folder: every story writes only its own files, and Playwright output goes to a per-story
# QA_RUN_DIR. Step 7 (GitHub push + PR) is pre-approved for these sessions only.
#
# Output: runs/<timestamp>-<app>/<STORY_ID>/{session.jsonl,stderr.log,result.md,test-results/,playwright-report/}
#         runs/<timestamp>-<app>/summary.md
# Works with the bash 3.2 that ships with macOS.

set -u
cd "$(dirname "$0")"

JOBS=3          # sessions running at the same time
WORKERS=2       # Playwright workers per session (QA_WORKERS)
STAGGER=5       # seconds between session starts
DRY_RUN=0

usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
die() { echo "run-stories: $*" >&2; exit 1; }

args=()
while [ $# -gt 0 ]; do
  case "$1" in
    -j) JOBS="${2:?-j needs a number}"; shift 2 ;;
    -w) WORKERS="${2:?-w needs a number}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage ;;
    -*) die "unknown option $1 (see --help)" ;;
    *) args+=("$1"); shift ;;
  esac
done
[ ${#args[@]} -gt 0 ] || usage 1

# Resolve arguments to story files: an app name expands to all its stories, a story ID must match exactly one file.
stories=()   # entries: "STORY_ID|app|file"
add_story() { # $1=file
  local file=$1 app id
  app="$(basename "$(dirname "$(dirname "$file")")")"
  id="$(basename "$file" .md | sed -E 's/^([A-Za-z]+-[0-9]+)-.*/\1/')"
  for s in ${stories[@]+"${stories[@]}"}; do [ "${s%%|*}" = "$id" ] && return; done
  stories+=("$id|$app|$file")
}
for a in "${args[@]}"; do
  if [ -f "apps/$a/app.json" ] && [ "${a:0:1}" != "_" ]; then
    found=0
    for f in apps/"$a"/user-stories/*.md; do [ -f "$f" ] && { add_story "$f"; found=1; }; done
    [ $found -eq 1 ] || die "app '$a' has no stories"
  else
    matches=()
    for f in apps/[!_]*/user-stories/"$a"-*.md; do [ -f "$f" ] && matches+=("$f"); done
    [ ${#matches[@]} -eq 1 ] || die "'$a' matches ${#matches[@]} story files (expected exactly 1) and is not an app name"
    add_story "${matches[0]}"
  fi
done

# One app per batch.
APP="${stories[0]#*|}"; APP="${APP%%|*}"
for s in "${stories[@]}"; do
  a="${s#*|}"; a="${a%%|*}"
  [ "$a" = "$APP" ] || die "all stories in a batch must belong to one app: ${stories[0]%%|*} is in '$APP' but ${s%%|*} is in '$a'. Run one batch per app."
done

# The GitHub MCP server reads GITHUB_PAT when each session starts.
if [ -z "${GITHUB_PAT:-}" ] && [ -f .env ]; then set -a; . ./.env; set +a; fi
[ -n "${GITHUB_PAT:-}" ] || [ $DRY_RUN -eq 1 ] || die "GITHUB_PAT is not set (and not found in .env); step 7 would fail"
command -v claude >/dev/null || die "claude CLI not found"
command -v jq >/dev/null || die "jq not found (used to read session results)"

RUN_ROOT="runs/$(date '+%Y%m%d-%H%M%S')-$APP"
kickoff_for() { # $1=STORY_ID
  printf 'Mode: unattended\n'
  sed -E "s/^Active story:.*/Active story: $1/" qa_user_prompt.md
}

echo "App: $APP ($(jq -r .baseURL "apps/$APP/app.json") -> $(jq -r .targetRepo "apps/$APP/app.json"))"
echo "Stories (${#stories[@]}), $JOBS at a time, $WORKERS Playwright worker(s) each:"
for s in "${stories[@]}"; do IFS='|' read -r id app file <<<"$s"; printf '  %-10s %-16s %s\n' "$id" "$app" "$file"; done
if [ $DRY_RUN -eq 1 ]; then
  first="${stories[0]%%|*}"
  echo; echo "Output would go to $RUN_ROOT/<STORY_ID>/. Kick-off prompt for $first:"; echo "----"
  kickoff_for "$first"; echo "----"
  echo "Command: QA_RUN_DIR=$RUN_ROOT/$first QA_WORKERS=$WORKERS claude -p <prompt> --output-format stream-json --verbose --allowedTools mcp__github"
  exit 0
fi
mkdir -p "$RUN_ROOT"

run_story() { # $1=STORY_ID $2=app ; runs in a background subshell
  local id=$1 app=$2 dir="$RUN_ROOT/$1" start rc
  mkdir -p "$dir"
  start=$(date +%s)
  QA_RUN_DIR="$dir" QA_WORKERS="$WORKERS" claude -p "$(kickoff_for "$id")" \
    --output-format stream-json --verbose \
    --allowedTools mcp__github \
    > "$dir/session.jsonl" 2> "$dir/stderr.log" < /dev/null
  rc=$?
  jq -rs 'map(select(.type == "result")) | last | .result // "(no result message; see session.jsonl and stderr.log)"' \
    "$dir/session.jsonl" > "$dir/result.md" 2>/dev/null || echo "(could not parse session.jsonl)" > "$dir/result.md"
  local is_error cost
  is_error=$(jq -rs 'map(select(.type == "result")) | last | .is_error // true' "$dir/session.jsonl" 2>/dev/null || echo true)
  cost=$(jq -rs 'map(select(.type == "result")) | last | .total_cost_usd // empty' "$dir/session.jsonl" 2>/dev/null)
  [ "$rc" -eq 0 ] && [ "$is_error" = "false" ] && status=finished || status=failed
  echo "$status|$(( $(date +%s) - start ))|${cost:-?}" > "$dir/status"
  echo "[$(date '+%H:%M:%S')] $id ($app): $status after $(( ($(date +%s) - start) / 60 )) min"
}

pids=()
cleanup() {
  echo; echo "Stopping ${#pids[@]} session(s)..."
  for p in ${pids[@]+"${pids[@]}"}; do pkill -TERM -P "$p" 2>/dev/null; kill -TERM "$p" 2>/dev/null; done
  exit 130
}
trap cleanup INT TERM

running() { local n=0 p; for p in ${pids[@]+"${pids[@]}"}; do kill -0 "$p" 2>/dev/null && n=$((n + 1)); done; echo $n; }

echo; echo "Logs: $RUN_ROOT/"
for s in "${stories[@]}"; do
  IFS='|' read -r id app file <<<"$s"
  while [ "$(running)" -ge "$JOBS" ]; do sleep 5; done
  echo "[$(date '+%H:%M:%S')] $id ($app): started"
  run_story "$id" "$app" &
  pids+=($!)
  sleep "$STAGGER"
done
wait

# Summary
summary="$RUN_ROOT/summary.md"
{
  echo "# Batch run $(basename "$RUN_ROOT") (app: $APP)"
  echo
  echo "Status \"finished\" means the session ended normally; check the PR column and result.md for the QA outcome."
  echo
  echo "| Story | App | Status | Minutes | Cost (USD) | PR | Result |"
  echo "|---|---|---|---|---|---|---|"
  for s in "${stories[@]}"; do
    IFS='|' read -r id app file <<<"$s"
    IFS='|' read -r st secs cost < "$RUN_ROOT/$id/status" 2>/dev/null || { st=unknown; secs=0; cost=?; }
    pr=$(grep -oE 'https://github\.com/[^ )]+/pull/[0-9]+' "$RUN_ROOT/$id/result.md" 2>/dev/null | head -1)
    echo "| $id | $app | $st | $(( secs / 60 )) | $cost | ${pr:--} | [$id/result.md]($id/result.md) |"
  done
} > "$summary"
echo; cat "$summary"
grep -q '| failed |\|| unknown |' "$summary" && exit 1 || exit 0
