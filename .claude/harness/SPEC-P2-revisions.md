# Spec: P2 — revisions, file_index and content-addressed blobs, dual-written from `apps/`

**Triage label:** `ready-for-agent`
**Phase:** P2 of [DESIGN.md §13](DESIGN.md) ("Add `revision` / `file_index` / blob storage;
**dual-write** from the existing `apps/` filesystem, which stays authoritative")
**Depends on:** P1, landed and verified ([SPEC-P1-closeout.md](SPEC-P1-closeout.md),
[VERIFICATION-P1.md](VERIFICATION-P1.md))
**Authority this phase has:** none. `apps/` stays the source of truth for the whole phase.
**Tickets:** seven, in [issues/p2/](issues/p2/README.md).

---

## Problem Statement

The design's whole point is one sentence: *Postgres is the single arbiter of truth.* After P1
that sentence is still entirely aspirational. Postgres owns run **status** and history and
nothing else; the test code the product exists to produce — stories, plans, seed, suites — lives
in a mounted filesystem under `apps/<app>/`, and the only reason the portal can see it is that
the API container and the agent share a disk.

For the maintainer of this harness, that costs the following today:

- **The agent's work has no history.** Steps 4 and 5 (generate, heal) write into
  `apps/<app>/specs/` and `apps/<app>/tests/<slug>/` in place. A heal that makes a suite worse
  overwrites the suite that was better, and there is nothing to go back to. The harness never
  commits the agent's output anywhere; this repo's own git history is incidental, records the
  developer's commits rather than run boundaries, and does not exist at all for a deployed
  instance.
- **A run cannot be reconstructed.** `runs` and `run_steps` record that five steps happened.
  They record nothing about *what the tree looked like* at any of those boundaries. "What did
  this run actually produce, and what did the previous one produce?" is unanswerable from the
  database.
- **A crash loses more than it should.** The driver resumes at a step boundary, which is the
  right granularity — but there is no snapshot *at* the boundary, so resume re-enters a
  worktree that the dead step left half-written. "Retries converge" (invariant 4) has nothing
  underneath it.
- **Nothing is deduplicated and nothing can be collected.** `artifacts` carries a `sha256`
  column but keys blobs by `run_key/<relpath>`, so the same unchanged file is stored again under
  a new key on every run. There is no content-addressed store, and therefore no GC story at all
  — the mark-and-sweep in §9 has no reference graph to scan.
- **The API cannot be stateless.** Every read path bottoms out in `config.repo_root()`. Two API
  replicas need the same mount; the runner cannot leave the API process; `apps/` cannot be
  deleted. P3, P4 and P5 each stand directly on a revision model that does not exist, so the
  migration is blocked at its first real step.
- **"Is this in sync?" is answered by asking GitHub.** `require_bootstrapped` does an
  `ls-remote`, and `push.py` decides whether to commit by diffing worktrees. Invariant 5 says
  that question is a Postgres query comparing a head revision's hash against a recorded
  `delivered_sha`. Neither column exists.

And the risk that makes the ordering matter: the obvious way to fix all of the above is to move
truth into Postgres and flip the reads at the same time. That is a single change with no
fallback, against a schema and a hashing scheme nobody has yet run against a real agent session.

## Solution

Build the revision model and run it in **dual-write** for a whole phase, with `apps/` still
authoritative and nothing in the system reading the new tables to make a decision. At every
completed step boundary the harness snapshots the target's tracked tree, uploads each file's
bytes to content-addressed blob storage, and commits one immutable `revision` row naming that
tree. If every one of those writes failed, runs, delivery and the portal would behave exactly as
they do today.

Dual-write only pays off if someone checks the two copies agree, so the phase also ships the
**parity check** — a comparison of the head revision against the on-disk tracked tree — and the
read-only portal surface that displays it. That is what turns "the revision model is written"
into "the revision model is proven against real runs", which is what §13 claims P2 is for.

Concretely, the maintainer gets:

1. **A versioned history of every target's tracked tree**, one revision per step boundary that
   changed something, immutable and content-addressed.
2. **A deduplicated blob store** under the per-tenant key layout of §9, so identical files across
   revisions and runs are stored once — and so P3's hydrate and §9's GC have something real to
   read.
3. **`tenant_id` on every table**, defaulted to a single seeded tenant, which makes P5 a backfill
   rather than a schema migration across the whole system.
4. **A parity check** answering "does the database agree with the filesystem?" for any target,
   in the portal and as an API route — the evidence that P3's read-flip is safe to make.
5. **A read-only revisions view in the portal**: revision list, tree hash, file list, and one
   file's contents fetched from blob storage rather than from disk.
6. **No behavior change.** Same runs, same delivery, same artifacts, same portal pages.

## User Stories

1. As the harness maintainer, I want every completed step boundary to commit a snapshot of the
   target's tracked tree, so that the work a run produced is recorded rather than inferred.
2. As the harness maintainer, I want revisions to be immutable and append-only, so that a later
   run can never rewrite what an earlier one produced.
3. As the harness maintainer, I want each revision to name its parent, so that a target's history
   is a chain I can walk rather than a bag of rows.
4. As the harness maintainer, I want a revision to carry a tree hash computed from its contents,
   so that "are these two trees the same?" is a string comparison and not a directory walk.
5. As the harness maintainer, I want a step that changed nothing to commit no revision, so that
   `rev` counts real changes rather than counting steps.
6. As the harness maintainer, I want file bytes stored under their own content hash, so that an
   unchanged file is stored once no matter how many revisions reference it.
7. As the harness maintainer, I want blobs uploaded before the row that references them is
   committed, so that a crash can leave an unreferenced blob but never a revision pointing at
   missing bytes.
8. As the harness maintainer, I want a failed revision write to leave the run green and the last
   good revision intact, so that scaffolding for a future phase can never cost me a run today.
9. As the harness maintainer, I want revision writes to go through the step-boundary hook the
   driver already has, so that the driver keeps exactly one injection point as §13 requires.
10. As the harness maintainer, I want one definition of "what is in the tracked tree", shared by
    delivery and by snapshotting, so that the two cannot drift into disagreeing about what the
    product delivers.
11. As the harness maintainer, I want the tracked tree to exclude `app.json` and `reports/`, so
    that config and evidence do not become versioned tree content and later leak into a customer
    repo.
12. As the harness maintainer, I want the tree-hash encoding pinned by a known-value test, so
    that a refactor cannot silently change a durable format and orphan every revision ever
    written.
13. As the harness maintainer, I want blob keys laid out per tenant from day one, so that the key
    space does not have to be rewritten when a second tenant exists.
14. As the harness maintainer, I want `tenant_id` present and non-null on every table, so that P5
    is a data backfill instead of a migration touching every model.
15. As the harness maintainer, I want the current tenant resolved by one function, so that P5
    replaces a single call site rather than auditing every query.
16. As the harness operator, I want to see a target's revision history in the portal, so that I
    can tell what each run changed without shelling into a container.
17. As the harness operator, I want to see which files a revision contains and how large they
    are, so that I can confirm a run produced the suite I expected.
18. As the harness operator, I want to open one file's contents out of blob storage from the
    portal, so that I can read the generated test the database claims to hold.
19. As the harness operator, I want the portal to tell me whether a target's head revision
    matches the files on disk, so that dual-write failures are visible instead of silent.
20. As the harness operator, I want the parity check to name exactly which paths are missing,
    extra or different, so that a mismatch is a bug report rather than a mystery.
21. As the harness operator, I want to take a snapshot of a target without starting a run, so
    that a target that has never run still has a head revision to compare against.
22. As the harness operator, I want a target's first revision to be the tree as it stood *before*
    the run started, so that the first run's revision describes what the run did and not what it
    inherited.
23. As the harness operator, I want every blob read authorized through the database row that
    names it, so that knowing a key is not enough to read bytes.
24. As the harness operator, I want revision and parity views to be read-only, so that nothing in
    the portal can make the database disagree with the filesystem.
25. As the agent, I want to keep writing into `apps/<app>/` exactly as I do now, so that this
    phase changes nothing about how a step behaves.
26. As the P3 implementer, I want the stored paths already shaped like the per-target worktree
    that hydrate will build, so that flipping reads does not require rewriting every stored path.
27. As the P3 implementer, I want revisions proven against real agent runs before truth moves, so
    that the read-flip is a configuration change rather than a leap.
28. As the P4 implementer, I want a per-target tree snapshot that does not depend on this repo's
    own git history, so that the model survives the move into a per-run sandbox.
29. As the GC implementer, I want blobs referenced by rows I can scan, so that the mark-and-sweep
    in §9 has a reference graph to mark from.
30. As a reviewer of this phase, I want a migration whose columns are all actually written, so
    that no column lies about being populated.
31. As a reviewer of this phase, I want the schema and the ORM models checked against each other
    automatically, so that a model change without a migration fails in CI rather than on deploy.
32. As a reviewer of this phase, I want the new writes exercised by a full fake run through the
    driver, so that the tests prove the hook composition and not just the functions behind it.

## Implementation Decisions

### Scope and sequencing

- P2 adds **no new seam**. It reuses three that already exist (see *Seams* below) and introduces
  one new module behind them, plus read-only routes.
- P2 **changes no existing behavior**. Delivery, artifacts, run states, the lease lock, the
  reaper and every current portal page are untouched. Reviewers should treat any diff to
  `repo.py`'s locking trio, `push.py` or `bootstrap.py` as out of scope unless it is adding
  `tenant_id`.
- Order of work: schema and the tenant helper first; then the tracked-tree contract; then
  snapshot-and-commit behind the step-boundary hook; then the baseline snapshot in the launcher;
  then parity; then the read routes and the portal panel.

### Schema

New tables: `tenants`, `revisions`, `file_index`. `tenant_id` added to `projects`, `targets`,
`runs`, `run_steps`, `artifacts` and `app_locks`.

- `revisions` carries: `tenant_id`, `target_id`, `rev` (monotonic per target, from 1),
  `parent_rev` (null for the baseline), `tree_hash`, `produced_by_run_id` (nullable — a manual
  snapshot has no run), `author`, `delivered_sha` (nullable, **never written in P2**),
  `created_at`. Unique on `(target_id, rev)`.
- `file_index` is keyed `(revision_id, path)` and carries `blob_key` and `size`. It is **derived**
  (DESIGN decision 1) and exists so the portal can list and display files; nothing may treat it
  as authoritative.
- **OCC is the unique constraint, not a version column.** Committing revision N+1 inserts
  `rev = N+1` with `parent_rev = N`; a concurrent committer loses on
  `unique(target_id, rev)`. DESIGN §3 lists an `occ_version` column on the revision row — it is
  **not** added, because an unused column misdescribes where the check happens. Amend §3 to say
  the unique constraint is the OCC point. (With one live run per target this contention is
  theoretical today; the constraint is what keeps it theoretical.)
- **No `bundle_key`, no `occ_version`.** Git bundles (§5) presuppose a per-run worktree with its
  own history, which arrives in P4; there is nothing in P2 whose history is worth bundling. P2
  adds only columns it writes, so `test_migrations_match_the_models` stays a meaningful check.
- **`delivered_sha` is added but left null.** Delivery still works off the filesystem in P2, so
  invariant 5 ("'in sync?' is a Postgres query") is deliberately **not** satisfied yet;
  `require_bootstrapped` keeps asking GitHub. Recording an approval-time sha is P3/P7 work and
  must not be smuggled in here, because it would make delivery depend on the new tables.
- **Head revision is derived, not stored.** The head is the row with the greatest `rev` for a
  target. No mutable `targets.head_revision_id` pointer: revisions are append-only, and a second
  place recording "which is current" is a second thing that can be wrong.
- **Tenant backfill:** each `tenant_id` column is added non-null with `server_default '1'` so
  existing rows backfill, and the server default is **dropped in the same revision**. The
  migration seeds one tenant row. Application code always sets `tenant_id` explicitly from a
  single `current_tenant_id()` helper, which is the one call site P5 replaces.

### The tracked tree

What a revision snapshots, for target `<app>`:

| Tracked | Source on disk |
|---|---|
| `package.json`, `package-lock.json`, `playwright.config.ts`, `.gitignore`, `.github/workflows/playwright.yml` | repo root |
| `seed.spec.ts` | `apps/<app>/seed.spec.ts` |
| `user-stories/*.md` | `apps/<app>/user-stories/` |
| `specs/*.md` | `apps/<app>/specs/` |
| `tests/**` | `apps/<app>/tests/` |

Explicitly **not** tracked: `apps/<app>/app.json` (config, not tree content — §4; it is
SaaS-internal and must never become something a revision delivers, even though today's
`bootstrap` still pushes it), `apps/<app>/reports/**` (agent-written reports and evidence
screenshots: run output, which is why `push.py` already declines to deliver them), and everything
in §4's artifact column (`node_modules/`, `test-results/`, `playwright-report/`, traces, videos,
`session.jsonl`).

- **Stored paths are target-relative**, i.e. the shape §4 defines and the shape P3's hydrate will
  build — *not* repo-root-relative with an `apps/<app>/` prefix. The alternative (store today's
  on-disk layout, rewrite paths in P3) was rejected: the revision is a whole-worktree snapshot of
  **one target**, and baking this repo's multi-app monorepo layout into the durable record would
  put a path migration in front of P3. The cost is one mapping function, which is exactly the
  function hydrate needs.
- The root infra files are shared on disk across all targets but are **logically per-target** in
  the model, and each target's revision therefore includes its own copy. Content addressing makes
  that free: identical bytes are one blob.
- `playwright.config.ts` is tracked as the hand-maintained file it is today. §4 marks it
  *generated* from Postgres config; that change lands with hydrate in P3, and it will be the one
  tracked file whose content *shape* changes. Nothing in P2 should anticipate it.

### Content addressing and the tree hash

- A blob key is `tenant/<tenant_id>/blobs/<sha256-of-contents>`, per §9. Content addressing is
  scoped per tenant deliberately: cross-tenant dedup is worth nothing and would make blob
  existence a side channel.
- **Existing artifact keys are unchanged.** `artifacts` keeps `run_key/<relpath>`; re-keying it
  to `tenant/<id>/artifacts/...` would orphan everything already stored, for no benefit while
  there is one tenant. That re-key belongs with P5.
- `tree_hash` is `sha256` over the file list in a format pinned by test: for each path in
  ascending byte order of the path, the line `<blob-sha256>  <path>\n` (two spaces), concatenated
  and hashed. It deliberately resembles a stripped-down git tree: sorted, content-only, and
  independent of directory iteration order, file mtimes and file modes. Two revisions with the
  same tree hash hold the same bytes at the same paths, which is what makes the parity check and
  the skip-if-unchanged rule cheap.

### Writing a revision

At a step boundary, in this order (invariant 3, *blob before row*):

1. Walk the tracked tree, hashing each file.
2. Compute `tree_hash`. **If it equals the head revision's `tree_hash`, stop and commit
   nothing.** Three of the five steps (read-story, plan, explore) routinely change no tracked
   file, and a revision per step would otherwise make `rev` a step counter.
3. For each file, skip the upload if the blob key already exists; otherwise upload.
4. In **one transaction**, insert the `revision` row (`parent_rev` = the head's `rev`) and all its
   `file_index` rows.

A crash between 3 and 4 leaves unreferenced blobs, which is the harmless direction and what §9's
mark-and-sweep is for. A crash before 3 leaves nothing. Either way the previous head is intact
and a retry converges, because the tree hash of a given tree does not depend on when it was
taken.

### Where sync-out hangs: the step-boundary seam

`run_pipeline`'s single `collect` callable, composed in `launcher.make_collector`. DESIGN §13
names this explicitly, including the thing not to do: **do not add a `sync_out=` parameter next
to `collect=`.** The driver keeps exactly one injection point.

Two consequences for the composed hook:

- **Each half isolates its own failures.** The driver wraps the whole callable in one
  `try/except` and treats it as best-effort, so an exception from artifact collection would
  otherwise skip the revision commit entirely (and vice versa). The composed hook catches per
  half and reports both.
- **Order: artifacts first, then the revision snapshot.** Existing behavior runs first and is
  never delayed by new work.

**A failed revision write must never fail a run in P2.** The driver's existing best-effort
treatment of `collect` is exactly right while `apps/` is authoritative, and it is load-bearing
for the "no behavior change" promise. P3 inverts this: once truth moves, a failed sync-out has to
fail the run. Say so in the code comment, because the natural instinct on reading a swallowed
exception is to "fix" it.

### The baseline revision

The baseline is taken **in the launcher, before the pipeline starts**, when a target has no head
revision. Not at the first sync-out: that would conflate the tree the run inherited with the tree
its first step produced, and the first revision of every target would be unreadable. Not a
one-shot backfill script either — code that runs once and is never exercised again.

The same function is exposed as `POST /targets/{id}/revisions/snapshot`, so an operator can give
a never-run target a head to compare against, and so parity is usable before any run exists.
This route is **P2-only scaffolding**: in P3 the filesystem is not authoritative and "snapshot
the disk" stops meaning anything. Mark it as such where it is defined.

### Parity

A pure function over (the head revision's `file_index` rows, a scan of the on-disk tracked tree)
returning: paths only in the database, paths only on disk, paths whose content hashes differ, and
`in_sync`. No I/O in the comparison itself, so it tests without a database or a filesystem.

Exposed as `GET /targets/{id}/parity` and rendered as a banner in the portal. It is the phase's
evidence: a run that leaves parity green has proven the revision model against real work.

### Read surface

- `GET /targets/{id}/revisions` — rev, tree hash, author, produced-by run, created-at, file count.
- `GET /revisions/{revision_id}/files` — path, blob key, size.
- `GET /revisions/{revision_id}/file?path=<tracked-path>` — streams the bytes from blob storage.
  `path` is a query parameter rather than a wildcard path segment so that tracked paths with
  slashes need no escaping.
- Every one of these resolves through the row first and filters by the request's tenant, so a
  blob is **never served by key alone** (§9). That the tenant is always 1 today is not a reason to
  leave the filter out — it is the structural half of P5.
- Portal: a read-only **Revisions** panel on the target, showing the parity banner, the revision
  list, the selected revision's files, and one file's contents. Delivery and reset still have no
  UI; this phase does not change that.

### Seams

Confirmed with the maintainer before writing this spec. All three already exist; none is added.

1. **Step boundary** — `run_pipeline`'s one injected `collect` callable. Sync-out composes behind
   it in the launcher.
2. **Blob bytes** — the existing `Storage` Protocol, extended by **one** method, `exists(key) ->
   bool`, which is what content-addressed dedup needs; uploads keep using `put_file`. Both
   in-test fakes (`FakeStorage` in `test_artifacts.py`, `_FakeStorage` in `test_api.py`) gain it.
   No separate blob-store abstraction: a second storage interface is a second thing to configure,
   fake and keep in sync for no gain.
3. **Tracked-tree definition** — `delivery/render.py`, which already owns the path contract
   (`INFRA_COMMON`, the story-file regexes, the delivered-path derivations) and already has
   `apphub.py` importing from it so there is one definition of "what a story file is called". The
   tracked-tree enumeration and the target-relative ↔ on-disk mapping go there, so snapshotting
   and delivery cannot drift about what the product versions.

## Testing Decisions

### What makes a good test here

Test what a caller can observe: rows committed, blobs stored, bytes served, parity reported.
Never the shape of a private helper. The highest seam available is a whole run driven through
`run_pipeline` with a `FakeRunner`, a fake `Storage` and the Postgres fixture — the test asserts
on the revisions and blobs that exist afterwards, which proves the hook composition in the
launcher as well as the functions behind it. Use that seam for anything that happens during a
run, and the pure functions directly only for the two things that are genuinely pure (parity, the
tree hash).

One deliberate exception to "don't test implementation": **the tree-hash encoding is pinned by a
known-value test.** It is a durable on-disk format that every revision ever written depends on,
so it is external behavior even though it looks internal.

### What to test

- **Tree hash:** a known-value test fixing the format; determinism across two snapshots of the
  same tree; independence from directory iteration order; a one-byte change to one file changes
  the hash.
- **Tracked-tree contract:** `app.json`, `reports/`, `node_modules/`, `test-results/`,
  `playwright-report/` and `session.jsonl` are absent from a snapshot; the five root infra files
  and the story/spec/test trees are present, at target-relative paths.
- **Through the driver** (prior art: `test_artifacts.py`): a five-step fake run commits exactly
  one revision when only one step changes the tree; two runs that change nothing in between leave
  one revision, not two; a run that changes tests on steps 4 and 5 commits two.
- **Dedup:** a file unchanged between revisions is uploaded once (assert on the fake's object
  count and that `exists` short-circuited); two targets sharing identical infra files share one
  blob.
- **Blob before row:** a `Storage` whose `put_file` raises leaves **zero** revision and
  `file_index` rows, and the run still reaches `COMPLETED`.
- **Failure isolation:** an artifact collector that raises does not prevent the revision commit;
  a revision writer that raises does not prevent artifact collection; neither fails the run.
- **Baseline:** a target with no head gets rev 1 from the pre-run tree, and the first step's
  change becomes rev 2 with `parent_rev = 1`; the manual snapshot route creates a baseline for a
  never-run target.
- **Chain and immutability:** `parent_rev` links the chain; a second insert of the same
  `(target_id, rev)` is rejected.
- **Parity:** green for a freshly snapshotted target; and each of missing / extra / modified
  reported separately and by exact path.
- **Read routes** (prior art: `test_api.py` with `TestClient` and a fake storage): the file list
  matches the committed revision; the file route returns the stored bytes; a revision belonging
  to another tenant is not readable.
- **Schema:** every table declared on `Base.metadata` has a non-null `tenant_id` (a structural
  test — this is the assertion that makes P5 a backfill); `test_migrations.py`'s existing
  autogenerate check covers the rest, including a lingering server default.
- **Portal** (prior art: `Bootstrap.test.jsx`, which asserts the success *and* failure banner):
  the parity banner renders in both states; the file list and one file's contents render.

### Prior art to follow

- `server/tests/test_artifacts.py` — a full `run_pipeline` + `FakeRunner` + `FakeStorage` +
  Postgres run, asserting on rows afterwards. The model for every during-a-run test here.
- `server/tests/conftest.py` — schema built by running the Alembic migrations from zero, and
  `QA_REQUIRE_DB` so CI fails rather than skips when Postgres is absent.
- `server/tests/delivery_helpers.py` — fake only the boundary you must (REST), keep the rest real
  (git, the filesystem). The snapshot tests follow it: a real temp tree, a fake blob store.
- `server/tests/test_api.py` — `TestClient` with dependency overrides for storage.

### Acceptance criteria

- [ ] `tenants`, `revisions`, `file_index` exist; `tenant_id` is non-null on every other table;
      one tenant is seeded; `test_migrations.py` passes.
- [ ] A real agent run (`QA_RUNNER=claude`) on `practice-target` leaves a revision chain whose
      head's `file_index` matches the on-disk tracked tree, with parity green — recorded in a
      `VERIFICATION-P2.md` alongside P1's.
- [ ] A fake run with a storage that raises leaves no revision rows and still completes.
- [ ] Delivery (`make deliver`), artifact collection, run states and every existing portal page
      behave identically to P1 — no test in the existing suite changes except to add `exists` to
      the two storage fakes.
- [ ] The portal shows a target's revisions, one revision's files, one file's contents from blob
      storage, and the parity banner.
- [ ] `make ci-test` green.

## Out of Scope

- **Reading from the database to make any decision.** That is P3, and it is the whole reason P2
  exists as a separate phase. `apps/` stays authoritative; `config.repo_root()` stays.
- **`delivered_sha` and the invariant-5 "in sync?" query.** The column is added and left null;
  `require_bootstrapped` keeps asking GitHub.
- **Garbage collection** (§9): no mark-and-sweep, no 24 h grace period, no cascade on abandoned
  runs. P2 creates the reference graph GC will need and deliberately leaves orphan blobs behind.
- **Git bundles** (§5) and `bundle_key`. P4, with the sandbox that has a history worth bundling.
- **Containers, egress allowlists, sandbox isolation, quotas, timeouts, token budgets** (§6). P4.
- **Real multi-tenancy** (§5 of the migration table): no quotas, no per-tenant PATs, no KMS
  envelope encryption, no tenant-scoped auth. P2 carries the column and the `current_tenant_id()`
  indirection; P5 gives them meaning.
- **Moving config into Postgres.** `app.json` stays a file and stays out of the tracked tree.
  Rendering `playwright.config.ts` from the database is P3.
- **The queue and batch runs.** Still one run per target, still a 409 on the second. Reinstating
  batching needs a scheduler above the lock (§5) and is its own piece of work.
- **Re-keying `artifacts` to the tenant prefix.** P5, when a second tenant makes it matter.
- **Portal write-back** of any kind — the revisions surface is read-only, and delivery/reset still
  have no UI.
- **The stale `prompts/` text** naming `./scripts/push-artifacts.sh` (VERIFICATION-P1 known gap
  0). Still recommended as a small separate task; still not this phase.

## Further Notes

- **The sentence to re-read before reviewing this phase** is §13's: "Proves the revision model
  against real runs with zero behavior change — the safety net is still there." Both halves are
  requirements. A P2 that quietly starts reading the new tables has removed the safety net; a P2
  whose revisions are never compared to the filesystem has proven nothing.
- **Three documented decisions in DESIGN.md need amending** as part of this phase, because P2 is
  where they meet code: §3's `occ_version` column (replaced by the unique constraint), §3's
  `bundle_key` (deferred to P4 with bundles), and §4's `playwright.config.ts` *(generated)* note
  (still hand-maintained until P3's hydrate). Amend them in the same commits rather than leaving
  the design describing a schema that was not built.
- **The subtlest correct code in the system is still the lease-lock trio** in `repo.py`
  (`FOR UPDATE`, in-place reaping of an expired lease, `pause_run` keeping the lock while
  clearing the lease, the reaper skipping `PAUSED`). P2 touches it only to add `tenant_id` to
  `app_locks`. DESIGN §5 says leave it alone; that still holds.
- **Why dedup is worth having in P2 rather than later:** the generated suites are the bulk of the
  tracked tree and they change a few files at a time. Without content addressing, a revision per
  step boundary multiplies storage by the number of boundaries; with it, a revision costs the
  bytes that actually changed. The model is only affordable because it is content-addressed, so
  the two land together.
- **The first run after this lands will produce two revisions for work that feels like one** —
  the baseline from the pre-run tree, then the run's own changes. That is intended (user story
  22) and worth saying in the portal copy, because it reads like an off-by-one otherwise.
