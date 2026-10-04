#!/usr/bin/env bash
# Tool: reset an app's target repo to a FRESH, EMPTY state (DESTRUCTIVE, agent repo untouched).
#
#   ./reset-target.sh <app> [--yes] [--dry-run]
#
# Wipes the app's target repo so a later ./bootstrap-target.sh <app> starts clean:
#   - replaces <targetBranch> with a single empty commit (all files AND history gone)
#   - deletes every other branch (e.g. qa/SCRUM-xxx-*), which closes their PRs
# It does NOT re-bootstrap; run ./bootstrap-target.sh <app> afterwards. IRREVERSIBLE on the
# live GitHub repo. Asks you to type the repo name to confirm (skip with --yes). Reusable for
# any app. Works with the bash 3.2 that ships with macOS.
set -u
QA_TOOL="reset-target"
. "$(dirname "$0")/scripts/qa-lib.sh"

DRY=0; YES=0; APP_ARG=""
for a in "$@"; do case "$a" in
  --dry-run) DRY=1;;
  --yes|-y) YES=1;;
  -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  -*) qa_die "unknown option $a";;
  *) [ -z "$APP_ARG" ] && APP_ARG="$a" || qa_die "unexpected arg $a";;
esac; done

qa_need jq; qa_need gh; qa_need git
qa_resolve "$APP_ARG"
qa_load_env

echo "App:    $APP"
echo "Target: $TARGET_REPO ($TARGET_BRANCH)"

# Nothing to reset on an empty repo.
if ! qa_repo_has_commits "$TARGET_REPO"; then
  echo "already empty: $TARGET_REPO has no commits. Run ./bootstrap-target.sh $APP to set it up."
  exit 0
fi

url="$(qa_clone_url "$TARGET_REPO")"

# Remote branches: report them, and figure out which to delete (all but the target branch).
branches="$(git ls-remote --heads "$url" 2>/dev/null | awk '{sub("refs/heads/","",$2); print $2}')"
others="$(printf '%s\n' "$branches" | grep -v "^$TARGET_BRANCH\$" || true)"

echo "Will reset '$TARGET_BRANCH' to a single empty commit (all files and history removed)."
if [ -n "$others" ]; then
  echo "Will delete these other branches (closing their PRs):"
  printf '%s\n' "$others" | sed 's/^/  /'
else
  echo "No other branches to delete."
fi

if [ $DRY -eq 1 ]; then echo "(dry-run) no changes made."; exit 0; fi

if [ $YES -ne 1 ]; then
  printf 'This is irreversible. Type the repo name to confirm (%s): ' "$TARGET_REPO"
  read -r reply
  [ "$reply" = "$TARGET_REPO" ] || qa_die "confirmation did not match; aborted."
fi

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
work="$tmp/repo"
git clone --depth 1 "$url" "$work" >/dev/null 2>&1 || qa_die "could not clone $TARGET_REPO"
cd "$work"

# Build an empty orphan commit and force it onto the target branch.
git checkout --orphan fresh >/dev/null 2>&1 || qa_die "could not create orphan branch"
git rm -rf . >/dev/null 2>&1 || true
qa_git commit --allow-empty -q -m "chore: reset target repo for a fresh start ($APP)"
git branch -M "$TARGET_BRANCH"
git push -f origin "$TARGET_BRANCH" >/dev/null 2>&1 || qa_die "force-push to $TARGET_BRANCH failed"
echo "reset: '$TARGET_BRANCH' is now a single empty commit."

# Delete every other remote branch.
if [ -n "$others" ]; then
  while IFS= read -r b; do
    [ -n "$b" ] || continue
    if git push origin --delete "$b" >/dev/null 2>&1; then
      echo "  deleted branch $b"
    else
      echo "  WARN: could not delete branch $b (protected or the repo's default branch?)"
    fi
  done <<EOF
$others
EOF
fi

echo
echo "done. The repo is empty. Next: ./bootstrap-target.sh $APP"
