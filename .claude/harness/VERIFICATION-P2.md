# P2 verification record

**Phase:** P2 of [DESIGN.md §13](DESIGN.md#13-migration-plan) — "Add `revision` / `file_index` /
blob storage; **dual-write** from the existing `apps/` filesystem, which stays authoritative."
**Spec:** [SPEC-P2-revisions.md](SPEC-P2-revisions.md), seven tickets in [issues/p2/](issues/p2/README.md).
**Verified:** 2026-10-23/24, on `portal/build`.
**Purpose:** the same as P1's — so "P2 is done" rests on evidence, and so P3 knows which paths
are *proven* against a real agent and a real object store and which rest on fakes.

The sentence this phase is measured against is §13's: *"Proves the revision model against real
runs with zero behavior change — the safety net is still there."* Both halves are requirements,
so this record is organised around them: what the revision model was proven to do, and what was
checked to confirm nothing else moved.

---

## Definition of done for P2

1. `tenants`, `revisions`, `file_index` exist; `tenant_id` is non-null on every other table;
   one tenant is seeded; the autogenerate check finds no drift.
2. A real agent run leaves a revision chain whose head's `file_index` matches the on-disk
   tracked tree, with parity green.
3. A fake run with a storage that raises leaves no revision rows and still completes.
4. Delivery, artifact collection, run states and every existing portal page behave as in P1.
5. The portal shows a target's revisions, one revision's files, one file's contents from blob
   storage, and the parity banner.
6. `make ci-test` green.

All six held at the time of writing. **Nothing reads the new tables to make a decision**:
`apps/` is still authoritative, `config.repo_root()` is untouched, and `require_bootstrapped`
still asks GitHub. `delivered_sha` exists and is written by nothing.

## Automated suites

| Check | Result |
|---|---|
| `cd server && uv run pytest` | **241 passed**, 0 skipped (was 173 at the end of P1) |
| `cd web && npm test` | **28 passed**, 5 files (was 13, 4 files) |
| `cd server && uv run ruff check .` | clean |
| `make ci-test` | green (all three, with `QA_REQUIRE_DB=1`) |

The +68 backend tests are the tracked-tree contract (8), the revision model and tree hash (18),
parity as a pure function (8), the read routes and snapshot action (16), step-boundary
composition through a whole run (11) and tenancy/schema structure (7). The +15 frontend tests
are the revisions panel (11), the api wrapper's new methods and its HTML guard (4).

### Changes to the existing suite

The spec allowed one: adding `exists` to the two storage fakes. What actually changed:

| Change | Why |
|---|---|
| The two hand-rolled storage fakes collapsed into `tests/storage_helpers.py` | Ticket 01's prefactor. No assertion changed — only where the double comes from |
| `exists` added to that one shared fake | The seam's single new method |
| `test_api.py` passes `tenant_id` on a hand-built `Artifact` row | The column is non-null and application code sets it explicitly; a test that constructs ORM rows directly has to as well |
| `conftest.py` stops truncating `tenants`, and deletes any *extra* tenant after each test | The seeded row is reference data the migration establishes, not test state. Truncating it left every `tenant_id` FK dangling |

No existing assertion about run behavior, delivery, artifacts or the portal was modified.

---

## Live verification

Against the real stack: dockerised Postgres, dockerised SeaweedFS, the real API container, the
real nginx-served portal in a real browser.

### The migration, against a database with real rows in it

The dev database was not empty — it carried P1's rows. The migration backfilled them:

```
tenants:  1 row (id=1, "default")
projects 2/2   targets 1/1   runs 2/2   run_steps 10/10   artifacts 10/10   app_locks 0/0
           (rows / rows with a non-null tenant_id)

column_default for tenant_id, all 8 tables: (empty)
```

So the backfill default did its job on 25 pre-existing rows and was dropped in the same
revision, as the spec requires. `test_migrations.py`'s autogenerate check agrees the schema
and the models describe the same thing, including the absence of that default.

### The tracked tree, on a real target

`saucedemo` snapshotted through the portal: **41 files**, and the exclusions hold.

```
app.json tracked?        False
reports/ tracked?        False      (7 story reports + 13 evidence PNGs on disk)
node_modules tracked?    False
session.jsonl tracked?   False
five infra files:        all present
seed.spec.ts:            present
user-stories/specs/tests: 7 / 4 / 24
blob keys:               all under tenant/1/blobs/<sha256>
```

### Content addressing and dedup, against the real object store

Not against a fake — against SeaweedFS, counted through the S3 API:

| | |
|---|---|
| `file_index` rows across both targets | **55** |
| distinct `blob_key` values they reference | **50** |
| objects actually stored under `tenant/1/blobs/` | **50** |

The five repo-level infra files are byte-identical for `saucedemo` and `practice-target`, so
they are stored once and referenced by both revisions. Every stored key is a 64-char content
hash under the tenant prefix.

A second snapshot of an unchanged tree returned `200 {"created": false}` and committed nothing,
so `rev` counts real changes rather than attempts.

### Bytes served from blob storage are the bytes on disk

All **41** of `saucedemo`'s tracked files were fetched through
`GET /revisions/1/file?path=…` and compared with `cmp` against their files on disk:

```
checked=41 mismatches=0
```

### Parity, in both directions

Green immediately after a snapshot. Then three faults were induced on disk at once — one file
appended to, one new file added, one file moved away — and the route reported each separately
and by exact path:

```json
{"in_sync": false, "rev": 1,
 "only_in_db":   ["specs/SCRUM-104-product-details-test-plan.md"],
 "only_on_disk": ["tests/checkout/_parity-probe.spec.ts"],
 "modified":     ["tests/checkout/cart-review.spec.ts"]}
```

The modified file is reported as modified only — not also as missing and extra. All three
probe changes were reverted and parity returned green.

### The portal, in a real browser

Loaded at `localhost:8080` through nginx, not jsdom. The panel showed the head revision and its
tree hash, the green parity banner, the revision table (rev, parent, tree hash, author,
producing run, file count, created), the 41-file list with human sizes, and the contents of
`tests/checkout/cart-review.spec.ts` — a generated Playwright spec — fetched out of SeaweedFS.

### A whole run through the real stack

Driven against live Postgres and live SeaweedFS through the launcher's real composed hook, with
a synthetic runner standing in for the agent (the real agent run is the section below). A
throwaway workspace, so `apps/` stayed clean:

```
after the baseline      rev 1  parent=None  run=None  author=baseline  files=7
after the run           rev 1  parent=None  run=None  author=baseline  files=7
                        rev 2  parent=1     run=4     author=run:…     files=9
                        rev 3  parent=2     run=4     author=run:…     files=9
                        parity in_sync=True
                        run status=completed   artifacts=5
after a second run      (unchanged — still 3 revisions, no re-baseline)
```

That is the shape the spec asks for: the baseline is the tree the run *inherited* and records no
producing run; five steps committed **two** revisions rather than five, because read-story, plan
and explore changed no tracked file; the chain is linked by `parent_rev`; a second run that
changed nothing committed nothing and did not re-baseline.

### Run states, unchanged

Pause, resume and stop driven live through the portal API against a running pipeline:

```
pause   -> running, pause_requested=true   ...then: paused, last_completed=read_story, lease=None
resume  -> relaunched
stop    -> running, stop_requested=true    ...then: stopped, last_completed=plan
start a new run on the same app -> HTTP 201   (the lock was released)
```

Artifacts were collected at exactly the two boundaries the run reached (`read_story.txt`,
`plan.txt`), still keyed `run_key/relpath` — **not** re-keyed to the tenant prefix, which is
P5's job. The run that reached those boundaries changed no tracked file, and committed no
revision.

---

## The real agent run

<!-- REAL_RUN_SECTION -->

---

## What is covered only by fakes

Honest limits of the above:

- **Blob-store failure modes.** "Upload raises → zero revision rows, run still completes" is
  proven with a fake whose `put_file` raises, not by taking SeaweedFS down mid-run. The same
  goes for the per-half failure isolation in the step-boundary hook.
- **Concurrent commits of the same `rev`.** `unique(target_id, rev)` is this phase's OCC point,
  and it is asserted by inserting the same `(target_id, rev)` twice in one test. Two live
  committers racing was never provoked — with one live run per target it cannot happen today,
  which is exactly why the constraint is there.
- **`S3Storage.exists` against a missing bucket.** The `ClientError → False` path is reasoned,
  not exercised; the live runs all had the bucket.
- **A second tenant.** The tenant filter on every read is asserted with a second `tenants` row
  in the test suite. There has never been a second tenant in a live database, and nothing
  resolves `current_tenant_id()` to anything but 1.
- **Large files.** Everything snapshotted so far is source text; the largest tracked file is
  ~20 KB. Streaming behavior for a large blob is untested.

---

## Defects found while verifying

Both fixed inside this phase, as the ticket requires.

1. **The portal blanked on any refresh of a route that collides with an API path.** The API
   paths sit at the root alongside the SPA's client routes, and nginx picks between them on the
   `Accept` header — but neither response carried `Vary: Accept`, and the HTML shell went out
   with an `ETag` and no `Cache-Control`. A browser that navigated to `/projects` therefore
   cached the shell under that URL and then served it to the app's own `fetch("/projects")`;
   the wrapper saw `text/html`, returned the document as a string, and `projects.map` threw
   three frames away. Symptom: a blank page and `e.map is not a function`.

   Reproduced by navigating twice to `/projects`. Fixed by making those responses `Vary` on
   `Accept`, with `no-store` on the shell as a second line. The api wrapper now also refuses an
   HTML document where data was expected and names the cause, so a future proxy slip is a
   legible error rather than a blank page; the tracked-file route opts out, since it serves
   whatever the path implies.

   **This defect predates P2** — it is in P1's nginx/SPA split — but it surfaced while
   verifying the revisions panel, so it is fixed here rather than merely recorded.

2. **Listing revisions lazy-loaded every revision's file index** to display a file count: 41
   rows per revision on a real target, to show one number. The count now comes from a single
   aggregate. Found when a verification script touched `revision.files` outside a session and
   raised `DetachedInstanceError` — the N+1 was the same lazy load, just inside one.

---

## Decisions recorded during this phase

| Question | Decision |
|---|---|
| DESIGN §3's `occ_version` column | **Not built.** `unique(target_id, rev)` is the OCC point; a version column would misdescribe where the check happens and nothing would read it. §3 amended |
| DESIGN §3's `bundle_key` | **Deferred to P4**, with the sandbox that has a history worth bundling. P2 adds only columns it writes, which is what keeps the models-match-migrations check meaningful. §3 amended |
| DESIGN §4's `playwright.config.ts` *(generated)* | **Marked as arriving with P3's hydrate.** P2 tracks it as the hand-maintained file it still is. §4 amended |
| A mutable `targets.head_revision_id` | **Not added.** The head is derived as the greatest `rev`; a second place recording "which is current" is a second thing that can be wrong |
| Where the tracked-tree contract lives | `delivery/render.py`, with the path contract delivery already owns, so snapshotting and delivery cannot drift about what the product versions |
| Stored path shape | **Target-relative**, not repo-root-relative with an `apps/<app>/` prefix — the shape P3's hydrate builds, so the read-flip needs no path migration |
| Blob content type | Blobs are stored as `application/octet-stream`. A blob key is a content hash with no extension and the same bytes can be referenced from paths with different extensions, so the media type belongs to the *reference*: the read route derives it from the requested tracked path |
| A Python-side ORM default for `tenant_id` | **Not used.** Every insert names `current_tenant_id()` explicitly, which is what makes P5 one replacement rather than an audit |
| `conftest.py` and the seeded tenant | Preserved across truncation as reference data, with extra tenants deleted, so each test starts from exactly the state the migration left |

---

## Known gaps left open for P3

Not defects — deliberate, and the next reader should know:

1. **Nothing reads the revision tables to make a decision.** That is the phase's contract, and
   it means the whole model is still scaffolding: delete every revision row and the system
   behaves identically. P3 is the flip.
2. **`delivered_sha` is null everywhere**, so invariant 5 ("'is this in sync?' is a Postgres
   query") is still unsatisfied. `require_bootstrapped` still asks GitHub via `ls-remote`.
3. **Orphan blobs accumulate and nothing collects them.** "Blob before row" guarantees orphans
   by design, and deleting a target cascades its revisions and `file_index` rows while leaving
   their blobs in SeaweedFS. Observed during this verification: deleting the two throwaway
   verification projects left 0 orphaned index rows and a number of unreferenced objects. §9's
   mark-and-sweep is the answer and is explicitly out of scope here; P2's job was to create the
   reference graph it will scan, which it has.
4. **The snapshot route and button are P2-only scaffolding.** In P3 the filesystem is not
   authoritative and "snapshot the disk" stops meaning anything. Both say so where they are
   defined.
5. **`POST /targets/{id}/revisions/snapshot` is the only write on the revisions surface**, and
   it is an operator action. Nothing in the portal can make the database disagree with the
   filesystem.
6. **The real runner still is not wired into the API container.** It has no `node`, no `claude`
   CLI and no API key; the real agent run below was driven from the host, where the CLI lives.
   This is P1's known gap, unchanged by P2, and P4's sandbox is where it is meant to land.
7. **`prompts/` still names `./scripts/push-artifacts.sh`.** P1's known gap 0, still out of
   scope, still worth doing as a small separate task.
