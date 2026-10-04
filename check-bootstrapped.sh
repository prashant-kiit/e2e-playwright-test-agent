#!/usr/bin/env bash
# Tool: is a target repo bootstrapped for an app?
#
#   ./check-bootstrapped.sh <app>
#
# Exit 0 (and print "bootstrapped: ...") if the app's target repo+branch already carries the
# infra (apps/<app>/app.json and playwright.config.ts). Exit 1 otherwise, telling you to
# bootstrap. Read-only: it never writes. Reusable for any app in apps/<app>/.
set -u
QA_TOOL="check-bootstrapped"
. "$(dirname "$0")/scripts/qa-lib.sh"

qa_need jq; qa_need gh
qa_resolve "${1:-}"
qa_load_env

if qa_is_bootstrapped "$TARGET_REPO" "$APP" "$TARGET_BRANCH"; then
  echo "bootstrapped: $TARGET_REPO ($TARGET_BRANCH) is ready for app '$APP'"
  exit 0
else
  echo "NOT bootstrapped: $TARGET_REPO ($TARGET_BRANCH) is missing infra for app '$APP'." >&2
  echo "Run:  ./bootstrap-target.sh $APP" >&2
  exit 1
fi
