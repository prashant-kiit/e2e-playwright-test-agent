#!/usr/bin/env bash
# Shared helpers for the QA target-repo tools (check-bootstrapped / bootstrap-target / push-artifacts).
# Source this file; do not run it directly. Works with the bash 3.2 that ships with macOS.
#
# The agent repo is the SOURCE OF TRUTH: these helpers copy files from here into a target repo,
# never the other way round. Everything an app needs is declared in apps/<app>/app.json.

# Repo root = parent of this script's directory.
QA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

qa_die() { echo "${QA_TOOL:-qa}: $*" >&2; exit 1; }
qa_need() { command -v "$1" >/dev/null 2>&1 || qa_die "missing dependency: $1"; }

qa_app_json() { echo "$QA_ROOT/apps/$1/app.json"; }
qa_field() { jq -r --arg k "$2" '.[$k] // ""' "$(qa_app_json "$1")"; }

# Infra files that define a runnable target repo (workspace-relative; pushed at the same path).
# This is the single list used by bootstrap and by the bootstrapped-check.
qa_infra_files() { # $1=app
  printf '%s\n' \
    package.json \
    package-lock.json \
    playwright.config.ts \
    .gitignore \
    .github/workflows/playwright.yml \
    "apps/$1/app.json" \
    "apps/$1/seed.spec.ts"
}

# Resolve an app -> APP, TARGET_REPO, TARGET_BRANCH (exported for the caller).
qa_resolve() { # $1=app
  APP="$1"
  [ -n "$APP" ] || qa_die "usage needs an <app> (a folder under apps/)"
  [ -f "$(qa_app_json "$APP")" ] || qa_die "no such app: apps/$APP/app.json not found"
  TARGET_REPO="$(qa_field "$APP" targetRepo)"
  TARGET_BRANCH="$(qa_field "$APP" targetBranch)"; [ -n "$TARGET_BRANCH" ] || TARGET_BRANCH="master"
  [ -n "$TARGET_REPO" ] && [ "$TARGET_REPO" != "owner/repo-that-receives-the-tests" ] \
    || qa_die "apps/$APP/app.json: set a real \"targetRepo\" (owner/repo)"
  export APP TARGET_REPO TARGET_BRANCH
}

# Load GITHUB_PAT from .env if not already in the environment (gh keyring is used otherwise).
qa_load_env() { if [ -z "${GITHUB_PAT:-}" ] && [ -f "$QA_ROOT/.env" ]; then set -a; . "$QA_ROOT/.env"; set +a; fi; }

# A token for pushing over HTTPS: prefer GITHUB_PAT, else gh's token.
qa_token() { if [ -n "${GITHUB_PAT:-}" ]; then printf '%s' "$GITHUB_PAT"; else gh auth token 2>/dev/null; fi; }

qa_clone_url() { local t; t="$(qa_token)"; [ -n "$t" ] || qa_die "no GitHub token (set GITHUB_PAT in .env or run: gh auth login)"; printf 'https://x-access-token:%s@github.com/%s.git' "$t" "$1"; }

# 0 if the target repo has at least one commit (409 from the API when empty).
qa_repo_has_commits() { gh api "repos/$1/commits?per_page=1" >/dev/null 2>&1; }

# 0 if <path> exists on <ref> of <repo>.
qa_file_on_branch() { gh api "repos/$1/contents/$2?ref=$3" >/dev/null 2>&1; }

# "bootstrapped" = the target branch carries this app's app.json AND playwright.config.ts.
qa_is_bootstrapped() { # $1=repo $2=app $3=branch
  qa_file_on_branch "$1" "apps/$2/app.json" "$3" && qa_file_on_branch "$1" "playwright.config.ts" "$3"
}

# Commit identity for machine-made commits in the target repo.
qa_git() { git -c user.name="qa-harness" -c user.email="qa-harness@users.noreply.github.com" "$@"; }
