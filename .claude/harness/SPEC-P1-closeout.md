# Spec: P1 closeout — verify and land the shell → Python migration

**Triage label:** `ready-for-agent`
**Phase:** P1 of [DESIGN.md §13](DESIGN.md) ("Shell → Python, in place. No architecture change.")
**Status of P1 at time of writing:** functionally complete, entirely uncommitted, documentation removed.

---

## Problem Statement

P1 of the migration plan — replacing the six `scripts/*.sh` tools with Python modules
returning typed results — has been *written* but never *landed*. For the maintainer of
this harness that means:

- **The work exists only as dirty working tree.** Six script deletions are staged; 26
  modified files and 13 new files are not. There is no commit on `portal/build` containing
  any of P1. A lost working tree loses the whole phase.
- **The documented entry point is gone.** `README.md` (497 lines) and `TASK.md` (98 lines)
  are deleted and unstaged, with nothing in their place. README was explicitly addressed to
  coding agents ("read this file top to bottom before changing anything") and carried the
  gotchas section recording failures that had already happened. `DESIGN.md` still links to
  `README.md#0-admin-portal-web-ui`, which now resolves to nothing.
- **A capability was dropped silently.** `run-stories.sh` ran several stories of one app in
  parallel, skipped stories already generated, could force a redo, could preview with
  `--dry-run`, and wrote a batch summary. DESIGN.md §11 records it as "already superseded by
  `orchestrator/driver.py`". It is not: the driver runs exactly one story, and starting a
  second run on the same app is *rejected* with `RunConflict` → HTTP 409. DESIGN.md §5 says
  "the rest queue", but there is no queue anywhere in the server. Batch operation is simply
  gone, and nobody reading DESIGN.md would know that.
- **Nothing enforces that any of this still works.** The only workflow in
  `.github/workflows/` is `playwright.yml`, which is the file pushed *into customer repos* —
  it never runs this repo's own tests. `make test` exists but no automation calls it, and it
  does not run `ruff` at all.
- **The GitHub client has no test coverage.** Every `test_delivery_*.py` fakes the GitHub
  REST calls. The real `httpx`-based client's request construction and response parsing are
  exercised only by hand.

The result is a phase that is *probably* done, with no artifact proving it and no commit
preserving it.

## Solution

Close P1 out properly: prove what works, record what was deliberately dropped, fix the
small defects, restore the documentation to match reality, and commit the phase as a
reviewable unit.

Concretely, the maintainer gets:

1. A **verification record** of what was tested and how, so "P1 is done" is a claim backed
   by evidence rather than by the absence of complaints.
2. **Documentation that matches the code** — a rewritten README describing the Python
   delivery tools and the portal, with the dangling cross-references repaired.
3. **An explicit decision on batch runs**: either reinstate the capability, or record its
   removal in DESIGN.md so the "superseded by the driver" claim stops being wrong.
4. **CI that runs the backend and frontend suites plus lint**, so P2 starts on a green,
   enforced baseline.
5. **P1 committed** on `portal/build` in coherent commits.

### What verification already established

These were run during specification and should not be re-derived from scratch; re-run them
as regression checks:

| Check | Result |
|---|---|
| `cd server && uv run pytest` | **165 passed** |
| `cd web && npm test` | **12 passed** (4 files) |
| `uv run ruff check app/` | **clean** |
| `uv run ruff check .` | **11 errors**, all in `alembic/` (10× E501 + 1× I001 in the generated initial migration, 1× I001 in `env.py`) |
| `python -m app.delivery check saucedemo` (live GitHub) | correctly reports bootstrapped |
| `python -m app.delivery check practice-target` (live GitHub) | correctly reports NOT bootstrapped, prints the remedy |
| `python -m app.delivery bootstrap practice-target --dry-run` (live clone) | resolves the target and lists all 7 infra files without pushing |
| `scripts/` directory | gone; no `gh` or `jq` remains in harness tooling |

So the delivery path works against real GitHub for the read-only and dry-run commands. The
**mutating** commands (`bootstrap` for real, `push`, `reset`) have no live verification —
that is the main remaining risk, and it is what the acceptance criteria below target.

## User Stories

1. As a maintainer, I want P1 committed on `portal/build`, so that the phase survives a lost working tree.
2. As a maintainer, I want the script deletions and the Python modules that replace them in the same commit, so that the diff reads as a migration rather than as a deletion followed by unrelated additions.
3. As a maintainer, I want a written record of which P1 commands were verified live against GitHub, so that I know which paths are proven and which are merely tested against fakes.
4. As a maintainer, I want the mutating delivery commands verified end to end at least once against a throwaway repo, so that the first real delivery is not also the first real test.
5. As a coding agent, I want a README that describes the commands that actually exist, so that I do not try to invoke `scripts/push-artifacts.sh`.
6. As a coding agent, I want the gotchas section preserved from the old README, so that I do not reintroduce a failure that already happened once.
7. As a reader of DESIGN.md, I want its link to the README to resolve, so that §0's description of the current portal is reachable.
8. As a maintainer, I want `TASK.md` either restored, folded into the README, or deleted deliberately, so that its absence is a decision rather than an accident.
9. As an operator, I want to know whether I can still run several stories of one app in one go, so that I can plan a day's work.
10. As a maintainer, I want DESIGN.md's claim that `run-stories.sh` is "superseded by `orchestrator/driver.py`" corrected or made true, so that the design document does not misstate the system's capabilities.
11. As an operator, I want starting a run on an app that already has a live run to either queue or tell me clearly why it cannot, so that a 409 is not my first hint that batching is gone.
12. As a maintainer, I want CI to run the backend test suite on every push, so that a regression is caught by automation rather than by me remembering to run `make test`.
13. As a maintainer, I want CI to run the frontend test suite, so that the portal UI is covered on the same trigger.
14. As a maintainer, I want CI to run `ruff check`, so that lint is enforced rather than advisory.
15. As a maintainer, I want CI to stand up Postgres, so that the DB-backed tests actually execute instead of silently skipping.
16. As a maintainer, I want CI to fail loudly if the DB-backed tests skip, so that a green tick cannot mean "165 tests skipped".
17. As a maintainer, I want `make test` to run the same checks CI runs, so that local and automated results agree.
18. As a maintainer, I want the 11 `ruff` errors in `alembic/` resolved, so that `ruff check .` is clean and lint can be a gate.
19. As a maintainer, I want the decision about generated migration files recorded, so that the next generated migration does not reopen the question.
20. As an operator who authenticated with `gh auth login`, I want to be told that `GITHUB_PAT` is now required, so that I am not confused by an auth failure.
21. As a maintainer, I want the removal of the `gh auth token` fallback recorded as an intentional behavior change, so that it is not later "fixed" as a bug.
22. As a maintainer, I want `pyproject.toml`'s reference to `CHECKPOINT-0 §5` to point at something that exists, so that the rationale for a load-bearing lint ignore is actually readable.
23. As a maintainer, I want the `UP042` ignore to keep its explanation wherever that explanation now lives, so that nobody "modernises" the VARCHAR-backed enum columns and breaks them again.
24. As a maintainer, I want the real GitHub REST client covered by tests, so that a change to its request construction or response parsing fails in the suite.
25. As a maintainer, I want those tests to run without network access or credentials, so that the suite stays runnable offline.
26. As a maintainer, I want `apphub.run_bootstrap`'s shell-shaped `{"rc", "output"}` return value replaced by a typed result, so that P1's "typed results everywhere" goal is actually met.
27. As a portal user, I want the bootstrap form to keep reporting an outcome and some text after that change, so that the UI behaves the same.
28. As a maintainer, I want the driver to keep exactly one injected step-boundary callable, so that P2's sync-out work composes behind that single seam instead of adding a second driver parameter.
29. As a maintainer, I want the `jq` remaining in `.github/workflows/playwright.yml` documented as out of scope, so that nobody removes a dependency that runs in a customer's GitHub Actions rather than in our tooling.
30. As a reviewer, I want the P1 commits scoped so that the delivery modules, the documentation and the CI setup are separable, so that I can review them independently.
31. As a maintainer, I want a stated definition of done for P1, so that P2 can start from an agreed baseline.
32. As a maintainer, I want the per-command exit codes of the Python CLI confirmed to match the old scripts, so that any muscle memory or wrapper still works.

## Implementation Decisions

### Scope and sequencing

- This spec covers **P1 only**. It introduces no revision model, no blob content storage, no
  `tenant_id`, no sandbox and no multi-tenancy. Those are P2–P5 and are listed as out of
  scope below.
- The work is ordered **commit first, then fix**. The current state is functionally good
  (165 tests green, live GitHub verified on the read paths); preserving it beats improving it.
  The first commit should land P1 substantially as it stands.

### Documentation

- `README.md` is **rewritten, not restored**. Roughly half the old file documented the six
  shell scripts and their flags; that content is now wrong. The rewrite keeps the structure
  and voice, keeps §0 (the portal) and the gotchas, and replaces the shell-flow sections with
  the `python -m app.delivery` subcommands and their `make` wrappers.
- The old README is recoverable from git history, so the rewrite should be a deliberate
  reconstruction from the committed version rather than from memory.
- `DESIGN.md`'s cross-reference to `README.md#0-admin-portal-web-ui` must resolve after the
  rewrite — either keep that anchor or update the link.
- `TASK.md`'s fate is an explicit decision. Default: fold anything still live into the README
  and delete it, rather than leave a deleted file unstaged.
- The `CHECKPOINT-0 §5` rationale cited by `pyproject.toml`'s `UP042` ignore must end up
  somewhere that exists in the repo. Simplest option: inline the actual reason into the
  `pyproject.toml` comment and drop the dangling citation.

### The batch-run gap

- This is a **decision to make, not a defect to fix silently**. Two acceptable outcomes:
  - **Record the removal.** Amend DESIGN.md §11 so `run-stories.sh` is listed as *dropped*
    rather than *superseded*, and note in §5 that the queue it describes is not yet
    implemented. Cheapest, and honest.
  - **Implement the queue** DESIGN.md §5 already promises: a second run on a target with a
    live run is accepted and queued rather than rejected with `RunConflict`.
- The two are not equivalent in cost and should not be bundled. Prefer recording the removal
  in P1 and treating the queue as its own piece of work, because P1's contract is "no
  architecture change".
- Whichever is chosen, the portal's behavior when an app already has a live run must be
  intelligible to an operator rather than a bare 409.

### CI

- Add a workflow for **this** repo's own checks. It must not be confused with
  `.github/workflows/playwright.yml`, which is harness output pushed into customer repos and
  is not CI for this project.
- It runs: backend `pytest`, frontend `vitest`, and `ruff check`.
- It must provide **Postgres as a service**. `conftest.py` deliberately skips the DB-backed
  tests when Postgres is unreachable, so a CI job without a database would report success
  having run almost nothing. The job needs a guard that fails if the DB-backed tests skipped.
- `conftest.py` builds the schema by **running the Alembic migrations** from zero, not
  `Base.metadata.create_all`. CI must preserve that — it is the only thing that catches
  migration drift.
- `make test` and CI should run the same set of checks, with `ruff` added to `make test`.

### Lint

- `app/` is already clean; the 11 errors are all in `alembic/`. Choose one and record it:
  exclude `alembic/versions/` from `E501` (generated code, long `sa.Column` lines are
  idiomatic) while keeping `I001` fixed, or reformat the generated migration. Excluding
  generated migrations from line-length is the lower-friction answer, since every future
  autogenerated revision will have the same long lines.
- `ruff format` is **not** adopted as a gate in this spec. It currently reports 28 files
  needing reformatting; the project selects lint rules only, and a repo-wide reformat would
  bury the P1 diff. If wanted, it is a separate commit of its own.

### Typed results

- `apphub.run_bootstrap` currently returns `{"rc": int, "output": str}` — a shell-shaped
  value kept so the portal's bootstrap form and its tests did not have to change. It is the
  last untyped seam in the delivery path and P1's stated goal is typed results, so it should
  become a typed result object, with the portal form and `test_apphub.py` / the Bootstrap
  component updated to match.
- The portal's externally visible behavior must not change: the form still reports an outcome
  and some text, and a `DeliveryError` remains an outcome rather than a server error.

### Credentials

- The `gh auth token` fallback that `qa-lib.sh` had is gone; `GITHUB_PAT` (environment or
  `.env`) is now the only source. This follows from dropping `gh` (decision 20) and should be
  **documented as an intentional behavior change** in the README, not re-added.

### Seams

- **P1 adds no new seam.** The two seams it touches already exist and both stay single:
  - **Delivery**: the injected `Tools` value (GitHub client + git + token + workspace) that
    every delivery function takes. All four commands and all the API routes go through it,
    and it is what the tests substitute. No delivery function should reach for credentials or
    git outside it.
  - **Step boundary**: `run_pipeline`'s one injected callable, fired after each completed
    step. Artifact collection is composed behind it in the launcher. P2's sync-out (upload
    blobs, then commit a revision) must compose behind that **same single hook** rather than
    adding a second driver parameter — the driver keeps one injection point. Recording this
    here so P1's closeout does not accidentally add a second one.

## Testing Decisions

### What makes a good test here

Test observable behavior at the seam, not the path taken to produce it. This codebase
already states the principle well in `server/tests/delivery_helpers.py`: the delivery tools
are mostly git plumbing, so *faking git would test the fake*. Instead the git side is real —
a bare repo on disk standing in for GitHub — and only the GitHub REST calls are faked. Keep
that split. A test should assert what landed in the remote (files, branches, commit subjects)
rather than which git subcommands were invoked.

Two existing conventions are load-bearing and must not be weakened:

- The schema under test is built by **running the Alembic migrations from zero**, never
  `create_all`. A revision that forgets a column still passes a `create_all`-backed suite, so
  this is the only place migration drift can fail before deploy. `test_migrations.py` exists
  for exactly this.
- DB-backed tests **skip** when Postgres is unreachable so the pure-domain tests still run
  offline. That is correct locally and dangerous in CI, which is why CI needs the
  skip-detection guard rather than a change to this behavior.

### Modules to be tested

- **`delivery/github.py`** — the real `httpx` client, currently uncovered. Add tests driving
  it through a stubbed HTTP transport so request construction (paths, auth header, body) and
  response parsing (found/not-found, PR shape, token scopes) are asserted without network or
  credentials. This is the single largest coverage gap in P1.
- **`delivery/__main__.py`** — exit codes per command, confirming parity with the old
  scripts: `check` exits 1 when not bootstrapped, other failures exit 2, success 0.
  `test_delivery_cli.py` is the prior art.
- **`apphub.run_bootstrap` / `bootstrap_app`** — the typed-result change, asserted through
  the portal-facing behavior rather than the dict shape. Prior art: `test_apphub.py`, plus
  `web/src/pages/Bootstrap.test.jsx` on the frontend side.
- **Driver step boundary** — `test_driver.py` already injects the hook and asserts step rows,
  lock release and emitted lines. Keep `NullCollector` as the default so driver tests need no
  storage.
- **Regression baseline** — the full suite must stay at or above its current count (165
  backend, 12 frontend) with no new skips.

### Prior art to follow

| Need | Follow |
|---|---|
| Real git, fake GitHub REST, bare remote on disk | `server/tests/delivery_helpers.py` |
| Delivery command behavior | `test_delivery_bootstrap.py`, `test_delivery_push.py`, `test_delivery_reset.py` |
| CLI exit codes | `test_delivery_cli.py` |
| API routes with dependency overrides, no network | `test_api_delivery.py` |
| Migration-built schema, per-test truncation | `server/tests/conftest.py`, `test_migrations.py` |
| Fake blob storage | the `FakeStorage` class in `test_artifacts.py` |

### Acceptance criteria

- `cd server && uv run pytest` green, no new skips, count ≥ 165.
- `cd web && npm test` green, count ≥ 12.
- `cd server && uv run ruff check .` clean.
- CI runs all three on push, with Postgres available, and fails if DB-backed tests skipped.
- Each of the four delivery commands verified against a throwaway repo at least once,
  including the mutating ones, with the outcome recorded.
- `README.md` present, describing only commands that exist; DESIGN.md's link to it resolves.
- No dangling reference to `CHECKPOINT-0.md` remains.
- DESIGN.md's `run-stories.sh` row and §5 concurrency text agree with what the code does.
- P1 committed on `portal/build`; `git status` clean apart from deliberate ignores.

## Out of Scope

- **P2 and later.** No `revision` / `file_index` tables, no content-addressed blob storage,
  no dual-write from `apps/`, no `tenant_id` columns. P1's contract is "no architecture
  change" and this spec honors it.
- **P3's stateless API.** `QA_REPO_ROOT`, the `/workspace` mount and filesystem-owned config
  all stay. `config.repo_root()` stays, with its existing note that P3 removes it.
- **P4 sandboxing** — container-per-run, egress allowlists, per-run token budgets, wall-clock
  timeouts.
- **P5 multi-tenancy** — per-tenant encrypted PATs, KMS envelope encryption, quotas,
  tenant-scoped blob reads, GC.
- **The `jq` in `.github/workflows/playwright.yml`.** That file is harness output pushed into
  customer repos, where it runs inside GitHub Actions. Decision 20's "drop `gh` and `jq`"
  is about *our* tooling. Leave it alone.
- **Adopting `ruff format`.** 28 files would be reformatted; that is a separate, isolated
  commit if wanted at all, and bundling it would make the P1 diff unreviewable.
- **Prompt content.** `prompts/` and the agent definitions under `apps/agent/runtime/` are
  untouched.
- **Rewriting the batch runner.** If the queue is chosen over recording the removal, it is its
  own spec; this one only requires that the discrepancy stop being undocumented.

## Further Notes

- **DESIGN.md is not self-consistent about concurrency**, and P1 closeout is the moment to fix
  the text. §5 describes "one active run per target; the rest queue"; §11 describes
  `run-stories.sh` as superseded by the driver. In the code, `repo.start_run` takes the app's
  lock row `FOR UPDATE`, reaps an expired lease, and otherwise raises `RunConflict`. There is
  no queue and no batching. The lease-and-lock mechanism itself is good and well tested — it
  is only the surrounding prose that overstates it.
- **The lease lock deserves its reputation.** `start_run` reaping a stale lock from a crashed
  run, `pause_run` keeping the lock but clearing the lease, and the reaper skipping `PAUSED`
  runs so a deliberate pause is never read as a crash — that trio is the subtlest correct
  thing in the current code. Any P1 cleanup near it should leave it alone.
- **The delivery tests are a good model for P2.** Real git against a bare on-disk remote, fake
  only the network boundary. When P2 adds blob upload, the same instinct applies: real
  temporary worktree, fake only the object store.
- **`session.jsonl` placement is already decided** (decision 6: run artifact, not tree
  content) and `artifacts.classify` already files `.jsonl` as `log`. Nothing to do in P1, but
  worth knowing the groundwork is there.
- The harness identity on machine-made commits (`qa-harness`) was ported faithfully from
  `qa-lib.sh`'s `qa_git`, so history in customer repos keeps attributing these commits to the
  harness rather than to whoever runs the server. Preserve it.
- Live verification during specification used the two real target repos
  (`e2e-playwright-agent-test-target`, already bootstrapped; `e2e-playwright-test-custom-target`,
  still empty). The second is the natural throwaway for verifying the mutating commands, and
  `reset` exists precisely to put it back.
