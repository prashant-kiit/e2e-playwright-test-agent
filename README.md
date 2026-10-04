# e2e-playwright-test-agent

An **agentic QA harness**: a user story (markdown) goes in. Out come an automated, cross-browser Playwright test suite and a test plan. The agent **stops there for human review**; a human then delivers the suite as a pull request to a separate test repository, where CI runs the tests and generates the results report.

The work is done by **Claude Code**, using three Playwright sub-agents (planner, generator, healer) and the Playwright Test MCP server. The agent explores, plans, generates and heals the tests, then stops. **Delivery is a separate, human-initiated step**: a human reviews the generated code and runs `push-artifacts.sh`. Four shell tools for the target repo (`check-bootstrapped.sh`, `bootstrap-target.sh`, `push-artifacts.sh`, `reset-target.sh`) do the Git/GitHub work via `git`/`gh`, not a GitHub MCP. This repo contains no application code. It holds the configuration, prompts, agent definitions, tools and the artifacts the agents produce.

> **For coding agents:** read this file top to bottom before changing anything. The section [Gotchas](#9-gotchas-read-before-changing-things) records failures that already happened. Don't reintroduce them.

---

## 1. At a glance

| Item | Value |
|---|---|
| Agent runtime | Claude Code (CLI). OpenCode was used earlier and removed because it hung on complex Playwright work |
| Test framework | `@playwright/test` ^1.63 (TypeScript, no build step, no `tsconfig`) |
| Applications under test | One folder per app under [apps/](apps/). Each `apps/<app>/app.json` holds everything app-specific (URL, target repo, locator style, agent notes). Currently:<br>**[saucedemo](apps/saucedemo/)**, `https://www.saucedemo.com` (public demo shop, `standard_user` / `secret_sauce`) → [`prashant-kiit/e2e-playwright-agent-test-target`](https://github.com/prashant-kiit/e2e-playwright-agent-test-target)<br>**[practice-target](apps/practice-target/)**, `https://custom-test-target-app.vercel.app` (static UI sandbox; mock login `demo` / `password123` for `/dashboard` only) → [`prashant-kiit/e2e-playwright-test-custom-target`](https://github.com/prashant-kiit/e2e-playwright-test-custom-target) (still empty; the first run bootstraps it) |
| Input | One **active story** per run, named in [qa_user_prompt.md](qa_user_prompt.md) (`Active story: SCRUM-xxx`). The app is wherever `apps/*/user-stories/SCRUM-xxx-*.md` lives.<br>saucedemo: **SCRUM-101…107** (checkout, login, product catalog, product details, shopping cart, menu & navigation, dynamic catalog)<br>practice-target: **SCRUM-201…208** (auth, forms, buttons, modals, dropdowns, table, dynamic content, navigation) |
| Workflow definition | [qa_system_prompt.md](qa_system_prompt.md) (5 working steps + a stop-for-review step; the agent never delivers; all paths derived from the active story); kick-off prompt in [qa_user_prompt.md](qa_user_prompt.md) |
| This repo | `prashant-kiit/e2e-playwright-test-agent` (default branch `master`) |
| Current state | Only SCRUM-101 has been run: 22 test cases × 4 browser projects = 88/88 passing, 1 test healed, delivered as PR #1 to the SauceDemo target repo (merged). The other 14 stories have no plans or tests yet |

---

## 2. Adding or switching an application

**Switch to another story or app:** change the `Active story:` line in [qa_user_prompt.md](qa_user_prompt.md). That's all.

**Add a new app:**
1. Copy [apps/_template/](apps/_template/) to `apps/<new-app>/` (lower-case, no spaces; it becomes the project prefix).
2. Fill in `app.json`: `name`, `baseURL`, `targetRepo`, `targetBranch`, `locators`, `agentNotes`.
3. Write `seed.spec.ts` (bring the app to the starting state every agent session needs, e.g. logged in).
4. Add stories as `user-stories/<STORY_ID>-<slug>.md`. Story IDs must be unique across all apps. Keep each story lean (~2 acceptance criteria: one happy path + one key negative) to control token cost; see `apps/_template/user-stories/`.
5. Check it: `npx playwright test apps/<new-app>/seed.spec.ts` should pass on the 4 new `<new-app>-*` projects.

Nothing else changes: `playwright.config.ts` discovers the folder, and the prompt derives every path (plan, tests, report, evidence, branch, PR title) from the story file.

**Run several stories of one app at once:** [run-stories.sh](run-stories.sh) starts one headless Claude Code session per story, in parallel. All stories in a batch must belong to the same app; a batch that mixes apps is refused, so run one batch per app.

```bash
./run-stories.sh SCRUM-201 SCRUM-202 SCRUM-205     # specific stories of one app
./run-stories.sh practice-target                   # every story of an app
./run-stories.sh -j 2 -w 1 saucedemo               # 2 sessions at a time, 1 Playwright worker each
./run-stories.sh --force SCRUM-201                 # redo a story already marked done
./run-stories.sh --dry-run practice-target         # show what would run; costs nothing
```

- Defaults: 3 sessions at a time (`-j`), 2 Playwright workers per session (`-w`), sessions started 5 s apart. Each session costs as much as an interactive run.
- Each session gets `qa_user_prompt.md` with its own `Active story:`, `Mode: unattended` and `Run-ID:` lines. The prompt's "Unattended (batch) runs" rules apply: no questions (safe defaults, recorded in the session's final summary), only its own story's files, and no delivery (the agent stops after healing; the run-id is stamped into `.qa-state.json`).
- **Reruns are safe (e.g. after a session limit).** State is tracked per story in `.qa-state.json` (git-ignored, survives deleting `runs/`). On a rerun:
  - a story already **generated** (marked `ready` in state, or whose test suite is already committed) is **skipped** — add `--force` to redo it;
  - any other story has its previous generated files (plan, tests) **wiped, then regenerated from scratch**, so a story's artifacts never mix two runs.
- Artifacts stay at their stable paths (`apps/<app>/specs|tests/`); the run-id is metadata (in `.qa-state.json`), so CI and the later human delivery are unaffected.
- The `--dry-run` output shows, per story, whether it would `run` or `skip` and why.
- **The agent never delivers** (in batch or interactively). After the batch, a human reviews each `ready` story and runs `./push-artifacts.sh <app> <STORY_ID>` to open/update its PR. The batch summary prints that command.
- **The batch refuses to start unless the app's target repo is bootstrapped** (it runs `./check-bootstrapped.sh <app>` up front). If not, run `./bootstrap-target.sh <app>` first.
- Sessions share this folder. Each story writes only its own files, and each session's Playwright output goes to `runs/<timestamp>-<app>/<STORY_ID>/` (via `QA_RUN_DIR`), so parallel test runs can't wipe each other.
- Per story: `session.jsonl` (full transcript, stream-json), `stderr.log`, `result.md` (the session's final summary), `clean.log` (files wiped before the redo), `test-results/`, `playwright-report/`. Overall: `runs/<timestamp>-<app>/summary.md`, one row per story with status, minutes, cost and the tests path. Status: **ready** = tests generated+healed, awaiting human review/delivery; **incomplete** = session ended but no test suite (rerun to finish); **failed** = session errored (e.g. hit the limit); **skipped** = already generated.
- Headless sessions deny tool calls that aren't allowed in `.claude/settings.json` (or by the script) instead of asking. If a story stalls, search its `session.jsonl` for denied calls.
- Ctrl-C stops all running sessions. `GITHUB_PAT` is loaded from `.env` if it isn't already set.

---

## 3. How the pipeline works

```
apps/<app>/user-stories/<STORY_ID>-<slug>.md      (+ apps/<app>/app.json)
        │
        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Claude Code main session (orchestrator), driven by qa_system_prompt.md   │
│                                                                          │
│  1 Read story ──► 2 playwright-test-planner ──► apps/<app>/specs/        │
│                       (explores the live app in a browser)               │
│                ──► 3 Exploratory testing (main session, MCP browser tools)│
│                ──► 4 playwright-test-generator ──► apps/<app>/tests/<slug>/
│                ──► 5 playwright-test-healer (Chromium only; CI runs all 4)       
│                ──► 6 STOP for human review (no delivery, no report)       │
└──────────────────────────────────────────────────────────────────────────┘
        │
        ▼  (human reviews the generated tests)
   ./push-artifacts.sh <app> <STORY_ID>   ──►  branch + PR in app.json target
        │
        ▼
<targetRepo>  <targetBranch> ◄── PR from qa/<STORY_ID>-<slug>  (its CI runs the tests)
```

**Who does what:**
- The **main session** orchestrates the steps: step 1 (read story), step 3 (exploratory testing with the `mcp__playwright-test__browser_*` tools), and step 6 (stop with a final summary). **It does not touch the target repo or deliver** — it needs no GitHub access.
- **A human** reviews the generated tests and runs `./push-artifacts.sh <app> <STORY_ID>` to open the PR — in both batch and interactive modes.
- **Sub-agents can't call other sub-agents.** All hand-offs happen through files on disk (`apps/<app>/specs/`, `tests/`) and through the main session.
- Steps 2, 4 and 5 are delegated to the sub-agents in [.claude/agents/](.claude/agents/).

### The steps (summary of qa_system_prompt.md)

Steps 1–6 are the agent's work; it stops at step 6. Delivery is a separate human step (below the table).

| Step | Actor | Output |
|---|---|---|
| 1 Read user story | main session | Resolved paths and app settings, summary of ACs, URL, credentials (no target-repo check — bootstrap is a delivery concern) |
| 2 Create test plan | `playwright-test-planner` | `apps/<app>/specs/<STORY_ID>-<slug>-test-plan.md` (scenarios with steps, expected results and the stable locators found) |
| 3 Exploratory testing | main session + Playwright MCP | Findings, screenshots, the locators that worked |
| 4 Generate scripts | `playwright-test-generator` | `apps/<app>/tests/<slug>/*.spec.ts`, verified on `<app>-chromium` |
| 5 Execute and heal | `playwright-test-healer` | Green on the app's Chromium project. Cross-browser is left to the target repo's CI (token saving) |
| 6 Stop for human review | main session | A short final summary (no file, no PR). The agent does not deliver |
| — Deliver (human) | human + `push-artifacts.sh` | After reviewing the tests, a human runs `./push-artifacts.sh <app> <STORY_ID>`: syncs story+plan+tests to `qa/<STORY_ID>-<slug>` and opens/updates a PR into `targetBranch` (repo must be bootstrapped). The results report is generated by CI |

---

## 4. Repository map

```
.
├── .claude/
│   ├── agents/                         # Sub-agent definitions (generated by `npx playwright init-agents --loop=claude`)
│   │   ├── playwright-test-planner.md    # explores app → saves a test plan (model: sonnet)
│   │   ├── playwright-test-generator.md  # plan → test files (model: sonnet)
│   │   └── playwright-test-healer.md     # runs/debugs/fixes failing tests; only agent with Edit/Write (model: sonnet)
│   ├── hooks/
│   │   └── close-test-browsers.sh      # closes paused test browsers (see §7.3)
│   ├── settings.json                   # shared Claude Code settings: env, permissions, hooks (committed)
│   └── settings.local.json             # per-user approvals (git-ignored)
├── .github/workflows/playwright.yml    # CI: runs tests + writes the results report to the Job Summary
├── .mcp.json                           # MCP servers for Claude Code: playwright-test (stdio)
├── check-bootstrapped.sh               # tool: is a target repo bootstrapped for an app?
├── bootstrap-target.sh                 # tool: sync infra to a target repo (bootstrap/re-bootstrap)
├── push-artifacts.sh                   # tool: deliver a story's artifacts as a PR (sync)
├── reset-target.sh                     # tool: wipe a target repo to a fresh, empty state (destructive)
├── scripts/qa-lib.sh                   # shared helpers for the four tools
├── .env.example                        # template: GITHUB_PAT= (copy to .env, which is git-ignored)
├── apps/
│   ├── _template/                      # copy this to add an app (skipped by the config)
│   ├── saucedemo/
│   │   ├── app.json                    # baseURL, targetRepo, locators, agentNotes
│   │   ├── seed.spec.ts                # logs in → /inventory.html
│   │   ├── user-stories/SCRUM-10x-*.md # SCRUM-101…107
│   │   ├── specs/SCRUM-101-checkout-test-plan.md      # generated (22 scenarios)
│   │   ├── tests/checkout/             # generated suite for SCRUM-101, 9 files / 22 tests
│   │   └── reports/                    # legacy SCRUM-101/103 reports (reports are now generated by CI, not the agent)
│   └── practice-target/
│       ├── app.json
│       ├── seed.spec.ts                # opens / (not logged in)
│       └── user-stories/SCRUM-20x-*.md # SCRUM-201…208 (specs/, tests/ appear when run; no agent report)
├── playwright.config.ts                # discovers apps/*/app.json → <app>-<browser> projects; timeouts, reporters
├── run-stories.sh                      # batch runner: one headless session per story, in parallel
├── qa_system_prompt.md                 # THE workflow: 5 steps + stop-for-review, path conventions
├── qa_user_prompt.md                   # kick-off prompt: names the active story
├── TASK.md                             # the owner's running backlog / roadmap (see §11)
├── package.json / package-lock.json    # only devDeps: @playwright/test, @types/node; no npm scripts
└── LICENSE
```

**Generated or ignored (never commit):**

| Path | What it is |
|---|---|
| `node_modules/` | npm dependencies |
| `test-results/` | Playwright per-run output. **Wiped at the start of every run** |
| `playwright-report/` | HTML report |
| `runs/` | Batch runs from `run-stories.sh`: per-story transcripts, results and Playwright output |
| `.playwright-mcp/` | MCP console logs, page snapshots, and the hook log `close-test-browsers.log` |
| `.env` | Real secrets |
| `.claude/settings.local.json` | Per-user Claude Code approvals |

`.gitignore` is a large Python template with a Playwright and a Claude Code section appended at the end.

### Generated test suite (`apps/saucedemo/tests/checkout/`)

> This table describes the **original** SCRUM-101 delivery (22 tests, 4 browsers). The stories have since been trimmed to a lean ~2-AC scope and the agent now generates/heals on Chromium only, so a re-run (`--force`) produces a smaller suite. The table is kept as a reference of the generator's output shape.


| File | Tests | Covers |
|---|---|---|
| `cart-review.spec.ts` | 4 | AC1: cart contents, details, continue shopping / checkout |
| `checkout-info.spec.ts` | 1 | AC2: reach and fill the information page |
| `checkout-info-validation.spec.ts` | 6 | AC2/AC5: each mandatory field and its error message |
| `checkout-info-edgecases.spec.ts` | 2 | AC5: special characters / whitespace (accepted by the app, documented as observations) |
| `order-overview.spec.ts` | 3 | AC3: items, payment/shipping info, subtotal + tax = total |
| `order-completion.spec.ts` | 2 | AC4: confirmation page, Back Home, cart cleared |
| `navigation-cancel.spec.ts` | 2 | Business rule 5: cancel from each checkout step |
| `e2e-happy-path.spec.ts` | 1 | Full purchase flow |
| `ui-validation.spec.ts` | 1 | UI elements present |

Test file conventions used by the generator:
- Header comments `// spec: apps/<app>/specs/...` and `// seed: apps/<app>/seed.spec.ts`.
- `test.describe` per AC.
- A `beforeEach` that **repeats the seed's setup steps**. Tests don't import the seed.
- Locators as described in the app's `app.json` `locators`.
- Relative URLs.
- No fixed waits.

---

## 5. Components in detail

### 4.1 MCP servers ([.mcp.json](.mcp.json))

| Server | Transport | Purpose |
|---|---|---|
| `playwright-test` | stdio: `npx playwright run-test-mcp-server` | Browser automation and test-runner tools (`browser_*`, `planner_*`, `generator_*`, `test_run`, `test_debug`, `test_list`). Reads `playwright.config.ts` |

Delivery to the target repo is **not** done through an MCP server. It uses the shell tools in §4.6 via `git` and the `gh` CLI.

**How the `playwright-test` server gives an agent a browser:** `planner_setup_page` / `generator_setup_page` run the `seedFile` they're given (`apps/<app>/seed.spec.ts`) in the given `project` (`<app>-chromium`). Without a `project` they use the first project (whichever app sorts first), and without a `seedFile` they create a default seed, so the prompt always passes both. The test is then **paused at its end**, and the agent drives that live page with `browser_*` tools.

Consequences:
- The browser stays open until the paused worker process goes away. `browser_close` only closes the tab. See §7.3.
- The paused test has **no test timeout**, so the only limits on a stuck click or fill are `actionTimeout` / `navigationTimeout` from the config. See §7.1.
- The server runs headed by default. Add `"--headless"` to its `args` for sandbox/CI use.

### 4.2 Sub-agents ([.claude/agents/](.claude/agents/))

These were generated by `npx playwright init-agents --loop=claude`; re-running that command overwrites them. Each file has YAML frontmatter (`name`, `description`, `tools`, `model: sonnet`, `color`) followed by its system prompt.

| Agent | Can edit files? | Key MCP tools |
|---|---|---|
| `playwright-test-planner` | No (saves via `planner_save_plan`) | `planner_setup_page`, `browser_*` (incl. `browser_run_code_unsafe`), `planner_save_plan` |
| `playwright-test-generator` | No (writes via `generator_write_test`) | `generator_setup_page`, `browser_*`, `generator_read_log`, `generator_write_test` |
| `playwright-test-healer` | Yes (`Edit`, `MultiEdit`, `Write`) | `test_run`, `test_debug`, `test_list`, `browser_snapshot`, `browser_generate_locator`, console/network tools |

### 4.3 Playwright config ([playwright.config.ts](playwright.config.ts))

| Setting | Value | Why |
|---|---|---|
| `testDir` | `./tests` | Includes each app's seed (it runs as a normal test too) |
| `outputDir`, HTML report folder | `test-results/`, `playwright-report/`; under `$QA_RUN_DIR` when set | `run-stories.sh` sets `QA_RUN_DIR` per story so parallel runs keep separate output |
| `workers` | 1 on CI; `$QA_WORKERS` when set; otherwise Playwright's default | `run-stories.sh` sets `QA_WORKERS` (default 2) so parallel sessions don't overload the machine |
| `baseURL` (per project) | Read from each `apps/<app>/app.json`. There is no global default | Tests and the seeds use relative URLs. The config throws if an `app.json` has no `baseURL` |
| `use.actionTimeout` | `10_000` | **Required.** Playwright's default is no limit, and a paused MCP test has no test timeout, so a click on a missing or hidden element would hang forever (this happened: a 58-minute hang) |
| `use.navigationTimeout` | `15_000` | Same reason, for navigations |
| `reporter` | `[['list'], ['html', { open: 'never' }]]` | `open: 'never'` stops a failing local run from blocking on the HTML report server |
| `retries` | 2 on CI, 0 locally | Standard |
| `trace` | `on-first-retry` | Standard |
| `projects` | Generated: for every `apps/<app>/app.json` (folders starting with `_` skipped), `<app>-chromium`, `<app>-firefox`, `<app>-webkit`, `<app>-mobile-chrome` (Pixel 7), each with `testDir: apps/<app>` | Adding an app never touches the config. Project order is alphabetical by app, so nothing may rely on the default first project: always pass `project` to the MCP setup tools |

### 4.4 Claude Code settings ([.claude/settings.json](.claude/settings.json))

| Key | Value | Purpose |
|---|---|---|
| `env.MCP_TOOL_TIMEOUT` | `120000` | Backup limit: any single MCP tool call is cancelled after 2 minutes. Applies to sessions started after the change |
| `enabledMcpjsonServers` | `playwright-test` | Pre-approves the project's MCP server |
| `permissions.allow` | `mcp__playwright-test`, `Bash(npx playwright test:*)`, `Bash(npx playwright show-report:*)`, `Edit(apps/*/specs/**)`, `Edit(apps/*/tests/**)`, `Edit(apps/*/reports/**)` | Steps 1–6 run without prompts. The agent does no GitHub/target-repo work, so **neither `check-bootstrapped.sh` nor `push-artifacts.sh` is allowed** — both are human/`run-stories.sh` concerns. If `push-artifacts.sh` were ever invoked in-session it would be stopped by this permission. |
| `hooks.SubagentStop`, `hooks.SessionEnd` | `"$CLAUDE_PROJECT_DIR"/.claude/hooks/close-test-browsers.sh` (timeout 15s) | Closes paused test browsers (§7.3) |

Note: in permission rules, `Edit(path)` covers every file-writing tool. `Write(path)` rules are not matched by file permission checks, so don't add them.

### 4.5 CI ([.github/workflows/playwright.yml](.github/workflows/playwright.yml))

GitHub-hosted `ubuntu-latest`, triggered on push/PR to `main`/`master`. The steps:
1. `npm ci`
2. `npx playwright install --with-deps`
3. `npx playwright test --reporter=list,html,json` (all the app's projects, including the seed test)
4. **Write the results report to the run's Job Summary** — a per-project pass/fail/flaky/skipped table built from `results.json` with `jq` (no third-party actions, no extra permissions)
5. Upload `playwright-report/` as an artifact (30 days)
6. Fail the job if any test failed (step 3 runs with `continue-on-error` so the summary and artifact are always produced first)

**This is where the QA report comes from — CI, not the agent.** It needs **no secrets**: it doesn't run Claude Code or the agents. The same workflow file is pushed to the target repo during bootstrap (`bootstrap-target.sh`), so each target repo produces its own report on every PR.

### 4.6 Target-repo tools (`check-bootstrapped.sh`, `bootstrap-target.sh`, `push-artifacts.sh`, `reset-target.sh`)

Target-repo work is done by four reusable shell tools (any app in `apps/<app>/`), via `git` and the `gh` CLI — there is no GitHub MCP. Shared helpers live in [scripts/qa-lib.sh](scripts/qa-lib.sh); each tool reads `targetRepo`/`targetBranch` from `apps/<app>/app.json`. The **agent repo is the source of truth**: the tools copy from here into the target, never the reverse.

| Tool | What it does |
|---|---|
| `./check-bootstrapped.sh <app>` | Read-only. Exit 0 if `apps/<app>/app.json` and `playwright.config.ts` exist on the target's `targetBranch`, else exit 1 with the bootstrap hint. Used by `run-stories.sh` as the up-front batch gate (and by a human before an interactive run if they want to check). The agent does not run it. |
| `./bootstrap-target.sh <app> [--dry-run]` | Sync the infra files (package manifests, `playwright.config.ts`, `.gitignore`, the workflow, the app's `app.json` and seed) to `targetBranch`. First commit on an empty repo; on an existing one, commits only changed files (`--dry-run` previews). This is how infra/workflow/config updates reach already-delivered repos. |
| `./push-artifacts.sh <app> <STORY_ID> [--body-file F] [--run-id R] [--dry-run]` | Deliver one story: sync its story, plan and test suite onto `qa/<STORY_ID>-<slug>` (tests folder replaced wholesale), reuse the branch and update the PR on reruns, open/update the PR into `targetBranch`, print the PR URL. Requires the repo to be bootstrapped; pushes no report/evidence/infra. |
| `./reset-target.sh <app> [--yes] [--dry-run]` | **Destructive.** Wipe the target repo to a fresh, empty state: replace `targetBranch` with a single empty commit (all files and history gone) and delete every other branch (closing their PRs). Asks you to type the repo name to confirm (skip with `--yes`); `--dry-run` previews; an already-empty repo is a no-op. Does NOT re-bootstrap — run `./bootstrap-target.sh <app>` afterwards. Leaves the agent repo untouched. |

Auth: the tools use `GITHUB_PAT` (from `.env`) if set, otherwise `gh`'s own login. All four tools are **run by a human or by `run-stories.sh`** (`check-bootstrapped.sh` only), never by the agent — the test-writing agent does no GitHub work and needs no credentials. None of them is in the agent's allow-list.

---

## 6. Setup and running

### 5.1 Prerequisites

- Node.js (LTS) and npm
- Claude Code CLI (`claude`)
- `git`, the GitHub CLI (`gh`) and `jq` — the delivery tools use them
- GitHub access to each target repo, via `gh auth login` and/or a `GITHUB_PAT` in `.env`. It needs push + pull-request rights, and Workflows write (bootstrap pushes `.github/workflows/playwright.yml`).

### 5.2 One-time setup

```bash
npm ci
npx playwright install --with-deps
cp .env.example .env        # then put the real token in .env: GITHUB_PAT=...
```

### 5.3 Run the QA flow

First make sure the active app's target repo is bootstrapped (one-time per repo, and again
after any infra/workflow/config change):

```bash
./check-bootstrapped.sh <app>     # e.g. saucedemo — exits non-zero if not ready
./bootstrap-target.sh  <app>      # sync infra to the target repo (bootstrap or re-bootstrap)
```

To start a target repo over from scratch (wipe all history, branches and PRs), reset it first,
then re-bootstrap:

```bash
./reset-target.sh <app> --dry-run   # preview what would be wiped
./reset-target.sh <app>             # destructive; type the repo name to confirm
./bootstrap-target.sh <app>         # rebuild the clean infra
```

Then run the flow:

```bash
set -a; source .env; set +a   # GITHUB_PAT available to the delivery tools / gh
claude                        # /mcp should show playwright-test connected
```

Then paste the contents of [qa_user_prompt.md](qa_user_prompt.md). (The agent does not check bootstrap — run `./check-bootstrapped.sh <app>` yourself first if you want to confirm there's somewhere to deliver.) Expect a visible browser window during steps 2–5. The agent **stops after step 5** with the healed suite in `apps/<app>/tests/<slug>/` and a summary — it does not deliver. Review the generated tests, then deliver with:

```bash
./push-artifacts.sh <app> <STORY_ID>     # e.g. ./push-artifacts.sh saucedemo SCRUM-101
```

(Batch runs via `run-stories.sh` run the bootstrap check automatically but, like interactive runs, stop at step 5 — you deliver each `ready` story with `./push-artifacts.sh` afterwards.)

### 5.4 Run the tests directly

```bash
npx playwright test                                         # all projects
npx playwright test apps/saucedemo/tests/checkout/ --project=saucedemo-chromium
npx playwright test apps/*/seed.spec.ts                     # smoke check of every app + config
npx playwright show-report                                  # open the last HTML report
```

### 5.5 Secrets

- The only secret is `GITHUB_PAT`.
- **Locally:** keep it in `.env` (git-ignored) and load it with `set -a; source .env; set +a`.
- **CI/sandbox:** inject it as a platform secret (e.g. a GitHub Actions secret named `GITHUB_PAT`; `GITHUB_TOKEN` is a reserved name).
- Never put a real value in `.env.example`, `.mcp.json` or any committed file.
- In a container, pass it at run time (`docker run -e GITHUB_PAT`), never at build time.

---

## 7. Reliability mechanisms

### 6.1 Timeouts (no infinite hangs)

- **What happened:** an agent's `browser_click` on a hidden menu link waited 58 minutes, and a `browser_run_code_unsafe` waited for a form field that no longer existed.
- **Root cause:** Playwright's default `actionTimeout` is 0 (unlimited), and a paused MCP test has no test timeout.
- **Fix:**
  - `actionTimeout: 10_000` and `navigationTimeout: 15_000` in the config. A stuck action now fails after 10 seconds with a reason like "element is not visible", which the agent can recover from.
  - `MCP_TOOL_TIMEOUT=120000` in settings as a backup.

### 6.2 Reports

The QA results report is generated by **CI** (the Job Summary of each `playwright.yml` run), not by the agent — see §4.5. The agent writes no report file; it only puts a short scope summary in the PR body. (`apps/saucedemo/reports/` still holds the earlier SCRUM-101/103 reports from before this change.)

### 6.3 Graceful browser shutdown ([.claude/hooks/close-test-browsers.sh](.claude/hooks/close-test-browsers.sh))

- **Problem:** after an agent finishes, its paused seed-test worker keeps the browser open. A paused worker never exits by itself, even after its browser closes.
- **When the hook runs:**
  - On `SubagentStop`, only when `agent_type` starts with `playwright-test-`, so another sub-agent finishing doesn't close a browser the main session is using.
  - On `SessionEnd`.
- **What it does:**
  1. Finds the `claude` process that fired the hook, then that session's `run-test-mcp-server` node process.
  2. Sends SIGTERM to its child worker(s). Playwright then closes the browser cleanly, measured at under 1 second.
  3. Waits up to 5 seconds for the browser processes to exit, and force-kills them only if they don't.
  4. Force-kills the now-empty worker.
- **What it leaves alone:** the MCP server stays up and starts a fresh worker on the next `*_setup_page`. Other Claude Code sessions are never touched.
- **Log:** `.playwright-mcp/close-test-browsers.log`. Review or disable the hooks with `/hooks`.

Manual fallback: `pkill -f "Google Chrome for Testing"`. This closes only Playwright's bundled Chromium, not the user's Chrome.

---

## 8. Delivery contract (human step, target repo)

Delivery is a **human-initiated step** after reviewing the agent's generated tests. It is handled by the delivery tools in §4.6 (`check-bootstrapped.sh`, `bootstrap-target.sh`, `push-artifacts.sh`), not by an MCP server, by the agent, or by hand-crafted git. The agent repo is the source of truth.

0. Deliver to the **active app's** target repo (from `apps/<app>/app.json`). Never mix apps in one repo.
1. **Bootstrap is separate from delivery.** `bootstrap-target.sh <app>` syncs the infra (`package.json`, `package-lock.json`, `playwright.config.ts`, `.gitignore`, `.github/workflows/playwright.yml`, `apps/<app>/app.json`, `apps/<app>/seed.spec.ts`) to the target repo — creating the first commit on an empty repo, or updating changed files on an existing one. Run it after any infra/workflow/config change so existing repos pick it up.
2. **The batch refuses to run against a repo that isn't bootstrapped.** `check-bootstrapped.sh <app>` (true when `apps/<app>/app.json` and `playwright.config.ts` exist on `targetBranch`) is run up front by `run-stories.sh`; if false it stops and tells you to bootstrap. The agent itself does not check — it only writes tests — and `push-artifacts.sh` re-checks at delivery.
3. **Delivery is a human step** run after review: `push-artifacts.sh <app> <STORY_ID>` syncs the story, plan and test suite onto `qa/<STORY_ID>-<slug>` (replacing the tests folder wholesale, so deletions propagate), reuses the branch and updates the PR on reruns, and opens/updates the PR into `targetBranch`. No report or evidence is pushed (CI generates the report). It never pushes infra or another app's folder. The agent does not run this tool.

App-specific delivery facts live in that app's `agentNotes`. Currently: the SauceDemo repo has history (bootstrap done, PR #1 merged, branch `qa/SCRUM-101-checkout` exists) and still has the pre-refactor paths (`user-stories/scrum-latest.md`, `specs/saucedemo-checkout-test-plan.md`, `tests/seed.spec.ts`, `tests/saucedemo-checkout/`, `reports/SCRUM-101-checkout-test-report.md`), which the next SauceDemo delivery should delete. The Practice Target repo is empty, so its first delivery does the bootstrap.

---

## 9. Gotchas (read before changing things)

| Symptom / temptation | Reality |
|---|---|
| Removing `actionTimeout` / `navigationTimeout` | Agents will hang indefinitely on missing elements (§7.1) |
| Writing outputs under `test-results/` | They are deleted on the next test run |
| `push-artifacts.sh`/`bootstrap-target.sh`/`reset-target.sh`: auth or push fails | No `GITHUB_PAT` in `.env` and `gh` not logged in, or the token lacks push/PR/Workflows rights to the target repo (`reset-target.sh` also needs force-push and branch-delete rights). Fix `.env` or run `gh auth login` |
| Using `${input:...}` in `.mcp.json` | That's VS Code syntax. Claude Code only supports `${VAR}` / `${VAR:-default}` |
| Relying on the default MCP project | Projects are generated alphabetically per app. Always pass `project: <app>-chromium` and `seedFile` to `*_setup_page` |
| Editing `playwright.config.ts` to add an app | Not needed. Add `apps/<app>/app.json`; folders starting with `_` are ignored |
| Agent opens the burger menu via `browser_evaluate` (JS click) and then clicks a menu item | The menu stays `aria-hidden`, so the item is never visible. Open it with a real `browser_click` on `[data-test="open-menu"]` (or the "Open Menu" button) |
| Assuming SauceDemo rejects whitespace or special characters in checkout fields | It accepts them and moves to step two. Tests document this as an observation, not a defect, so code that re-fills the form afterwards will fail |
| Cart page "total price" (AC1) | SauceDemo shows no total on the cart page. Totals appear on the overview page (AC3). This is documented in the report |
| Adding `Write(...)` permission rules | They have no effect. Use `Edit(...)` |
| Re-running `npx playwright init-agents` | Overwrites `.claude/agents/*` and `.mcp.json` (which now has only `playwright-test` — delivery no longer uses an MCP server) |
| `.playwright-mcp/` filling up | Expected (MCP logs and snapshots). It's git-ignored and safe to delete |

---

## 10. Debugging a stuck or failed run

1. **Playwright MCP server log** (fastest):
   `~/Library/Caches/claude-cli-nodejs/-Users-prashant-Desktop-Project-e2e-playwright-test-agent/mcp-logs-playwright-test/*.jsonl`
   A repeating `Tool '<name>' still running (Ns elapsed)` means that call is stuck. The preceding `Calling MCP tool` line names it.
2. **Session and sub-agent transcripts:**
   `~/.claude/projects/-Users-prashant-Desktop-Project-e2e-playwright-test-agent/<session-id>.jsonl` and `.../<session-id>/subagents/agent-*.jsonl`. These hold the exact tool arguments, e.g. the selector or code that hung.
3. **Browser console and page snapshots:** `.playwright-mcp/console-*.log`, `.playwright-mcp/page-*.yml`.
4. **Browser cleanup log:** `.playwright-mcp/close-test-browsers.log`.
5. **While a run is live:** watch the headed browser. An idle page while Claude Code waits on a tool call means a stuck action; press Esc to cancel that call without killing the flow.

(Cache and transcript paths are derived from the project's absolute path and differ on another machine.)

---

## 11. Roadmap and open questions

[TASK.md](TASK.md) is the owner's backlog. Items 1–2 and 4 refer to the abandoned OpenCode setup and are historical. Open themes:

- **Sandboxed, unattended runs:**
  - Each test run in a fresh Claude Code session inside a sandbox.
  - Headless browser (`--headless` in `.mcp.json`).
  - Delivery is a deliberate human step after review (`./push-artifacts.sh`); the agent never delivers in any mode.
  - Defining what lives inside vs outside the sandbox, and how permissions are managed there.
- **Triggering:** target app → this agent → PR to a test repo → that repo's CI runs `npx playwright test`.
- **Human in the loop:** questions Claude Code asks should appear in a frontend, with answers flowing back.
- **Scope control:**
  - Generate tests only for what changed (git history).
  - Split agents into bounded scenarios.
  - Commit/push in batches rather than one bulk commit.
- **Robustness:** timeouts (done, §7.1), monitoring logs, resuming after a failure, multi-tenant sessions.
- **Artifacts and versioning:**
  - A custom test target with versioned tests and user stories.
  - Whether artifacts belong in the repo/file storage or in object storage (e.g. S3).
- **Hygiene:** remove unused files and stay minimal.

---

## 12. Rules for agents working in this repo

- Treat [qa_system_prompt.md](qa_system_prompt.md) as the source of truth for the workflow and file paths. If you change the folder convention, update the prompt, the config, `.claude/settings.json` permissions and this README together.
- Don't hard-code secrets. `GITHUB_PAT` comes from the environment only.
- Keep the action/navigation timeouts. App-specific settings belong in `apps/<app>/app.json`, never in the config or the prompt.
- Generated artifacts belong in `apps/<app>/specs/` and `apps/<app>/tests/<slug>/`. The results report is generated by CI (§4.5), not written here. Don't hand-edit generated tests unless you're acting as the healer.
- Run `npx playwright test apps/*/seed.spec.ts` after any config change. Every app's seed should pass on its 4 projects.
- Don't commit `test-results/`, `playwright-report/`, `.playwright-mcp/`, `.env` or `.claude/settings.local.json`.
