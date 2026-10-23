# P1 verification record

**Phase:** P1 of [DESIGN.md §13](DESIGN.md#13-migration-plan) — "Shell → Python, in place. No architecture change."
**Verified:** 2026-10-23, on `portal/build`.
**Purpose:** so "P1 is done" is a claim backed by evidence rather than by the absence of
complaints — and so the next phase knows which paths are *proven* and which are only
covered by fakes.

---

## Definition of done for P1

P1 is done when all of these hold. All held at the time of writing.

1. The six `scripts/*.sh` tools are gone and their behavior exists as Python returning
   typed results. No `gh` and no `jq` anywhere in *our* tooling.
2. Every delivery function works through the single injected `Tools` seam; none reaches for
   credentials or git outside it.
3. `cd server && uv run pytest` is green with no skips, and the count does not regress.
4. `cd web && npm test` is green and does not regress.
5. `cd server && uv run ruff check .` is clean.
6. CI runs all three on every push, with Postgres available, and fails if tests skipped.
7. Each of the four delivery commands has been run against a real GitHub repo at least
   once, **including the mutating ones**, with the outcome recorded here.
8. The docs describe commands that exist; no dangling cross-references.
9. P1 is committed on `portal/build`.

**No architecture change** was made: no revision/`file_index` tables, no blob content
storage, no `tenant_id`, no sandbox, no multi-tenancy. `QA_REPO_ROOT`, the `/workspace`
mount and filesystem-owned config all stay, as P1's contract requires.

## Automated suites

| Check | Result |
|---|---|
| `cd server && uv run pytest` | **170 passed**, 0 skipped (was 165 before closeout) |
| `cd web && npm test` | **13 passed**, 4 files (was 12) |
| `cd server && uv run ruff check .` | **clean** (was 11 errors, all in `alembic/`) |
| `cd server && uv run ruff check app/` | clean |
| `make test` | runs all three (ruff → pytest → vitest) |

The +5 backend tests are the typed-result change at the `run_bootstrap` seam and the CI
skip-guard tests; the +1 frontend test is the failed-bootstrap outcome in the portal form.

### The skip guard, measured

The DB-backed tests skip when Postgres is unreachable, which is correct locally and
dangerous in CI. Measured on this suite with no database reachable:

```
$ DATABASE_URL=…@127.0.0.1:59999/qa uv run pytest -q
65 skipped, 105 passed            # exit code 0
```

**65 of 170 tests skip and pytest still exits 0.** That is the green tick CI must not be
able to produce, so:

- `QA_REQUIRE_DB=1` turns conftest's "Postgres unreachable" skip into a loud failure.
  Verified both directions (`tests/test_db_guard.py`, plus end to end against a dead port:
  the DB tests error instead of skipping).
- A CI step reads the junit report the test step already wrote and fails if *any* test
  skipped. Verified the parser reports `0` on a normal run and `65` on the run above.

The schema under test is built by **running the Alembic migrations from zero**, not
`Base.metadata.create_all`. CI preserves that; it is the only thing that catches migration
drift before deploy.

## Live verification against real GitHub

Target repos used:

- `prashant-kiit/e2e-playwright-agent-test-target` — the real SauceDemo target (has
  history; read-only checks only).
- `prashant-kiit/e2e-playwright-test-custom-target` — the **throwaway**, used for the
  mutating commands and reset afterwards.

### Read-only and dry-run

| Command | Outcome |
|---|---|
| `check saucedemo` | correctly reports bootstrapped; exit 0 |
| `check practice-target` (before bootstrap) | correctly reports NOT bootstrapped, prints the remedy; exit 1 |
| `bootstrap practice-target --dry-run` | resolved the target and listed all 7 infra files without pushing |
| `push practice-target SCRUM-201 --dry-run` | named the branch `qa/SCRUM-201-auth`, the three artifact paths and the PR title; pushed nothing |
| `reset practice-target --dry-run` | previewed the wipe and the branches it would delete; changed nothing |

### Mutating — the full cycle (the main risk this record closes)

Run in order against the throwaway repo:

| Step | Command | Outcome |
|---|---|---|
| 1 | `bootstrap practice-target` | **pushed** all 7 infra files as the first commit on `master`. The `.github/workflows/playwright.yml` push also proves the token's `workflow` scope works |
| 2 | `check practice-target` | now reports **bootstrapped**; exit 0 — the NOT-bootstrapped → bootstrapped transition verified live |
| 3 | `bootstrap practice-target` (again) | `already in sync - nothing to push.` — idempotent, no empty commit |
| 4 | `push practice-target SCRUM-201` | created branch `qa/SCRUM-201-auth` and **opened PR #1** |
| 5 | `push practice-target SCRUM-201` (again) | `branch already matches the agent repo - no new commit`, **reused PR #1** — no duplicate PR, no force-push |
| 6 | `reset practice-target --confirm-repo wrong/repo` | **refused**: `confirmation did not match`; exit 2. Nothing touched |
| 7 | `reset practice-target --confirm-repo <correct>` | `master` replaced with a single empty commit; `qa/SCRUM-201-auth` deleted (closing PR #1) |
| 8 | `check practice-target` | back to NOT bootstrapped; exit 1. Repo left as found |

Verified via REST after step 8: `master` has an empty tree, the story branch is gone, and
`find_pr` returns `None` for it.

Two properties checked on the pushed result, both deliberate:

- **Commit identity.** Commits in the target are authored `qa-harness
  <qa-harness@users.noreply.github.com>`, ported faithfully from `qa-lib.sh`'s `qa_git`, so
  history attributes them to the harness and not to whoever ran the server.
- **What the story branch carries.** Exactly the story, the plan and the tests folder on
  top of infra — no report, no evidence, no other app's folder.

> `push` needs a generated suite, and `practice-target` has none, so step 4 used a
> throwaway plan + spec file written for the purpose, clearly labelled as a fixture and
> deleted afterwards. It exercised the delivery path, not the generator. `push` against a
> story with no tests folder fails correctly with
> `no test suite at … - run the QA flow (steps 4-5) first`.

### Exit-code parity with the old scripts

Checked per command (user story 32), so wrappers and muscle memory still work:

| Situation | Exit |
|---|---|
| any command, success | `0` |
| `check`, target not bootstrapped | `1` |
| unknown app (`check`/`bootstrap`/`push`) | `2` |
| `reset` without `--confirm-repo` and without `--dry-run` | `2` |
| `reset` with a mismatched `--confirm-repo` | `2` |

`1` is reserved for `check`'s "not bootstrapped" and is never used for anything else.

### Credentials

`GITHUB_PAT` is now the only credential source — the `gh auth token` fallback went with
`gh`. This is an **intentional behavior change** (DESIGN.md §11), documented in README
§5.6, not a regression to be "fixed".

The token used reported scopes `project, repo, workflow, write:packages` and an expiry of
**2026-11-02**. Worth noting operationally: delivery stops working that day until the PAT
is rotated. A fine-grained PAT reports *no* scopes, which the client treats as "cannot
tell" rather than "insufficient", so it is not pre-rejected.

## What is covered only by fakes

Honest limits of the above — these are exercised in the suite but not against real GitHub:

- **`delivery/github.py`'s request construction and response parsing.** Covered offline by
  `test_delivery_github.py` through `httpx.MockTransport` (18 tests, 28 assertions across
  the six operations, the 409-means-empty-repo and 404-means-absent signals, 401/403 raising
  `CredentialError` rather than reading as "absent", scope/expiry header parsing). The live
  runs above exercised the same client for real, but only the happy paths.
- **Git plumbing semantics** — wholesale tests-folder replacement, branch reuse, the
  no-force-push property. Covered by real git against a bare on-disk remote
  (`tests/delivery_helpers.py`); faking git would test the fake.
- **Error paths on the mutating commands**: a mid-push network failure, a token that loses
  access between operations, a protected branch refusing the reset. None of these were
  provoked against real GitHub.
- **The API delivery routes** (`POST /targets/<id>/deliver`, `/reset`) are tested with
  dependency overrides and no network (`test_api_delivery.py`); they have not been driven
  against real GitHub through HTTP.

## Decisions recorded during closeout

| Question | Decision |
|---|---|
| `run-stories.sh` — superseded or dropped? | **Dropped, not superseded.** DESIGN.md §11 now says so and lists the four lost capabilities. Batch runs are gone; reinstating them means a queue above the per-app lock and is its own work |
| DESIGN.md §5's "the rest queue" | Marked **not yet implemented**. A second run on a live target is rejected (`RunConflict` → 409), and the portal already says "This app already has a live run." |
| 9 × `E501` in the generated migration | **Excluded `alembic/versions/` from `E501`** rather than reflowing: every future autogenerated revision would otherwise reopen it. Import order and the other rules still apply there |
| `ruff format` | **Not adopted.** 28 files would be reformatted and it would bury the P1 diff. Separate commit if ever wanted |
| `pyproject.toml`'s `CHECKPOINT-0 §5` citation | File does not exist in the repo; the actual reason is now **inline** on the `UP042` ignore |
| `TASK.md` | **Folded into README §11 and deleted** — deliberately, not left as an unstaged deletion. Recoverable from git history |
| `jq` in `.github/workflows/playwright.yml` | **Out of scope**, documented in DESIGN.md §11 and README §5.5. That file runs in a customer's GitHub Actions, which has `jq` and not our Python |
| `apphub.run_bootstrap`'s `{"rc", "output"}` | Replaced with a typed `BootstrapOutcome(ok, output)`; the portal still reports an outcome plus text, and a `DeliveryError` is still an outcome, not a 500 |
| A second driver seam for P2's sync-out | **Not added.** `run_pipeline` keeps exactly one step-boundary callable; P2 composes behind it. Recorded in DESIGN.md §13 and on the function itself |

## Known gaps left open at the end of P1

Not defects in P1, but the next reader should know:

0. **`prompts/` still tells the agent to run a deleted script.** Found during closeout and
   **deliberately not fixed**: this spec puts prompt content out of scope. But it is the
   most likely way the P1 migration bites someone, so it is written down here rather than
   left to be discovered:

   | File | Stale instruction |
   |---|---|
   | `prompts/qa_system_prompt.md` | lines 5, 56, 71, 103, 293, 298, 311, 321 — "a human runs `./scripts/push-artifacts.sh {APP} {STORY_ID}`"; line 103 also claims "`run-stories.sh` already verifies bootstrap" |
   | `prompts/steps/5-heal.md` | line 26 — same `./scripts/push-artifacts.sh` reference |

   None of these runs during a QA flow (the agent is told *not* to deliver, and has no
   permission to), so nothing is broken today — but the text names a file that no longer
   exists and a batch runner that is gone. The replacement wording is
   `python -m app.delivery push <app> <STORY_ID>` / `make deliver APP=… STORY=…`.
   **Recommended as the first small task after P1.**

1. **No batch runs.** One story per run, serialized per app, no queue.
2. **Delivery has no portal UI.** The routes exist; only the bootstrap form is wired up, so
   delivery is CLI-only in practice.
3. **`QA_RUNNER=fake` is the default.** Running the real `claude` CLI inside the API
   container is not wired end to end.
4. **The PAT expires 2026-11-02.**
