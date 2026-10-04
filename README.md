# e2e-playwright-test-agent

An **agentic QA harness**: a user story (markdown) goes in. Out come an automated, cross-browser Playwright test suite, a test plan and an execution report, all delivered as a pull request to a separate test repository.

The work is done by **Claude Code**, using three Playwright sub-agents (planner, generator, healer) and two MCP servers (Playwright Test, GitHub). This repo contains no application code. It holds the configuration, prompts, agent definitions and the artifacts the agents produce.

> **For coding agents:** read this file top to bottom before changing anything. The section [Gotchas](#gotchas-read-before-changing-things) records failures that already happened. Don't reintroduce them.

---

## 1. At a glance

| Item | Value |
|---|---|
| Agent runtime | Claude Code (CLI). OpenCode was used earlier and removed because it hung on complex Playwright work |
| Test framework | `@playwright/test` ^1.63 (TypeScript, no build step, no `tsconfig`) |
| Applications under test | **SauceDemo**, `https://www.saucedemo.com` (public demo shop, account `standard_user` / `secret_sauce`)<br>**Playwright Practice Target**, `https://custom-test-target-app.vercel.app` (static UI sandbox; mock login `demo` / `password123`, needed only for `/dashboard`) |
| Input | One **active story** per run, named in [qa_user_prompt.md](qa_user_prompt.md) and looked up in the story registry in [qa_system_prompt.md](qa_system_prompt.md):<br>[user-stories/saucedemo/](user-stories/saucedemo/) (**SCRUM-101…107**, one story per area: checkout, login, product catalog, product details, shopping cart, menu & navigation, dynamic catalog)<br>[user-stories/practice-target/](user-stories/practice-target/) (**SCRUM-201…208**, one story per area: auth, forms, buttons, modals, dropdowns, table, dynamic content, navigation) |
| Workflow definition | [qa_system_prompt.md](qa_system_prompt.md) (7 steps); kick-off prompt in [qa_user_prompt.md](qa_user_prompt.md) |
| Output repos (one per app, default branch `master`) | SauceDemo → [`prashant-kiit/e2e-playwright-agent-test-target`](https://github.com/prashant-kiit/e2e-playwright-agent-test-target)<br>Practice Target → [`prashant-kiit/e2e-playwright-test-custom-target`](https://github.com/prashant-kiit/e2e-playwright-test-custom-target) (still empty; the first run bootstraps it) |
| This repo | `prashant-kiit/e2e-playwright-test-agent` (default branch `master`) |
| Current state | Practice Target stories, config projects and seed are added; no QA run for them yet. SauceDemo: the full flow has run once successfully: 22 test cases × 4 browser projects = 88/88 passing, 1 test healed. Delivered as PR #1 to the SauceDemo target repo (merged) |

---

## 2. How the pipeline works

```
user-stories/<active story>.md
        │
        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Claude Code main session (orchestrator), driven by qa_system_prompt.md   │
│                                                                          │
│  1 Read story ──► 2 playwright-test-planner ──► specs/<plan>.md          │
│                       (explores the live app in a browser)               │
│                ──► 3 Exploratory testing (main session, MCP browser tools)│
│                ──► 4 playwright-test-generator ──► tests/<app>/<area>/*.spec.ts
│                ──► 5 playwright-test-healer (Chromium loop, then all 4 browsers)
│                ──► 6 Report ──► reports/SCRUM-101-checkout-test-report.md │
│                ──► 7 GitHub MCP ──► branch + PR in the target repo        │
└──────────────────────────────────────────────────────────────────────────┘
        │
        ▼
the active app's target repo (SauceDemo → e2e-playwright-agent-test-target,
                              Practice Target → e2e-playwright-test-custom-target)
  master ◄── PR from qa/<STORY_ID>-<slug>  (target repo's CI runs the tests)
```

**Who does what:**
- The **main session** orchestrates the steps, does step 1 (reading the story), step 3 (exploratory testing with the `mcp__playwright-test__browser_*` tools), step 6 (writing the report) and step 7 (GitHub MCP calls).
- **Sub-agents can't call other sub-agents.** All hand-offs happen through files on disk (`specs/`, `tests/`, `reports/`) and through the main session.
- Steps 2, 4 and 5 are delegated to the sub-agents in [.claude/agents/](.claude/agents/).

### The seven steps (summary of qa_system_prompt.md)

| Step | Actor | Output |
|---|---|---|
| 1 Read user story | main session | Summary of ACs, URL, credentials |
| 2 Create test plan | `playwright-test-planner` | `specs/<app>/<STORY_ID>-<slug>-test-plan.md` (scenarios with steps, expected results and the stable locators found) |
| 3 Exploratory testing | main session + Playwright MCP | Findings, screenshots, the locators that worked |
| 4 Generate scripts | `playwright-test-generator` | The story's test directory (e.g. `tests/saucedemo/checkout/`), verified on the app's Chromium project |
| 5 Execute and heal | `playwright-test-healer` | Green on Chromium first, then one run on all 4 projects with browser-specific fixes |
| 6 Report | main session | `reports/<STORY_ID>-<slug>-test-report.md` (+ `reports/evidence/<STORY_ID>-*.png`) |
| 7 Deliver | main session + GitHub MCP | Bootstraps `master` if the target repo is empty, pushes to the story's branch (`qa/<STORY_ID>-<slug>`), opens a PR into `master` |

---

## 3. Repository map

```
.
├── .claude/
│   ├── agents/                         # Sub-agent definitions (generated by `npx playwright init-agents --loop=claude`)
│   │   ├── playwright-test-planner.md    # explores app → saves a test plan (model: sonnet)
│   │   ├── playwright-test-generator.md  # plan → test files (model: sonnet)
│   │   └── playwright-test-healer.md     # runs/debugs/fixes failing tests; only agent with Edit/Write (model: sonnet)
│   ├── hooks/
│   │   └── close-test-browsers.sh      # closes paused test browsers (see §6.3)
│   ├── settings.json                   # shared Claude Code settings: env, permissions, hooks (committed)
│   └── settings.local.json             # per-user approvals (git-ignored)
├── .github/workflows/playwright.yml    # CI: runs `npx playwright test` on push/PR to main|master
├── .mcp.json                           # MCP servers for Claude Code: playwright-test (stdio), github (http)
├── .env.example                        # template: GITHUB_PAT= (copy to .env, which is git-ignored)
├── playwright.config.ts                # baseURL, timeouts, reporters, 4 browser projects
├── qa_system_prompt.md                 # THE workflow: 7 steps, app + story registry, target repo per app
├── qa_user_prompt.md                   # one-line kick-off prompt that points at qa_system_prompt.md
├── user-stories/
│   ├── saucedemo/SCRUM-10x-*.md        # SCRUM-101…107 (SauceDemo, one story per feature area; only 101 has been run)
│   └── practice-target/SCRUM-20x-*.md  # SCRUM-201…208 (Practice Target, one story per feature area)
├── specs/
│   ├── README.md                       # placeholder ("directory for test plans")
│   ├── saucedemo/SCRUM-101-checkout-test-plan.md   # generated by the planner (22 scenarios)
│   └── practice-target/                # plans for SCRUM-201…208 (none yet)
├── tests/
│   ├── saucedemo/                      # SauceDemo only (SauceDemo projects)
│   │   ├── seed.spec.ts                #   logs in → /inventory.html; every SauceDemo agent session starts here
│   │   └── checkout/                   #   generated suite for SCRUM-101, 9 files / 22 tests
│   └── practice-target/                # Practice Target only (practice-* projects)
│       ├── seed.spec.ts                #   opens / (not logged in)
│       └── <area>/                     #   generated suites for SCRUM-201…208 (none yet)
├── reports/
│   ├── SCRUM-101-checkout-test-report.md
│   └── evidence/<STORY_ID>-*.png       # screenshots from exploratory testing (prefix lets step 7 pick a story's files)
├── TASK.md                             # the owner's running backlog / roadmap (see §10)
├── package.json / package-lock.json    # only devDeps: @playwright/test, @types/node; no npm scripts
└── LICENSE
```

**Generated or ignored (never commit):**

| Path | What it is |
|---|---|
| `node_modules/` | npm dependencies |
| `test-results/` | Playwright per-run output. **Wiped at the start of every run** |
| `playwright-report/` | HTML report |
| `.playwright-mcp/` | MCP console logs, page snapshots, and the hook log `close-test-browsers.log` |
| `.env` | Real secrets |
| `.claude/settings.local.json` | Per-user Claude Code approvals |

`.gitignore` is a large Python template with a Playwright and a Claude Code section appended at the end.

### Generated test suite (`tests/saucedemo/checkout/`)

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
- Header comments `// spec: specs/...` and `// seed: tests/<app>/seed.spec.ts`.
- `test.describe` per AC.
- A `beforeEach` that **repeats the seed's login steps**. Tests don't import the seed.
- `data-test` attribute locators.
- Relative URLs.
- No fixed waits.

---

## 4. Components in detail

### 4.1 MCP servers ([.mcp.json](.mcp.json))

| Server | Transport | Purpose |
|---|---|---|
| `playwright-test` | stdio: `npx playwright run-test-mcp-server` | Browser automation and test-runner tools (`browser_*`, `planner_*`, `generator_*`, `test_run`, `test_debug`, `test_list`). Reads `playwright.config.ts` |
| `github` | http: `https://api.githubcopilot.com/mcp/` with `Authorization: Bearer ${GITHUB_PAT}` | Step 7: create branch, push files, open the PR in the target repo |

**How the `playwright-test` server gives an agent a browser:** `planner_setup_page` / `generator_setup_page` run the `seedFile` they're given (the app's `tests/<app>/seed.spec.ts`) in the given `project` (default: the first project, `chromium`). Without a `seedFile` they create a default seed, so the prompt always passes both. The test is then **paused at its end**, and the agent drives that live page with `browser_*` tools.

Consequences:
- The browser stays open until the paused worker process goes away. `browser_close` only closes the tab. See §6.3.
- The paused test has **no test timeout**, so the only limits on a stuck click or fill are `actionTimeout` / `navigationTimeout` from the config. See §6.1.
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
| `baseURL` (per project) | `SAUCEDEMO_BASE_URL` (`https://www.saucedemo.com`) on the SauceDemo projects, `PRACTICE_BASE_URL` (`https://custom-test-target-app.vercel.app`) on the `practice-*` projects. There is no global default | Tests and the seeds use relative URLs. A new project must set its own `baseURL` |
| `use.actionTimeout` | `10_000` | **Required.** Playwright's default is no limit, and a paused MCP test has no test timeout, so a click on a missing or hidden element would hang forever (this happened: a 58-minute hang) |
| `use.navigationTimeout` | `15_000` | Same reason, for navigations |
| `reporter` | `[['list'], ['html', { open: 'never' }]]` | `open: 'never'` stops a failing local run from blocking on the HTML report server |
| `retries` / `workers` | 2 / 1 on CI, 0 / auto locally | Standard |
| `trace` | `on-first-retry` | Standard |
| `projects` | SauceDemo: `chromium`, `firefox`, `webkit`, `Mobile Chrome` (Pixel 7), with `testMatch: **/saucedemo/**/*.spec.ts`<br>Practice Target: `practice-chromium`, `practice-firefox`, `practice-webkit`, `practice-mobile-chrome`, with `testMatch: **/practice-target/**/*.spec.ts` | `chromium` must stay **first**: MCP setup uses the first project by default. For Practice Target stories the prompt passes `project: practice-chromium` and `seedFile: tests/practice-target/seed.spec.ts` explicitly. Each app's projects only see that app's tests, so `npx playwright test` runs everything correctly with no flags |

### 4.4 Claude Code settings ([.claude/settings.json](.claude/settings.json))

| Key | Value | Purpose |
|---|---|---|
| `env.MCP_TOOL_TIMEOUT` | `120000` | Backup limit: any single MCP tool call is cancelled after 2 minutes. Applies to sessions started after the change |
| `enabledMcpjsonServers` | `playwright-test`, `github` | Pre-approves the project's MCP servers |
| `permissions.allow` | `mcp__playwright-test`, `Bash(npx playwright test:*)`, `Bash(npx playwright show-report:*)`, `Edit(specs/**)`, `Edit(tests/**)`, `Edit(reports/**)` | Steps 1–6 run without prompts. **GitHub MCP is deliberately not allowed**, so step 7 asks before pushing or opening PRs |
| `hooks.SubagentStop`, `hooks.SessionEnd` | `"$CLAUDE_PROJECT_DIR"/.claude/hooks/close-test-browsers.sh` (timeout 15s) | Closes paused test browsers (§6.3) |

Note: in permission rules, `Edit(path)` covers every file-writing tool. `Write(path)` rules are not matched by file permission checks, so don't add them.

### 4.5 CI ([.github/workflows/playwright.yml](.github/workflows/playwright.yml))

GitHub-hosted `ubuntu-latest`, triggered on push/PR to `main`/`master`. The steps:
1. `npm ci`
2. `npx playwright install --with-deps`
3. `npx playwright test` (all 4 projects, including the seed test)
4. Upload `playwright-report/` as an artifact (30 days)

It needs **no secrets**: it doesn't run Claude Code or the agents. The same workflow file is pushed to the target repo during step 7's bootstrap, so the target repo's CI runs the tests on each PR.

---

## 5. Setup and running

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
npx playwright test tests/saucedemo/checkout/ --project=chromium
npx playwright test tests/saucedemo/seed.spec.ts tests/practice-target/seed.spec.ts   # smoke check of both apps + config (8 runs)
npx playwright show-report                                  # open the last HTML report
```

### 5.5 Secrets

- The only secret is `GITHUB_PAT`.
- **Locally:** keep it in `.env` (git-ignored) and load it with `set -a; source .env; set +a`.
- **CI/sandbox:** inject it as a platform secret (e.g. a GitHub Actions secret named `GITHUB_PAT`; `GITHUB_TOKEN` is a reserved name).
- Never put a real value in `.env.example`, `.mcp.json` or any committed file.
- In a container, pass it at run time (`docker run -e GITHUB_PAT`), never at build time.

---

## 6. Reliability mechanisms

### 6.1 Timeouts (no infinite hangs)

- **What happened:** an agent's `browser_click` on a hidden menu link waited 58 minutes, and a `browser_run_code_unsafe` waited for a form field that no longer existed.
- **Root cause:** Playwright's default `actionTimeout` is 0 (unlimited), and a paused MCP test has no test timeout.
- **Fix:**
  - `actionTimeout: 10_000` and `navigationTimeout: 15_000` in the config. A stuck action now fails after 10 seconds with a reason like "element is not visible", which the agent can recover from.
  - `MCP_TOOL_TIMEOUT=120000` in settings as a backup.

### 6.2 Report location

Reports go to `reports/`, never `test-results/`. Playwright deletes `test-results/` at the start of every run, and it is git-ignored.

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

## 7. Step 7 delivery contract (target repo)

These rules are defined in [qa_system_prompt.md](qa_system_prompt.md) step 7. Keep them consistent if you change either side.

0. Deliver to the **active app's** target repo (Target applications table in the prompt). Never mix apps in one repo.
1. Use only the **GitHub MCP server**: no local `git` commands, and nothing is committed to *this* repo.
2. **If the target repo has no commits**, push one bootstrap commit straight to `master` containing `package.json`, `package-lock.json`, `playwright.config.ts`, `.gitignore`, `.github/workflows/playwright.yml` and the app's seed (`tests/saucedemo/seed.spec.ts` or `tests/practice-target/seed.spec.ts`). Commit message: `chore: bootstrap Playwright project`. A PR can't be opened against an empty repo.
3. Create the story's branch from the registry (e.g. `qa/SCRUM-201-auth`) from `master`. Stop and ask if it already exists.
4. Push the active story's files from the registry (story, plan, tests, report, evidence) at the same paths. Also push `playwright.config.ts` and the app's seed if they're missing on `master` or differ, because the target repo's CI needs the app's projects.
5. Open a PR into `master` titled `<STORY_ID>: <story title> E2E test suite`, with test counts, per-browser results and open defects in the body.

The SauceDemo repo has history (bootstrap done, PR #1 merged): its bootstrap is skipped, and a re-run must not reuse the `qa/SCRUM-101-checkout` branch name. That repo still has the pre-move paths (`user-stories/scrum-latest.md`, `specs/saucedemo-checkout-test-plan.md`, `tests/seed.spec.ts`, `tests/saucedemo-checkout/`). The next SauceDemo delivery (any of SCRUM-101…107) pushes the new paths and should delete the old ones, or CI there would run the checkout suite twice. The Practice Target repo is empty, so its first run (any of SCRUM-201…208) does the bootstrap.

---

## 8. Gotchas (read before changing things)

| Symptom / temptation | Reality |
|---|---|
| Removing `actionTimeout` / `navigationTimeout` | Agents will hang indefinitely on missing elements (§6.1) |
| Writing outputs under `test-results/` | They are deleted on the next test run |
| `github` MCP: `400 Authorization header is badly formatted` | `GITHUB_PAT` wasn't in the environment when `claude` started. Load `.env` and restart `claude` |
| Using `${input:...}` in `.mcp.json` | That's VS Code syntax. Claude Code only supports `${VAR}` / `${VAR:-default}` |
| Reordering `projects` | MCP setup uses the first project. Keep `chromium` first |
| Agent opens the burger menu via `browser_evaluate` (JS click) and then clicks a menu item | The menu stays `aria-hidden`, so the item is never visible. Open it with a real `browser_click` on `[data-test="open-menu"]` (or the "Open Menu" button) |
| Assuming SauceDemo rejects whitespace or special characters in checkout fields | It accepts them and moves to step two. Tests document this as an observation, not a defect, so code that re-fills the form afterwards will fail |
| Cart page "total price" (AC1) | SauceDemo shows no total on the cart page. Totals appear on the overview page (AC3). This is documented in the report |
| Adding `Write(...)` permission rules | They have no effect. Use `Edit(...)` |
| Re-running `npx playwright init-agents` | Overwrites `.claude/agents/*` and `.mcp.json`. Re-add the `github` server afterwards |
| `.playwright-mcp/` filling up | Expected (MCP logs and snapshots). It's git-ignored and safe to delete |

---

## 9. Debugging a stuck or failed run

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

## 10. Roadmap and open questions

[TASK.md](TASK.md) is the owner's backlog. Items 1–2 and 4 refer to the abandoned OpenCode setup and are historical. Open themes:

- **Sandboxed, unattended runs:**
  - Each test run in a fresh Claude Code session inside a sandbox.
  - Headless browser (`--headless` in `.mcp.json`).
  - GitHub actions without approval prompts (needs the `mcp__github` tools allowed, or auto mode).
  - Defining what lives inside vs outside the sandbox, and how permissions are managed there.
- **Triggering:** target app → this agent → PR to a test repo → that repo's CI runs `tests/`.
- **Human in the loop:** questions Claude Code asks should appear in a frontend, with answers flowing back.
- **Scope control:**
  - Generate tests only for what changed (git history).
  - Split agents into bounded scenarios.
  - Commit/push in batches rather than one bulk commit.
- **Robustness:** timeouts (done, §6.1), monitoring logs, resuming after a failure, multi-tenant sessions.
- **Artifacts and versioning:**
  - A custom test target with versioned tests and user stories.
  - Whether artifacts belong in the repo/file storage or in object storage (e.g. S3).
- **Hygiene:** remove unused files and stay minimal.

---

## 11. Rules for agents working in this repo

- Treat [qa_system_prompt.md](qa_system_prompt.md) as the source of truth for the workflow and file paths. If you change a path in one place, update the prompt, `.claude/settings.json` permissions and this README together.
- Don't hard-code secrets. `GITHUB_PAT` comes from the environment only.
- Keep `chromium` as the first project, and keep the action/navigation timeouts.
- Generated artifacts belong in `specs/`, the story's test directory (`tests/saucedemo/checkout/`, `tests/practice-target/<area>/`) and `reports/`. Don't hand-edit generated tests unless you're acting as the healer, and record healing in the report.
- Run `npx playwright test tests/saucedemo/seed.spec.ts tests/practice-target/seed.spec.ts` after any config change. It should pass on all 8 projects in about 10 seconds.
- Don't commit `test-results/`, `playwright-report/`, `.playwright-mcp/`, `.env` or `.claude/settings.local.json`.
