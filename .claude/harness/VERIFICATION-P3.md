# P3 verification record

**Phase:** P3 of [DESIGN.md §13](DESIGN.md#13-migration-plan) — "Flip reads to DB + blobs;
`apps/` becomes derived; delete the repo mount."
**Spec:** [SPEC-P3-flip-reads.md](SPEC-P3-flip-reads.md) →
[issue #7](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/7), nine tickets
(#8–#16).
**Verified:** 2026-10-24, on `portal/build`.
**Purpose:** the same as P1's and P2's — so "P3 is done" rests on evidence, and so P4 knows
which paths are *proven* against a real agent, a real object store and a real customer repo,
and which rest on fakes.

The sentence this phase is measured against is §13's: *"Flip reads to DB + blobs; `apps/`
becomes derived; delete the repo mount."* All three clauses are requirements, so this record is
organised around them — plus the inversion, because P3 turns P2's central safety property
upside down on purpose and that is the phase, not a regression.

---

## Definition of done for P3

1. Target config lives in `targets`; `app.json` does not exist anywhere in the repo or in any
   delivered commit; `test_migrations.py` passes.
2. A real agent run (`QA_RUNNER=claude`) hydrates from the head revision, works in its own
   worktree, commits revisions at step boundaries and tears the worktree down.
3. Materializing any revision reproduces its tree hash exactly.
4. A run whose ingest fails ends `failed`, with the lock freed and the last good revision
   intact.
5. A story can be created, edited and deleted in the portal, each committing one revision; the
   same writes are refused while a run is live.
6. A delivery records `delivered_sha`, and the portal answers "delivered / N revisions ahead"
   without a network call.
7. The delivered `.github/workflows/playwright.yml` is byte-identical to the previous one and
   is no longer a workflow of this repository.
8. `grep -r QA_REPO_ROOT` finds nothing outside historical documents; the `/workspace` mount is
   gone from the compose file; `apps/` is deleted.
9. `make ci-test` green.

_(Each is checked off against observed evidence in **Acceptance criteria, line by line** below.)_

## Automated suites

| Check | Result |
|---|---|
| `cd server && uv run pytest` | **524 passed**, 0 skipped (was 247 at the end of P2) |
| `cd web && npm test` | **43 passed**, 6 files (was 28, 5 files) |
| `cd server && uv run ruff check .` | clean |
| `make ci-test` | green (all three, with `QA_REQUIRE_DB=1`) |

### New suites, and what each is for

| File | What it pins down |
|---|---|
| `tests/test_target_config.py` | A target's configuration round-trips through its row, and the refusal `resolve_target` used to perform at read time happens at the **write** path |
| `tests/test_infra_entries.py` | Infra entries carry `(source, destination)`; a source may be a renderer; the workflow template keeps its `on:` triggers and is no longer a workflow of this repo; the base URL survives into the generated config as a string literal and nothing more |
| `tests/test_hydrate.py` | **The round-trip property**, over five generated tree shapes; a missing or tampered blob fails the hydrate leaving no partial tree; a second hydrate is byte-identical; generated entries are rendered, not copied; teardown removes read-only `node_modules` |
| `tests/test_run_worktree.py` | A run works in its own worktree, two runs never share one, no-head-revision fails immediately, teardown fires at every terminal state and on pause, a resumed run re-hydrates, and the artifact sweep indexes no tracked file |
| `tests/test_authoring.py` | Creating a target commits revision 1; story create/edit/delete/rename each commit one revision; a config edit that reaches the tree commits one and one that does not commits none; every write is refused while a run is live |
| `tests/test_delivery_state.py` | *delivered* / *N revisions ahead* from one query, with `httpx` and `subprocess` poisoned; `delivered_sha` written by the catalog and nothing else; the workspace materialized and removed per operation |
| `tests/test_no_repo_mount.py` | **The structural half of the phase.** No module under the server package references a repo-root helper, the removed environment variable, or a path naming `apps/`; the prompts, agent runtime and delivery templates all resolve from inside the installed package with nothing mounted |
| `tests/test_agent_prompts.py` | The agent's working directory is the worktree; the prompt carries the row's `baseURL`, `locators` and `agentNotes`; no prompt names an app directory, `app.json`, a story glob or either P1-era shell script; every placeholder is substituted |
| `web/src/pages/Stories.test.jsx`, `TargetConfig.test.jsx` | The story editor and the config form, including the live-run conflict banner and the "nothing changed, so no revision" case |

### Changes to the existing suite

- **`test_tracked_tree.py` re-pointed, not rewritten.** The same exclusions, the same
  markdown-only globs, the same junk filtering — against a worktree root instead of
  `apps/<app>/`. That was the ticket's instruction and it held: only the fixture changed.
- **The parity tests are deleted, not adapted** (`server/tests/test_parity.py`, and the parity
  banner's cases in `web/src/pages/Revisions.test.jsx`). Parity compared the database against
  an authoritative filesystem; with one copy of the truth left there is nothing to compare
  against, and a check with nothing to check does not belong in the suite.
- **`test_step_boundary_revisions.py` inverted.** The cases asserting that a failed revision
  write leaves a run `completed` now assert that it leaves the run `failed`, with the lock
  freed and the previous head intact. That inversion is the phase.
- **`test_artifacts.py` passes unchanged**, which is the point of putting the worktree outside
  the run directory.

---

## Live verification

### The cutover, against a database with real rows in it

The dev database held two targets created under P1/P2 — `practice-target` (6 revisions from
P2's verification runs) and `saucedemo` (1) — at migration `8f21c4b07e3a`. It was dumped first,
then migrated and cut over:

```
$ uv run alembic upgrade head
INFO  Running upgrade 8f21c4b07e3a -> c3a7e90b41d2, P3: a target's configuration becomes columns on `targets`

$ uv run python -m app.cutover
practice-target: rev 7 (new), config imported
saucedemo: rev 2 (new), config imported
done: 2 target(s), 2 revision(s) committed, 2 config row(s) imported
```

Both targets snapshotted, **parity green on both** (the command refuses otherwise and names the
target), and both `app.json` files imported into their rows:

| | `base_url` | `target_repo` | branch | notes |
|---|---|---|---|---|
| `practice-target` | `https://custom-test-target-app.vercel.app` | `prashant-kiit/e2e-playwright-test-custom-target` | `master` | 3 |
| `saucedemo` | `https://www.saucedemo.com` | `prashant-kiit/e2e-playwright-agent-test-target` | `master` | 4 |

**Re-running it is a genuine no-op**, which is its contract:

```
$ uv run python -m app.cutover
practice-target: rev 7 (unchanged), config already current
saucedemo: rev 2 (unchanged), config already current
done: 2 target(s), 0 revision(s) committed, 0 config row(s) imported
```

The new revisions are not noise: the infra half of the tracked tree genuinely changed in this
phase — `playwright.config.ts` became generated, `package.json`/`package-lock.json` moved to
templates, and the workflow moved out of `.github/`. The cutover's snapshot is the first
revision of each target that describes the tree P3 hydrates.

### The round-trip property, against the real object store

The check that **replaced parity**, run over both real head revisions with blobs streamed from
SeaweedFS:

```
practice-target: rev 7
  committed  32809ba48347af26d8c4dbb31af3973db2eae8ed63c2be276f38701c54e1d828
  re-scanned 32809ba48347af26d8c4dbb31af3973db2eae8ed63c2be276f38701c54e1d828
  round trip OK
  generated config: baseURL present=True, unprefixed chromium=True
saucedemo: rev 2
  committed  3e7dfc919c291356e26a74877eecbeaf912f1b74b7c66e13ddfe5d74087ad714
  re-scanned 3e7dfc919c291356e26a74877eecbeaf912f1b74b7c66e13ddfe5d74087ad714
  round trip OK
  generated config: baseURL present=True, unprefixed chromium=True
```

Parity compared two copies and could only ever say "these two disagree". This says something
stronger and needs only one copy: *the bytes we stored reconstruct the tree we named*. It is
also the first thing to run after any change to the tracked-tree contract.

### Hydrate, with the real install step

`practice-target`'s head materialized into a fresh worktree, dependencies installed, on the
host where `npm` exists:

```
=== hydrate: installing dependencies (npm ci) ===
=== hydrate: worktree built from revision 7 (26 files) at /tmp/qa-dry-hydrate/wt ===
hydrate took 1.3s; rev=7 files=26 installed=True
--- worktree ---
   .github/  .gitignore  node_modules/  package-lock.json  package.json
   playwright.config.ts  seed.spec.ts  specs/  tests/  user-stories/
re-scan matches committed: 32809ba48347af26d8c4dbb31af3973db2eae8ed63c2be276f38701c54e1d828
```

Two things worth noting. The tree hash still matches **after** `npm ci`, which is the
`node_modules` exclusion doing its job on a real install rather than on a fixture. And the
whole hydrate took **1.3 s** against a warm npm cache — the step P4 replaces with a prebaked
image is already not the expensive part.

### The generated config, actually running

The generated `playwright.config.ts` was exercised by running the target's seed in the
hydrated worktree, against the live site:

```
$ QA_RUN_DIR=/tmp/qa-dry-hydrate/out npx playwright test seed.spec.ts --project=chromium
  ✓  1 [chromium] › seed.spec.ts:4:7 › Test group › seed (1.3s)
  1 passed (1.8s)
```

`chromium`, not `practice-target-chromium`: the config is single-target, which is what makes
the project name bare and what stops a project name or a test path from reaching another
customer's tests. Output landed in `QA_RUN_DIR`, not in the worktree.

### The API image, with nothing mounted

Rebuilt from the amended compose file and inspected:

```
$ docker inspect …api-1 --format '{{range .Mounts}}{{.Type}} {{.Source}} -> {{.Destination}}{{end}}'
volume  …/e2e-playwright-test-agent_apidata/_data -> /data

$ docker exec …api-1 ls /
app bin boot data dev entrypoint.sh etc home lib … usr var      # no /workspace

$ docker exec …api-1 env | grep '^QA_'
QA_FAKE_DELAY=0  QA_NPM_CACHE=/data/npm-cache  QA_RUNNER=fake
QA_RUNS_DIR=/data/runs  QA_WORKTREES_DIR=/data/worktrees         # no QA_REPO_ROOT

$ curl -sf localhost:8000/health
{"status":"ok","service":"qa-portal"}
```

One mount, and it is per-run scratch. The prompts, the agent runtime and the delivery templates
are all inside the image because they are inside `server/app/`:

```
$ docker exec …api-1 ls app/prompts/steps app/agent_runtime app/delivery/templates
app/prompts/steps:      1-read_story.md … 5-heal.md  _context.md
app/agent_runtime:      agents  hooks  mcp.json  settings.json
app/delivery/templates: gitignore  package-lock.json  package.json  seed.spec.ts  workflows
```

### The portal as the input surface, through the containerised API

A throwaway target created and driven entirely through the running container's HTTP API — no
filesystem anywhere in the picture.

**Creating a target commits revision 1 from the templates:**

```
POST /projects/8/targets  →  201
  target   {"id": 7, "app": "p3-verify", "base_url": "https://custom-test-target-app.vercel.app",
            "target_repo": "owner/p3-verify", "agent_notes": ["created by the P3 verification"]}
  revision {"rev": 1, "parent_rev": null, "author": "operator", "file_count": 6,
            "tree_hash": "c255a70fcf570a65cd19ae3b53b6613f4fb09c57893f3e3d594902fa13974e21"}
```

Six files: the seed plus the five infra entries, the generated config among them. The target
can be hydrated and run from that moment — which is what let the baseline-from-disk hook go.

**Every write commits one operator-authored revision, and only when something changed:**

| Action | Result |
|---|---|
| `PUT /targets/7/stories/SCRUM-900` | rev 2, 7 files |
| run 14 (five fake steps, changing no tracked file) | **no revision** — `rev` counts changes, not steps |
| `PUT` the story with edited content | rev 3 |
| `PUT` the *same bytes* again | `"revision": null` — nothing committed |
| `PATCH /targets/7/config {"base_url": "https://moved.example.com"}` | rev 4; the stored `playwright.config.ts` reads `const baseURL = "https://moved.example.com";` |
| `PATCH` only `{"locators": …}` | `"revision": null` — it reaches the agent through its prompt, not the tree |
| `PATCH {"base_url": "nonsense"}` | **422** `base URL must be an absolute http(s) URL, got 'nonsense'` |
| `DELETE /targets/7/stories/SCRUM-900` | rev 5, 6 files, story gone, its plan and suite untouched |

**And every write is refused while a run is live**, with the reason and the remedy:

```
PUT    /targets/7/stories/SCRUM-900  -> HTTP 409
PATCH  /targets/7/config             -> HTTP 409
DELETE /targets/7/stories/SCRUM-900  -> HTTP 409

detail: target 7 has a live run (14), which is working from an older revision. Saving now
        would be reverted by that run's next snapshot, and there is no merge. Wait for it to
        finish, or pause or stop it, then save again.
```

That is the honest answer rather than a queue: the run hydrated from an older head, and
resolving the conflict would need merge logic, which this system does not have anywhere
(DESIGN.md invariant 2).

**Teardown, inside the container:**

```
$ docker exec …api-1 sh -c 'ls -A /data/worktrees | wc -l; ls /data/runs | wc -l'
0      # worktrees remaining -- bounded by live runs, not by history
8      # run dirs kept -- that is the evidence, and it is a different directory
```

### The routes that are gone

```
GET  /apps                              404
GET  /apps/practice-target/stories      404
POST /apps/bootstrap                    404
POST /targets/7/revisions/snapshot      404
GET  /targets/7/parity                  404
GET  /settings                          200, and carries no `repo_root`
```

### The portal, in a real browser

`http://localhost:8080`, against the rebuilt container:

- The targets list speaks of targets only. Each row carries its slug, a link to its target
  repo built from the row, a **delivery badge**, and Stories / Config / Revisions panels.
- The story dropdowns are populated from each head revision's `file_index`, titles parsed from
  the stored bytes — `SCRUM-201 — Authentication and Protected Dashboard` and so on. The
  throwaway target whose story had just been deleted shows *"No stories yet — write one in the
  Stories panel"* with **Start QA run** disabled.
- The delivery badge reads `8 revs ahead`, `2 revs ahead`, `5 revs ahead`, each with the full
  summary as its tooltip (`never delivered (8 revision(s) to push)`).
- The Revisions panel lists the whole chain — rev 8 `run:20261024-150803-…`, rev 7 `cutover`,
  down to rev 1 `operator` — with **no parity banner and no "Snapshot now" button**, and the
  replacement hint explaining that a five-step run usually leaves two or three revisions
  because `rev` counts changes.
- Settings reports no repo root.

---

## The real agent run

`QA_RUNNER=claude`, run 13, `practice-target` / **SCRUM-203 Button Interactions** — a story with
no plan and no tests in the head revision, so the run had real work to do. Driven from the host
(the API image ships neither the `claude` CLI nor node; see known gap 2), against the dev
Postgres and SeaweedFS, through `launcher.run_with_worktree` — the launcher's own composition,
unchanged.

```
target practice-target (id 1), head revision 7 tree 32809ba48347af26d8c4…
run 13 (20261024-150803-practice-target-177f0a) started
worktree will be /tmp/qa-p3-worktrees/20261024-150803-practice-target-177f0a
run dir will be  /tmp/qa-p3-runs/20261024-150803-practice-target-177f0a
=== hydrate: installing dependencies (npm ci) ===
=== hydrate: worktree built from revision 7 (26 files) at /tmp/qa-p3-worktrees/… ===
=== run … started (begin at read_story) ===
=== step: read_story ===   20:38:03 → 20:38:19
=== step: plan ===         20:38:19 → 20:40:46
=== step: explore ===      20:40:46 → 20:42:57
=== step: generate ===     20:42:57 → 20:49:30
=== step: heal ===         20:49:30 → 20:50:11
=== run … completed ===
=== teardown: worktree removed ===
run finished in 729s
status=completed error=None
worktree still present: False
```

**729 s, five steps, $4.42, and two revisions.** Every clause of the acceptance criterion in one
run: hydrated from the head revision, worked in its own worktree, committed revisions at the
step boundaries that changed something, and had the worktree torn down.

### The revision chain it produced

| rev | parent | author | files | tree hash | `delivered_sha` |
|---|---|---|---|---|---|
| 10 | 9 | `operator` | 29 | *(a story edit made after the delivery, to move the head past it)* | — |
| **9** | 8 | `run:20261024-150803-practice-target-177f0a` | 29 | `c125e41b3654dda9a166637283433cd9e9d1116c8b36b6bef597fda8a826d625` | **`68ff5bba5b4bf0702dacf9bf18affd32d90794e4`** |
| **8** | 7 | `run:20261024-150803-practice-target-177f0a` | 27 | `91121158e96b76157cb50790abcdfd75f79d0f39f3359ef31882a10015d9725a` | — |
| 7 | 6 | `cutover` | 26 | `32809ba48347af26d8c4dbb31af3973db2eae8ed63c2be276f38701c54e1d828` | — |
| 6 | 5 | `run:20261024-071806-…` (P2) | 26 | `9db772b03a5b…` | — |
| … | | | | | |
| 1 | — | `operator` | 14 | `a9744c3757eb…` | — |

**Two revisions for five steps**, and that is the shape to expect. Rev 8 is the plan
(`specs/SCRUM-203-buttons-test-plan.md`, 26 → 27 files); rev 9 is the suite
(`tests/buttons/click-counter.spec.ts` and `async-action.spec.ts`, 27 → 29). `read_story`,
`explore` and `heal` each changed no tracked file and each committed nothing — `heal` because it
found all 12 generated tests already passing and had nothing to fix, which is itself the
skip-when-unchanged check working on a real run rather than a fixture.

### The prompt the agent actually received

Captured from the live invocation. Everything in it comes from the target's row or the head
revision — nothing from a file in this repo:

```
Active story: SCRUM-203 — Button Interactions
Target: Playwright Practice Target (practice-target)
Mode: full
Run-ID: 20261024-150803-practice-target-177f0a

## This target
Base URL: https://custom-test-target-app.vercel.app
Locators: data-testid attributes: page.getByTestId('...')
Notes you must respect in every step:
- The seed opens the home page without logging in. Only /dashboard is protected …
- Every route works as a deep link, and unknown paths return HTTP 200 …
- The target repo was empty when this app was added, so the first delivery does the bootstrap.

## Your working directory
… It holds exactly one target — this one — so every path below is relative to it …
| The active story        | `user-stories/SCRUM-203-buttons.md`        |
| The test plan you write | `specs/SCRUM-203-buttons-test-plan.md`     |
| The test suite you write| `tests/buttons/`                           |
| The seed …              | `seed.spec.ts`                             |
| Browser project to use  | `chromium`                                 |
```

No `apps/`, no `app.json`, no glob, no `{APP_DIR}`, no `--project=practice-target-chromium`, and
no mention of either P1-era shell script. The `baseURL`, `locators` and `agentNotes` are the
row's; the four paths are worktree-relative; the delivery note names the real target repo and
branch from the row. The agent's own step-1 summary read them back correctly, including the
business rule, and it worked only inside `tests/buttons/` and `specs/`.

### The artifact sweep never saw the worktree

The reason the worktree is a sibling of the run directory rather than a child, checked against
a real run:

```
artifacts indexed for run 13:  [('log', 4), ('other', 2), ('report', 1)]
tracked files or node_modules swept as artifacts: 0
```

Seven artifacts, all genuinely run output. `node_modules` was ~200 files in that worktree and
none of it was uploaded.

### The delivery, and `delivered_sha`

```
BEFORE
  rev 9  delivered False  delivered_sha None  revisions_ahead 9  bootstrapped False
  summary 'never delivered (9 revision(s) to push)'
  answered with httpx and subprocess poisoned: 'never delivered (9 revision(s) to push)'

ensure_bootstrapped → done (re-bootstrap): pushed to prashant-kiit/e2e-playwright-test-custom-target@master
push                → branch qa/SCRUM-203-buttons
                       commit 68ff5bba5b4bf0702dacf9bf18affd32d90794e4
                       PR https://github.com/prashant-kiit/e2e-playwright-test-custom-target/pull/2

AFTER
  rev 9  delivered True  delivered_sha 68ff5bba…  revisions_ahead 0  bootstrapped True
  summary 'delivered (revision 9)'
  answered with httpx and subprocess poisoned: 'delivered (revision 9)'
```

Both answers were produced with `httpx.Client.send` and `subprocess.run` replaced by functions
that raise, which is the strongest form of "no network call" available: not "we did not observe
one" but "one would have failed the check".

**Then the portal showed the other state.** One operator story edit through the portal API
committed rev 10, and `GET /targets/1/delivery` answered:

```json
{"app": "practice-target", "repo": "prashant-kiit/e2e-playwright-test-custom-target",
 "bootstrapped": true, "delivered": false, "rev": 10, "delivered_sha": null,
 "revisions_ahead": 1, "summary": "1 revision(s) ahead of the last delivered one"}
```

`bootstrapped` stayed true while `delivered` went false — the two questions the catalog keeps
apart, and the reason both fields exist.

### What was delivered is provably the revision that was recorded

The head revision materialized from blobs, compared file by file against the commit that was
pushed:

```
revisions produced by run 13: [8, 9]
  rev 8: committed 91121158e96b7615  re-scanned 91121158e96b7615  OK
  rev 9: committed c125e41b3654dda9  re-scanned c125e41b3654dda9  OK

revision 9 has 29 files; the delivered commit has 29
  byte-identical at the same path: 29/29
  present but different:            none
  in the revision, not delivered:   none
  delivered, not in the revision:   none
```

That is the round-trip property confirmed **against revisions the real run committed**, not only
against generated fixtures — and then the same bytes found in the customer's repo.

The delivered tree, for the record — root-relative, one commit, no configuration file:

```
.github/workflows/playwright.yml   .gitignore   package.json   package-lock.json
playwright.config.ts   seed.spec.ts
specs/SCRUM-201-auth-test-plan.md … SCRUM-203-buttons-test-plan.md
tests/auth/… (5)   tests/buttons/async-action.spec.ts   tests/buttons/click-counter.spec.ts
tests/forms/… (5)  user-stories/SCRUM-201 … SCRUM-208 (8)

$ git ls-tree -r --name-only HEAD | grep -c app.json
0

$ shasum -a 256 .github/workflows/playwright.yml
8f74de1572347891e1ae2d410c45aa8e5a61dcb741dcc724725f7e1c3b1657fd   # == the template
```

`app.json` appears nowhere in the delivered commit, and the delivered workflow is byte-identical
to `server/app/delivery/templates/workflows/playwright.yml` — which git itself records as an
`R100` rename of the file that used to be a live workflow of this repository.

---

## The inversion

P3 turns P2's central safety property upside down, and that is the phase. P2's comment said so:
*"A failed revision write must never fail a run in P2 … P3 inverts this. Do not 'fix' the
swallowed exception before then."* It is resolved rather than left.

| | P2 | P3 |
|---|---|---|
| Artifact collection raises | reported, run completes | reported, run completes, **ingest still runs** |
| Ingest raises | reported, run **completes** | reported, run **fails**; lock freed; previous head intact |
| Driver's step-boundary hook | blanket `try/except` | fails the step and the run, exactly as a crashed runner does |

Asserted through whole runs rather than through the functions:
`test_an_ingest_that_raises_fails_the_run`, `test_a_failed_ingest_frees_the_lock`,
`test_a_failed_ingest_stops_the_run_at_that_step`,
`test_an_artifact_collector_that_raises_still_does_not_fail_the_run`, and
`test_a_failed_ingest_leaves_the_previous_head_intact`.

The asymmetry is deliberate in both directions. Evidence is not the work: losing a trace is no
reason to fail a run that produced a healed suite. And a run that reports success having
dropped its work is the one failure mode the phase exists to make impossible.

---

## Defects found while verifying

Fixed inside the phase, as the ticket requires.

1. **The delivery-state route needed a GitHub PAT to answer a Postgres question.** Found in a
   real browser, not by a test: the targets list showed no delivery badge and the console had
   three `503`s. `GET /targets/{id}/delivery` hung off the full delivery seam, and constructing
   that seam reads `GITHUB_PAT` — so an operator with no PAT configured got a 503 for an answer
   that never leaves the database. Exactly the dependency invariant 5 exists to remove,
   reintroduced one layer up.

   Fixed by giving the route its own `get_catalog` dependency: the database half of the seam,
   with no git, no GitHub client and no credential. `test_delivery_state_needs_no_credential`
   pins it by making `default_tools()` fail the way a missing PAT does and asserting the route
   still answers 200. The unit tests could not have caught this — they injected a double for
   the whole seam, so the construction that reads the environment never ran.

2. **The round-trip fixture hid a spurious revision.** While writing `test_hydrate.py`, a
   five-step fake run committed a revision for a tree nothing had touched. The cause was the
   test fixture writing placeholder bytes for `playwright.config.ts` while hydrate rendered the
   real thing, so the first ingest saw a diff that no agent had made. The fix is the fixture
   writing infra through the real `write_infra` — but the finding is about the product: a
   target's **revision 1 must be byte-identical to what hydrate would build from its row**, or
   every target's first run commits a revision for the config alone. That is why
   `authoring.initial_tree` renders through the same path, and
   `test_a_run_that_changes_nothing_commits_no_revision` is what keeps it true.

3. **A run-id assertion that could never have held.** `test_run_id_lands_in_the_commit_and_the_pr_body`
   asserted the Run-ID appears in `remote_log`, which reports commit *subjects* (`%s`) while the
   Run-ID is in the body. Caught while rewriting the delivery tests; the helper now has a
   `remote_commit_messages` variant using `%B`, and both halves are asserted.

4. **`app.json` reading still lived in `app/delivery`.** The structural test
   `test_delivery_no_longer_reads_a_configuration_file` found it: `render.py` still had
   `read_app_json` and `app_json_path`, reaching through `config.repo_root()`, after delivery
   had stopped using them. Moved to the cutover, their last caller, and deleted with it.

5. **The browser-cleanup hook logged into the tree being versioned.** It wrote
   `$CLAUDE_PROJECT_DIR/.playwright-mcp/close-test-browsers.log`, and from P3
   `$CLAUDE_PROJECT_DIR` is the worktree — a tree that becomes a revision and is then deleted,
   so the log was both lost and briefly a stray file inside the tree being hashed. It writes to
   `QA_RUN_DIR` now.

---

## What is covered only by fakes

Honest limits of the above:

- **Blob-store failure modes.** "A missing or tampered blob fails the hydrate before any step"
  is proven with a fake store whose objects are cleared or rewritten, not by corrupting
  SeaweedFS. The same goes for "an ingest that raises fails the run": the raise comes from a
  fake `put_file`, not from a real outage.
- **Concurrent revision writes.** `unique(target_id, rev)` is still the OCC point and the API
  maps its `IntegrityError` to a 409, but two writers racing was never provoked — with one live
  run per target and writes refused during a run, it cannot happen today, which is why the
  constraint rather than a lock is the answer.
- **A second tenant.** The tenant filter on every read is asserted with a second `tenants` row
  in the suite. There has never been a second tenant in a live database.
- **`npm ci` on a cold cache, and a missing `npm`.** The real hydrate ran against a warm cache
  in 1.3 s. The "no `npm` → hard error" path is asserted by emptying `PATH` in a test; a cold
  first install was never timed, and it is the step P4 replaces anyway.
- **A hydrate of a very large tree.** The biggest real revision here is 41 files of source
  text. Streaming behaviour for a large blob is still untested (unchanged from P2).
- **Delivery against a repo that drifted.** "A path the revision does not name is left alone"
  is asserted by having a test commit a file to the story branch out of band. A customer
  genuinely rewriting their repo was not simulated.
- **The real runner inside a container.** The real agent run below was driven from the host,
  because the API image ships neither the `claude` CLI nor node. The hydrate → ingest →
  teardown composition *was* exercised inside the container, with the fake runner and no
  mount — so what is unproven is the CLI in the image, which is precisely P4's prebaked
  sandbox.

---

## Decisions recorded during this phase

1. **Delivered paths became root-relative.** The stored shape, the hydrated shape and the
   delivered shape are one shape now, which is what lets the generated single-target config
   find the suite it ships beside. Previously delivery pushed `apps/<app>/user-stories/…`; it
   pushes `user-stories/…`. Existing customer repos therefore keep their old `apps/<app>/`
   paths until somebody removes them — recorded as a known gap below rather than cleaned up by
   a delivery, because deleting paths a revision does not name is not a delivery's business.
2. **A delivery writes the whole head revision, but deletes only the story's tests folder.**
   Wholesale replacement of the tree would delete whatever a customer added. Customer drift is
   a non-event (DESIGN.md §7) and its deliberate repair is the later "re-sync infra" action.
3. **`require_bootstrapped` and `NotBootstrapped` were deleted, not ported.** Once
   "bootstrapped" means "a revision carries a `delivered_sha`", nothing can usefully *require*
   it before the first delivery, because the first delivery is what writes one.
   `ensure_bootstrapped` folds the setup into that first approved push (decision 16), which is
   what the route already did.
4. **The cutover and `app/monorepo.py` were deleted with parity.** Both existed only to read
   `apps/` through a repo root, and both gated on parity. Keeping a command that cannot run
   would be keeping the mount in spirit. They are recoverable from git history, and this record
   holds their output.
5. **The root `.gitignore` was copied to the templates rather than moved.** The spec says the
   three remaining root infra files move; for `package.json` and `package-lock.json` that is a
   genuine move (the harness has no Playwright suite of its own any more). The harness repo
   still needs its own ignore rules, so `templates/gitignore` is a copy and the two are now
   independent files — which is the point of the `(source, destination)` split. The delivered
   bytes are unchanged.
6. **`qa_user_prompt.md` was deleted.** It told the agent to resolve its run configuration from
   `prompts/qa_system_prompt.md`, which is package data the agent cannot read, for an
   interactive mode that has not existed since P1.
7. **`qa_system_prompt.md` stopped duplicating the five step prompts.** That duplication is
   what let it drift into describing `app.json` and `run-stories.sh` while the real prompts
   moved on. It describes the steps and links them now.
8. **Deleting `apps/` dropped 20 files that no revision holds, all of them deliberately.**
   Checked rather than assumed: of the 77 files the deletion removed, 57 are in a head
   revision. The 20 that are not are the three `app.json` files (config is a row now and is
   never a tree file), `apps/_template/`'s two remaining files (the template set moved to
   `server/app/delivery/templates/`, and the example story was template-only), and 16 files
   under `apps/saucedemo/reports/` — the agent's old reports and evidence screenshots, which
   DESIGN.md §4 has always excluded from the tracked tree because they are run output and CI
   generates reports now. All 20 are in git history. The first version of this check was
   vacuous — it diffed the wrong commit, so nothing could have failed it — which is worth
   recording as a reminder that a check passing on an empty input set is not a check.

9. **Scratch defaults are not derived from the package's own location.** `config.py` defaults to
   `/tmp/qa-runs` and `/tmp/qa-worktrees` rather than something relative to `__file__`: a path
   relative to the installed package is a plausible-looking way to reacquire "somewhere on the
   host we all share".

---

## Known gaps left open for P4 and later

Not defects — deliberate, and the next reader should know:

1. **A live run is still pinned to the replica that started it.** The worktree and the run
   directory are local scratch and the SSE log bus is in-process. P3 removed the *shared
   authoritative* disk, which is what made two replicas impossible; it did not make the API
   horizontally scalable. That is P4, and the README says so rather than claiming otherwise.
2. **The real runner is not in the API image.** It has no `claude` CLI, no node and no API key,
   so `QA_RUNNER=claude` must be driven from a host that has them. This is P1's known gap,
   narrowed rather than closed: what used to also need a mounted repo now needs only the CLI.
   P4's prebaked sandbox image is where it lands.
3. **Existing customer repos still hold the old `apps/<app>/` paths.** Delivery writes
   root-relative paths now and deletes nothing it does not own, so the pre-P3 copies linger
   until someone removes them. The SauceDemo target's `agent_notes` already record the same
   thing about its pre-refactor paths from PR #1.
4. **Orphan blobs still accumulate and nothing collects them.** Unchanged from P2, and P3 adds
   them in the same harmless direction: every skipped-because-unchanged snapshot and every
   failed ingest can leave bytes nothing references. §9's mark-and-sweep is still unwritten.
5. **No egress control, no quotas, no timeouts, no token budget.** §6's isolation is P4. A real
   run drives a browser against a live external site from the host, with the host's network.
6. **`base_url` is format-validated, not resolution-validated.** A base URL pointing at a
   private address is accepted. Checking that the host resolves to a public address is §6's DNS
   rebinding work and lands with P4's egress control.
7. **Prompts are code-shipped, not in Postgres.** DESIGN.md §12's `prompts` table, tenant
   overrides and versioning are P5.
8. **`audit_log` does not exist.** Delivery records `delivered_sha` on the revision it
   delivered, which answers "what did we push, and from what?". "Who approved it" is §10's
   immutable audit table, which is its own piece of work.
9. **A story edit during a live run is refused, not queued.** Deliberate: queueing it would be
   merge logic, and there is none. A queue is a design question, not a missing feature.
10. **Deleting a story leaves its plan and suite behind.** An operator deleting a story has not
    asked for a healed suite to be destroyed. Removing the tests too is a deliberate second
    act, and the portal says so after a delete.

---

## What P4 inherits

Stated here because P3 was written to make it true, and because the next phase's whole job is
that these three run somewhere else:

1. **Hydrate, ingest and teardown are plain functions the launcher composes**, not driver
   parameters. `launcher.run_with_worktree` is three calls and a `finally`:
   `hydrate_worktree(...)`, `run_pipeline(...)`, `hydrate.teardown(...)`. Moving them into a
   container is a change of *where* they run, not of *what* they do — and
   `test_hydrate_ingest_and_teardown_are_plain_functions_the_launcher_composes` says so
   structurally.
2. **The worktree path travels through `StepContext`**, so a sandboxed runner receives it the
   same way the in-process one does. The driver derives it from the same `config.worktree_dir`
   the launcher used rather than taking it as a parameter, which is what keeps the driver's one
   injected callable one.
3. **Dependency install is already a single named function**, `hydrate.install_dependencies`,
   skipped for the fake runner. P4's prebaked image and warm cache replace that one function
   rather than being threaded through the pipeline.

And the three things P4 has to add that P3 deliberately did not: the container, egress control,
and moving the SSE bus out of process so a live run stops being pinned to one replica.

## A note on the revision count

**The first run after this lands produces fewer revisions than P2's did**, and that is not a
regression. P2 took a *baseline from disk* before the pipeline started, so a target's first run
left two revisions — the tree it inherited and then its own work — and the portal had to
explain the pair. There is no disk to baseline from now, and every target gets revision 1 when
it is created, so the baseline-from-disk hook is deleted and the surprise goes with it.

What remains, and the portal now says so in the Revisions panel: **a run commits a revision only
at the step boundaries that changed something.** Reading the story and exploring normally change
no tracked file, so a five-step run usually leaves two or three revisions, not five. `rev` counts
changes, not steps.

---

## Acceptance criteria, line by line

Issue #7's list, each against the evidence above.

| # | Criterion | Evidence |
|---|---|---|
| 1 | Target config lives in `targets`; `app.json` exists nowhere in the repo or in any delivered commit; `test_migrations.py` passes | Migration `c3a7e90b41d2` adds the five columns non-null and drops the backfill default; the autogenerate check finds no drift. `test_no_app_json_exists_anywhere_in_the_repository` for the repo; `git ls-tree \| grep -c app.json` → **0** for the delivered commit |
| 2 | A real `QA_RUNNER=claude` run hydrates from the head revision, works in its own worktree, commits revisions at step boundaries and tears the worktree down, recorded in a `VERIFICATION-P3.md` | Run 13 above: hydrated from rev 7, worked in `/tmp/qa-p3-worktrees/20261024-150803-…`, committed revs 8 and 9, `worktree still present: False`. This document |
| 3 | Materializing any revision reproduces its tree hash exactly | `test_hydrate.py`'s property over five generated tree shapes; and live against both real heads and both revisions run 13 committed — four for four |
| 4 | A run whose ingest fails ends `failed`, lock freed, last good revision intact | `test_an_ingest_that_raises_fails_the_run`, `test_a_failed_ingest_frees_the_lock`, `test_a_failed_ingest_leaves_the_previous_head_intact`. Fake store, not a real outage (see fakes) |
| 5 | A story can be created, edited and deleted in the portal, each committing one revision; the same writes refused while a run is live | Live through the containerised API: revs 2, 3, 5 for create/edit/delete, `null` for an unchanged save; all three verbs **409** during run 14, with the reason |
| 6 | A delivery records `delivered_sha`, and the portal answers "delivered / N revisions ahead" without a network call | `68ff5bba…` recorded on rev 9; both answers produced with `httpx` and `subprocess` poisoned; the badge rendered in a real browser in both states |
| 7 | The delivered workflow is byte-identical to the previous one and is no longer a workflow of this repository | `R100` rename, identical sha256 in the repo *and* in the delivered commit; `.github/workflows/` holds only `ci.yml`, asserted structurally |
| 8 | `grep -r QA_REPO_ROOT` finds nothing outside historical documents; the `/workspace` mount is gone; `apps/` is deleted | The grep returns only `VERIFICATION-P1.md`, `SPEC-P1-closeout.md`, DESIGN's amended note, the README's gotcha describing the test, and the tests asserting its absence. `docker inspect` shows one mount, `/data`. `apps/` deleted, with the 20 untracked files it held audited above |
| 9 | `make ci-test` green | **524 backend + 43 frontend, 0 skipped, ruff clean** |

### The ticket-level criteria not already covered

| Ticket | Criterion | Evidence |
|---|---|---|
| #8 | A target whose parity is red blocks the cutover with that target named | `test_a_target_whose_parity_is_red_blocks_the_cutover_and_is_named`, by tampering with a `file_index` row so the tree hash still matches and parity is the only thing that notices. Never provoked live — both real targets were green |
| #8 | Re-running the cutover commits no revision and changes no row | Live: `0 revision(s) committed, 0 config row(s) imported` |
| #9 | A push to `master` no longer runs any customer's suite from this repo's CI | `.github/workflows/` contains only `ci.yml`, and `ci.yml` contains no `playwright test` — both asserted in `test_no_repo_mount.py` |
| #10 | The driver still takes exactly one step-boundary callable | `test_the_driver_still_takes_exactly_one_step_boundary_callable` pins the signature to `[session_factory, run_id, runner, emit, collect]` |
| #10 | A run on a target with no head revision fails immediately with that reason; the baseline hook is gone | `test_a_run_whose_target_has_no_head_revision_fails_immediately` (no step attempted, lock freed, reason recorded) and `test_the_baseline_from_disk_hook_is_gone` |
| #11 | Prompts and the agent runtime resolve from package data, asserted structurally | `test_no_repo_mount.py` with the working directory moved elsewhere; and `docker exec … ls app/prompts/steps app/agent_runtime` inside the image |
| #12 | An agent edit to a generated file is discarded at ingest | `test_an_agent_edit_to_a_generated_file_is_discarded_at_ingest`, and its companion proving the edit does not mask a real change in the same step |
| #13 | A concurrent revision write loses with a 409 rather than overwriting | The API maps `unique(target_id, rev)`'s `IntegrityError` to 409. Not provoked with two live writers (see fakes) |
| #14 | No delivery function reads config or a credential outside `Tools`, asserted structurally | `test_no_delivery_function_reads_config_or_a_credential_outside_tools` — which is what found `read_app_json` still living in `app/delivery` |
| #15 | The API image runs with no mounted repo | One mount (`/data`), no `/workspace`, no `QA_REPO_ROOT`, healthy, and a full five-step run with hydrate and teardown completed inside it |

---

## Closing

P3's three clauses, in the order §13 wrote them:

- **Flip reads to DB + blobs.** A run starts from the head revision and the target's row; the
  prompt is rendered from that row; delivery pushes a materialized revision and answers "in
  sync?" from one query. Nothing reads a shared disk to make a decision.
- **`apps/` becomes derived.** It is not derived — it is **gone**, along with `app.json`, the
  root `playwright.config.ts` and the live workflow. What a worktree holds is derived, per run,
  from the database, and thrown away.
- **Delete the repo mount.** Deleted, and `tests/test_no_repo_mount.py` is what keeps it
  deleted.

And the inversion: a failed ingest fails the run. Parity's last act was to gate the cutover that
removed it; the round-trip property replaced it with something stronger, which one copy of the
truth is enough for.

What is **not** true, and the README says so: the API is not horizontally scalable. A live run
is still pinned to the replica that started it. That is P4.
