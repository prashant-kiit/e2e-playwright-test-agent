# e2e-playwright-test-agent

An **agentic QA harness**: a user story (markdown) goes in. Out come an automated, cross-browser Playwright test suite and a test plan. The agent **stops there for human review**; a human then delivers the suite as a pull request to a separate test repository, where CI runs the tests and generates the results report.

The work is done by **Claude Code**, using three Playwright sub-agents (planner, generator, healer) and the Playwright Test MCP server. The agent explores, plans, generates and heals the tests, then stops. **Delivery is a separate, human-initiated step**: a human reviews the generated code and runs `python -m app.delivery push` (or `make deliver`). Target-repo work is done by the Python modules in [server/app/delivery/](server/app/delivery/) — `git` as a subprocess, GitHub over REST — not by a GitHub MCP and no longer by shell scripts. This repo contains no application code. It holds the configuration, prompts, agent definitions, tools and the artifacts the agents produce.

> **For coding agents:** read this file top to bottom before changing anything. The section [Gotchas](#9-gotchas-read-before-changing-things) records failures that already happened. Don't reintroduce them.

---

## 0. Admin Portal (web UI)

The harness is driven from a **single-operator web portal**. It orchestrates the same per-step Claude Code workflow, keeps run state in a database, and stores artifacts in an object store so you can watch, pause/resume/stop and browse runs from a browser. (The original shell flow — `scripts/run-stories.sh` and its four delivery tools — is gone; see [§5.6](#56-target-repo-delivery-appdelivery) and the note on batch runs in [§2](#2-adding-or-switching-an-application).)

**Architecture** (all Dockerized; `docker-compose.yml`):

| Piece | Tech | Role |
|---|---|---|
| `web/` | React + Vite, served by nginx | The portal UI (login, projects/targets, live run view, artifacts, history, bootstrap, settings) |
| `server/` | FastAPI + uvicorn (uv) | API + orchestrator: drives the 5 steps one at a time, checkpoints each, streams the log (SSE). Also owns target-repo delivery (`app/delivery/`) |
| Postgres | — | **Authoritative run state**: runs, steps, the lease-based per-app lock, history (replaces `.qa-state.json`). Since P2 it also carries the *dual-written* revision model (`revisions`, `file_index`), which nothing reads to make a decision yet |
| SeaweedFS | S3-compatible | **Artifact blobs** (evidence/report/logs), indexed by the `artifacts` table (MinIO was dropped; it is no longer freely pullable). Since P2 it also holds **content-addressed tree blobs** under `tenant/<id>/blobs/<sha256>` |

**One owner per concern:** Postgres owns run *status*, a target's *configuration*, and — via `revisions` + `file_index` — the index of its tracked tree; SeaweedFS owns the *blobs* those rows name, tree content and run artifacts alike; the customer's git repo holds the *delivered* copy of the tests (pushed by `app/delivery/push.py`). Nothing on a local disk owns anything.

**Revisions are the truth (P3).** A target's configuration is a row on `targets`; its **tracked tree** — stories, plans, seed, test suite and the infra files — lives in content-addressed blobs indexed by an immutable `revision`. Creating a target commits revision 1 from the templates. Before a run's first step the orchestrator **hydrates** that head revision into a per-run worktree (blobs streamed from SeaweedFS and verified as they are written, generated files rendered from the row, dependencies installed); the agent works there and nowhere else; at each completed step boundary **ingest** commits revision N+1; when the run ends the worktree is deleted. A step that changed no tracked file commits nothing, so `rev` counts real changes rather than steps. Each target gets a **Stories** editor, a **Configuration** form and a read-only **Revisions** panel — the portal is the only way a story gets in, and every write commits one operator-authored revision. **A failed ingest fails the run:** once truth has moved, a swallowed failure would mean a run reporting success having dropped its work ([DESIGN.md §13](.claude/harness/DESIGN.md), [VERIFICATION-P3.md](.claude/harness/VERIFICATION-P3.md)).

**Quick start:**

```bash
make up                               # postgres + seaweedfs + api (migrates on boot) + web
open http://localhost:8080            # log in — password is QA_ADMIN_PASSWORD (default: admin)
```

- `make help` lists every target. The API container runs `alembic upgrade head` on boot (schema lives in `server/alembic/`), then uvicorn.
- `QA_RUNNER` selects the agent: **`fake`** (default — synthetic steps, no tokens, for demos/CI) or `claude` (the real per-step runner; needs the `claude` CLI in the execution environment). `QA_FAKE_DELAY` slows the fake runner so you can exercise pause/stop.
- **Nothing is mounted into the API.** A target's configuration is a row, its tree is a revision in blob storage, and the prompts, the agent runtime and the delivery templates ship inside the server package. The API's only local state is per-run scratch on a volume: `QA_WORKTREES_DIR` (the hydrated worktree), `QA_RUNS_DIR` (run output) and `QA_NPM_CACHE`. `git` is installed in the image because delivery pushes from the control plane.

**What P3's statelessness is, and what it is not.** P3 removed the *shared authoritative* mount: no replica needs another replica's disk to answer a question or to start a run, which is the dependency that made two API replicas impossible and that P4's container-per-run stands on. It does **not** make the API horizontally scalable on its own — the worktree and the run directory are local scratch and the SSE log bus is in-process, so **a live run is still pinned to the replica that started it.** Moving the runner out of the API process is P4's job.

**Run modes:** *Full app* (test the whole app) or *Changed only* (focus on the acceptance criteria that changed in the user story since the last tested version — a story diff, since we have the live URL and story, not the app's source).

**Concurrency:** at most one live run per app, enforced by a lease-backed lock (not a boolean); a crashed run's lease expires and a reaper frees the app. A *paused* run keeps its lock until resumed or stopped and is never reaped. **A second run on an app that already has a live one is refused, not queued** — the portal says "This app already has a live run." There is no queue and no batching (see [§2](#2-adding-or-switching-an-application)).

**What the portal does *not* cover yet:** delivery and reset exist as API routes (`POST /targets/<id>/deliver`, `POST /targets/<id>/reset`) but have no UI — the targets list shows each target's **delivered / N revisions ahead** badge, which is one Postgres query, but approving a push is still CLI-only ([§5.6](#56-target-repo-delivery-appdelivery)). Target creation, the configuration form and the story editor are wired up.

**Developing the portal:**

```bash
make test                                  # CI's three checks: ruff + backend pytest + frontend vitest
cd server && uv run pytest                 # needs Postgres (make start); DB tests skip if absent
cd web && npm install && npm test          # Vitest
make dev-web                               # Vite dev server on :5173, proxies the API to :8000
make dev-api                               # uvicorn --reload on :8000
```

CI (`.github/workflows/ci.yml`) runs those same checks on every push with Postgres as a service, and **fails if any test skipped** — the DB-backed tests skip when Postgres is unreachable, so without that guard a green tick could mean "65 of 170 tests ran". Set `QA_REQUIRE_DB=1` to get the same strictness locally (`make ci-test`).

---

## 1. At a glance

| Item | Value |
|---|---|
| Agent runtime | Claude Code (CLI). OpenCode was used earlier and removed because it hung on complex Playwright work |
| Test framework | `@playwright/test` ^1.63 (TypeScript, no build step, no `tsconfig`) |
| Applications under test | One **target** row per app, created in the portal. Its row holds everything app-specific (base URL, target repo, locator style, agent notes) and its tree is a revision. Currently:<br>**saucedemo**, `https://www.saucedemo.com` (public demo shop, `standard_user` / `secret_sauce`) → [`prashant-kiit/e2e-playwright-agent-test-target`](https://github.com/prashant-kiit/e2e-playwright-agent-test-target)<br>**practice-target**, `https://custom-test-target-app.vercel.app` (static UI sandbox; mock login `demo` / `password123` for `/dashboard` only) → [`prashant-kiit/e2e-playwright-test-custom-target`](https://github.com/prashant-kiit/e2e-playwright-test-custom-target) (kept empty as the throwaway repo for verifying delivery; the first delivery bootstraps it) |
| Input | One **active story** per run, chosen in the portal. The orchestrator resolves it from the head revision's `file_index` — exactly one `user-stories/<ID>-*.md` matches, or the run fails before the agent starts.<br>saucedemo: **SCRUM-101…107** (checkout, login, product catalog, product details, shopping cart, menu & navigation, dynamic catalog)<br>practice-target: **SCRUM-201…208** (auth, forms, buttons, modals, dropdowns, table, dynamic content, navigation) |
| Workflow definition | [qa_system_prompt.md](server/app/prompts/qa_system_prompt.md) — reference, not a prompt. The orchestrator sends one step at a time from [server/app/prompts/steps/](server/app/prompts/steps/) (`_context.md`, the resolved run configuration, followed by `1-read_story.md` … `5-heal.md`), with every placeholder substituted from the target's row and the head revision |
| Backend | Python 3.11+ (`uv`), FastAPI, SQLAlchemy + Alembic, `httpx`. Lint: `ruff check .` (clean) |
| This repo | `prashant-kiit/e2e-playwright-test-agent` (default branch `master`) |
| Current state | **saucedemo** has four stories planned and generated — SCRUM-101 checkout (9 files / 22 tests), SCRUM-102 login (5 / 27), SCRUM-103 product-catalog (5 / 16), SCRUM-104 product-details (5 / 11) — with plans in `specs/`. Only SCRUM-101 has been *delivered* (PR #1 to the SauceDemo target repo, merged). SCRUM-105…107 and all of **practice-target** (SCRUM-201…208) have no plans or tests yet |

The target architecture this is migrating toward (multi-tenant SaaS, Postgres as the single arbiter of truth, revisions + blob storage, sandboxed runs) is in [.claude/harness/DESIGN.md](.claude/harness/DESIGN.md), along with the five-phase migration plan. **P1 (shell → Python) is done**; see [.claude/harness/VERIFICATION-P1.md](.claude/harness/VERIFICATION-P1.md) for what was tested and how.

---

## 2. Adding or switching an application

**The portal is the only way in.** There is no `apps/` directory and no `app.json`: onboarding an application never means committing to this repo.

1. **New Target** in the portal. Give it a slug, a display name, a base URL, the `owner/repo` that receives the tests, a locator convention and any agent notes. The base URL must be an absolute `http(s)` URL and the repo must be `owner/repo` and not the placeholder — both are refused at save, where you are still around to be told.
2. That writes the configuration row and commits **revision 1** from the templates: the seed, the infra files, and a `playwright.config.ts` generated from the base URL. The target has a tree to hydrate and a history to show immediately.
3. Tick *also sync the infra files to the target repo* to push the infra there now, or leave it — the first approved delivery folds the setup in.
4. Write stories in the target's **Stories** panel. Each create, edit and delete commits one operator-authored revision. Keep each story lean (~2 acceptance criteria: one happy path + one key negative) to control token cost.
5. Edit the seed in the target's tree if the app needs more than "open the home page" to reach its starting state.

Everything the agent needs is derived from there: the generated config carries the base URL and the four unprefixed browser projects, and the orchestrator resolves the story's paths from the head revision and renders them into the prompt. A worktree holds exactly one target, so a project name or a test path cannot reach another customer's tests.

**Changing where a target points** is the **Configuration** form, not an edit-and-redeploy. A changed base URL re-renders the generated config, which is a tree diff, which is a revision — as reviewable as a code change. `locators` and `agentNotes` reach the agent through its prompt, so they change the row and commit nothing.

**A story or config write is refused while that target has a live run** (409). The run hydrated from an older head and its next ingest would commit a tree without your edit, silently reverting it; there is no merge logic anywhere in this system, so the portal says so rather than queueing it.

### Running several stories of one app: not currently possible

`run-stories.sh` used to start one headless session per story, in parallel, skip stories already generated, preview with `--dry-run` and write a batch summary. **It was dropped in P1 and nothing replaced it.** The orchestrator runs **exactly one story per run**, and starting a second run on an app that already has a live run is refused (`RunConflict` → HTTP 409).

So today: start a run, wait for it, start the next. To work on several stories of one app, do them in sequence. Reinstating batching means adding a queue above the existing per-app lock — it is [its own piece of work](.claude/harness/DESIGN.md#5-run-lifecycle), not a small fix, because the lock deliberately serializes per target.

---

## 3. How the pipeline works

```
head revision: user-stories/<STORY_ID>-<slug>.md, seed.spec.ts, infra
   + the target's configuration row (base URL, locators, agent notes)
        │
        ▼  hydrate: blobs → a per-run worktree, generated files rendered, deps installed
        │
┌──────────────────────────────────────────────────────────────────────────┐
│ Claude Code session (orchestrated per step by server/app/orchestrator/) │
│                                                                          │
│  1 Read story ──► 2 playwright-test-planner ──► specs/        │
│                       (explores the live app in a browser)               │
│                ──► 3 Exploratory testing (main session, MCP browser tools)│
│                ──► 4 playwright-test-generator ──► tests/<slug>/
│                ──► 5 playwright-test-healer (Chromium only; CI runs all 4)
│                ──► 6 STOP for human review (no delivery, no report)       │
└──────────────────────────────────────────────────────────────────────────┘
        │
        ▼  ingest at each changed step boundary: revision N+1; then teardown
        │
        ▼  (human reviews the generated tests in the Revisions panel)
   python -m app.delivery push <app> <STORY_ID>   ──►  branch + PR in the target repo
        │
        ▼
<targetRepo>  <targetBranch> ◄── PR from qa/<STORY_ID>-<slug>  (its CI runs the tests)
```

**Who does what:**
- The **orchestrator** (`server/app/orchestrator/driver.py`) runs the steps one at a time and checkpoints each, so a run resumes at a step boundary. It has exactly **one** injected step-boundary hook; artifact collection is composed behind it (don't add a second one — see [DESIGN.md §13](.claude/harness/DESIGN.md#13-migration-plan)).
- The **agent session** does step 1 (read story), step 3 (exploratory testing with the `mcp__playwright-test__browser_*` tools), and step 6 (stop with a final summary). **It does not touch the target repo or deliver** — it needs no GitHub access.
- **A human** reviews the generated tests after the run and delivers with `python -m app.delivery push <app> <STORY_ID>`.
- **Sub-agents can't call other sub-agents.** All hand-offs happen through files in the worktree (`specs/`, `tests/`) and through the main session.
- Steps 2, 4 and 5 are delegated to the sub-agents in [server/app/agent_runtime/agents/](server/app/agent_runtime/agents/).

### The steps (summary of server/app/prompts/qa_system_prompt.md)

Steps 1–6 are the agent's work; it stops at step 6. Delivery is a separate human step (below the table).

| Step | Actor | Output |
|---|---|---|
| 1 Read user story | main session | Resolved paths and app settings, summary of ACs, URL, credentials (no target-repo check — bootstrap is a delivery concern) |
| 2 Create test plan | `playwright-test-planner` | `specs/<STORY_ID>-<slug>-test-plan.md` in the worktree (scenarios with steps, expected results and the stable locators found) |
| 3 Exploratory testing | main session + Playwright MCP | Findings, screenshots, the locators that worked |
| 4 Generate scripts | `playwright-test-generator` | `tests/<slug>/*.spec.ts` in the worktree, verified on `chromium` |
| 5 Execute and heal | `playwright-test-healer` | Green on the app's Chromium project. Cross-browser is left to the target repo's CI (token saving) |
| 6 Stop for human review | main session | A short final summary (no file, no PR). The agent does not deliver |
| — Deliver (human) | human + `app.delivery push` | After reviewing the tests: syncs story+plan+tests to `qa/<STORY_ID>-<slug>` and opens/updates a PR into `targetBranch` (repo must be bootstrapped). The results report is generated by CI |

---

## 4. Repository map

```
.
├── .claude/                            # DEVELOPMENT ONLY (your interactive sessions)
│   ├── harness/
│   │   ├── DESIGN.md                   # target SaaS architecture + the 5-phase migration plan
│   │   └── VERIFICATION-P1.md          # what P1 was tested against, and what is only covered by fakes
│   ├── skills/                         # dev skills (grilling, …)
│   ├── settings.json                   # dev settings: just MCP_TOOL_TIMEOUT
│   └── settings.local.json             # per-user approvals (git-ignored)
├── .github/workflows/
│   └── ci.yml                          # THIS repo's CI, and the ONLY workflow here: ruff + pytest + vitest
├── Makefile                            # the entry point: make help, up, test, check/bootstrap/deliver/reset
├── docker-compose.yml                  # postgres + seaweedfs + api + web
├── server/                             # FastAPI backend, orchestrator and delivery tools
│   ├── app/
│   │   ├── api.py, auth.py, auth_api.py, main.py  # routes, single-operator auth, app wiring
│   │   ├── models.py, repo.py, db.py     # ORM + the repository (run state, lease-backed lock)
│   │   ├── target_config.py              # a target's config, and what a valid value is (write-path)
│   │   ├── authoring.py                  # operator writes: a target, its stories, its config
│   │   ├── revisions.py                  # the tree hash, commit-a-revision, and the reads
│   │   ├── launcher.py                   # composes hydrate → pipeline → teardown around a run
│   │   ├── sandbox/hydrate.py            # materialize + render + install, and teardown (P4 moves these)
│   │   ├── domain/                       # pure logic: steps, statuses, lease rules (no DB, no IO)
│   │   ├── orchestrator/                 # driver (steps + checkpoints), runners (claude/fake), log bus
│   │   ├── delivery/                     # target-repo work; catalog.py is its database seam (§5.6)
│   │   │   └── templates/                # PACKAGE DATA: the infra files and the seed, delivered as-is
│   │   │       └── workflows/playwright.yml  # harness OUTPUT; not a workflow of this repo
│   │   ├── prompts/                      # PACKAGE DATA: the workflow prompts the runner sends
│   │   │   ├── qa_system_prompt.md       # THE workflow: 5 steps + stop-for-review (reference, not a prompt)
│   │   │   └── steps/_context.md, 1-read_story.md … 5-heal.md
│   │   ├── agent_runtime/                # PACKAGE DATA: the agent's own Claude Code config (§5.2)
│   │   │   ├── agents/                   # the three Playwright sub-agents
│   │   │   ├── hooks/close-test-browsers.sh  # closes paused test browsers (§7.3)
│   │   │   └── mcp.json, settings.json   # the MCP server; the agent's env, permissions and hooks
│   │   ├── apphub.py                     # prompts + settings + the optional infra sync
│   │   ├── package_data.py               # where the three package-data directories are (no mount)
│   │   ├── artifacts.py, storage.py      # classify + store artifact blobs (SeaweedFS/S3)
│   │   └── reaper.py                     # frees targets whose run died holding the lock
│   ├── alembic/                        # migrations; the test schema is built by running these from zero
│   └── tests/                          # pytest; delivery_helpers.py = real git + fake GitHub REST + fake catalog
├── web/                                # React + Vite portal (Vitest)
├── .env.example                        # template: GITHUB_PAT= (copy to .env, git-ignored, and source it)
└── LICENSE
```

**Generated or ignored (never commit):**

| Path | What it is |
|---|---|
| `node_modules/` | npm dependencies |
| `test-results/` | Playwright per-run output. **Wiped at the start of every run** |
| `playwright-report/` | HTML report |
| `QA_RUNS_DIR` (`/tmp/qa-runs`) | Per-run output: transcripts, results, Playwright output |
| `QA_WORKTREES_DIR` (`/tmp/qa-worktrees`) | Per-run hydrated worktrees. A **sibling** of the runs dir, never inside it: the artifact sweep is recursive and would otherwise upload the whole tree |
| `.playwright-mcp/` | MCP console logs, page snapshots, and the hook log `close-test-browsers.log` |
| `.env` | Real secrets |
| `server/junit.xml` | Test report written by `pytest --junit-xml` in CI |
| `.claude/settings.local.json` | Per-user Claude Code approvals |

`.gitignore` is a large Python template with a Playwright and a Claude Code section appended at the end. The copy delivered to target repos is a **template** at `server/app/delivery/templates/gitignore`, so this repo's own ignore rules and the customer's are no longer the same file.

### Generated test suite (`tests/checkout/` in a target's tree)

> This table describes the **original** SCRUM-101 delivery (22 tests, 4 browsers). The stories have since been trimmed to a lean ~2-AC scope and the agent now generates/heals on Chromium only, so a re-run produces a smaller suite. The table is kept as a reference of the generator's output shape.

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
- Header comments `// spec: specs/...` and `// seed: seed.spec.ts` (worktree-relative).
- `test.describe` per AC.
- A `beforeEach` that **repeats the seed's setup steps**. Tests don't import the seed.
- Locators as described in the target's `locators` configuration, injected into the agent's prompt.
- Relative URLs.
- No fixed waits.

---

## 5. Components in detail

### 5.1 MCP servers ([server/app/agent_runtime/mcp.json](server/app/agent_runtime/mcp.json))

| Server | Transport | Purpose |
|---|---|---|
| `playwright-test` | stdio: `npx playwright run-test-mcp-server` | Browser automation and test-runner tools (`browser_*`, `planner_*`, `generator_*`, `test_run`, `test_debug`, `test_list`). Reads `playwright.config.ts` |

The orchestrator passes this file with `--mcp-config --strict-mcp-config`, so a run gets *only* this server and never inherits whatever MCP servers a developer has configured.

Delivery to the target repo is **not** done through an MCP server. It uses the Python modules in §5.6, via `git` and the GitHub REST API.

**How the `playwright-test` server gives an agent a browser:** `planner_setup_page` / `generator_setup_page` run the `seedFile` they're given (`seed.spec.ts`, at the worktree root) in the given `project` (`chromium`). Without a `project` they use the first one, and without a `seedFile` they create a default seed, so the prompt always passes both. The test is then **paused at its end**, and the agent drives that live page with `browser_*` tools.

Consequences:
- The browser stays open until the paused worker process goes away. `browser_close` only closes the tab. See §7.3.
- The paused test has **no test timeout**, so the only limits on a stuck click or fill are `actionTimeout` / `navigationTimeout` from the config. See §7.1.
- The server runs headed by default. Add `"--headless"` to its `args` for sandbox/CI use.

### 5.2 Sub-agents ([server/app/agent_runtime/agents/](server/app/agent_runtime/agents/))

These were generated by `npx playwright init-agents --loop=claude`; re-running that command overwrites them. Each file has YAML frontmatter (`name`, `description`, `tools`, `model: sonnet`, `color`) followed by its system prompt.

**The application's agent config is isolated from yours.** `server/app/agent_runtime/` owns the subagents, the MCP server, the permissions and the browser-cleanup hook, and ships with the server package; `.claude/` at the repo root is development-only. The orchestrator (`server/app/orchestrator/claude.py`) shells out to `claude` with `cwd=` the run's **hydrated worktree**, which would otherwise auto-discover whatever ambient `.claude/` it finds, so it loads the runtime config explicitly instead: `--setting-sources "" --settings --mcp-config --strict-mcp-config --agents`. Subagents are passed inline as `--agents` JSON so their names stay bare, matching how the step prompts invoke them. The shipped `settings.json` is rendered with the hook's absolute path before it is handed to the CLI: `$CLAUDE_PROJECT_DIR` is the worktree now, and a tree the agent wrote is the last place to look for something we then execute. Isolation is default-on; `QA_AGENT_ISOLATE=0` falls back to ambient discovery for development.

| Agent | Can edit files? | Key MCP tools |
|---|---|---|
| `playwright-test-planner` | No (saves via `planner_save_plan`) | `planner_setup_page`, `browser_*` (incl. `browser_run_code_unsafe`), `planner_save_plan` |
| `playwright-test-generator` | No (writes via `generator_write_test`) | `generator_setup_page`, `browser_*`, `generator_read_log`, `generator_write_test` |
| `playwright-test-healer` | Yes (`Edit`, `MultiEdit`, `Write`) | `test_run`, `test_debug`, `test_list`, `browser_snapshot`, `browser_generate_locator`, console/network tools |

### 5.3 Playwright config (generated — [render.py](server/app/delivery/render.py))

**The file is generated.** It is rendered from the target's row on every hydrate and re-rendered before every ingest scan, so it has exactly one author and an agent's edit to it is discarded. There is no checked-in copy in this repo; a hand-maintained one would be a second author for the same file.

| Setting | Value | Why |
|---|---|---|
| `testDir` | `.` | One target per worktree, so the whole tree is this target's — the seed at the root runs as a normal test too |
| `outputDir`, HTML report folder | `test-results/`, `playwright-report/`; under `$QA_RUN_DIR` when set | The orchestrator sets `QA_RUN_DIR` per run so concurrent runs keep separate output |
| `workers` | 1 on CI; `$QA_WORKERS` when set; otherwise Playwright's default | Caps load when several Playwright processes share a machine |
| `baseURL` (per project) | **Inlined from the target's row** by `render_playwright_config`, through `json.dumps` rather than interpolation | Tests and the seed use relative URLs. The value is operator input on its way into a customer's repo, so a quote in it must not become a code-injection point |
| `use.actionTimeout` | `10_000` | **Required.** Playwright's default is no limit, and a paused MCP test has no test timeout, so a click on a missing or hidden element would hang forever (this happened: a 58-minute hang) |
| `use.navigationTimeout` | `15_000` | Same reason, for navigations |
| `reporter` | `[['list'], ['html', { open: 'never' }]]` | `open: 'never'` stops a failing local run from blocking on the HTML report server |
| `retries` | 2 on CI, 0 locally | Standard |
| `trace` | `on-first-retry` | Standard |
| `projects` | `chromium`, `firefox`, `webkit`, `mobile-chrome` (Pixel 7) — **no app prefix** | The config is single-target by construction, which is what makes the names bare and what stops a project name or a test path from reaching another customer's tests. Still always pass `project` to the MCP setup tools rather than relying on the first one |

### 5.4 Agent settings ([server/app/agent_runtime/settings.json](server/app/agent_runtime/settings.json))

| Key | Value | Purpose |
|---|---|---|
| `env.MCP_TOOL_TIMEOUT` | `120000` | Backup limit: any single MCP tool call is cancelled after 2 minutes. Applies to sessions started after the change |
| `mcp.json` (passed with `--strict-mcp-config`) | `playwright-test` only | The run gets exactly this server, no ambient ones |
| `permissions.allow` | `mcp__playwright-test`, `Bash(npx playwright test:*)`, `Bash(npx playwright show-report:*)`, `Edit(specs/**)`, `Edit(tests/**)`, `Edit(reports/**)` | Worktree-relative, because the agent's working directory *is* the target's tree. Steps 1–6 run without prompts; the agent does no GitHub work, so **no delivery command is allowed** |
| `hooks.SubagentStop`, `hooks.SessionEnd` | `close-test-browsers.sh`, rendered with the **packaged** hook's absolute path (timeout 15s) | Closes paused test browsers (§7.3). `$CLAUDE_PROJECT_DIR` is the worktree now, and a tree the agent wrote is the last place to look for something we then execute |

Note: in permission rules, `Edit(path)` covers every file-writing tool. `Write(path)` rules are not matched by file permission checks, so don't add them.

### 5.5 Target-repo CI ([the workflow template](server/app/delivery/templates/workflows/playwright.yml))

**This file is harness output, not our CI.** Bootstrap pushes it into each target repo. Our own CI is `ci.yml` (§0). GitHub-hosted `ubuntu-latest`, triggered on push/PR to `main`/`master`. The steps:
1. `npm ci`
2. `npx playwright install --with-deps`
3. `npx playwright test --reporter=list,html,json` (all the app's projects, including the seed test)
4. **Write the results report to the run's Job Summary** — a per-project pass/fail/flaky/skipped table built from `results.json` with `jq` (no third-party actions, no extra permissions)
5. Upload `playwright-report/` as an artifact (30 days)
6. Fail the job if any test failed (step 3 runs with `continue-on-error` so the summary and artifact are always produced first)

**This is where the QA report comes from — CI, not the agent.** It needs **no secrets**: it doesn't run Claude Code or the agents.

> The `jq` here is deliberate and **out of scope** for "drop `gh` and `jq`". That decision is about *our* tooling; this file runs in a customer's GitHub Actions, which has `jq` and does not have our Python. Don't remove it.

### 5.6 Target-repo delivery (`app/delivery/`)

Target-repo work is done by [server/app/delivery/](server/app/delivery/) — Python returning typed results, `git` as a subprocess, GitHub over REST via `httpx`. It replaced the six `scripts/*.sh` tools; there is no `gh` and no `jq` in our tooling any more.

Every command works through one injected value, `Tools` (GitHub client + git + token + **catalog**), and no delivery function may reach for config, credentials or git outside it. The catalog is delivery's seam onto the database: the target's configuration row, the head revision **materialized** into a temporary tree per operation, the delivery state, and the single write of `delivered_sha`. So what we push is provably the revision we record, and "is this in sync?" is one query rather than an `ls-remote` plus a worktree diff. The **harness is the source of truth**: delivery copies outward, never the reverse.

| Command | `make` wrapper | What it does |
|---|---|---|
| `python -m app.delivery check <app>` | `make check APP=x` | Read-only, and answered from **Postgres**: prints `delivered (revision N)` or `N revision(s) ahead of the last delivered one`, with the recorded commit. Exit 0 once anything has been delivered to the repo; exit 1 before that. No network call |
| `python -m app.delivery bootstrap <app> [--dry-run]` | `make bootstrap APP=x [DRY=1]` | Sync the infra entries (package manifests, the **generated** `playwright.config.ts`, `.gitignore`, the workflow) to `targetBranch`. Each comes from its source — a template in the server package, or the renderer reading the target's row — so there is nothing in a workspace to be missing. First commit on an empty repo; on an existing one, only what differs, and "already in sync" when nothing does |
| `python -m app.delivery push <app> <STORY_ID> [--body-file F] [--run-id R] [--dry-run]` | `make deliver APP=x STORY=y` | Deliver the **head revision**: materialize it, write it onto `qa/<STORY_ID>-<slug>` (the story's tests folder replaced wholesale, so deletions propagate; nothing else deleted, because customer drift is not ours to clean up), squash into one commit, open/update the PR into `targetBranch`, and **record `delivered_sha`** on that revision. Appends, never force-pushes. Prints the commit and the PR URL |
| `python -m app.delivery reset <app> --confirm-repo <owner/repo> [--dry-run]` | `make reset APP=x CONFIRM=o/r` | **Destructive.** Wipe the target repo: replace `targetBranch` with a single empty commit (all files and history gone) and delete every other branch (closing their PRs). Does NOT re-bootstrap. Leaves the agent repo untouched |

Run commands from `server/` (`cd server && uv run python -m app.delivery …`), or use the `make` wrappers from the repo root.

**Exit codes — one deliberate change from the old scripts.** `0` success; `1` *only* for `check` when the target is not bootstrapped; `2` for every other failure (unknown app, bad confirmation, credential problems).

The shell tools had no `2`: `qa-lib.sh`'s `qa_die` exited `1` for everything, so `check` returned the same code for "not bootstrapped" as for "no token" or "no such app". Splitting them is the point — `1` now means exactly one thing. A wrapper that only tests success/failure (`if ! make check; then …`) is unaffected; one that tests `-eq 1` to mean "a failure of any kind" will now miss the `2`s.

**Properties that are deliberate — don't "simplify" them away:**
- The story branch is **appended to, never force-pushed** ([DESIGN.md decision 10](.claude/harness/DESIGN.md#14-decision-log)): force-pushing a customer's branch destroys PR review threads.
- `reset` requires the repo name **echoed back** via `--confirm-repo`. The shell version read it from a TTY; there is no TTY behind a portal action, so the caller must pass it. A mismatch aborts with exit 2.
- Machine-made commits in customer repos are authored as **`qa-harness`** (ported from `qa-lib.sh`'s `qa_git`), so history attributes them to the harness rather than to whoever runs the server.
- Every command works through one injected `Tools` value (GitHub client + git + token + workspace). Nothing in `app/delivery/` reaches for credentials or git outside it — that is what lets the tests run offline.

**Auth: `GITHUB_PAT` only.** `gh` is gone and so is its `gh auth token` fallback — this is an **intentional behavior change**, not a regression. If you authenticated with `gh auth login` and nothing else, delivery fails with a `CredentialError` naming `GITHUB_PAT`; it must be in the process environment (§6.5 — there is no file fallback). It needs **push + pull-request rights and `workflow`** (bootstrap pushes `.github/workflows/playwright.yml`); `reset` additionally needs force-push and branch-delete rights. A fine-grained PAT reports no scopes at all, so the client treats "no scopes" as "cannot tell" and lets the push fail loudly rather than pre-rejecting a valid token.

Delivery is **run by a human** (or by the API routes behind it), never by the agent — the test-writing agent does no GitHub work and needs no credentials.

---

## 6. Setup and running

### 6.1 Prerequisites

- Docker (for the portal stack: Postgres, SeaweedFS, API, web)
- Node.js (LTS) and npm
- [`uv`](https://docs.astral.sh/uv/) for the Python backend
- Claude Code CLI (`claude`) — only needed for real (non-`fake`) runs
- `git`
- GitHub access to each target repo via a `GITHUB_PAT` (see §5.6 and §6.5). **`gh` and `jq` are no longer needed** — the delivery tools don't use them.

### 6.2 One-time setup

```bash
npm ci
npx playwright install --with-deps
cp .env.example .env        # then put the real token in it: GITHUB_PAT=... (and source it -- §6.5)
cd server && uv sync        # backend deps
cd web && npm install       # portal deps
```

### 6.3 Run the QA flow

Bring the stack up and work from the portal:

```bash
make up                     # http://localhost:8080
```

Create a project, then **New Target** (§2) — that commits its revision 1. Write a story in the target's Stories panel, then start a run and pick the story and mode. The run view streams each step and offers pause/resume/stop. One run per target at a time (§0).

To check or force the target repo's state (the first approved delivery folds the setup in, so neither is usually needed):

```bash
make check     APP=saucedemo            # read-only, from Postgres: delivered, or N revisions ahead
make bootstrap APP=saucedemo            # push the infra entries to the target repo now
```

To start a target repo over from scratch (wipe all history, branches and PRs), reset it first, then re-bootstrap:

```bash
make reset APP=practice-target DRY=1                                           # preview
make reset APP=practice-target CONFIRM=prashant-kiit/e2e-playwright-test-custom-target
make bootstrap APP=practice-target                                             # rebuild the infra
```

Then review the generated tests and deliver the story yourself:

```bash
make deliver APP=saucedemo STORY=SCRUM-101 DRY=1    # preview what would be pushed
make deliver APP=saucedemo STORY=SCRUM-101          # open/update the PR
```

The agent never delivers, in any mode.

### 6.4 Run the tests directly

```bash
# This repo has no Playwright suite of its own any more: a target's tests live in
# its revisions, and the config they run under is generated per target. To run a
# suite by hand, materialize a revision (or let a run hydrate one) and work there:
cd "$QA_WORKTREES_DIR/<run-key>"
npx playwright test                                         # all four projects
npx playwright test tests/checkout/ --project=chromium
npx playwright show-report                                  # open the last HTML report

make test                                                   # the harness's own checks (ruff + pytest + vitest)
```

### 6.5 Secrets

- The only secret is `GITHUB_PAT` (plus `QA_ADMIN_PASSWORD` for the portal login).
- **Locally:** keep it in `.env` (git-ignored) and **source it yourself** — `set -a; . ./.env; set +a` — before `make deliver`. Nothing reads the file for you: the delivery tools read `GITHUB_PAT` from the process environment and nowhere else.
- **CI/sandbox:** inject it as a platform secret (e.g. a GitHub Actions secret named `GITHUB_PAT`; `GITHUB_TOKEN` is a reserved name). This repo's own CI needs **no** secrets — it never touches a target repo.
- Never put a real value in `.env.example`, `server/app/agent_runtime/mcp.json` or any committed file. **The PAT comes from the environment only** — the `.env`-beside-the-workspace fallback was deleted in P3, because the delivery workspace is a tree an LLM wrote while reading a live customer website.
- In a container, pass it at run time (`docker run -e GITHUB_PAT`), never at build time.

---

## 7. Reliability mechanisms

### 7.1 Timeouts (no infinite hangs)

- **What happened:** an agent's `browser_click` on a hidden menu link waited 58 minutes, and a `browser_run_code_unsafe` waited for a form field that no longer existed.
- **Root cause:** Playwright's default `actionTimeout` is 0 (unlimited), and a paused MCP test has no test timeout.
- **Fix:**
  - `actionTimeout: 10_000` and `navigationTimeout: 15_000` in the config. A stuck action now fails after 10 seconds with a reason like "element is not visible", which the agent can recover from.
  - `MCP_TOOL_TIMEOUT=120000` in settings as a backup.

### 7.2 Reports

The QA results report is generated by **CI** (the Job Summary of each `playwright.yml` run in the *target* repo), not by the agent — see §5.5. The agent writes no report file; it only puts a short scope summary in the PR body. (`apps/saucedemo/reports/` still holds the earlier SCRUM-101/103 reports from before this change.)

### 7.3 Graceful browser shutdown ([server/app/agent_runtime/hooks/close-test-browsers.sh](server/app/agent_runtime/hooks/close-test-browsers.sh))

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

### 7.4 Crash recovery (runs)

Run state lives in Postgres, and the per-app lock is a **lease**, not a boolean. A run that dies holding the lock leaves an expired lease; `app/reaper.py` (and the next `start_run`) reaps it and frees the app. A **paused** run keeps its lock with the lease cleared, and the reaper skips `PAUSED` runs so a deliberate pause is never mistaken for a crash. That trio is the subtlest correct thing in the codebase — leave it alone.

---

## 8. Delivery contract (human step, target repo)

Delivery is a **human-initiated step** after reviewing the agent's generated tests. It is handled by the commands in §5.6, not by an MCP server, by the agent, or by hand-crafted git. The agent repo is the source of truth.

0. Deliver to the target's own repo, from its configuration row. Never mix targets in one repo.
1. **Bootstrap is folded into the first approved delivery** ([DESIGN.md decision 16](.claude/harness/DESIGN.md#14-decision-log)), so one approval means "set the repo up and deliver this story". `bootstrap <app>` still exists to push the infra entries (`package.json`, `package-lock.json`, the generated `playwright.config.ts`, `.gitignore`, `.github/workflows/playwright.yml`) on their own — run it after an infra or workflow change so existing repos pick it up. `app.json` is never delivered: configuration is SaaS-internal.
2. **"Is this delivered?" is one Postgres query.** The head revision either carries a `delivered_sha` or it is N revisions ahead of the newest one that does; a target is *bootstrapped* if any of its revisions carries one. `check <app>` prints that, the portal shows it as a badge, and neither touches the network — so the answer is the same for everyone and does not depend on GitHub being reachable.
3. **Delivery is a human step** run after review: `push <app> <STORY_ID>` materializes the head revision, writes it onto `qa/<STORY_ID>-<slug>`, squashes it into one commit, opens or updates the PR into `targetBranch`, and **records `delivered_sha` on the revision it delivered**. The story's tests folder is replaced wholesale so deletions propagate; nothing else is deleted, because customer drift is not a delivery's to clean up. If the branch already held those bytes, the existing sha is recorded anyway — "delivered" is about the bytes, not about whether we made a commit. No report or evidence is pushed (CI generates the report). The agent does not run this.

App-specific delivery facts live in that app's `agentNotes`. Currently: the SauceDemo repo has history (bootstrap done, PR #1 merged, branch `qa/SCRUM-101-checkout` exists) and still has the pre-refactor paths (`user-stories/scrum-latest.md`, `specs/saucedemo-checkout-test-plan.md`, `tests/seed.spec.ts`, `tests/saucedemo-checkout/`, `reports/SCRUM-101-checkout-test-report.md`), which the next SauceDemo delivery should delete. The Practice Target repo is kept empty as the throwaway for verifying delivery end to end.

---

## 9. Gotchas (read before changing things)

| Symptom / temptation | Reality |
|---|---|
| Removing `actionTimeout` / `navigationTimeout` | Agents will hang indefinitely on missing elements (§7.1) |
| Writing outputs under `test-results/` | They are deleted on the next test run |
| Delivery auth or push fails | No `GITHUB_PAT` **in the environment**, or the token lacks push/PR/`workflow` rights to the target repo (`reset` also needs force-push and branch-delete rights). Neither `gh auth login` nor a `.env` beside the workspace is a fallback any more — the workspace is a tree the agent wrote (§5.6) |
| Re-adding the `gh auth token` fallback "to be helpful" | It was removed on purpose with `gh` itself (DESIGN.md decision 20). `GITHUB_PAT` is the only credential path |
| Removing the `jq` from the workflow template | It is harness *output*, running in a customer's GitHub Actions. "Drop `gh` and `jq`" was about our tooling only (§5.5) |
| Neutering the workflow template's `on:` triggers, or moving it back to `.github/workflows/` | The template is deliberately at a path GitHub Actions does not read. Killing the triggers instead would leave the **delivered** copy inheriting a dead trigger, so it would never run in the customer's repo either — the exact failure the move prevents (DESIGN decision 23) |
| Looking for `scripts/run-stories.sh` or the other `scripts/*.sh` | All six are gone (P1). Use `python -m app.delivery …` / `make check\|bootstrap\|deliver\|reset`. Batch runs were dropped outright, not ported (§2) |
| Expecting to run several stories of one app at once | Refused: one live run per app, `RunConflict` → 409. There is no queue (§0, §2) |
| Using `${input:...}` in `server/app/agent_runtime/mcp.json` | That's VS Code syntax. Claude Code only supports `${VAR}` / `${VAR:-default}` |
| Relying on the default MCP project | Always pass `project: chromium` and `seedFile: seed.spec.ts` to `*_setup_page` |
| Looking for `playwright.config.ts`, `apps/` or `prompts/` in this repo | All deleted in P3. The config is generated from the target's row; a target's tree is a revision; the prompts, the agent runtime and the delivery templates are **package data** under `server/app/` |
| Adding a module that resolves "the templates" or "the prompts" relative to the checkout | That is the mount, by another name. `tests/test_no_repo_mount.py` fails on any reference to a repo-root helper or `QA_REPO_ROOT`, which is what keeps a shared disk from being quietly reacquired |
| Expecting the API to scale horizontally because "the mount is gone" | It removed the *shared authoritative* disk, not the local scratch. The worktree and run dir are local and the SSE bus is in-process, so a live run is pinned to the replica that started it until P4 |
| Agent opens the burger menu via `browser_evaluate` (JS click) and then clicks a menu item | The menu stays `aria-hidden`, so the item is never visible. Open it with a real `browser_click` on `[data-test="open-menu"]` (or the "Open Menu" button) |
| Assuming SauceDemo rejects whitespace or special characters in checkout fields | It accepts them and moves to step two. Tests document this as an observation, not a defect, so code that re-fills the form afterwards will fail |
| Cart page "total price" (AC1) | SauceDemo shows no total on the cart page. Totals appear on the overview page (AC3). This is documented in the report |
| Adding `Write(...)` permission rules | They have no effect. Use `Edit(...)` |
| Re-running `npx playwright init-agents` | Overwrites the agent definitions, and writes them to `.claude/agents/` — **not** `server/app/agent_runtime/agents/`, where they now live (§5.2). Move them back, or the orchestrator keeps using the old ones |
| Putting the agent's permissions/hooks/MCP back in the repo-root `.claude/` | `.claude/` is development-only. The orchestrator loads `server/app/agent_runtime/` explicitly with `--setting-sources ""`, so anything added to `.claude/` is invisible to a real run (and anything the agent needs is invisible if it's only there) |
| `.playwright-mcp/` filling up | Expected (MCP logs and snapshots). It's git-ignored and safe to delete |
| Building the test schema with `Base.metadata.create_all` | `conftest.py` runs the **Alembic migrations from zero** on purpose: a revision that forgets a column still passes a `create_all` suite. It is the only thing that catches migration drift before deploy |
| A green backend test run that "passed" with no database | Most of the suite *skips* when Postgres is unreachable, silently, exit code 0. CI sets `QA_REQUIRE_DB=1` to fail instead, plus a zero-skip check. Use `make ci-test` locally |
| "Modernising" `class Step(str, Enum)` to `StrEnum` (ruff `UP042`) | The two stringify differently (`str(Step.PLAN)` → `"Step.PLAN"` vs `"plan"`), and the VARCHAR-backed columns and their CHECK constraint are written in terms of the member values. The ignore in `server/pyproject.toml` explains it |
| Putting a git argv or stderr into an error message unredacted | The clone URL carries the PAT (`https://x-access-token:<token>@…`), and a `GitError` message reaches the API's HTTP detail and the portal's bootstrap banner. `delivery/errors.py`'s `redact()` is the choke point where it stops — don't bypass it by formatting argv yourself |
| Faking `git` in the delivery tests | They're mostly git plumbing, so faking git would test the fake. Use `tests/delivery_helpers.py`: real git against a bare repo on disk, fake only the GitHub REST calls |
| Adding a second step-boundary callable to `run_pipeline` | The driver keeps exactly **one** injection point. Compose into `collect` instead ([DESIGN.md §13](.claude/harness/DESIGN.md#13-migration-plan)) |

---

## 10. Debugging a stuck or failed run

1. **The portal first:** the run view streams each step's log; `runs/` holds the per-run working dir (transcript, Playwright output), and artifacts are browsable per run.
2. **Playwright MCP server log** (fastest for a stuck tool call):
   `~/Library/Caches/claude-cli-nodejs/-Users-prashant-Desktop-Project-e2e-playwright-test-agent/mcp-logs-playwright-test/*.jsonl`
   A repeating `Tool '<name>' still running (Ns elapsed)` means that call is stuck. The preceding `Calling MCP tool` line names it.
3. **Session and sub-agent transcripts:**
   `~/.claude/projects/-Users-prashant-Desktop-Project-e2e-playwright-test-agent/<session-id>.jsonl` and `.../<session-id>/subagents/agent-*.jsonl`. These hold the exact tool arguments, e.g. the selector or code that hung.
4. **Browser console and page snapshots:** `.playwright-mcp/console-*.log`, `.playwright-mcp/page-*.yml`.
5. **Browser cleanup log:** `.playwright-mcp/close-test-browsers.log`.
6. **API/orchestrator logs:** `make logs` (all services) or `docker compose logs api`.
7. **While a run is live:** watch the headed browser. An idle page while Claude Code waits on a tool call means a stuck action; press Esc to cancel that call without killing the flow.

(Cache and transcript paths are derived from the project's absolute path and differ on another machine.)

---

## 11. Roadmap and open questions

The target architecture and the five-phase migration plan live in [.claude/harness/DESIGN.md](.claude/harness/DESIGN.md).

- **P1 (shell → Python, no architecture change) is done** — [VERIFICATION-P1.md](.claude/harness/VERIFICATION-P1.md) records what was tested live and what is only covered by fakes.
- **P2 (revisions + `file_index` + content-addressed blobs, dual-written from `apps/`) is done** — specced in [SPEC-P2-revisions.md](.claude/harness/SPEC-P2-revisions.md), closed out in [VERIFICATION-P2.md](.claude/harness/VERIFICATION-P2.md). It was dual-write only: `apps/` stayed authoritative and nothing read the new tables to make a decision, which is what let P3 flip them with evidence rather than hope.
- **P3 (flip reads to the database and blobs, delete the repo mount) is done** — specced in [SPEC-P3-flip-reads.md](.claude/harness/SPEC-P3-flip-reads.md), closed out in [VERIFICATION-P3.md](.claude/harness/VERIFICATION-P3.md). Configuration is a row, the tree is a revision, a run hydrates its own worktree and throws it away, delivery pushes a materialized head revision and records `delivered_sha`, and "is this in sync?" is one query. `apps/`, `app.json`, the `/workspace` mount, `config.repo_root()` and parity are deleted; a structural test keeps the mount from coming back. The round-trip property — materialize a revision, re-scan it, same tree hash — replaced parity's comparison.
- **P4 (extract the runner into a container per run, with §6's isolation and egress) is next.** It inherits exactly what P3 left for it: hydrate, ingest and teardown as three plain functions around the pipeline, a worktree path travelling through `StepContext`, and dependency install already isolated as the one step a prebaked image replaces. It is also what makes a live run stop being pinned to one replica.

Open themes, beyond the phased plan:

- **Batch runs.** Dropped with `run-stories.sh` and not replaced (§2). Reinstating them means a queue above the per-app lock, with its own design.
- **Portal coverage.** Delivery and reset are API routes with no UI yet (§0). Prompt/config write-back from the UI is also open.
- **Real-runner wiring.** `QA_RUNNER=fake` is the default. The real runner is wired end to end and verified ([VERIFICATION-P3.md](.claude/harness/VERIFICATION-P3.md)), but the API image ships neither the `claude` CLI nor node, so running it there needs P4's prebaked sandbox image.
- **Human in the loop.** Questions the agent would ask should surface in the portal, with answers flowing back. Today runs are unattended, with safe defaults recorded in the session summary.
- **Scope control.** Generate tests only for what changed; split agents into bounded scenarios; commit in batches rather than one bulk commit.
- **Artifact hygiene.** A feature to clean up artifacts, and keeping only one version of each.
- **Blob garbage collection.** The reference graph (`revisions` + `file_index`) that DESIGN.md §9's mark-and-sweep needs exists, and orphan blobs are left behind deliberately — "blob before row" guarantees them, and deleting a target drops its index rows but not its bytes. The sweep itself is unbuilt.
- **Cost.** Keep the agent on a cheap model and the stories lean (~2 ACs) — each run costs a full agent session.
- **Prompts in Postgres.** The prompts are code-shipped package data (`server/app/prompts/`), rewritten in P3 for the per-target worktree. DESIGN.md §12's `prompts` table, tenant overrides and versioning are P5.

> The original `TASK.md` backlog was folded into this section and deleted. Items 1–2 and 4 of it referred to the abandoned OpenCode setup; everything still live is either above or in DESIGN.md. It is recoverable from git history.

---

## 12. Rules for agents working in this repo

- The tracked tree's shape is defined once, in [render.py](server/app/delivery/render.py): hydrate, ingest and delivery all read it from there, so they cannot disagree about what the product versions. If you change the folder convention, change it there and update the step prompts, `server/app/agent_runtime/settings.json` permissions and this README together.
- Don't hard-code secrets. `GITHUB_PAT` comes from **the environment only**; there is deliberately no file fallback.
- Keep the action/navigation timeouts in the generated config's renderer. Target-specific settings belong in the target's **row**, never hard-coded into the renderer or a prompt.
- Generated artifacts belong in `specs/` and `tests/<slug>/` **of the run's worktree**, which ingest turns into a revision. The results report is generated by CI (§5.5), not written here. Don't hand-edit generated tests unless you're acting as the healer.
- After changing the generated config's renderer or an infra template, re-run `make bootstrap APP=<app>` for each live target so their repos pick it up, and check the next run's hydrate still produces a tree whose seed passes.
- Run `make test` before committing backend or portal changes: the same three checks CI runs (ruff, pytest, vitest). CI additionally *requires* a database — `make ci-test` adds that, and is the closer match.
- Don't commit `test-results/`, `playwright-report/`, `.playwright-mcp/`, `.env`, `server/junit.xml` or `.claude/settings.local.json`.
