#!/usr/bin/env bash
# Tool: bootstrap (or re-bootstrap) an app's target repo. SYNC mode, agent repo = source of truth.
#
#   ./bootstrap-target.sh <app> [--dry-run]
#
# Pushes this repo's infra files to the app's target repo so they match the agent repo exactly:
#   package.json, package-lock.json, playwright.config.ts, .gitignore,
#   .github/workflows/playwright.yml, apps/<app>/app.json, apps/<app>/seed.spec.ts
# - Empty target repo -> first bootstrap commit creates <targetBranch>.
# - Existing target repo -> re-bootstrap: only the files that differ are committed (no-op if in sync).
# This is how infra/workflow/config updates (e.g. a new CI report) reach already-delivered repos.
# It does NOT touch story artifacts (that's push-artifacts.sh). Reusable for any app.
set -u
QA_TOOL="bootstrap-target"
. "$(dirname "$0")/scripts/qa-lib.sh"

DRY=0; APP_ARG=""
for a in "$@"; do case "$a" in --dry-run) DRY=1;; -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0;; -*) qa_die "unknown option $a";; *) APP_ARG="$a";; esac; done

qa_need jq; qa_need gh; qa_need git
qa_resolve "$APP_ARG"
qa_load_env

echo "App:    $APP"
echo "Target: $TARGET_REPO ($TARGET_BRANCH)"
echo "Files:  $(qa_infra_files "$APP" | tr '\n' ' ')"

if [ $DRY -eq 1 ]; then echo "(dry-run) would sync the above infra files into $TARGET_REPO@$TARGET_BRANCH"; exit 0; fi

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
url="$(qa_clone_url "$TARGET_REPO")"
work="$tmp/repo"

if qa_repo_has_commits "$TARGET_REPO"; then
  mode="re-bootstrap"
  git clone --depth 1 --branch "$TARGET_BRANCH" "$url" "$work" >/dev/null 2>&1 \
    || qa_die "could not clone $TARGET_REPO branch $TARGET_BRANCH"
else
  mode="bootstrap"
  git clone --depth 1 "$url" "$work" >/dev/null 2>&1 || qa_die "could not clone $TARGET_REPO"
  ( cd "$work" && git checkout -b "$TARGET_BRANCH" >/dev/null 2>&1 ) || qa_die "could not create branch $TARGET_BRANCH"
fi

# Copy infra from the agent repo (source of truth) into the clone.
while IFS= read -r f; do
  [ -f "$QA_ROOT/$f" ] || qa_die "missing workspace file: $f"
  mkdir -p "$work/$(dirname "$f")"
  cp "$QA_ROOT/$f" "$work/$f"
done < <(qa_infra_files "$APP")

cd "$work"
git add -A
if git diff --cached --quiet; then
  echo "already in sync — nothing to push."
  exit 0
fi
echo "Changes to push:"; git --no-pager diff --cached --name-status | sed 's/^/  /'
qa_git commit -q -m "chore: $mode Playwright project ($APP)"
git push -u origin "$TARGET_BRANCH" >/dev/null 2>&1 || qa_die "push to $TARGET_REPO@$TARGET_BRANCH failed"
echo "done ($mode): pushed to $TARGET_REPO@$TARGET_BRANCH"
