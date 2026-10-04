#!/usr/bin/env bash
# Run the QA workflow for several stories of ONE app at once: one headless Claude Code session per story.
# All stories in a batch must belong to the same app; a batch that mixes apps is refused.
#
#   ./run-stories.sh SCRUM-201 SCRUM-202 SCRUM-205     # specific stories of one app
#   ./run-stories.sh practice-target                   # every story of an app
#   ./run-stories.sh -j 2 -w 1 saucedemo               # 2 sessions at a time, 1 Playwright worker each
#   ./run-stories.sh --force SCRUM-201                 # regenerate a story already marked ready
#   ./run-stories.sh --dry-run practice-target         # show what would run, start nothing
#
# Each session runs the QA flow up to the healed test suite, then STOPS for human review.
# The agent does NOT deliver: after reviewing the generated tests, a human runs
# ./push-artifacts.sh <app> <STORY_ID> to open the PR in the target repo.
#
# Reruns are safe (e.g. after a session limit): a story already generated (marked "ready" in
# .qa-state.json, or whose tests are already committed) is SKIPPED; any other story has its
# previous generated files wiped and is regenerated from scratch, so a story's artifacts never
# mix two runs. Use --force to redo a skipped story. .qa-state.json tracks, per story, the last
# run-id and status.
#
# Each session gets the kick-off prompt from qa_user_prompt.md with its own "Active story:",
# "Mode: unattended" and "Run-ID:" lines (see "Unattended (batch) runs" in qa_system_prompt.md).
# Artifacts stay at stable paths (apps/<app>/specs|tests); the run-id is metadata only.
# The batch refuses to start unless the app's target repo is already bootstrapped
# (./check-bootstrapped.sh); if not, run ./bootstrap-target.sh <app> first.
#
# Status: ready = tests generated+healed, awaiting human review/delivery · incomplete = session
# ended cleanly but produced no test suite (rerun) · failed = session errored (e.g. limit) ·
# skipped = already generated (use --force to regenerate).
#
# Output: runs/<timestamp>-<app>/<STORY_ID>/{session.jsonl,stderr.log,result.md,clean.log,test-results/,playwright-report/}
#         runs/<timestamp>-<app>/summary.md ; persistent state in .qa-state.json
# Works with the bash 3.2 that ships with macOS.

set -u
cd "$(dirname "$0")"

JOBS=3          # sessions running at the same time
WORKERS=2       # Playwright workers per session (QA_WORKERS)
STAGGER=5       # seconds between session starts
DRY_RUN=0
FORCE=0
STATE_FILE=".qa-state.json"

usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
die() { echo "run-stories: $*" >&2; exit 1; }

args=()
while [ $# -gt 0 ]; do
  case "$1" in
    -j) JOBS="${2:?-j needs a number}"; shift 2 ;;
    -w) WORKERS="${2:?-w needs a number}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage ;;
    -*) die "unknown option $1 (see --help)" ;;
    *) args+=("$1"); shift ;;
  esac
done
[ ${#args[@]} -gt 0 ] || usage 1

# Resolve arguments to story files: an app name expands to all its stories, a story ID must match exactly one file.
stories=()   # entries: "STORY_ID|app|file|slug"
add_story() { # $1=file
  local file=$1 app id slug
  app="$(basename "$(dirname "$(dirname "$file")")")"
  id="$(basename "$file" .md | sed -E 's/^([A-Za-z]+-[0-9]+)-.*/\1/')"
  slug="$(basename "$file" .md | sed -E 's/^[A-Za-z]+-[0-9]+-//')"
  for s in ${stories[@]+"${stories[@]}"}; do [ "${s%%|*}" = "$id" ] && return; done
  stories+=("$id|$app|$file|$slug")
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

# The bootstrap check (./check-bootstrapped.sh) needs GitHub auth: GITHUB_PAT or `gh` login.
# Sessions themselves no longer deliver, so a PAT is not required for the agent runs.
if [ -z "${GITHUB_PAT:-}" ] && [ -f .env ]; then set -a; . ./.env; set +a; fi
[ -n "${GITHUB_PAT:-}" ] || [ $DRY_RUN -eq 1 ] || echo "run-stories: note: GITHUB_PAT not set; the bootstrap check will rely on 'gh' login." >&2
command -v claude >/dev/null || die "claude CLI not found"
command -v jq >/dev/null || die "jq not found (used to read session results and state)"
[ -f "$STATE_FILE" ] || echo '{}' > "$STATE_FILE"

# Gate: the app's target repo must be bootstrapped before any session starts.
if ./check-bootstrapped.sh "$APP" >/dev/null 2>&1; then BOOTED=1; else BOOTED=0; fi

RUN_ROOT="runs/$(date '+%Y%m%d-%H%M%S')-$APP"
RUN_ID="$(basename "$RUN_ROOT")"

kickoff_for() { # $1=STORY_ID
  printf 'Mode: unattended\nRun-ID: %s\n' "$RUN_ID"
  sed -E "s/^Active story:.*/Active story: $1/" qa_user_prompt.md
}

state_get() { jq -r --arg id "$1" ".[\$id].$2 // \"\"" "$STATE_FILE" 2>/dev/null; }
committed_tests() { # $1=app $2=id $3=slug ; 0 if the story's test suite is tracked by git
  git ls-files "apps/$1/tests/$3" 2>/dev/null | grep -q .
}
decide() { # $1=id $2=app $3=slug ; echo run|skip and a reason
  local st; st="$(state_get "$1" status)"
  if [ "$FORCE" = 1 ]; then echo "run forced"; return; fi
  [ "$st" = ready ] && { echo "skip already generated (state: ready, run $(state_get "$1" runId))"; return; }
  if [ -z "$st" ] && committed_tests "$2" "$1" "$3"; then
    echo "skip test suite already committed (use --force to regenerate)"; return
  fi
  echo "run ${st:-new}"
}

clean_artifacts() { # $1=app $2=id $3=slug $4=logfile
  local app=$1 id=$2 slug=$3 log=$4
  { echo "cleaning previous generated files for $id before redo:"
    for p in "apps/$app/specs/$id-$slug-test-plan.md" \
             "apps/$app/tests/$slug" \
             "apps/$app/reports/$id-$slug-test-report.md"; do
      [ -e "$p" ] && echo "  rm $p" && rm -rf "$p"
    done
    for p in apps/"$app"/reports/evidence/"$id"-*.png; do
      [ -e "$p" ] && echo "  rm $p" && rm -f "$p"
    done
  } >> "$log" 2>&1
}

echo "App: $APP ($(jq -r .baseURL "apps/$APP/app.json") -> $(jq -r .targetRepo "apps/$APP/app.json"))"
echo "Run-ID: $RUN_ID${FORCE:+  (force: $( [ $FORCE = 1 ] && echo on || echo off ))}"
if [ "$BOOTED" = 1 ]; then echo "Bootstrapped: yes"; else
  echo "Bootstrapped: NO"
  [ $DRY_RUN -eq 1 ] || die "target repo for '$APP' is not bootstrapped. Run: ./bootstrap-target.sh $APP"
fi
echo "Stories (${#stories[@]}), $JOBS at a time, $WORKERS Playwright worker(s) each:"
for s in "${stories[@]}"; do
  IFS='|' read -r id app file slug <<<"$s"
  printf '  %-10s %-16s %-40s [%s]\n' "$id" "$app" "$file" "$(decide "$id" "$app" "$slug")"
done
if [ $DRY_RUN -eq 1 ]; then
  first="${stories[0]%%|*}"
  echo; echo "Output would go to $RUN_ROOT/<STORY_ID>/. Kick-off prompt for $first:"; echo "----"
  kickoff_for "$first"; echo "----"
  echo "Command: QA_RUN_DIR=$RUN_ROOT/$first QA_WORKERS=$WORKERS claude -p <prompt> --output-format stream-json --verbose"
  exit 0
fi
mkdir -p "$RUN_ROOT"

run_story() { # $1=STORY_ID $2=app $3=slug ; runs in a background subshell
  local id=$1 app=$2 slug=$3 dir="$RUN_ROOT/$1" start rc is_error cost tests
  mkdir -p "$dir"
  clean_artifacts "$app" "$id" "$slug" "$dir/clean.log"
  start=$(date +%s)
  # No --allowedTools for push-artifacts: the agent must NOT deliver. It stops after Step 5;
  # a human runs ./push-artifacts.sh after review.
  QA_RUN_DIR="$dir" QA_WORKERS="$WORKERS" claude -p "$(kickoff_for "$id")" \
    --output-format stream-json --verbose \
    > "$dir/session.jsonl" 2> "$dir/stderr.log" < /dev/null
  rc=$?
  jq -rs 'map(select(.type == "result")) | last | .result // "(no result message; see session.jsonl and stderr.log)"' \
    "$dir/session.jsonl" > "$dir/result.md" 2>/dev/null || echo "(could not parse session.jsonl)" > "$dir/result.md"
  is_error=$(jq -rs 'map(select(.type == "result")) | last | .is_error // true' "$dir/session.jsonl" 2>/dev/null || echo true)
  cost=$(jq -rs 'map(select(.type == "result")) | last | .total_cost_usd // empty' "$dir/session.jsonl" 2>/dev/null)
  # Ready for review only if the session ended cleanly AND a test suite was produced.
  if ls "apps/$app/tests/$slug"/*.spec.ts >/dev/null 2>&1; then tests="apps/$app/tests/$slug"; else tests=""; fi
  if [ "$rc" -eq 0 ] && [ "$is_error" = "false" ] && [ -n "$tests" ]; then status=ready
  elif [ "$rc" -eq 0 ] && [ "$is_error" = "false" ]; then status=incomplete  # ran OK but no test suite (e.g. limit mid-flow)
  else status=failed; fi
  echo "$status|$(( $(date +%s) - start ))|${cost:-?}|$tests" > "$dir/status"
  echo "[$(date '+%H:%M:%S')] $id ($app): $status after $(( ($(date +%s) - start) / 60 )) min${tests:+  $tests}"
}

pids=()
cleanup() {
  echo; echo "Stopping ${#pids[@]} session(s)..."
  for p in ${pids[@]+"${pids[@]}"}; do pkill -TERM -P "$p" 2>/dev/null; kill -TERM "$p" 2>/dev/null; done
  exit 130
}
trap cleanup INT TERM
running() { local n=0 p; for p in ${pids[@]+"${pids[@]}"}; do kill -0 "$p" 2>/dev/null && n=$((n + 1)); done; echo $n; }

echo; echo "Logs: $RUN_ROOT/  State: $STATE_FILE"
for s in "${stories[@]}"; do
  IFS='|' read -r id app file slug <<<"$s"
  d="$(decide "$id" "$app" "$slug")"
  if [ "${d%% *}" = skip ]; then
    mkdir -p "$RUN_ROOT/$id"
    echo "skipped|0|0|$(state_get "$id" tests)" > "$RUN_ROOT/$id/status"
    echo "skipped: ${d#skip }" > "$RUN_ROOT/$id/result.md"
    echo "[$(date '+%H:%M:%S')] $id ($app): skipped — ${d#skip }"
    continue
  fi
  while [ "$(running)" -ge "$JOBS" ]; do sleep 5; done
  echo "[$(date '+%H:%M:%S')] $id ($app): started"
  run_story "$id" "$app" "$slug" &
  pids+=($!)
  sleep "$STAGGER"
done
wait

# Update persistent state (sequential, after all sessions finish — no concurrent writers).
now="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
for s in "${stories[@]}"; do
  IFS='|' read -r id app file slug <<<"$s"
  IFS='|' read -r st secs cost tests < "$RUN_ROOT/$id/status" 2>/dev/null || continue
  [ "$st" = skipped ] && continue   # keep the earlier state for skipped stories
  tmp="$(mktemp)"
  jq --arg id "$id" --arg app "$app" --arg st "$st" --arg run "$RUN_ID" --arg tests "$tests" --arg at "$now" \
    '.[$id] = {app:$app, status:$st, runId:$run, tests:$tests, updatedAt:$at}' "$STATE_FILE" > "$tmp" && mv "$tmp" "$STATE_FILE"
done

# Summary
summary="$RUN_ROOT/summary.md"
{
  echo "# Batch run $RUN_ID (app: $APP)"
  echo
  echo "status: **ready** = tests generated+healed, awaiting human review/delivery · **incomplete** = session ended but no test suite (rerun) · **failed** = session errored (e.g. limit) · **skipped** = already generated (use --force)"
  echo
  echo "To deliver a ready story after review:  ./push-artifacts.sh $APP <STORY_ID>"
  echo
  echo "| Story | App | Status | Minutes | Cost (USD) | Tests | Result |"
  echo "|---|---|---|---|---|---|---|"
  for s in "${stories[@]}"; do
    IFS='|' read -r id app file slug <<<"$s"
    IFS='|' read -r st secs cost tests < "$RUN_ROOT/$id/status" 2>/dev/null || { st=unknown; secs=0; cost=?; tests=; }
    echo "| $id | $app | $st | $(( secs / 60 )) | $cost | ${tests:--} | [$id/result.md]($id/result.md) |"
  done
} > "$summary"
echo; cat "$summary"
grep -qE '\| (failed|incomplete|unknown) \|' "$summary" && exit 1 || exit 0
