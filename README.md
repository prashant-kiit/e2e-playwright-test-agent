# e2e-playwright-test-agent

An **agentic QA harness**: a user story (markdown) goes in. Out come an automated, cross-browser Playwright test suite, a test plan and an execution report, all delivered as a pull request to a separate test repository.

The work is done by **Claude Code**, using three Playwright sub-agents (planner, generator, healer) and two MCP servers (Playwright Test, GitHub). This repo contains no application code. It holds the configuration, prompts, agent definitions and the artifacts the agents produce.

> **For coding agents:** read this file top to bottom before changing anything. The section [Gotchas](#9-gotchas-read-before-changing-things) records failures that already happened. Don't reintroduce them.

---

## 1. At a glance

| Item | Value |
|---|---|
| Agent runtime | Claude Code (CLI). OpenCode was used earlier and removed because it hung on complex Playwright work |
| Test framework | `@playwright/test` ^1.63 (TypeScript, no build step, no `tsconfig`) |
| Applications under test | One folder per app under [apps/](apps/). Each `apps/<app>/app.json` holds everything app-specific (URL, target repo, locator style, agent notes). Currently:<br>**[saucedemo](apps/saucedemo/)**, `https://www.saucedemo.com` (public demo shop, `standard_user` / `secret_sauce`) → [`prashant-kiit/e2e-playwright-agent-test-target`](https://github.com/prashant-kiit/e2e-playwright-agent-test-target)<br>**[practice-target](apps/practice-target/)**, `https://custom-test-target-app.vercel.app` (static UI sandbox; mock login `demo` / `password123` for `/dashboard` only) → [`prashant-kiit/e2e-playwright-test-custom-target`](https://github.com/prashant-kiit/e2e-playwright-test-custom-target) (still empty; the first run bootstraps it) |
| Input | One **active story** per run, named in [qa_user_prompt.md](qa_user_prompt.md) (`Active story: SCRUM-xxx`). The app is wherever `apps/*/user-stories/SCRUM-xxx-*.md` lives.<br>saucedemo: **SCRUM-101…107** (checkout, login, product catalog, product details, shopping cart, menu & navigation, dynamic catalog)<br>practice-target: **SCRUM-201…208** (auth, forms, buttons, modals, dropdowns, table, dynamic content, navigation) |
| Workflow definition | [qa_system_prompt.md](qa_system_prompt.md) (7 steps, all paths derived from the active story); kick-off prompt in [qa_user_prompt.md](qa_user_prompt.md) |
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
- Each session gets `qa_user_prompt.md` with its own `Active story:`, `Mode: unattended` and `Run-ID:` lines. The prompt's "Unattended (batch) runs" rules apply: no questions (safe defaults, recorded in the report), only its own story's files, and the run-id stamped into the report and PR body.
- **Reruns are safe (e.g. after a session limit).** State is tracked per story in `.qa-state.json` (git-ignored, survives deleting `runs/`). On a rerun:
  - a story already **delivered** (PR recorded in state, or its report already committed) is **skipped** — add `--force` to redo it;
  - any other story has its previous generated files (plan, tests, report, evidence) **wiped, then regenerated from scratch**, so a story's artifacts never mix two runs;
  - the branch stays `qa/<STORY_ID>-<slug>` and is updated in place (one branch and one PR per story across reruns).
- Artifacts stay at their stable paths (`apps/<app>/specs|tests|reports/`); the run-id is metadata (in the report, the PR body and `.qa-state.json`), so CI and step 7 are unaffected.
- The `--dry-run` output shows, per story, whether it would `run` or `skip` and why.
- **Step 7 is pre-approved** for these sessions (`--allowedTools mcp__github`), so they push and open PRs without asking. Interactive sessions still ask.
- Sessions share this folder. Each story writes only its own files, and each session's Playwright output goes to `runs/<timestamp>-<app>/<STORY_ID>/` (via `QA_RUN_DIR`), so parallel test runs can't wipe each other.
- Per story: `session.jsonl` (full transcript, stream-json), `stderr.log`, `result.md` (the session's final summary), `clean.log` (files wiped before the redo), `test-results/`, `playwright-report/`. Overall: `runs/<timestamp>-<app>/summary.md`, one row per story with status, minutes, cost and PR link. Status: **done** = PR opened; **incomplete** = session ended but no PR (rerun to finish); **failed** = session errored (e.g. hit the limit); **skipped** = already delivered.
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
│                ──► 6 Report ──► apps/<app>/reports/                      │
│                ──► 7 GitHub MCP ──► branch + PR in app.json targetRepo   │
└──────────────────────────────────────────────────────────────────────────┘
        │
        ▼
<targetRepo>  <targetBranch> ◄── PR from qa/<STORY_ID>-<slug>  (its CI runs the tests)
```

**Who does what:**
- The **main session** orchestrates the steps, does step 1 (reading the story), step 3 (exploratory testing with the `mcp__playwright-test__browser_*` tools), step 6 (writing the report) and step 7 (GitHub MCP calls).
- **Sub-agents can't call other sub-agents.** All hand-offs happen through files on disk (`apps/<app>/specs/`, `tests/`, `reports/`) and through the main session.
- Steps 2, 4 and 5 are delegated to the sub-agents in [.claude/agents/](.claude/agents/).

### The seven steps (summary of qa_system_prompt.md)

| Step | Actor | Output |
|---|---|---|
| 1 Read user story | main session | Resolved paths and app settings, summary of ACs, URL, credentials |
| 2 Create test plan | `playwright-test-planner` | `apps/<app>/specs/<STORY_ID>-<slug>-test-plan.md` (scenarios with steps, expected results and the stable locators found) |
| 3 Exploratory testing | main session + Playwright MCP | Findings, screenshots, the locators that worked |
| 4 Generate scripts | `playwright-test-generator` | `apps/<app>/tests/<slug>/*.spec.ts`, verified on `<app>-chromium` |
| 5 Execute and heal | `playwright-test-healer` | Green on the app's Chromium project. Cross-browser is left to the target repo's CI (token saving) |
| 6 Report | main session | `apps/<app>/reports/<STORY_ID>-<slug>-test-report.md` (+ `reports/evidence/<STORY_ID>-*.png`) |
| 7 Deliver | main session + GitHub MCP | Bootstraps the target repo if empty, pushes to `qa/<STORY_ID>-<slug>`, opens a PR into `targetBranch` |

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
├── .github/workflows/playwright.yml    # CI: runs `npx playwright test` on push/PR to main|master
├── .mcp.json                           # MCP servers for Claude Code: playwright-test (stdio), github (http)
├── .env.example                        # template: GITHUB_PAT= (copy to .env, which is git-ignored)
├── apps/
│   ├── _template/                      # copy this to add an app (skipped by the config)
│   ├── saucedemo/
│   │   ├── app.json                    # baseURL, targetRepo, locators, agentNotes
│   │   ├── seed.spec.ts                # logs in → /inventory.html
│   │   ├── user-stories/SCRUM-10x-*.md # SCRUM-101…107
│   │   ├── specs/SCRUM-101-checkout-test-plan.md      # generated (22 scenarios)
│   │   ├── tests/checkout/             # generated suite for SCRUM-101, 9 files / 22 tests
│   │   └── reports/                    # SCRUM-101 report + evidence/SCRUM-101-*.png
│   └── practice-target/
│       ├── app.json
│       ├── seed.spec.ts                # opens / (not logged in)
│       └── user-stories/SCRUM-20x-*.md # SCRUM-201…208 (specs/, tests/, reports/ appear when run)
├── playwright.config.ts                # discovers apps/*/app.json → <app>-<browser> projects; timeouts, reporters
├── run-stories.sh                      # batch runner: one headless session per story, in parallel
├── qa_system_prompt.md                 # THE workflow: 7 steps, path conventions
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
| `github` | http: `https://api.githubcopilot.com/mcp/` with `Authorization: Bearer ${GITHUB_PAT}` | Step 7: create branch, push files, open the PR in the target repo |

**How the `playwright-test` server gives an agent a browser:** `planner_setup_page` / `generator_setup_page` run the `seedFile` they're given (`apps/<app>/seed.spec.ts`) in the given `project` (`<app>-chromium`). Without a `project` they use the first project (whichever app sorts first), and without a `seedFile` they create a default seed, so the prompt always passes both. The test is then **paused at its end**, and the agent drives that live page with `browser_*` tools.

Consequences:
- The browser stays open until the paused worker process goes away. `browser_close` only closes the tab. See §7.3.
- The paused test has **no test timeout**, so the only limits on a stuck click or fill are `actionTimeout` / `navigationTimeout` from the config. See §7.1.
- The server runs headed by default. Add `"--headless"` to its `args` for sandbox/CI use.

Claude Code expands `${VAR}` in `.mcp.json` **when it starts**. `GITHUB_PAT` must already be in the environment of the shell that launches `claude`. Otherwise the `github` server fails with `400 Authorization header is badly formatted`.

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
| `enabledMcpjsonServers` | `playwright-test`, `github` | Pre-approves the project's MCP servers |
| `permissions.allow` | `mcp__playwright-test`, `Bash(npx playwright test:*)`, `Bash(npx playwright show-report:*)`, `Edit(apps/*/specs/**)`, `Edit(apps/*/tests/**)`, `Edit(apps/*/reports/**)` | Steps 1–6 run without prompts. **GitHub MCP is deliberately not allowed**, so step 7 asks before pushing or opening PRs |
| `hooks.SubagentStop`, `hooks.SessionEnd` | `"$CLAUDE_PROJECT_DIR"/.claude/hooks/close-test-browsers.sh` (timeout 15s) | Closes paused test browsers (§7.3) |

Note: in permission rules, `Edit(path)` covers every file-writing tool. `Write(path)` rules are not matched by file permission checks, so don't add them.

### 4.5 CI ([.github/workflows/playwright.yml](.github/workflows/playwright.yml))

GitHub-hosted `ubuntu-latest`, triggered on push/PR to `main`/`master`. The steps:
1. `npm ci`
2. `npx playwright install --with-deps`
3. `npx playwright test` (all 4 projects, including the seed test)
4. Upload `playwright-report/` as an artifact (30 days)

It needs **no secrets**: it doesn't run Claude Code or the agents. The same workflow file is pushed to the target repo during step 7's bootstrap, so the target repo's CI runs the tests on each PR.

---

## 6. Setup and running

### 5.1 Prerequisites

- Node.js (LTS) and npm
- Claude Code CLI (`claude`)
- A GitHub token with push access to **both** target repos. It needs `repo` and `workflow` scopes (classic) or Contents/Pull requests/Workflows read-write (fine-grained), because step 7 pushes `.github/workflows/playwright.yml`.

### 5.2 One-time setup

```bash
npm ci
npx playwright install --with-deps
cp .env.example .env        # then put the real token in .env: GITHUB_PAT=...
```

### 5.3 Run the QA flow

```bash
set -a; source .env; set +a   # GITHUB_PAT must be in the env BEFORE claude starts
claude                        # approve MCP servers on first run; /mcp should show both connected
```

Then paste the contents of [qa_user_prompt.md](qa_user_prompt.md). For first runs or debugging, run the steps one at a time using the per-step prompts in [qa_system_prompt.md](qa_system_prompt.md). Expect a visible browser window during steps 2–5, and approval prompts for each GitHub action in step 7.

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

### 6.2 Report location

Reports go to `apps/<app>/reports/`, never `test-results/`. Playwright deletes `test-results/` at the start of every run, and it is git-ignored.

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

## 8. Step 7 delivery contract (target repo)

These rules are defined in [qa_system_prompt.md](qa_system_prompt.md) step 7. Keep them consistent if you change either side.

0. Deliver to the **active app's** target repo (Target applications table in the prompt). Never mix apps in one repo.
1. Use only the **GitHub MCP server**: no local `git` commands, and nothing is committed to *this* repo.
2. **If the target repo has no commits**, push one bootstrap commit straight to `targetBranch` containing `package.json`, `package-lock.json`, `playwright.config.ts`, `.gitignore`, `.github/workflows/playwright.yml`, `apps/<app>/app.json` and `apps/<app>/seed.spec.ts`. Commit message: `chore: bootstrap Playwright project`. A PR can't be opened against an empty repo.
3. Create `qa/<STORY_ID>-<slug>` from `targetBranch`. Stop and ask if it already exists.
4. Push the story's files (story, plan, tests, report, evidence) at the same paths under `apps/<app>/`. Also push `playwright.config.ts`, `app.json` and the seed if they're missing or differ. Never push another app's folder: the target repo's config then discovers only its own app.
5. Open a PR into `targetBranch` titled `<STORY_ID>: <story title> E2E test suite`, with Chromium test counts and open defects in the body.

App-specific delivery facts live in that app's `agentNotes`. Currently: the SauceDemo repo has history (bootstrap done, PR #1 merged, branch `qa/SCRUM-101-checkout` exists) and still has the pre-refactor paths (`user-stories/scrum-latest.md`, `specs/saucedemo-checkout-test-plan.md`, `tests/seed.spec.ts`, `tests/saucedemo-checkout/`, `reports/SCRUM-101-checkout-test-report.md`), which the next SauceDemo delivery should delete. The Practice Target repo is empty, so its first delivery does the bootstrap.

---

## 9. Gotchas (read before changing things)

| Symptom / temptation | Reality |
|---|---|
| Removing `actionTimeout` / `navigationTimeout` | Agents will hang indefinitely on missing elements (§7.1) |
| Writing outputs under `test-results/` | They are deleted on the next test run |
| `github` MCP: `400 Authorization header is badly formatted` | `GITHUB_PAT` wasn't in the environment when `claude` started. Load `.env` and restart `claude` |
| Using `${input:...}` in `.mcp.json` | That's VS Code syntax. Claude Code only supports `${VAR}` / `${VAR:-default}` |
| Relying on the default MCP project | Projects are generated alphabetically per app. Always pass `project: <app>-chromium` and `seedFile` to `*_setup_page` |
| Editing `playwright.config.ts` to add an app | Not needed. Add `apps/<app>/app.json`; folders starting with `_` are ignored |
| Agent opens the burger menu via `browser_evaluate` (JS click) and then clicks a menu item | The menu stays `aria-hidden`, so the item is never visible. Open it with a real `browser_click` on `[data-test="open-menu"]` (or the "Open Menu" button) |
| Assuming SauceDemo rejects whitespace or special characters in checkout fields | It accepts them and moves to step two. Tests document this as an observation, not a defect, so code that re-fills the form afterwards will fail |
| Cart page "total price" (AC1) | SauceDemo shows no total on the cart page. Totals appear on the overview page (AC3). This is documented in the report |
| Adding `Write(...)` permission rules | They have no effect. Use `Edit(...)` |
| Re-running `npx playwright init-agents` | Overwrites `.claude/agents/*` and `.mcp.json`. Re-add the `github` server afterwards |
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
  - GitHub actions without approval prompts (needs the `mcp__github` tools allowed, or auto mode).
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
- Generated artifacts belong in `apps/<app>/specs/`, `apps/<app>/tests/<slug>/` and `apps/<app>/reports/`. Don't hand-edit generated tests unless you're acting as the healer, and record healing in the report.
- Run `npx playwright test apps/*/seed.spec.ts` after any config change. Every app's seed should pass on its 4 projects.
- Don't commit `test-results/`, `playwright-report/`, `.playwright-mcp/`, `.env` or `.claude/settings.local.json`.
