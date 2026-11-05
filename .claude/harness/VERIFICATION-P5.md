# P5 verification record

**Phase:** P5 of [DESIGN.md §13](DESIGN.md#13-migration-plan) — multi-tenancy: real auth,
tenant-scoped reads, KMS PATs, quotas, run-scoped store API, prompt overrides, audit log.
**Spec:** [issue #30](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/30),
seven tickets (#31–#37). **`SPEC-P5-multi-tenancy.md` is a zero-byte file** — see
§"Follow-ups" item 12; the spec of record is the issue.
**Opened:** 2026-11-03, on `portal/build`.
**Purpose:** the same as P1–P4's — so "P5 is done" rests on evidence rather than on a green
suite, and so each ticket after the first inherits a list of what is *proven*, what rests on
fakes, and what was deliberately deferred.

> ## P5 is CLOSED, on 2026-11-05.
>
> **Twenty tickets, three UAT checkpoints, and the record below says per slice what is proven
> and what is not.** The seven original tickets (#31–#37) plus #39 landed first; the two-axis
> review of #30 on 2026-11-04 then found that the spec's unbuilt half had never been ticketed
> at all — not deferred, simply absent — which produced #40–#50, and those ran in three waves,
> each ending at a UAT checkpoint against the live stack (#52, #53, #54).
>
> **What the three UATs found that the suite could not**, which is the whole reason they exist
> and now the sixth, seventh and eighth entries on this phase's list of the same:
>
> * **UAT 1** — the bypass allowlist had grown by one, and the honest reason (#44 widened the
>   guard to cover `DELETE`, so an existing cross-tenant sweep had to declare itself) is
>   recorded rather than ticked.
> * **UAT 2** — nothing broken, and that is itself the finding: the pause, the attempt
>   counter, the session restore and the liveness exemptions all behaved against a real
>   container. It also corrected this record: the Docker-backed tests use the *real* store and
>   run whenever the daemon is up, so `make ci-test` had been exercising the container path all
>   along.
> * **UAT 3** — **removing a user did not remove their access.** A deleted admin refreshed
>   into a new session and created another admin. Thirty days, not fifteen minutes, because
>   refresh never read the row either. Fixed; the residual 15-minute window is follow-up 55.
>
> **This record no longer says "partial".** Every ticket has a §Verified section, #36's
> included — it was the one gap, and UAT 3's closeout criterion is what closed it.
>
> ### The old banner, kept because its caveats are still the honest ones
>
> ## (historical) P5 was OPEN while this record was partial.
>
> **All six implementable tickets are complete in the tree and closed on the tracker**, and
> #30, the parent spec issue, is the only one of the seven still open. Tree state and tracker
> state are two separate facts and the tracker is the source of the second one
> (`docs/agents/issue-tracker.md`): #31, #32 and #34 are closed `completed` — #34's two-axis
> review was re-run and acted on (§Follow-ups items 27 and 27b), which is what its close was
> waiting on. **#35 is closed `completed` too.** **#33 is closed `completed` as well**: its
> two-axis review ran, found one real authorization gap (blob reads and writes authorized by
> tenant prefix rather than by a row and a content hash) plus six smaller items, and all of
> them are fixed in the slice they reviewed — see §"What the two-axis review found". **#37 is
> closed `completed`** as of 2026-11-04, with a comment carrying its evidence, its accepted
> gaps and its follow-ups.
>
> Two pieces of work in this record are **not** tickets of the seven. The **credential pair**
> — follow-ups 2 and 21, the missing `Secure` flag and `QA_SECRET_KEY` doubling as the key
> that decrypts every stored PAT — was the largest hole P5 had left, and it is closed; see
> §"Verified on 2026-11-04 — follow-ups 2 and 21". And **#39**, the prompt-history read
> surface #36 deliberately left out, is implemented; see its own §Verified section. Neither
> changes what #30 is waiting on.
>
> | Ticket | State in the tree |
> |---|---|
> | #31 P5-01 — users table + session-resolved `current_tenant_id()` | Implemented (`e492a9d`, review fixes `06a3acd`). **Not independently re-verified in this record** — see the note below |
> | #32 P5-02 — tenant-scoped reads + tenant-scoped uniqueness + fail-closed | **Complete.** The `users.email` half plus token expiry/refresh landed first (`105e9b7`); the enforced read path and the `projects`/`targets` composite uniqueness landed in the slice below, and were exercised against a live stack with a second real tenant |
> | #34 P5-03 — per-tenant KMS-encrypted PATs, scope/expiry/fail-loud | **Complete, reviewed and closed.** The envelope, the per-target `Tools` binding, the save-time scope check, the portal surface and the structural credential tests. The two-axis review found two real credential leaks (the PAT in `Tools.__repr__`, a data key reachable in a `SealError`) and one half-true acceptance criterion (a git-transport 401/403 did not mark the credential invalid); all fixed — see §Follow-ups 27b. **Still not seen against a real KMS, a real GitHub token or a browser** — see §"What is covered only by fakes" |
> | #35 P5-04 — per-tenant concurrency cap and monthly run quota at enqueue | **Complete, and the first P5 slice seen in a real browser.** The two columns, the typed 429 rejection above the `AppLock` trio, the usage endpoint and the portal gauges. Both breaches driven over HTTP against the live stack, leaving no run row. The three gaps it shipped with were all closed in later passes: an untested portal surface, caps that bounded only a configured tenant (follow-ups 28 and 29), and — found by the browser check itself — `/usage` missing from both proxy lists, which made the panel invisible in the real app while 84 frontend tests passed |
> | #33 P5-05 — run-scoped internal control-plane API | **Complete, reviewed and closed.** The token, the service, the routes, both gateways, and the whole run path rewired onto them. `DATABASE_URL` and `S3_*` are gone from a sandbox and the stores are off its network. Proven in a **real container** and then **against the real compose stack** — the only slice of P5 whose central claim is checked end to end against the deployed arrangement. Four real bugs, and none of them was found by the suite: three by running a container (a client that verified a token it holds no key for, a liveness gate that ate the end of every log, a flusher raced on close) and the fourth by the review (blob authorization by prefix, so a run could read *or overwrite* a sibling target's revision blobs). All fixed here. **Two gaps accepted and recorded rather than fixed** — `record_cost`'s liveness exemption, and the whole API being sandbox-reachable rather than only `/internal` (§Follow-ups 32–34) |
> | #36 P5-06 — prompts into Postgres, tenant-overridable and versioned | Implemented (`8b5aec3`). **Not verified in this record** — no §Verified section was written for it, so this record does not vouch for it. It left the "see what changed and when" half of story 24 open deliberately, which is [issue #39](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/39) |
> | #37 P5-07 — immutable `audit_log` for every control-plane mutation | **Complete and closed**, and verified by the suite plus a by-hand migration run. The table, the trigger, seven recorded mutations, the tenant-scoped read and `GET /audit`. **Never seen against the live stack or a browser, and there is no portal surface for it** — see §"Verified on 2026-11-04". Two of the mutations #37 lists are not recorded because they do not exist: user add/remove has no code path at all |
> | #39 — the prompt-history read surface (not one of the seven; #36's deliberate remainder) | **Implemented.** `prompt_store.history` with a `PromptRevision` type and `created_at`, `GET /prompts/{name:path}/history`, and the Prompts panel showing revisions with a line diff. Both proxy lists checked and needing no entry. **Seen only by its suite — no browser**, which is the gap P5-04's lesson is about |
> | follow-ups 2 and 21 — the credential pair (not a ticket) | **Done.** `Secure` on both cookies outside development, and `QA_ENVELOPE_KEY` separated from `QA_SECRET_KEY` with a boot-time refusal. **Observed against a real `uvicorn` boot in four configurations**, which found a defect the suite could not see (follow-up 43). Still no real KMS and no real browser |
>
> **P5-05's claims were checked against a real container and then against the real compose
> stack**, which is a stronger kind of evidence than the four slices before it had, and the
> section below says plainly which four bugs the suite did not find.
>
> **What this record does and does not claim.** The five §"Verified" sections below each
> cover one slice, and every line in them was observed. P5-01's own evidence lives in its two
> commit messages; it has not been re-run here, so this record does not vouch for it.
> **P5-02's isolation claims were checked against a second real tenant** over HTTP against
> the live stack. That tenant was deleted again afterwards, so the evidence was observed
> and then reverted and no second tenant exists in the dev database now. **P5-03's claims
> rest on the suite, two by-hand migration runs on throwaway databases, and a two-axis
> review that was re-run and acted on**; it has not met the live stack, a real KMS key or a
> real GitHub PAT. **A real browser has now been part of one P5 slice**:
> P5-04's usage panel was rendered in Chrome against the live stack, which is what caught
> `/usage` missing from both proxy lists. P5-01 to P5-03's surfaces have still never been
> rendered by one.

---

## Verified on 2026-11-03 — `105e9b7` (tenant-scoped email + expiring session)

The change: `users.email` becomes unique per `(tenant_id, email)`; `tenants.slug` becomes the
login handle; the single week-long session cookie becomes a 15-minute access cookie plus a
30-day stateless refresh cookie traded at `POST /auth/refresh`.

**Suite, run as CI runs it** (`QA_REQUIRE_DB=1 make test`, exit 0): ruff clean, **781 backend
tests**, **57 frontend tests**. New coverage: 13 tests in `test_auth.py` (slug
disambiguation, expiry through real cookies, cross-salt rejection, cookie attributes), 4 in
`test_tenancy.py` (the composite constraint both ways, slug uniqueness), 7 in `api.test.js`
(refresh-once-on-401, and `renewSession` for the one caller that cannot use it), 4 in the new
`RunDetail.stream.test.jsx`.

**The constraint flip, observed on a throwaway database** rather than inferred from the
suite. `alembic upgrade head` from zero → `downgrade -1` → `upgrade head` again, reading
`pg_constraint` at each stop:

| Stage | `users` | `tenants` |
|---|---|---|
| head | `uq_users_tenant_id_email UNIQUE (tenant_id, email)` | `uq_tenants_slug UNIQUE (slug)`, row `(1, 'default', 'default')` |
| downgrade −1 | `users_email_key UNIQUE (email)` | no `slug` column |
| re-upgrade | `uq_users_tenant_id_email` | `uq_tenants_slug`, slug `default` |

The point of doing this by hand: **the old global unique is replaced, not left beside the
new one.** An orphaned `users_email_key` would have made the entire change decorative while
every test still passed, because nothing in the suite asserts the *absence* of a constraint.
The same run, repeated with `QA_SEED_TENANT_SLUG=should-be-ignored` in the environment,
confirmed the seed slug no longer reads any env var.

**Expiry, through real cookies over real HTTP** — the seam agreed before the work started,
rather than at the token functions. `ACCESS_MAX_AGE` is squeezed to 1 second, login
succeeds, `/auth/me` is 200, the test sleeps past the window, `/auth/me` is 401, and
`POST /auth/refresh` restores it to 200. A realistic lifetime is restored before the refresh
so the assertion is not racing a one-second cookie on a loaded runner.

---

## Verified on 2026-11-03 — P5-02's two larger halves (the enforced read path)

The change: one `do_orm_execute` listener (`tenancy.install_read_guard`) adds the `tenant_id`
filter to **every ORM SELECT** of a tenant-owned entity, so a query can no longer *forget* the
filter — only explicitly opt out of it; and `projects.name` and `targets.app` become unique
per tenant rather than globally.

**Suite, run as CI runs it** (`QA_REQUIRE_DB=1 make test`, exit 0): ruff clean, **801 backend
tests** (up from 781), **57 frontend tests**. New coverage: 6 tests in
`test_tenant_isolation.py` (two logged-in tenants over HTTP), 8 in
`test_tenant_isolation_repo.py` (the repository sweep, the mixin check and the bypass
allowlist), 4 in `test_tenancy.py` (composite uniqueness, both directions), 2 in
`test_reaper.py` (a non-default tenant's crashed run, and one tenant's failing sweep not
stopping the rest).

**The hole it closes, stated as it was found.** `GET /artifacts/{id}/content` did
`session.get(Artifact, artifact_id)` and streamed the blob behind whatever came back. The
route was auth-gated, so it checked *whether* you were logged in and never *whose* artifact
you asked for: any logged-in user of any tenant could walk a small integer id and download
every other tenant's reports, screenshots and traces. The first red test in
`test_tenant_isolation.py` is that request, and before the guard existed it returned **200
with the other tenant's bytes**.

**The constraint flip, observed on a throwaway database** rather than inferred from the suite
— the same by-hand check the `users.email` flip got, and for the same reason: nothing in the
suite asserts a constraint's *absence*. `upgrade head` → `downgrade -1` → `upgrade head`,
reading `pg_constraint` at each stop:

| Stage | `projects` | `targets` |
|---|---|---|
| head | `uq_projects_tenant_id_name UNIQUE (tenant_id, name)` | `uq_targets_tenant_id_app UNIQUE (tenant_id, app)` |
| downgrade −1 | `projects_name_key UNIQUE (name)` | `uq_targets_app UNIQUE (app)` |
| re-upgrade | `uq_projects_tenant_id_name` | `uq_targets_tenant_id_app` |

Exactly those at each stage and nothing else, in both directions: the old global uniques are
**replaced, not left beside** the new composite ones.

**Against the live stack, with a second real tenant** — the first P5 work to meet either.
`docker compose up -d --build api` migrated the **dev database, which holds real data** (a
project, the `saucedemo` target, five runs and their artifacts from P4's walkthrough), and
tenant `acme` was created with SQL, because there is still no tenant-admin surface
(follow-up 6). Then two cookie jars, one per tenant, over `curl`:

| Request | as tenant 1 | as `acme` |
|---|---|---|
| `GET /projects`, `GET /targets` | its own rows | `[]`, `[]` |
| `GET /runs/1`, `/runs/1/steps` | 200 | **404** |
| `GET /artifacts/1/content` | 200 | **404** (200 *with tenant 1's bytes* before this change) |
| `GET /targets/1/revisions`, `/targets/1/stories` | 200 | **404** |
| `GET /targets/2/revisions` (`acme`'s own) | **404** | 200 |

The reverse direction matters as much as the forward one: tenant 1 is an admin and the seeded
operator, and it is refused `acme`'s rows just the same. Then the constraint, live: `acme`
created a project named `P4 walkthrough` and a target with the app slug `saucedemo` — **both
names tenant 1 already holds** — and got 201 for each, where the global constraint would
have given it a 409 it could do nothing about. A *second* `saucedemo` inside `acme` was still
refused, 409 "a target named 'saucedemo' already exists".

**The second tenant was then removed.** Tenant 2 (`acme`), its user `ops@acme.test`, its
project, its target, its revision and its 6 `file_index` rows were deleted in FK order, and
the 6 blobs under `tenant/2/blobs/` were deleted from SeaweedFS. Checked before deleting:
those blob keys were referenced by **tenant 2 alone** (— tenant blob keys are namespaced by
tenant, so a shared blob is not possible across tenants by construction, and the query
confirmed it). Checked after: no tenant-2 row remains anywhere, `tenant/2/` holds 0 objects,
`tenant/1/blobs/` still holds 124, tenant 1 still has its project, target, 4 revisions and 7
runs, and over HTTP it still logs in and reads its own rows and artifact bytes — while
`acme`'s login is now a 401.

So the evidence above was **observed and then reverted**, and the dev database is back to one
tenant. This matters for how the table above should be read: it records what a second tenant
*did*, not a second tenant you can go and look at. The next ticket that needs one creates it
the same way, with SQL, until follow-up 6 lands.

## Verified on 2026-11-03 — P5-03 / #34 (per-tenant KMS-encrypted PATs)

The change: a tenant's GitHub PAT moves from one `GITHUB_PAT` in the API's environment onto
the target's own row, envelope-encrypted; scope is validated against GitHub as it is pasted;
expiry is stored and warned about in-portal; and a 401/403 at delivery sets
`credential_state = invalid`, failing that delivery only. `token_from_env()` is **deleted**,
not guarded.

**Suite, run as CI runs it** (`QA_REQUIRE_DB=1 make test`, exit 0): ruff clean,
**874 backend tests** (up from 801), **70 frontend tests** (up from 57).
New coverage: 10 in the new `test_envelope.py` (the sealed form, tamper and version
rejection, the KMS wrapper sending only the data key, which wrapper a deployment gets), 30 in
the new `test_delivery_credentials.py` (save/clear/rotate, the three scope cases, expiry
warnings, `DbCredentials` against real rows including cross-tenant, and the `Tools` binding
and fail-loud guard), 15 in the new `test_api_credentials.py` (the HTTP contract, the role
gate, 401-at-delivery end to end), 4 in `test_delivery_git.py` (redaction of a bare token, of every
GitHub token prefix and of a sealed column, and a commit sha that must survive it),
6 in `test_sandbox_credentials.py`, and 13 frontend (9 in the new
`TargetCredential.test.jsx`, 4 in `Projects.test.jsx`).

**The migration, observed on two throwaway databases** rather than inferred from the suite,
because the suite structurally cannot make either claim — nothing in it asserts a column's
*absence*, and every target it creates post-dates the revision.

`upgrade head` → `downgrade -1` → `upgrade head`, reading `information_schema.columns` at
each stop:

| Stage | `github_pat_ciphertext` | `pat_expires_at` | `credential_state` |
|---|---|---|---|
| head | `text`, nullable, no default | `timestamptz`, nullable, no default | `varchar`, **not null**, **no default** |
| downgrade −1 | absent | absent | absent |
| re-upgrade | `text`, nullable, no default | `timestamptz`, nullable, no default | `varchar`, not null, no default |

And the backfill, on a second database where a target was inserted **at the previous
revision** and then migrated forward:

```
pre-revision target inserted
after upgrade: app='legacy-app' state='absent' ciphertext=None expires=None
insert without credential_state refused, as intended:
  null value in column "credential_state" of relation "targets" violates not-null constraint
```

Those two lines are the whole claim: an existing target becomes `absent` — which is exactly
true of it — and **the server default that performed the backfill was dropped in the same
revision**, so new rows must set the column from `CredentialState` rather than have the
database guess it. That is the pattern P2 set for `tenant_id` and P3 for the config columns,
and nothing in the suite would have noticed an orphaned default.

**No CHECK constraint, deliberately and consistently.** `native_enum=False` plus
SQLAlchemy 2.x's `create_constraint=False` default makes `credential_state` a plain
`VARCHAR(20)`, validated in the application by `_enum_col`'s `validate_strings=True` — the
same shape `runstatus` and `step` have had since the initial schema. Checked against
`pg_constraint` on the throwaway database: no table-level CHECK on any of them. It is
recorded here because the absence reads like an oversight, and the migration's own comment
had claimed a CHECK that has never existed.

**Two bugs the loop found, both in the first green version of the code.**

The first was caught by an existing test, which is the better outcome: naming the redaction
regex `_BARE_GITHUB_TOKEN` made `test_no_module_reachable_from_the_entrypoint_reads_a_github_credential[GITHUB_TOKEN]`
fail, because `app/delivery/errors.py` *is* imported by code a sandbox runs and the assertion
is on the source text. A name is a mention. Renamed to `_BARE_PAT`.

The second was a day-rounding error in the expiry warning. `timedelta.days` truncates, so a
credential with 2 days and 23 hours left was reported as "2 days" and one with 3 hours left
as **"0 days"** — a message that reads like "no deadline" about the most urgent case the
warning exists for. `_days_until` rounds up now, and never claims more time than the
credential has.

**"Fails the delivery only, never the run" is structural here, not defended.** The criterion
presumes a run could be at risk, and in this architecture none can be: delivery is a
separate, human-approved control-plane action (DESIGN.md §7) and no run ever performs one —
the only non-route caller is the optional infra sync at target creation, which is not a run
either. So the end-to-end test asserts what there is to assert: the route answers 502, the
credential becomes `invalid`, and nothing else moved. If a future change ever made a run
reach a delivery, that test would not notice; the thing keeping the rule true is the
architecture, and it is worth knowing which of the two is doing the work.

**What the credential rule is now held to, structurally.** P4's version was about one
operator token; there is a credential per customer to keep out now, plus the key material
that would open it. `tests/test_sandbox_credentials.py` asserts: `TargetConfig` has exactly
its seven configuration fields and no credential field, so there is no value for the sandbox
environment builder to pass along even by mistake; a real sealed PAT and the wrapping key in
the control plane's environment appear nowhere in a built sandbox environment, by name or by
value; and **no module reachable from the sandbox entrypoint's real import graph imports
`app.envelope` or `app.delivery.credentials`, or so much as mentions `decrypt_pat`,
`open_sealed` or `LocalKeyWrapper`**. That last one matters more than it looks: until #33
lands, a sandbox still holds `DATABASE_URL` and can therefore *read*
`targets.github_pat_ciphertext`. The envelope is what makes that harmless, and it stays
harmless only while nothing in there can unwrap a data key.

That assertion is also what settled where the credential surface is exported from.
`app/delivery/__init__.py` re-exports lazily so a sandbox wanting `tracked_tree` does not
import the credential reader — but the *table* of names lives in a file every sandbox loads,
and an entry reading `"decrypt_pat": "credentials"` would hand anything running in there the
exact name to ask for, one `getattr` away from the function that unwraps a data key. So the
credential functions are **not in the table at all**; `app/api.py` imports that module by
path instead, which is a line a reviewer sees.

**What the `Tools` seam looks like afterwards.** `for_target(tools, app)` is the one way a
delivery entry point acquires a credential, and it binds *and* marks-invalid-on-rejection in
one context manager — because those are two halves of one decision, and five entry points
each able to do the first and forget the second is how the fail-loud rule would quietly stop
holding. An unbound seam raises a `CredentialError` naming the call that was missed, rather
than an `AttributeError` on `None` from somewhere inside a push. **Four** paths deliberately
do **not** bind: `is_bootstrapped`, the already-bootstrapped arm of `ensure_bootstrapped`,
and the `--dry-run` arms of bootstrap and push. All four answer from Postgres and the blob
store and dial out to nothing, and a new target with no PAT saved yet — the normal state of
one — must still be able to say where it stands. `plan_reset` is a dry run that *does* bind,
because it makes two authenticated GitHub calls: the test is whether a path dials out, not
whether it writes. (The count said "three" here and "two" in `tools.py`'s module docstring
until the review in the slice below; both now say four.)

---

## Verified on 2026-11-03 — P5-04 / #35 (per-tenant quotas at the enqueue seam)

The change: `tenants` gains `max_concurrent_runs` and `monthly_run_quota`; `repo.start_run`
refuses an enqueue that would exceed either, with a typed rejection the route answers **429**;
`GET /usage` reports usage against both caps and the portal renders two gauges.

**Suite, run as CI runs it** (`QA_REQUIRE_DB=1 make ci-test`, exit 0): ruff clean,
**909 backend tests** (up from 883), **70 frontend tests** (unchanged — see the gap below).
New coverage: **16** tests in the new `test_quotas.py` (both breaches, tenant scoping,
unmetered, the boundary from the allowed side, ordering against the `AppLock` trio, what the
monthly count includes, the crashed-run and paused-run cases, and that setting one cap leaves
the other alone) and **7** in the new `test_api_quotas.py` (both breaches over HTTP, the
launcher never called, 429-vs-409, and the three usage-endpoint cases).

**+26 for 23 new tests**, and the missing 3 are accounted for rather than shrugged at: the
baseline was measured at 883 on a clean worktree of `263bfea`, and `test_no_repo_mount.py`
went 178 → 181 because three of its tests are parametrized over *every* module under `app/`
and this slice adds one (`app/domain/quotas.py`). A test count that does not add up is
usually a test that silently stopped collecting, so it was worth chasing to the file.

**The constraint and the backfill, observed on a throwaway database** rather than inferred
from the suite — the same by-hand check `users.email` and `projects.name` got, and for the
same reason. `upgrade head` → `downgrade -1` → `upgrade head`, reading
`information_schema.columns` and `pg_constraint` at each stop:

| Stage | `tenants` |
|---|---|
| head | `max_concurrent_runs integer NULL`, `monthly_run_quota integer NULL`, **no server default on either**; seeded row `(1, 'default', 3, 500)` |
| downgrade −1 | neither column present (`id`, `name`, `created_at`, `slug` only) |
| re-upgrade | both back, nullable, no default; seeded row `(1, 'default', 3, 500)` again |

Zero CHECK constraints on `tenants` at head, which matches every other enum/bounded column
in this schema (the values are enforced in the application, not the database) and is stated
here so the absence is not mistaken for an oversight.

**Two behaviours the docstring claims and the suite cannot see**, both checked by hand on
that database: a tenant inserted *after* the revision gets `NULL`/`NULL` — unmetered, the
documented default — and re-running the backfill `UPDATE` reported `UPDATE 1`, touching only
the row that was null and leaving the already-configured tenant alone. The `IS NULL` guard
does what its comment says.

**Against the live stack, with the real dev database.** `docker compose up -d --build api`
migrated the dev database (which holds P4's walkthrough data: a project, the `saucedemo`
target, runs and artifacts), and the existing tenant picked up `3`/`500`. Then, over `curl`
with a real session cookie (**taken before the crashed-run fix below**; the breach paths it
covers are unchanged by that fix, and `/usage` was retaken afterwards):

| Request | Answer |
|---|---|
| `GET /usage` | `live_runs 0, runs_this_month 0, max_concurrent_runs 3, monthly_run_quota 500`, both `at_*` false |
| `GET /usage` with `monthly_run_quota = 0` | `at_monthly_quota: true`, `at_concurrency_cap: false` |
| `POST /targets/1/runs` with `monthly_run_quota = 0` | **429**, "this tenant has started 0 of its 0 runs for this calendar month; the quota resets at the start of next month" |
| `POST /targets/1/runs` with `max_concurrent_runs = 0` | **429**, "this tenant already has 0 of 0 runs going at once; wait for one to finish or stop one…" |
| `runs` / `app_locks` after both refusals | unchanged — **no run row, no lock** |

**The crashed-run fix, demonstrated on the live stack after it landed** — the table above was
read before that fix, so the `/usage` query it exercised is not the one that shipped and the
evidence was retaken rather than left to stand. The dev database's seven runs are all
terminal, so they prove nothing either way; a crashed run was inserted with SQL (`pending`,
lease lapsed two hours), then the *same row* flipped to `paused` with its lease cleared:

| State of the one non-terminal run | `/usage` |
|---|---|
| `pending`, lease lapsed 2h (**crashed**) | `live_runs: 0`, `runs_this_month: 1` |
| same row, `paused`, lease `NULL` | `live_runs: 1`, `runs_this_month: 1` |

Which is the whole distinction in two lines: a crashed run holds **no** concurrency quota (the
trio is about to reap it) but **does** spend monthly quota (it started, and it cost a sandbox);
a paused run holds both. Before the fix the first row read `live_runs: 1` and a tenant at a cap
of 1 was locked out by its own dead run. The probe row was deleted afterwards and the dev
database is back to its seven original runs.

`runs_this_month` reading **0** on a database holding five runs is the calendar-month
boundary confirming itself: those runs are from October and the check ran on 3 November. The
caps were driven to `0` deliberately, because that is the only way to observe a breach
against the live stack without starting a real sandbox run; they were restored to `3`/`500`
afterwards and the dev database is back as it was. A cap of zero also reads a little oddly in
the message ("0 of 0"), which is left alone: it is a degenerate configuration used here as a
test instrument, not a state the product offers.

**The two-axis review, and what it found.** Run before the ticket was closed, as every slice
in this phase except P5-03's first attempt.

**The one that mattered: a regression the suite was green on.** `tenant_usage` counted
`Run.status.in_(LIVE)` with no lease test, so a **crashed** run — `PENDING`/`RUNNING` with a
lapsed lease — held concurrency quota. A tenant at a cap of 1 with one dead run would get 429
from the check *above* the lock trio that was three lines from reaping that very run, so a
restart that worked before this slice would stop working until the reaper came round, and the
reaper is a 30-second loop that may not be running at all. It also made
`ConcurrencyLimitReached`'s own docstring false: "self-clearing" has to mean this too.
`live_run_holding` had already settled what "genuinely live" means — paused counts, lapsed and
not paused is crashed — and the fix is that the count now asks the same question and gets the
same answer. Two tests pin both halves.

**Also found and fixed:**

- **`set_tenant_caps` conflated "no cap" with "don't change".** `None` is a *value* on these
  columns, so it cannot also be the "not specified" default: `set_tenant_caps(max_concurrent_runs=5)`
  silently wiped the monthly quota to unmetered. Both axes flagged it independently. Now an
  explicit `UNSET` sentinel, so only the caps you pass are touched and `None` still means
  unmetered on purpose. Two tests, one per direction.
- **A double switch on `QuotaKind`**: `_BREACHES` mapped kind → class and then the caller
  re-switched on the same kind to pick the matching `limit`/`used` out of `caps` and `usage` —
  one decision made twice in two places that could disagree. `quotas.breach` now returns a
  `Breach` carrying all three.
- `api.py`'s 429 comment claimed the arm was ordered "before `RunConflict` because it is the
  narrower class". Untrue and worth deleting rather than keeping: they are siblings and
  neither catches the other, so the order does not matter — which is what the comment says now.
- `test_quotas.py`'s docstring pointed at `tests/test_api.py` for the HTTP half; it is
  `tests/test_api_quotas.py`.
- The portal: `g.cap === null` would render "2 of undefined" if the field were ever absent
  (now `== null`, catching `undefined` too), and the reload fired after a 429 called an async
  `load()` with no `.catch`, making a failed re-read an unhandled rejection. The second was a
  pre-existing footgun at `afterWrite` that this slice added a second caller to, so the fix is
  one guarded `reload()` both callers share rather than a `.catch` at each site.
- This record's own errors: a ticket-table row that had lost its `> ` and broken out of the
  banner blockquote, a test count that did not add up, and "three §Verified sections" when
  there are now four.

**Declined, recorded so they are decisions and not oversights:**

- **A cap of `0` is accepted** and means total lockout, with a message that reads oddly ("0 of
  0 runs going at once"). Kept: suspending a tenant is a real need, `0` is the honest way to
  say it, and the odd sentence only appears in a configuration an operator chose deliberately.
- **`resume_run` is not quota-checked.** Correct as built — `PAUSED` is in `LIVE`, so a
  resumed run was already counted and starts nothing new. The reviewer's residual case is real
  and is follow-up 30.
- **Two independent gauges duplicating the rejection's wording** between `components.jsx` and
  `repo.py`. DESIGN.md §6 endorses the two-gauge shape; the duplication is a consequence and
  the portal has no test to hold the wording anyway (see below).

**One review claim checked and found wrong**, recorded because this record's job is evidence
rather than deference: the standards axis said the conftest caps restore leaves a
test-created second tenant behind because "`tenants` isn't truncated". It is not truncated,
but `_truncate_all` does `DELETE FROM tenants WHERE id <> :seeded`, so `test_quotas.py`'s
`OTHER = 2` is removed like any other extra row — which is exactly why the restore only needs
`WHERE id = :seeded`.

**The two gaps this slice first shipped with, and how they were closed.** Both were recorded
as follow-ups 28 and 29 before being closed in a second pass; the detail is there and the
short version is here.

The portal surface shipped with **no test of its own**, the frontend component seam having
been declined when this ticket's seams were agreed — and the review then found two defects in
it by *reading*, which is exactly the class of bug a component test catches cheaply. The seam
was taken afterwards: **84 frontend tests, up from 70**, and both of those defects are now
pinned by tests that were confirmed to fail with the fix reverted.

More seriously, the caps bounded only a tenant somebody had configured, and nothing configured
one — there is no `create_tenant` in this application, so a tenant comes from the seed or from
raw SQL and both skipped the caps. `NULL` meant unmetered, so every tenant created after this
ticket was unbounded, which left #35's own premise ("one busy or abusive tenant cannot starve
the platform") true only by luck. Revision `f1a62c90d4e7` gives both columns a **server
default**, the one mechanism both creation paths go through. `NULL` still means no cap; it is
now asked for rather than inherited.

**A browser then rendered the panel, and the first thing it found was that the panel did not
render.** This is the entry that most justifies its own existence, so it is written out in
full.

`GET /usage` was in **neither proxy list** — not nginx's `location ~ ^/(auth|projects|...)`
in `docker/nginx.conf`, nor `apiPaths` in `web/vite.config.js`. The API's paths sit at the
root and collide with the SPA's client routes, so both configs carry an explicit allowlist of
prefixes to forward. A path missing from it does **not** 404: it falls through to
`try_files $uri /index.html` and answers **200 with the SPA shell**, `api.js` detects HTML and
raises, and `Projects.jsx`'s deliberately forgiving `.catch(() => setUsage(null))` swallows it.
The gauges simply were not there. Every one of the 84 frontend tests passed throughout,
because **jsdom has no proxy** — there is no configuration between the component and its
mocked `api`, so this class of bug is structurally invisible to them.

Fixed in both configs, and then covered so the next route cannot repeat it:
`test_api_proxy_paths.py` extracts every root path `web/src/api.js` requests (plus
`RunDetail.jsx`'s `EventSource`, which bypasses `api.js` on purpose) and asserts each appears
in both lists, that the two lists agree with each other, and — guarding the guard — that the
extraction actually found the known endpoints, since a regex matching nothing would make the
whole file vacuously green. 20 tests, and it isolated exactly `/usage` while passing for the
nine prefixes that were already correct.

**What was seen, in Chrome, against the live stack** (screenshots in `.playwright-mcp/`,
gitignored):

| State | Rendered |
|---|---|
| Caps `3`/`500`, nothing running | `RUNNING NOW 0 of 3`, `THIS MONTH 0 of 500` |
| `max_concurrent_runs` set to `0` | the concurrency gauge amber-bordered and inline-annotated "at your concurrent-run cap — wait for a run to finish, or stop one"; **the monthly gauge unchanged**, which is the two-independent-gauges decision visible |
| Pressing **Start QA run** at that cap | the row shows the server's own sentence — "this tenant already has 0 of 0 runs going at once; wait for one to finish or stop one, then start this again" — and `runs`/`app_locks` were unchanged afterwards |

The dev database was returned to its seven runs and `3`/`500` caps. The "0 of 0" wording
noted earlier as reading oddly is confirmed to read oddly on screen; it is still only
reachable in the degenerate suspension configuration used here as an instrument.

**The honest limit of even this.** A browser rendered it and a person looked at the result;
that is one viewport, one theme and one data shape. It is not cross-browser, not responsive
and not accessibility-audited, and nothing in P5 claims otherwise.

---

## Verified on 2026-11-03 — P5-05 / #33 (the run-scoped internal control-plane API)

The change, and it is the largest of the phase: a sandbox stops holding `DATABASE_URL` and
the `S3_*` credentials. In their place the control plane mints a short-lived, run-scoped
bearer token (`app/run_token.py`) and exposes a narrow internal API (`app/internal_api.py`)
over one set of operations (`app/control/service.py`). Everything a run does to Postgres and
to blob storage goes through that, as one run of one target of one tenant.

**What the exposure was, and what it is now.** P4 recorded the store credentials as accepted
exposure with a stated plan, and this is the other end of that note. Before: a process
running a model that writes and executes TypeScript against a web page an attacker may
control held the control plane's own database credential — read and write access to every
tenant's rows — and the object store's keys, and was trusted not to use them. The envelope
(P5-03) made the sealed PATs it could *read* harmless, which was the right mitigation and not
a fix. After: it holds a token naming one run, one target and one tenant, refused the moment
that run stops being live, and the stores are not on its network at all.

### The scope of the work, because it is bigger than the ticket's acceptance criteria say

The ticket enumerates the operations "hydrate and ingest perform today". That list is
necessary and **not sufficient**, and the gap is worth recording rather than discovering
later: the sandbox runs the *whole* pipeline (`drive_run`), so it also wrote run status, step
rows, the heartbeat lease, the cost columns and the agent session id. Acceptance criterion 1
says a sandbox carries no `DATABASE_URL`, which cannot be true while any of those go direct.
So the API covers the run lifecycle too — about twenty operations, which is now a readable
list (`app/control/gateway.py`) rather than the eight of ninety `repo` functions the driver
happened to use.

### What was observed

**Suite, run as CI runs it** (`QA_REQUIRE_DB=1 make ci-test`, exit 0): ruff clean,
**1063 backend tests** (up from 932 at `dd6ad79`), **84 frontend tests** (unchanged; this
slice has no portal surface). Also run in the default **random order** and in a fixed order,
because this change moved what every run-driving test is wired to.

**+131, and all of it accounted for:**

| Where | Δ | What |
|---|---|---|
| `test_control_gateway.py` (new) | +46 | One suite run twice — once against `LocalGateway`, once against `HttpGateway` over the real routes — so the two transports cannot drift |
| `test_internal_api.py` (new) | +23 | The HTTP framing: bearer header, 401 vs 403 vs 409 vs 422, streaming, and the two authorities not overlapping |
| `test_run_token.py` (new) | +11 | Forgery, tampering, expiry, cross-salt replay, and the read-vs-verify asymmetry below |
| `test_control_service.py` (new) | +11 | The authorization boundary itself, against two real tenants *and* two targets of one tenant |
| `test_no_repo_mount.py` | +27 | Three tests parametrized over every module under `app/`, and this slice adds nine |
| `test_sandbox_credentials.py` | +9 | The store credentials' absence, the token's presence, and the proxy-bypass host becoming the control plane |
| `test_compose_stack.py` | +2 | The stores off the sandbox network, the API on it, and nothing else on it |
| `test_api_proxy_paths.py` | +1 | `/internal` is absent from both proxy allowlists *by assertion* rather than by accident of how those lists are derived |
| `test_tenancy.py` | +1 | Replaced one test with two: the token carries the tenant, and it cannot be minted for another tenant's run |

**The container path, against a real container** (`make ci-test-docker`, 6 Docker-backed
tests, exit 0). This is the evidence that matters most, because it is the only thing that
exercises the deployed arrangement end to end: a real container holding **no** store
credentials, a real token, real HTTP, a real `uvicorn` control plane, real rows. It hydrated
its head revision, ran five steps, committed revisions whose `author`, `produced_by_run_id`
and `parent_rev` are indistinguishable from a thread run's, indexed artifacts, and streamed a
log the API read back by cursor. `tests/test_docker_sandbox.py` grew a `control_plane`
fixture to make that possible — the container cannot reach the test's database any more, so
something has to be at the URL it is given.

**And then against the real compose stack**, which is a step beyond the test harness: `make
up`, log in as the seeded admin, `POST /targets/1/runs` for the existing `saucedemo` target,
and read the rows back out of Postgres. `QA_SANDBOX=docker`,
`QA_CONTROL_PLANE_URL=http://api:8000`. The run completed all five steps and left **30 log
lines** in `run_log`, hydrated **13 files from revision 4**, and indexed **5 artifacts** —
all written by a container holding no database credential and no object-store key, through
the internal API. Two details worth reading off that log:

- it ends `=== run <key> completed ===` and `=== teardown: worktree removed ===`, which are
  precisely the lines the liveness-gate bug dropped — the fix is confirmed in the stack
  rather than only in a test;
- it committed **no revision**, correctly: compose does not set `QA_FAKE_TREE_WRITES`, so the
  fake runner changes no tracked file, and "a step that changed no tracked file commits
  nothing" is the documented behaviour.

`docker network inspect qa-sandbox` reports `Internal: true` with exactly one member, the
API. Postgres and SeaweedFS are no longer on it.

**A procedural trap found the same way, and it is now in README §9.** The first attempt at
that run sat in `pending` for ever with a `sandbox_handle` and no container. The cause was
not the code: `docker compose up -d --build` does **not** rebuild the sandbox image, because
the `sandbox` service carries `profiles: ["never-started"]` and Compose skips the build of a
service a profile excludes. The image in use was nine days old and predated all of P5, so its
entrypoint still wanted `DATABASE_URL` and exited at once. `make up` and `make sandbox-images`
build it explicitly; `docker compose up --build` silently does not. The failure mode is worth
knowing because it is indistinguishable from a dispatch bug: a run stuck `pending`, a handle
on the row, and a container that `AutoRemove` has already taken away.

**Three real bugs were found by running it, not by the suite**, and each is now pinned:

1. **`HttpGateway` verified its own token.** A sandbox holds no signing key — it must not,
   since a key that verifies also *mints* — so this raised on every real run while every
   in-process test passed, because the test environment has the key. The client now
   `read_unverified`s the claims it needs for addressing (the run id in every URL, the tenant
   id in every blob key) and the server remains the only verifier. A structural test asserts
   `read_unverified` appears in exactly two files.
2. **The liveness gate ate the end of every log.** `=== run <key> completed ===`, the
   teardown line and the cost line are all emitted from `drive_run`'s `finally`, *after* the
   final status transition — so gating `publish_log` on liveness dropped precisely the lines
   an operator reads first. The symptom was a container log that was complete except for how
   the run ended. Four operations are now deliberately exempt and enumerated in one place
   (`service.scoped_run`): status, cost, log, and nothing that touches a run's work.
3. **`GatewayLogBus.close` raced its own flusher.** It set the stop flag and flushed, while
   the background thread already held the batch and was waiting on its request; the process
   then exited and killed the daemon thread mid-request. It joins first now, for the reason
   `reaper.heartbeat_during` joins.

**A fourth bug was in the tests, and is worth recording because it presents as a hang.** A
test that uses both the `session` and `session_factory` fixtures gets two teardowns, and the
second one's `TRUNCATE` waits for ever on the first one's open transaction. Two of the
rewired files hit it. `tests/control_helpers.BorrowedSessionFactory` is the fix: lend the
test's own session rather than taking a second connection.

### The acceptance criteria, one at a time

| Criterion | Evidence |
|---|---|
| A sandbox carries neither `DATABASE_URL` nor `S3_*`; it carries a run-scoped token | `test_sandbox_credentials.py`: the control plane's environment holds all five, none comes out, and no *value* comes out under another name either. The token is minted and verified in the test, not faked |
| Hydrate, fetch/upload blobs, commit N+1, artifacts and log lines all work through the API | `test_control_gateway.py` for each operation on both transports; the Docker test for all of them at once, in a container |
| The token authorizes only that run's target and tenant | `test_control_service.py` (two real tenants; a same-tenant inconsistent scope so the tenant filter cannot be what refuses it; and **a second target of the same tenant**, which is where the first attempt at this was wrong — see below) and `test_internal_api.py` (403s, including a blob key and an artifact prefix) |
| The token is rejected once the run is no longer live | `test_control_service.py` over all three terminal statuses; `test_control_gateway.py` on both transports; and the four exemptions are themselves tested, including that a finished run still cannot commit a revision or drive its status |
| The stores are unreachable from a sandbox; the internal API takes their place on the egress bypass | Two halves, both structural: the sandbox is given no endpoint (`test_sandbox_credentials.py`, including that no value in its environment mentions `postgres` or `seaweedfs`), and they are off its network (`test_compose_stack.py`, which also asserts the API is the *only* thing on it) |
| Both thread and docker paths use the API; the existing structural tests still hold | `LocalGateway` and `HttpGateway` are two transports over one `service.py`, and `test_control_gateway.py` runs one suite against both. `build_allowlist` is untouched. The no-second-pipeline, no-repo-mount and no-GitHub-credential tests all still pass |

### What the two-axis review found, and what changed

The review ran after the suite was green and found one thing the suite could not,
plus several the prose standard asks for. All are fixed in this slice rather than
deferred.

**The real one: blob authorization was by prefix, and a prefix is the wrong
authority.** `authorize_blob_key` checked only `tenant/<id>/`, so a run could
read *or overwrite* any blob of its own tenant — including another target's
revision blobs — from a guessed or learned content hash. #30 is explicit about
this ("every blob read authorized through a Postgres row belonging to the
requesting tenant — **no serve-by-key-alone**") and #33's own criterion 3 says
"exactly that run's target", so this was a gap against both. The overwrite half
was worse than the read half: `commit_revision` confirms blobs *exist*, not what
is in them, so chosen bytes under a sibling's key would have been materialized
into that target's next hydrate. The three operations are now authorized
differently, because they leak differently:

| | Authority | Why not the others |
|---|---|---|
| read | a `file_index` row of a revision of **this run's target** | the row is what pins the read to the target the token names |
| write | the bytes must hash to the key | content addressing makes an overwrite a no-op; a prefix rule cannot see the bytes at all |
| exists | the tenant prefix | it is ingest's dedup check, asked about a key derived from content the run already holds, so the answer is not a side channel — and a row check would break dedup, whose whole job is blobs no revision references yet |

Two tests pin it at the service, both with a **second target of the same tenant**
so neither the tenant filter nor the prefix can be what refuses them. Writing
them surfaced something worth recording: a sibling target with an *identical*
tree shares every blob, because content addressing dedups per tenant — so the
fixture has to give the sibling a file only it has. Dedup is not a leak, and a
test that did not notice the difference would have been asserting the wrong
thing.

**`authorized_run` had grown a second copy of its own three checks**, which is
precisely what that module's docstring argues against ("five operations each
doing their own three checks is how one of them ends up doing two"). It is
`scoped_run` plus the liveness gate now.

**Smaller, all fixed:** `control` was unannotated at ~15 call sites while
`RunGateway` existed and was used as a type only by a test; `SessionFactory` was
still exported from the pipeline *driver*, so `control/local.py` imported a
session-factory type from it (moved to `app/db.py`, which owns the session);
`GatewayLogBus` took a `run_id` it silently discarded in favour of the gateway's
scope, where `run_pipeline` guards the same mismatch two modules away; the
ingest closure re-read `run_facts()` at every step boundary — five HTTP round
trips per run for a target config that cannot change under a live run; and the
test suite had its own copy of the service's borrow-don't-close shim.

**Two findings were accepted rather than fixed, and both are below:** the
`record_cost` exemption, and the API surface a sandbox can now reach.

### What this slice does **not** claim

- **The thread path does not exercise HTTP framing.** It reaches `service.py` in-process. That
  was a deliberate choice (one authorization decision, no event loop inside a daemon thread),
  and the mitigation is that `test_control_gateway.py` runs its whole suite through both
  transports and `test_internal_api.py` drives the routes directly. What no in-process test
  can cover is what the Docker test is for — and two of the three bugs above were found
  there, which is the honest measure of that gap's size.
- **A paused run's token stays valid.** ~~`is_live` includes `PAUSED`, deliberately: it is the
  definition the whole repository already uses (`repo.live_run_holding` turns on it) and a
  second definition of "live" would be a second thing that can be wrong. Pause destroys the
  container at once and a resume mints a new token, so the token of a paused run belongs to a
  sandbox that no longer exists — but a copy taken before the pause works until the run ends
  or the signature expires. Closing that needs a token table, which is the cost `app/auth.py`
  already declined to pay for sessions, for the same reason.~~
  **Closed on 2026-11-04 by #48 (P5-16), and without a token table.** The trade-off was
  stated as a choice between "one definition of live" and "a token that dies with its
  sandbox", and it was a false one: the gate is not asking whether the run is over, it is
  asking whether the sandbox the token was minted for is still the one doing the work.
  `is_live` still answers the first question and still includes `PAUSED` everywhere — the
  lock trio and the reaper are untouched — and a fourth field on the scope answers the
  second. `runs.sandbox_attempt` is a generation counter; `repo.pause_run` moves it on; the token
  names the attempt it was minted for; `authorized_run` compares the two. One integer on a
  row that was already being read on every call.
  Two things about the shape are worth keeping, because the first attempt at it was wrong.
  **The increment belongs at the pause, not at the resume**: the window being closed *is*
  the pause, and a run may stay paused for an hour or for ever. And **refusing a paused run
  outright does not work**: a resumed sandbox calls `run_facts` before `begin_run` has moved
  the row out of `PAUSED`, so that reading refuses the resume itself — which the suite said
  immediately, in three files. The counter has no such ordering to get wrong.
  One consequence, deliberate and documented where it happens:
  `launcher._persist_session` no longer archives the session on the way out of a pause,
  because the token it would write with has just been retired. The save at **every step
  boundary** is what covers it, and that save exists for this exact reason — a pause gives
  no warning — so what a pause now costs is still the exploration of the step it
  interrupted and no more.
  Two readings of "not running" now share one answer there, and the guard reads
  `run_status` rather than `run_state` because only the former is exempt from the gate —
  which is #50's find, and is why a normally-ending run no longer logs a warning with a
  traceback about a session it deliberately did not save. This is a behaviour change on
  the thread path that none of the three tickets asked for in those words; it is forced by
  the token retirement, and it is bounded by the per-boundary save.
- **The run-scoped token is not revocable.** Expiry is the backstop and liveness is the gate;
  between them there is no way to cut a specific token short while its run continues.
- **No real agent run.** The container test uses `QA_RUNNER=fake`, so what is proven is the
  control-plane path, not that a real agent works through it. The P4 real-agent run remains
  the only thing that proves the full image, and it predates this change.
- **A token leaked from a finished run can still forge log lines and rewrite two
  cost columns** for that run, until its signature expires. Of the three
  liveness exemptions, `record_cost` is the one that is *not* forced by
  ordering — it could be recorded control-plane-side at teardown instead of by
  the sandbox in its `finally`. It is where it is so that `drive_run`'s "every
  way out of a run records what it cost" stays in one process, and what is
  traded away is two accounting columns on a run that is already over. A
  deliberate trade, recorded as one.
- **The whole API is now reachable from a sandbox, not just `/internal`.**
  Serving the internal routes means the API sits on the sandbox network, so a
  compromised agent can reach `/auth/login` over the network — where before, the
  only things it could reach were Postgres and the object store. It has no
  credentials, its token authorizes nothing on those routes (asserted in
  `test_internal_api.py`), and there is no rate limiting in front of them. This
  is a smaller surface than a database credential and a wider one than these
  routes alone. The clean fix is a second listener — `/internal` on its own
  port, and only that port on the sandbox network — which is a deployment
  change, not a code one. **Follow-up, not done here.**
- **Not seen in a browser**, and nothing in this slice has a portal surface to see.


---

## Verified on 2026-11-04 — `#37` / P5-07 (the immutable audit log)

The change: `audit_log(id, tenant_id, actor, action, target, before, after, at)`, append-only,
written by seven control-plane mutations and read back through the enforced read path. The
acting user joins the acting tenant in `app/tenancy.py` as a second `ContextVar`, bound by
`require_auth`.

**Suite, run as `make test` runs it** (ruff clean, **1120 backend tests**, **89 frontend
tests**, all passing). New coverage: 27 tests in the new `tests/test_audit.py`, 3 more in
`test_delivery_cli.py` for the CLI's rows, plus one line added to
`test_tenant_isolation_repo.py`'s enumerated listings — the file whose standing rule
is that "a read added later is a line here", and `audit.entries` is a read added later.

**The trigger, observed on a throwaway database** rather than inferred from the suite, because
"append-only" is the one claim in this ticket that application code cannot make. `alembic
upgrade head` from zero → the two refusals → `downgrade -1` → `upgrade head` again, reading
`information_schema`, `pg_trigger` and `pg_proc` at each stop:

```
after upgrade head     table=1 trigger=1 function=1 head=b7e04c91a2d5
  UPDATE refused: (psycopg.errors.RestrictViolation) audit_log is append-only: UPDATE is not permitted (row id 1)
  DELETE refused: (psycopg.errors.RestrictViolation) audit_log is append-only: DELETE is not permitted (row id 1)
  TRUNCATE allowed, rows left=0
after downgrade -1     table=0 trigger=0 function=0 head=a3f70c2e8b91
after re-upgrade       table=1 trigger=1 function=1 head=b7e04c91a2d5
```

Three things that matters for, beyond the two refusals themselves. The downgrade drops the
**function** as well as the table — a trigger goes with its table but a function does not, so
without that line a downgrade/upgrade cycle would meet an existing function (which is also why
the revision uses `CREATE OR REPLACE`). `TRUNCATE` is **still permitted**, deliberately: the
trigger is row-level, and a statement-level one would leave the test fixture unable to reset
the table between tests, which would end with the suite not asserting this at all. And the
error arrives as `restrict_violation` rather than a bare `raise`, so a caller can tell this
refusal from a connection failure.

**What writes a row, each asserted through the surface that performs it** — an HTTP route
where there is one, the repo function where there is not:

| Mutation | Surface | Row |
|---|---|---|
| Delivery approval | `POST /targets/{id}/deliver` **and `python -m app.delivery push`** | `delivery.approve`, with the story, the branch, the `delivered_sha` and the PR URL; the CLI's row carries `via: "cli"` |
| PAT save / rotate | `PUT /targets/{id}/pat` | `pat.save`, `before`/`after` carrying the credential *state* — one action for both, because `before` is what distinguishes them |
| PAT clear | `DELETE /targets/{id}/pat` | `pat.clear` |
| Infra sync / re-sync | `POST /projects/{id}/targets` with `sync_infra` (the first sync) **and `python -m app.delivery bootstrap`** (the re-sync) | `infra.sync`, with the outcome — recorded even when the push failed, and **redacted and length-bounded**, because this is the one payload built from program output |
| Target reset | `POST /targets/{id}/reset` **and `python -m app.delivery reset`** | `target.reset`, with the branches it deleted |
| Quota change | `repo.set_tenant_caps` (no route by design) | `quota.change`, both caps on both sides |
| Prompt save | `PUT /prompts/{name}` | `prompt.save`, with the rev |

**A dry run writes no row.** `--dry-run` and `dry_run: true` touch nothing in the customer's
repo, so neither `delivery.approve` nor `target.reset` records one. The first cut *did* record
them with a `dry_run` flag, on the reasoning that an admin exercising the surface should not be
invisible; the review was right that the flag was the tell. `delivery.approve` has to mean "a
push happened", or every compliance query over it has to be filtered by hand before it can be
believed.

**The CLI is audited, and its actor is `system`.** `make deliver` binds no user, so the row
says `system` rather than naming one. "A human at a console did this and we cannot say which"
is a far better answer than silence — and the fix for the rest of it is the `--tenant` option
follow-up 20 already wants, which should grow an actor option at the same time.

Follow-up 24 is closed by the second and third rows: it asked that #37 cover
`PUT`/`DELETE /targets/{id}/pat` rather than let P5-03 grow a bespoke log line, and it does.

**The prompt save is not in #37's list, and is recorded on purpose.** [#39](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/39)
asks where a prompt revision's *actor* lives, since `prompts` records when a revision was
saved but not by whom, and asks that it be settled when #37 lands so the two do not become two
half-answers. It is settled here: a prompt steers an unattended agent against the customer's
own application, so changing one is a control-plane mutation, and the actor is an audit row
rather than a new column on `prompts`. #39's remaining scope is unaffected — it is a read
surface for the revision bodies, which this does not provide.

**Two of the mutations #37 lists are not recorded, because there is nothing to record.**
`user add/remove` has no code path in the tree at all — no route, no repo function, nothing
but the migration that seeds the single operator. An `Action` member for it would read as
covered while nothing could write it, so there is none, and
`test_the_two_mutations_with_no_surface_are_recorded_as_a_gap` fails the moment a
user-administration route or repo function appears. That is the point at which the row has to
be written. `quota change` **is** recorded, at `repo.set_tenant_caps`, even though it has no
route either: it has a code path, reachable from a console, and a mutation with no HTTP
surface is still a mutation.

**The actor is a scope, not an argument**, and it lives in `app/tenancy.py` beside the tenant
rather than in `app/audit.py`. Two reasons, the second found while writing it: the mutations
include two with no request behind them (`set_tenant_caps`, the delivery CLI), so there is
nothing to thread an argument from; and `app/auth.py` binds both, so an actor owned by the
audit module would have made the auth module import the ORM. Outside any scope it is
`SYSTEM_ACTOR` (`"system"`), which is a real answer for the CLI and a console rather than a
missing one — and `require_auth` binds it for *every* authenticated request precisely so it
can never be a stand-in for a user a route forgot to resolve.

### What the two-axis review found

Run as `/code-review` against `8b5aec3` with the work uncommitted: a Standards axis against
the repo's documented conventions plus the Fowler smell baseline, and a Spec axis against #37,
#30 and #39. **Ten findings, four of them real defects**, all fixed in the slice they
reviewed.

**The serious one: `make deliver` left no trail at all.** The audit writes were on the HTTP
routes only, and `app/delivery/__main__.py` calls `push_artifacts`, `reset_target` and
`bootstrap` directly — a path `Makefile` documents as the *only* way to deliver today
("delivering and resetting are CLI- or API-only"). So the first version of this slice could
push a commit into a customer's repo and record nothing, which is precisely the question #37
exists to answer, missed on the path an operator is most likely to use. Worse, `app/audit.py`
*claimed* the CLI was covered by `SYSTEM_ACTOR` while nothing there wrote a row. Now audited,
with three tests.

**"Infra re-sync" was not the audited path.** `infra.sync` was recorded only in
`create_target`'s `sync_infra` flag — the *first* sync. A re-sync is `python -m app.delivery
bootstrap`, which was unrecorded. The spec's word is "re-sync".

**A credential could have reached the one table nothing may delete.**
`apphub.run_bootstrap` returns `BootstrapOutcome(ok=False, output=str(exc))`, and a git failure
is built from the argv that failed — which carries the PAT in the remote URL. That went into
`infra.sync`'s `after.output` unredacted and unbounded, in direct contradiction of this
module's own "never record a credential" rule, and
`test_no_audit_row_ever_carries_the_token` did not cover the path because it exercises the PAT
routes. Now through `delivery.redact` and bounded to 2000 characters, with a test that plants
a token in a simulated git failure.

**And a latent trap the suite could not see.** Auditing the CLI meant the CLI opens its own
session, via `app.db.SessionLocal` — which points at the *developer's* `qa` database, not
`qa_test`. The three CLI mutation tests passed only because the dev database had never had
this migration applied: the write failed and the CLI's deliberate "a missing audit row must
not fail a push that already happened" swallowed it. The next `make up` would have turned them
into tests that write rows into the developer's database. `conftest._no_dev_database` now
blocks that seam as the fourth sibling of `_no_real_blob_storage`, `_no_real_kms` and
`_no_real_dns`, and `_record` re-raises `AssertionError` specifically so a guard cannot be
swallowed by its own error handling.

**Two overclaiming docstrings, which matter here more than usual**, because this slice's
docstrings are what a reader will trust about where the actor lives and how durable a row is.
`app/auth.py` said it binds `audit.current_actor`; after the actor moved to `tenancy.py` that
name does not exist, and the import two lines below contradicted it. And `app/audit.py` said
the row "commits in its own transaction" when `record` commits **the session it is handed** —
a second commit on the request's session, not an independent one. Both corrected, the second
with the constraint it implies for callers.

**Accepted rather than fixed**, each now stated where it belongs:

- **`quota.change` always records `actor: "system"`.** `repo.set_tenant_caps` is console-only,
  so nothing binds an actor; "naming the acting user" is structurally unmet for that one
  mutation rather than merely untested. It is honest (a console operator *is* not an
  authenticated user) and it becomes answerable when the tenant-admin surface arrives.
- **`tenancy.actor_scope` has no production caller** — only `require_auth`'s
  `set_current_actor` does. Kept for symmetry with `tenant_scope`, which does, and because the
  alternative is tests binding and unbinding a ContextVar by hand.
- **Immutability is partial by design.** The trigger is row-level, so `TRUNCATE` passes, and
  `ALTER TABLE ... DISABLE TRIGGER` needs only table ownership. #37's "never updated or
  deleted" is a stronger claim than the database enforces; the gap is the test fixture's
  reset, and closing it would end with the suite unable to assert immutability at all.
- **`prompt.save` is beyond #37's enumerated list.** Deliberate and user-approved before
  implementation, and it closes #39's actor question rather than leaving it for a third
  ticket. Recorded here as added behaviour so the next reader knows it was a decision.

The smaller Standards findings — an unused `actor=` hook on `record` (deleted; the scope *is*
the design), `was` as a variable name, a duplicated credential-state dict, `__all__` splitting
an import block, `AuditEntryOut.action` typed `str` where `Action` exists, and an unbounded
`limit` on `GET /audit` — were all applied. The five near-identical `audit.record` call sites
were **left alone**: each records a different payload, and collapsing them behind a helper
would hide what each mutation actually writes, which is the thing a reader of those routes
most needs to see.


### What is covered only by the suite

- **No live stack, no browser, no portal surface.** `GET /audit` has been exercised only by
  `TestClient`. There is no Audit page, so nothing a customer can read — the trail is
  queryable by an admin over HTTP and by SQL, and that is all. P5-04's lesson was that a
  route missing from both proxy lists is invisible in the real app while the frontend suite
  passes; `/audit` has not been checked against either proxy list, and a portal page added
  later must check them first.
- **The seven mutations are driven against fakes.** Delivery and reset are stubbed
  (`monkeypatch` over `push_artifacts` / `reset_target`), the bootstrap runner returns a
  canned success, the PAT validator accepts any token and the wrapper is `LocalKeyWrapper`.
  What is proven is that each route records what it did; what is not proven is any of those
  routes against a real remote — which is the same standing gap P5-03 and P5-05 record.
- **`before`/`after` are asserted per mutation, not schema-checked.** They are free-form
  JSON by design (what is worth recording differs per action), so nothing structurally
  prevents a later action from writing a shape no reader expects.

---

## Verified on 2026-11-04 — follow-ups 2 and 21 (the credential pair)

Not a ticket. Two follow-ups this record already carried, taken together because they compound:
the missing `Secure` flag (item 2, which this file called "the highest-value item in the list")
and `QA_SECRET_KEY` doing double duty as the key that decrypts every stored customer PAT
(item 21). They were the only items on the list where the gap was live in a deployment rather
than theoretical, and the second is why the first mattered more than it looked: a leak of that
one variable forged any user's session **and** opened every customer's GitHub credential.

**Suite, run as `make test` runs it** (ruff clean, **1148 backend tests**, **89
frontend tests** — unchanged, this slice has no frontend — all passing). New coverage: 14 tests
in the new `tests/test_deployment_env.py`, 4 in `test_auth.py` for the flag, 9 in
`test_envelope.py` for the key (three of them added by the review below), and one more entry in
`test_sandbox_credentials.py`'s `FORBIDDEN` list, which is parametrized over several of its
assertions.

**One signal, defaulting to the safe side.** The repo had no notion of dev versus deployment,
and both fixes need one: `Secure` has to be off for a dev stack on plain HTTP, and the local
envelope key has to exist offline. `config.is_dev_deployment()` reads `QA_ENV`, and
**`QA_ENV` defaults to `prod`** — only the exact string `dev` opts out, so `devv`, `staging`
and `""` are all deployments. The asymmetry is the fix applied to itself: item 21's complaint
was a fallback nothing warned about, so here the convenient branch is the one you have to ask
for by name. `docker-compose.yml` asks for it, and so does `tests/conftest.py` — explicitly,
because httpx will not store a `Secure` cookie received over `http://testserver` and every
login in the suite would otherwise hand back an empty jar.

**Follow-up 2.** Both cookies now carry `Secure` outside development: the access cookie, the
refresh cookie, **the renewed access cookie from `/auth/refresh`**, and **both deletes in
`clear_session_cookies`**. The renewed cookie is the one a narrower fix
would have missed: a flag set at login but not at refresh protects only the first fifteen
minutes of a session. The deletes are a smaller point, and the first draft of this section got
the reason wrong — a browser keys cookie *identity* on name, domain and path, not on `Secure`,
so a delete matches either way. They carry it so the expiring `Set-Cookie` does not itself
travel in clear, and so the contract has no exception to remember. The attribute that genuinely
must match is the refresh cookie's `Path=/auth`, which `clear_session_cookies` already repeats. Asserted on the
`Set-Cookie` headers rather than through the client's jar: the jar is what stores a cookie,
and the flag is an instruction about when to send it.

**Follow-up 21.** `QA_ENVELOPE_KEY` is now the local wrapper's key and **`app/envelope.py` no
longer reads `QA_SECRET_KEY` at all**. Three refusals go with it, because the separation is
only real if the fallbacks are:

* a deployment with neither `QA_KMS_KEY_ID` nor `QA_ENVELOPE_KEY` **does not start**. Falling
  back to a constant published in `envelope.py` would be strictly worse than the arrangement
  being fixed, since `QA_SECRET_KEY` was at least secret;
* the two keys set to the *same value* is refused everywhere, development included. It is
  item 21 reintroduced by hand and the likeliest way to satisfy this check by copying a line
  in a deployment config, and the only other place it would be discovered is an incident;
* `QA_ENV=dev` falls back to `DEV_ENVELOPE_KEY`, a constant of its own. A dev fallback that
  read `QA_SECRET_KEY` would have left the dev stack in exactly the arrangement being fixed
  and made the whole change real only where somebody had already set the new variable.

The behavioural proof is the one item 21 asked for, stated as the thing that was broken: a
seal taken with one `QA_SECRET_KEY`, the variable rotated, and the seal still opens.

**`QA_ENVELOPE_KEY` joins `FORBIDDEN`** in `test_sandbox_credentials.py` — the list applied to
every sandbox environment *and* every compose service. A sandbox holds sealed ciphertext it can
do nothing with, which is the property the envelope buys, and this key is precisely what would
turn that back into a readable credential. It is absent from compose for the same reason
`QA_SECRET_KEY` is: a dev stack needs no value, and a deployment supplies it through its own
secret mechanism rather than a file in this repository.

**Observed against a real `uvicorn` boot, not inferred from `TestClient`**, because "refuses to
start" is a claim about a process and the suite asserts it through a lifespan:

```
no QA_ENV, no QA_ENVELOPE_KEY, no QA_KMS_KEY_ID
  CredentialConfigError: no key is configured to protect stored customer credentials...
  ERROR:    Application startup failed. Exiting.          exit 3
QA_ENVELOPE_KEY set, no KMS
  stored credentials are protected by: local (in-process key; not a production configuration)
  INFO:     Application startup complete.
QA_ENVELOPE_KEY == QA_SECRET_KEY
  CredentialConfigError: ...must not be the same value    exit 3
QA_ENV=dev, nothing else
  INFO:     Application startup complete.                 (no warning)
```

**And that boot found the one real defect in this slice.** The startup line was written at
`INFO`, and the API process installs no logging configuration at all — uvicorn configures its
own loggers and leaves the root logger without a handler, so an `app.*` record below `WARNING`
is dropped before it reaches a terminal. The line whose entire purpose is that *a deployment
running the in-process key can be seen to be running it* printed nothing, in exactly the
deployment it is about, while its test passed: `caplog` installs a handler, so the suite
structurally could not see this. It is now `WARNING` when a deployment is on the local wrapper
and `INFO` in development — the honest levels anyway, and `KeyWrapper.production` carries the
distinction rather than the caller matching on `describe`'s prose. The same oversight applies
to every other `logger.info` in this process, which is **follow-up 43** and not fixed here.

**So the narrow claim, stated exactly.** What a deployment is now guaranteed to see is the
*warning*: that this process is storing customer PATs under a key in its own process. A
deployment on a real KMS logs its line at `INFO` and will therefore see **nothing** until
follow-up 43 is fixed — so "`describe` says which wrapper was built" is true of the case that
matters and not yet of the other one. That is the weaker claim and the correct one; the review
caught this section asserting the stronger.

### What the two-axis review found

Run as `/code-review` against `b8a3971` with the work uncommitted: a Standards axis against the
repo's conventions plus the Fowler smell baseline, and a Spec axis against follow-ups 2 and 21
as `b8a3971` stated them. **One real defect, and it was this slice's own central claim.**

**The equal-keys refusal did not refuse the case it was most likely to meet.** The guard
compared `QA_ENVELOPE_KEY` against `os.environ.get("QA_SECRET_KEY", "")`, while `app/auth.py`
resolved the same variable with a *real* default, `dev-secret-change-me`. So with
`QA_SECRET_KEY` unset — every dev stack, and any deployment that forgot it —
`QA_ENVELOPE_KEY=dev-secret-change-me` meant the two keys were genuinely identical, and the
guard compared one of them to the empty string and allowed it. That is follow-up 21
reintroduced, inside its own fix, in the one configuration this record, `envelope.py`'s
docstring and `.env.example` all said was refused. Reproduced by hand before fixing, because a
guard that refuses the wrong input is worse than no guard: it is a guard somebody trusts.

The cause was not the comparison but the arrangement behind it. **Three modules each re-derived
these keys, with two different defaults between them** — `auth.py`, `run_token.py` and the new
line in `envelope.py` — which is the "one place that knows a thing" rule broken in the most
expensive place in the tree. `config.secret_key()` and `config.run_token_key()` are now that
one place, both older readers delegate to them, and the guard compares against the keys that
are **in effect** rather than against raw variables. The second finding fell out of the same
move: `QA_ENVELOPE_KEY == QA_RUN_TOKEN_KEY` is the same smell and was unrefused. Both are now
refused, by name, with three tests — two of which fail on the old code.

**The record was also wrong twice, which matters here because the record is the deliverable.**
It justified `Secure` on the two cookie *deletes* by saying a delete must match the cookie it
replaces "on every attribute the browser keys on" — true of `Path`, which is why
`clear_session_cookies` repeats it, and false of `Secure`, which is not part of cookie
identity. And it claimed `describe` lets a deployment see which wrapper was built, when a KMS
deployment logs that at `INFO` and follow-up 43 says this process drops `INFO`. Both now state
the narrower true thing. The Spec axis also found that this slice owed §Decisions its rows and
had argued its choices only in prose; six rows are now there.

Smaller Standards items, all applied: `log_credential_config` renamed to
`check_credential_config` (its first job is to stop the process, and the name hid that),
`verify_credential_config` returning the wrapper instead of a two-tuple of its own fields, an
inlined single-caller `config.deployment_env()`, a `promptPath` helper for the encode dance
`api.js` had three times, `savedAt` renamed `savedLabel` (it returns "shipped default", not a
time), a dead exported `hasChanges` deleted, and a `docker-compose.yml` comment whose "It" had
two antecedents.

**What this does not claim.** `Secure` has been asserted on response headers under `TestClient`
and never against a real browser over real TLS, and the envelope's production path is still
`StubKms` — no real KMS key has ever wrapped anything. The fix moves the key out of the wrong
variable; it does not make `QA_KMS_KEY_ID` set anywhere, which remains the thing a real
deployment must do. There is also **no migration**: changing the local wrapper's key means
every PAT already sealed under `QA_SECRET_KEY` in a dev database stops decrypting and must be
re-saved. `decrypt_pat` fails loud (`CredentialError`), so it surfaces as a clear refusal
rather than as corruption — and it is item 21's own cost, paid once, deliberately, instead of
indefinitely.

---

## Verified on 2026-11-04 — `#39` (the prompt history read surface)

The change: `prompt_store.history` gains a type and a timestamp, `GET /prompts/{name:path}/history`
exposes it, and the portal's Prompts panel shows a prompt's revisions with a diff. P5-06 built
the versioning and the run recording and left the "so that I can **see what changed and when**"
half of #30's story 24 with no surface at all — the rows were append-only and carried
`created_at`, `history()` was called by nothing outside the tests, and `ResolvedPrompt` dropped
the timestamp, so even a caller that wanted one could not get it through the type.

**Suite** (ruff clean, **1157 backend tests**, **102 frontend tests**, all
passing). New coverage: 5 tests in `test_agent_prompts.py` for the read path, 4 in
`test_api.py` for the route, 7 in the new `web/src/diff.test.js`, and 6 in `Settings.test.jsx`
for the panel.

**`PromptRevision`, not a widened `ResolvedPrompt`.** #39 left the choice open and the ticket's
own reasoning decides it: only one of the two is ever sent to an agent. Widening the first
would put a timestamp nothing renders on the type the runner consumes, and — the reason that
matters — would let a historical revision be passed wherever the live prompt is expected, which
is how a run comes to be given revision 2 of a prompt it recorded as revision 5.

**`created_at` is nullable, and that is the fourth acceptance criterion's trap.** A tenant who
has never overridden a prompt has **no rows**, so the obvious `history()` answers an empty
tuple — a page told "no history" about a prompt whose current body it is displaying. It reports
the shipped default at `SEED_REV` instead, exactly as `current_all` does, **without seeding
it**: this is a GET's path and a read that wrote would have no transaction of its own to commit
with, which is the bug `read_prompts` already carries a paragraph about. Those bytes became the
tenant's at no particular moment, so the timestamp is `None` rather than "now" — a date that
changed on every page load would be an invented fact in the one surface whose job is to say
when things changed. The portal renders it as "shipped default".

**An unknown name is a 404**, the answer the `PUT` gives. An empty list would read as "this
prompt has never been edited", which is a different statement and a wrong one.

**Both proxy lists were checked first, per P5-04's lesson, and need no entry.** `/prompts` is
already in `docker/nginx.conf` and `web/vite.config.js`, both of which match on the first path
segment, so the sub-path is forwarded by what is already there. `test_api_proxy_paths.py`
asserts first segments and stays green on its own terms — which means it would *not* have
caught a genuinely new prefix here, and the check was done by reading the two configs.

**The diff is forty lines of our own, not a dependency.** "What changed" is a diff question and
a customer comparing two bodies by eye is doing the work the panel exists to do — but the
portal has no other use for a diff, so a library would be a build-size and supply-chain cost
carried for one caller. `web/src/diff.js` is the textbook LCS table over lines; prompt bodies
are a few dozen lines and it runs on a click. Its own module with its own tests, including the
two cases that make a line diff wrong in practice: a trailing newline must not read as a
changed last line (prompt bodies are files and all end with one), and a blank line *inside* a
body must still be a line, because it is a paragraph break in a prompt.

**The history is fetched when it is opened, not with the page.** Three prompts on screen and
one request each on load would pull every superseded body of all of them, and a prompt body is
the largest column in this schema. Revisions are listed newest first although the API answers
oldest first — "what did I just change" is the question a customer opens this with — while each
diff still compares against the *previous* revision, so an entry answers "what did this edit
change". The first revision has nothing before it, so it shows its body rather than a diff.

**A failed fetch is reported, never swallowed.** P5-04's quota panel shipped invisible because
it degraded to nothing with 84 tests passing; a `.catch` that set empty state here would do the
same thing to this one.

### What is covered only by the suite

- **No browser.** The panel, the revision list and the diff have been exercised in jsdom
  alone. That is the gap P5-04's lesson is specifically about, and the two slices in this phase
  that were checked in a real browser each found something the suite could not see.
- **The route has been driven by `TestClient` only**, like `GET /audit` before it.
- **Tenant scoping is inherited, and asserted.** `Prompt` is `TenantOwned`, so the read guard
  filters the history query; there is a behavioural test that one tenant's revisions are
  invisible to another, which is #39's third criterion.

### What #39 asked and this does not do

- **No rollback.** "Restore revision 2" is append-only-friendly — it saves revision 2's body as
  revision 5 — and the ticket named it as the obvious next ask, out of scope unless wanted. The
  endpoint shape does not make it awkward: it would be a `POST` beside this `GET`.
- **The actor question was already settled**, by #37 rather than here: a prompt save is a
  control-plane mutation, so `prompt.save` is an audit row and the actor is not a new column on
  `prompts`. This surface shows *what* changed and *when*; *who* is a join away in `audit_log`
  and is deliberately not shown on the page, which would be a second read surface for a second
  table.

---

54. **The object store holds 532 objects no purge will ever name.** Found by UAT 2 while
    listing the bucket by tenant prefix. `tests/test_docker_sandbox.py` takes a `real_store`
    fixture — the actual SeaweedFS of the dev stack — and its `@pytest.mark.docker` tests run
    whenever the daemon is usable rather than skipping, so **every** local `make ci-test` run
    writes real objects into it. The fixtures then truncate the rows. What is left is objects
    belonging to runs that no longer exist, under a tenant that still does, so
    `accounts.purge` cannot reach them (it walks rows) and `artifacts.rekey` cannot either.
    Harmless on a dev stack and a trap on any other reading: **a store listing is not an
    inventory.** The honest options are a mark-and-sweep against `artifacts` + `file_index`
    (which DESIGN.md §9 already describes and which nothing implements), or a test fixture
    that cleans up after itself. Neither is ticketed.
55. **A removed user keeps their access cookie for up to 15 minutes.** The residue of the UAT
    3 finding, after the refresh path was fixed. Demonstrated on the fixed build: a user
    removed seconds earlier, holding an unexpired access cookie, still got `POST /users` → 201
    and created an admin account. Closing it needs `require_auth` to read the row on **every
    request**, which is exactly the round trip `app/auth.py` declined, so this is a decision
    rather than an oversight. Four options with their costs — read per request; shorten the
    access cookie; a small revocation list bounded by `ACCESS_MAX_AGE`; or accept it and say
    so where a reader will look — are written up in full in
    **[issue #56](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/56)**,
    which is where this is now tracked. (Note the coincidence: GitHub issue #56 is this
    item, follow-up **55**; follow-up 56 below is the prompt-timestamp one.)

    **Closed 2026-11-05 — option 3, the revocation list.** `revoked_users` is a
    tenant-owned table of user ids removed within `ACCESS_MAX_AGE`; `accounts.remove_user`
    writes a row in the same transaction as the `DELETE`, and `require_auth` reads it on
    every authenticated request and answers the same bare 401 a missing cookie gets. So a
    removal takes effect on the removed user's **next request**, not at their cookie's
    expiry. The decision and the three rejected options are in
    `docs/adr/0004-a-removal-revokes-the-session-it-leaves-behind.md` and restated where
    `app/auth.py` makes the stateless argument, in the removal's own terms rather than as
    "a role change takes effect at next login".

    What it cost, and what it did not: one read per authenticated request, of a table that
    holds one row per removal — not of `users`, so the access cookie is still
    claim-carrying and `app/auth.py`'s argument survives with one named exception.
    `revocation.revoke` deletes the expired rows as it writes the next; that prune is an ORM
    bulk delete and so tenant-scoped like every other one, which means each tenant's
    removals trim that tenant's list and a tenant that removes somebody once keeps that row
    until it removes somebody again. Nothing reads an expired row either way — `is_revoked`
    bounds the question by the window rather than trusting the prune, which is also what
    stops an unpruned row from locking out an id. The first version of this paragraph
    claimed the table held "the last fifteen minutes and nothing else", which the guard's
    coverage of bulk writes makes false; `tests/test_revocation.py` asserts what it really
    bounds.

    Three residues, each by decision and each written down at the ADR: a **demotion** still
    waits for the next refresh (a revocation means "no access", so using it for a downgrade
    would log out somebody who still works here); a **purged tenant's** user keeps a
    verifying cookie for up to fifteen minutes, because `revoked_users` is tenant-owned and
    the purge deletes it too — with nothing left to read or write, every read filtered to a
    tenant with no rows and every write failing its `tenant_id` FK; and a **stolen cookie**
    is still worth the rest of its fifteen minutes, because this revokes a user rather than
    a token.

    **Covered by the suite, not by a live stack.** `tests/test_auth.py` and
    `tests/test_api_users.py` assert the existing access cookie stops working — including
    UAT 3's own sequence, the admin who removes themselves and then tries to create another
    admin, over HTTP with two cookie jars — and `tests/test_revocation.py` covers the
    window, the self-pruning and the tenant filter (user ids collide across tenants, so an
    unfiltered list would log out an unrelated customer). What has **not** been observed is
    the thing UAT 3 observed: this has not been re-run against the live stack with real
    cookies. That is the same gap this record names everywhere else, and it is the honest
    status of the fix.
56. **A seeded prompt revision 1 renders as a date somebody saved.** Found by #36's
    verification. A shipped default is not a row until something makes it one, and
    `prompt_store._seed` materialises rev 1 at the moment the *first override* is saved — so
    both revisions come back with the same `created_at`, to the microsecond, and rev 1's is
    when it became this tenant's row rather than when those bytes shipped. `#39`'s
    `savedLabel` renders "shipped default" only for a `null` `created_at`, which is the
    not-yet-a-row case, so a seeded rev 1 shows a date. Not a correctness bug — the row really
    was created then — but the Prompts panel will tell a customer somebody edited a prompt
    when nobody did. The fix is a label, and which label is a product question.

### The sweep (2026-11-05, UAT 3's closeout criterion)

All 56 items, each either closed, ticketed, or surviving with its reason. Closed items keep
their text above with a dated note rather than being deleted, because the reasoning is the
part worth keeping.

**Closed during the phase** — 2, 6, 9, 13, 15, 21, 27, 27b, 28, 29, 38, 48, 49, 50, 51, 52,
53, and 4 (on the last day). Each carries a dated note at its own entry naming what closed it.

**Surviving, and why each one is not being closed now:**

| # | Survives because |
|---|---|
| 1, 55 | The stateless-session decision. 1 is the general statement; **55 is closed** (2026-11-05, issue #56 — the `revoked_users` revocation list; see its entry and `docs/adr/0004`). What survives of 1 is a *stolen* token, which nothing revokes |
| 3 | Artifact URLs bypass the refresh dance. Real, and bounded: a 401 there is a reload, not data loss |
| 5 | One pointless `POST /auth/refresh` on a cold login page. Costs a request |
| 7, 8 | The portal cannot show or discover your tenant slug. A usability gap that multi-tenancy created and nothing has needed yet |
| 10 | Review suggestions **declined** — decisions, recorded so they are not mistaken for oversights |
| 11 | A test seam read off the module. Deliberate |
| 12 | `SPEC-P5-multi-tenancy.md` is still a zero-byte file; the issue is the spec of record. Cosmetic, and fixing it means deciding which is canonical |
| 14 | The README still says P4's closeout is pending. **Fixed in this closeout** (see below) |
| 16, 17, 18 | The three documented holes in the tenant guard: the identity map, a lazy load off a bypassed row, and raw SQL. Each is a property of SQLAlchemy rather than of this code, each is stated where the guard is installed, and no call site relies on any of them |
| 19 | One round trip per reaped run. A cost, measured and accepted |
| 20 | The delivery CLI can only deliver tenant 1's targets — `--tenant` resolves a slug now, but `make deliver` has no tenant. **The largest remaining single-tenant assumption in the tree** |
| 22, 23, 24, 25, 26 | The credential lifecycle: no re-wrap tooling, a revoked token reads `valid` until used, no audit row for a PAT save, nothing delivers before a PAT is saved, the authoring account is reported once. All real, all P6-shaped |
| 30, 31 | A lowered cap does not bound a live run, and the quota month is UTC with nothing saying so |
| 32, 33, 34 | `/internal` on the main listener, `record_cost`'s exemption, and no request budget on the internal API. Accepted trade-offs with their reasoning at the call sites |
| 35, 36, 37, 39 | The audit log has no customer-facing read, no cursor, no pruning, and a column one rename from being too short |
| 40 | A *token* still cannot be revoked — the same decision as 1. A **user** can be, since 55 closed: `revoked_users` ends every session a removed user holds, which is the case that mattered |
| 41 | The CLI and console say `system`, because they bind no user. Honest, and #46 relies on it |
| 42 | `audit.record` commits the session it is given. Stated at every call site |
| 43, 44 | Logging below WARNING, and a `QA_ENV` typo being silent in the safe direction |
| 45, 46, 47 | Prompt history reads every revision with no paging, has been seen only by jsdom, and has no rollback by decision |
| 54 | 532 orphaned objects in the dev store, and the mark-and-sweep DESIGN.md §9 describes is unbuilt |
| 56 | A seeded prompt rev 1 shows a date. The fix is a label |

**Nothing on that list blocks P5.** Two items are sharp enough to name here rather than leave
in a table: **55**, the security residue tracked as
[issue #56](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/56) and
**closed on 2026-11-05** by the revocation list (its entry above records the decision, its
cost and its three residues), and
**20**, which is the single-tenant assumption still sitting in the delivery CLI — a multi-tenant control plane whose `make deliver` can only ever reach one
customer.


## Verified on 2026-11-04 — P5-18 / #52 (UAT 1: fail-closed against live tenants)

The first of P5's three UAT checkpoints, and the first evidence in this phase that
**fail-closed holds against a running stack rather than against a fixture.** The ticket's
own reason for existing is that the suite structurally cannot gather it: every test in it
reads as one tenant at a time, and the thing being proved is what happens when **no** tenant
is acting — a test that binds a scope to assert the unscoped path fails has already lost the
condition it is testing.

Against the live compose stack (`make up`, api rebuilt from this tree), on the **dev
database, which holds real data** — a project, the `saucedemo` target, 9 runs, 4 revisions
and 25 artifacts from P4's walkthrough.

**Four migrations met that data for the first time.** The database was at `f1a62c90d4e7`
(P5-04's default caps); the entrypoint's `alembic upgrade head` applied `a3f70c2e8b91`
(prompts), `b7e04c91a2d5` (audit_log and its append-only trigger), `c4f91b280e36`
(`runs.sandbox_attempt`) and `d5e82a013f47` (`purge_log`). Checked afterwards: every row
still there (1 tenant, 1 user, 1 project, 1 target, 9 runs, 4 revisions, 25 artifacts), the
trigger present, both new columns present. Additive migrations are the low-risk kind, but
four unapplied ones meeting real rows is still worth observing rather than assuming.

**Two tenants, created without raw SQL** — the thing follow-up 6 blocked until #46:

```
$ docker compose exec api python -m app.accounts create-tenant \
      --name "Acme Ltd" --slug acme --admin boss@acme.test
tenant: Acme Ltd (log in with slug 'acme')
admin: boss@acme.test
password: ...
```

…and the same for `Globex Inc` / `globex`. Both arrived **bounded** at 3 concurrent / 500
monthly from the column's server default, which is the first evidence for #35's
"a tenant arrives bounded" on a path that is neither the migration seed nor raw SQL — the
two paths that argument was written about. Each wrote one `user.add` audit row against its
own new tenant with `system` as the actor, as the CLI binds no user.

Each tenant then logged in over HTTP and created a project and a target of its own
(`acme-app`, `globex-app`, both at revision 1 in blob storage).

**Every tenant is refused every other tenant's rows, in every direction.** Three cookie
jars, `curl`, HTTP status only:

| Request | as tenant 1 | as `acme` | as `globex` |
|---|---|---|---|
| `GET /projects` | `['P4 walkthrough']` | `['acme-project']` | `['globex-project']` |
| `GET /targets` | `['saucedemo']` | `['acme-app']` | `['globex-app']` |
| `GET /runs` | 9 rows | 0 | 0 |
| `GET /targets/1/revisions` (tenant 1's) | 200 | **404** | **404** |
| `GET /runs/1`, `GET /artifacts/1/content` | 200 | **404** | **404** |
| `GET /targets/4/revisions` (`acme`'s) | **404** | 200 | **404** |
| `GET /targets/5/revisions` (`globex`'s) | **404** | **404** | 200 |

The reverse direction matters as much as the forward one, and is the half a single-tenant
fixture cannot show: tenant 1 is the seeded operator and an admin, and it is refused both new
tenants' rows just the same.

**A route that forgot its authentication dependency fails closed.** `AuthDep` is on the
whole router (`app/api.py`), so the way to forget it is to mount a route on a router that
does not carry it — which is exactly what a new feature router looks like if nobody notices.
A temporary `GET /uat-unguarded-projects` was added on a bare `APIRouter`, the api image
rebuilt, and the route called **with no cookie**:

```
HTTP 500
  File "/app/app/tenancy.py", line 368, in _filter_by_tenant
    tenant_id = current_tenant_id()
  File "/app/app/tenancy.py", line 113, in current_tenant_id
    raise NoTenantScope(
app.tenancy.NoTenantScope: no tenant scope is active, so there is no tenant to act as.
A request resolves one from the authenticated user (auth.require_auth -- check the route
has its auth dependency); ...
```

Not a leak and not a silent default: a 500 raised **inside the read guard**, with a message
that names the probable cause and the dependency to check. Before #43 this route would have
answered **200 with tenant 1's projects**, which is the whole of story 6's "a missing filter
is a bug that fails closed rather than a leak". The probe was then reverted, the image
rebuilt, and the path confirmed 404.

**An ORM `UPDATE` and an ORM `DELETE` outside any tenant scope are refused** (#44's
guarantee, observed rather than asserted). Run inside the api container with no
`tenant_scope()` anywhere in the process, aimed at tenant 2's throwaway project rather than
tenant 1's real data — the guard is supposed to raise before touching anything, so which row
is named cannot matter, and if it did the row lost is one this UAT created minutes earlier:

```
RESOLVER: raised NoTenantScope
UPDATE:   refused, NoTenantScope      # update(Project).where(id==3).values(name="stolen")
DELETE:   refused, NoTenantScope      # delete(Project).where(id==3)
AFTER:    [(3, 'acme-project')]       # read back inside tenant_scope(2)
```

**The reaper still sees every tenant across a real timer tick.** A crashed run cannot be
produced through the API — a crash *is* a run whose process stopped renewing its lease — so
one was seeded per tenant with SQL, recorded here verbatim in intent: a live run holding its
target's lock with a lease that lapsed an hour ago, for tenant 2 and tenant 3, with tenant
1's rows untouched. Then one real 30-second tick:

```
api-1  | reaped 2 run(s) with expired leases: [11, 12]
```

Run 11 is tenant 2's and run 12 is tenant 3's; both ended `failed` with
`lease expired (reaped)` and `app_locks` went to 0. **Neither belongs to the default
tenant**, which is what makes this an observation rather than a formality: a sweep that
quietly resolved to tenant 1 — the failure `reaper._for_each_tenant` exists to prevent —
would have reaped neither and reported a clean pass.

**The bypass allowlist: the criterion as written does not pass, and here is why.** It asked
that the list be "no larger than it was before the wave". It is larger by one. Before wave 1
(`e24c9cf`) it held three entries; it now holds four:

| Entry | Why it is allowed to cross the boundary |
|---|---|
| `repo: get_user_for_login` | Login resolves *which* tenant is acting, so it cannot already be scoped. Scoped by the slug the caller typed instead. |
| `repo: get_run_across_tenants` | The cross-tenant primary-key read itself, used by the reaper entry below. |
| `reaper: _tenant_of` | Resolves a reaped run's tenant in order to *open* its scope, so it cannot already be inside it. |
| `bus: prune_run_logs` | **The new one.** |

The new entry arrived in `b8fb7a5` — #44 itself, the commit that put ORM `UPDATE`/`DELETE`
under the guard. It is not a new bypass: the log retention sweep was *already* a cross-tenant
bulk delete, and it needed no opt-out only because the guard did not reach writes. Once it
did, the sweep had to declare itself. So the honest reading is that **the set of things
crossing the tenant boundary did not grow; the set of things that must say so grew by one,
because the guard got wider** — and the alternative was to leave deletes unguarded, which is
what #44 existed to fix. Wave 3 added nothing: #47's purge deliberately runs inside
`tenant_scope` and takes no bypass at all, which is why the list is unchanged after five more
tickets.

`make ci-test` green: ruff clean, **1307 backend tests, 115 frontend tests.**

**What this does not prove.** No run was *dispatched through the portal* during UAT 1 — the
stack came up with `QA_RUNNER=fake` — so nothing here says anything about a real agent. That
is UAT 2 (#53). The two new tenants and their rows were left in place for it, and for UAT 3
(#54) to offboard.

**A correction, and a thing worth knowing about the suite.** An earlier draft of this section
said no run executed at all. That was wrong: `tests/test_docker_sandbox.py` takes a
`real_store` fixture — the actual SeaweedFS of this stack, not `FakeStorage` — and its
`@pytest.mark.docker` tests run whenever the daemon is usable rather than skipping. Docker was
up for this whole session, so **every `make ci-test` run really started containers and really
wrote objects into the dev store.** Sixteen such runs are visible in SeaweedFS as
`tenant/1/runs/20261104-1[345]*-demo-<uuid>-*/` (5 objects each, 80 in all), which is one per
full-suite run through the day.

That is by design and not a defect, but two consequences follow. It means
`make ci-test-docker`'s container coverage was *already* being exercised by `make ci-test` on
this machine, which is the honest reading of #53's last criterion. And it means the suite
leaves real objects behind in the dev store whose database rows the fixtures then truncate —
orphans that no purge will ever name, because the tenant they belonged to still exists and
the runs do not. Harmless here, and worth knowing before anyone reads a store listing as
inventory.


## Verified on 2026-11-04 — P5-19 / #53 (UAT 2: a real agent run over the HTTP seam)

P5's missing counterpart to #16 (P3-09) and #28 (P4-10): **a real `QA_RUNNER=claude` run, in a
real container, driven end to end over the HTTP control-plane seam, paused and resumed by
hand.** P4-10 proved a real run in a real container; it could not prove this, because the HTTP
seam did not exist then.

Run 13, on tenant 2 (`acme`)'s own target rather than tenant 1's — so the phase's real
P4-walkthrough evidence was not written into. `QA_RUNNER=claude`, `QA_SANDBOX=docker`,
`QA_SPEND_BUDGET_USD=10`, api rebuilt from this tree.

**It completed.** All five steps, **$4.01** and **428 sandbox-seconds**, no error. From a
110-byte user story it produced an 11 KB test plan and three spec files (~17 tests) under
`tests/login-valid-user/`, and the log is unmistakably a real agent at work:

```
[explore]  I ran all 17 scenarios from the plan by hand in the browser, starting from
           `seed.spec.ts` in `chromium`...
[explore]  Unexpected result: the locked-out login is rejected, yet a
           `session-username=locked_out_user` cookie...
[generate] I generated 17 tests in 3 files under `tests/login-valid-user/`...
[heal]     After healing, all 17 tests pass on Chromium; the last two runs were both 17/17.
```

It committed **three revisions** over the HTTP seam — 3, 4 and 5 on target 4, parent-chained,
each authored `run:20261104-170707-acme-app-3aa7ad` and `produced_by_run_id = 13`, growing the
tree from 8 files to 11 — and collected **8 artifacts**, every one of them keyed
`tenant/2/runs/<run_key>/...`. That last fact also closes #42's "not proven against
SeaweedFS": the new key shape was written by a real run into the real store.

**The sandbox holds no credentials, observed on the running container.** Not read off the
compose file — `docker inspect` on the live container, environment variable *names* only:

```
ANTHROPIC_API_KEY  CLAUDE_CONFIG_DIR  HTTPS_PROXY  NO_PROXY  QA_APP
QA_CONTROL_PLANE_URL  QA_RUN_ID  QA_RUN_TOKEN  QA_RUNNER  QA_RUNS_DIR  ...
```

and each forbidden name checked individually: `DATABASE_URL` absent, `S3_ENDPOINT` absent,
`S3_ACCESS_KEY` absent, `S3_SECRET_KEY` absent, `S3_BUCKET` absent, `QA_SECRET_KEY` absent,
`QA_ENVELOPE_KEY` absent, `QA_RUN_TOKEN_KEY` absent.

**And the stores are off its network**, which is the half a variable list cannot show. The
container is attached to `qa-sandbox` alone, and from *inside* it:

```
postgres    -> (no DNS answer)
seaweedfs   -> (no DNS answer)
api         -> 172.18.0.2
```

The API really is the only thing a run can resolve.

**The pause, and #48's guarantee, against the live API.** Paused mid-`explore` through the
portal route. The run went to `paused`, `sandbox_handle` was cleared, and the container was
destroyed. The token copied from the container's environment *before* the pause then:

```
HTTP 403
{"detail":"run 13 is no longer on attempt 1; its sandbox is gone and this token
  no longer authorizes anything"}
```

Both tokens decoded through `run_token.read_unverified`, which is the only reader a sandbox
has:

| token | scope it carries | against the live API |
|---|---|---|
| copied before the pause | `RunScope(run_id=13, target_id=4, tenant_id=2, sandbox_attempt=1)` | **403** |
| the resumed sandbox's | `RunScope(run_id=13, target_id=4, tenant_id=2, sandbox_attempt=2)` | **200** |

Same run, same target, same tenant; one claim apart. Before #48 the first of those was a 200
for the whole length of the pause, which is the window review item 51 described and this is
the observation of it being shut. The resumed token on *another* run's path is 403 too.
`runs.sandbox_attempt` on the row read 2.

**The resume got its session back**, which is the thing P4 built the per-boundary archive for:

```
=== session: restored; the agent remembers what it explored ===
=== hydrate: worktree built from revision 3 (8 files) ===
=== run 20261104-170707-acme-app-3aa7ad started (begin at explore) ===
```

Re-hydrated from **revision 3** — the revision the interrupted attempt had already committed —
and restarted at `explore`, the step the pause interrupted, not at the beginning.

**The liveness exemptions, observed rather than reasoned about.** The last two lines in
`run_log` are

```
187 | === run 20261104-170707-acme-app-3aa7ad completed ===
188 | === teardown: worktree removed ===
```

Both are published **after** `complete_run()`, and `spend_usd` was written after it too. Had
the gate covered `publish_log` and `record_cost`, those two lines would simply be missing and
the cost would be null — which is the debugging session P5-05's record says this cost once.
Once the run was terminal, **both** tokens answered 403.

**Teardown left nothing**: no `qa-run-*` container, no `qa-proxy-*` container, and
`sandbox_handle` cleared — P4's "every finished run leaking its egress proxy" staying fixed.

**`make ci-test-docker` runs without skipping**, checked rather than assumed: the
`@pytest.mark.docker` selection collects 6 tests and all 6 pass as dots, no `s`. Exit 0, with
1307 backend and 115 frontend tests.

**A thing about the suite that this uncovered**, and the reason UAT 1's own "no run executed"
line is now corrected: `tests/test_docker_sandbox.py` takes a `real_store` fixture — the actual
SeaweedFS of this stack — and its Docker-marked tests run whenever the daemon is usable rather
than skipping. Docker was up all day, so **every `make ci-test` really started containers and
really wrote into the dev store**: sixteen passes are visible as
`tenant/1/runs/20261104-1[345]*-demo-<uuid>-*/`, five objects each. By design, and useful —
it means the container path was being exercised far more than the record claimed — but it also
means the suite leaves objects whose rows the fixtures then truncate, and a store listing is
therefore not an inventory.

**#50's flake.** The mechanism is recorded in follow-up 53 and in `bc73027`: the session
archive's digest was a function of the clock, because `tarfile.open(path, "w:gz")` writes the
current time into the gzip header, so "identical bytes are not a new version" held only for
two saves inside one wall-clock second. It is a mechanism, not a disappearance — the fix is
`mtime=0` and a test that saves an unchanged directory twice a real second apart. Three
consecutive clean full-suite runs on the finished tree:

```
run 1: 1309 passed in 263.63s
run 2: 1309 passed in 264.92s
run 3: 1309 passed in 267.78s
```

1309 rather than 1307 because UAT 3's fix brought two tests with it. Worth recording how the
first attempt at this went: three runs started while the UAT-3 auth tests were still being
written failed 1, 2 and 2 — **my own edits mid-run, not a flake**, which is a reminder that
"three consecutive green runs" only means something if nothing else is touching the tree.

**What this does not prove.** The run used one target, one story and one site; nothing here
says anything about the agent's behaviour on a different application. The pause was taken at
one point in one step. And the egress allowlist was not probed during this run — `#28`'s
breach tests remain the evidence for that.


## Verified on 2026-11-05 — P5-06 / #36 (the prompts, verified at last)

The section #36 never had. It was implemented in `8b5aec3` and this record said plainly that
it did not vouch for it: "no §Verified section was written for it". UAT 3's closeout asks for
one, so here it is — observed against the live stack rather than reconstructed from the
commit.

**The shipped defaults are rows a tenant can see.** `GET /prompts` as tenant 1:

```
  qa_system_prompt.md     rev=1 len=8348      steps/3-explore.md   rev=1 len=975
  steps/1-read_story.md   rev=1 len=366       steps/4-generate.md  rev=1 len=1922
  steps/2-plan.md         rev=1 len=972       steps/5-heal.md      rev=1 len=1463
                                              steps/_context.md    rev=1 len=1975
```

**An override is a new revision, not an overwrite.** `PUT /prompts/steps/2-plan.md` with 90
bytes of tenant-1-specific instruction answered `rev=2`, and the history carries both:

```
  rev=1  len=972   (the shipped default)
  rev=2  len=90    (tenant 1's)
```

**And the override is that tenant's alone**, which is story 24's actual claim. A tenant
created fresh for this check (`promptcheck`, made with the #46 command and purged afterwards)
read the same prompt and got `rev=1 len=972` while tenant 1 continued to read `rev=2 len=90`.
Two tenants, one prompt name, different bytes, observed over HTTP.

**A run is pinned to the versions it used.** A fake run on tenant 1's target
(`QA_RUNNER=fake`, so this cost nothing) completed and recorded:

```
runs.prompt_revs = {"steps/2-plan.md": 2, "qa_system_prompt.md": 1,
                    "steps/1-read_story.md": 1, "steps/3-explore.md": 1,
                    "steps/4-generate.md": 1, "steps/5-heal.md": 1,
                    "steps/_context.md": 1}
```

It picked up the override made minutes earlier — `2` for the one prompt that had been edited
and `1` for the rest — which is the end-to-end claim: an edit in the portal reaches the next
run, and the run records what it was told rather than what the prompt says now.

**One thing observed that is worth writing down, because the portal will show it.** Both
revisions came back with the *same* `created_at`, to the microsecond. That is not a bug but it
is misleading: a shipped default is not a row until something makes it one, and
`prompt_store._seed` materialises rev 1 at the moment the first override is saved — so rev 1's
timestamp is when it *became this tenant's row*, not when those bytes shipped. `#39`'s
`savedLabel` renders "shipped default" only for a `null` `created_at`, which is the
not-yet-a-row case; a *seeded* rev 1 has a real timestamp and will render as a date somebody
appears to have saved. Two revisions sharing a timestamp to the microsecond is the tell.
Recorded as follow-up 56 rather than changed here: the honest fix is a label, and which label
is a product question.

**What this still does not prove.** No browser — the Prompts panel and its diff have been
rendered only by `Settings.test.jsx`, which is the gap P5-04's lesson is about and which #39's
own row already admits. And the override reached a *fake* run; the real run in UAT 2 used
tenant 2's prompts, which were the shipped defaults, so "a real agent behaved differently
because of an override" is not something this record claims.


## Verified on 2026-11-05 — P5-20 / #54 (UAT 3: onboarded, used, offboarded)

The round trip, which is the test: a tenant created through the application, used for real
work, then purged — with the bucket and the tables checked afterwards. It is the one exercise
that proves onboarding and offboarding are inverses, and no suite will run it against a real
object store.

Three tenants were created and all three are gone. `acme` is the interesting one: it did the
real agent run of UAT 2.

**Created without SQL** — `python -m app.accounts create-tenant`, three times. Each got its
tenant row, its first admin, a `user.add` audit row against its own tenant with `system` as
the actor, and caps of 3/500 from the column's server default.

**Deviation, recorded rather than ticked.** The criterion says "created through the portal".
It was created through an **operator command**, and that is
`docs/adr/0002-tenant-creation-is-an-operator-action.md`, not an omission: every authenticated
surface here acts *as a tenant*, and the person creating one belongs to none, so `AdminDep`
would mean "an admin of A may create B" and ungated would let anyone create tenants. The
requirement the criterion is really about — "no SQL" — holds. The ADR's "revisit when" is a
platform-operator role.

**The second deviation, also recorded.** "No SQL is run at any point" is not true of `acme`'s
full lifetime: UAT 1 seeded a crashed run into it with `INSERT`, because a crash cannot be
produced through an API. Every *administrative* action on it — invite, remove, quota change,
purge — went through the portal routes or the command, and no SQL mutated it otherwise.

**User administration, through the portal.** As `boss@acme.test`:

| Action | Result |
|---|---|
| `GET /users` | `[{"id":3,"email":"boss@acme.test","role":"admin"}]` |
| `POST /users` `{dev@acme.test, member}` | 201 with a one-time password |
| that password at `POST /auth/login` | 200 — the invite works end to end |
| `DELETE /users/5` | 204; gone from the listing; **their login is now 401** |

and as the invited *member*, every admin route refused with `{"detail":"tenant-admin role
required"}`:

```
  GET /users -> 403    GET /audit -> 403      PUT /usage/caps -> 403
  POST /users -> 403   DELETE /users/3 -> 403     (GET /targets -> 200, its own reads work)
```

**The quota route (#45), live.** Raising the concurrency cap to 7 left the monthly quota at
500 — the omitted-versus-`null` distinction, against a real deployment — and
`{"monthly_run_quota": null}` made it unmetered with `at_monthly_quota: false`. A third call
repeating a stored value answered 200 and wrote **no** audit row, which is the review fix
working where it matters. The operator path still exists: `repo.set_tenant_caps` is reachable
from a console and is what the route calls.

**The audit log's own account of it**, read through `GET /audit`:

```
quota.change  actor=boss@acme.test  before={concurrency 7, monthly 500} after={7, null}
quota.change  actor=boss@acme.test  before={3, 500}                     after={7, 500}
user.add      actor=boss@acme.test  target=user:5  after={dev@acme.test, member}
user.add      actor=system          target=user:3  after={boss@acme.test, admin}
```

Two `quota.change` rows for three calls, and the two `user.add` rows differ in exactly the way
the design intends: `system` for the CLI-created first admin, the acting admin for the portal
invite.

**The two defined answers #46 chose.** Removing the last admin — which here was also removing
yourself — is **409** carrying the remedy: *"boss@acme.test is the last admin of this tenant
and cannot be removed; make another admin first, then remove this one."* With a second admin
present, removing yourself is **204** and allowed, and the remaining admin logs in and sees a
one-user tenant. Both observed.

### The finding this UAT exists for

**Removing a user did not remove their access.** After `DELETE /users/3` removed
`boss@acme.test`, that account's own cookies still worked: `POST /auth/refresh` minted a fresh
access cookie (200, `role: admin`), and with it the deleted account read `/users`, **created
another admin account** (`POST /users` → 201) and changed the tenant's quotas. The audit log
recorded every move under the deleted account's name, which is how it was noticed — the trail
was the only control that saw it.

The mechanism: neither `require_auth` nor `/auth/refresh` re-read the `users` row. `app/auth.py`
justifies that as "a role or tenant change takes effect at the user's next login", which is a
fair bargain for a *downgrade* — the person still works here. P5-14 added a **removal**, and
removal is the case it does not cover: an offboarded contractor, a compromised account. And
because refresh is what re-issues the short cookie, the honest description of the old behaviour
was not "fifteen minutes" but **"up to thirty days"**, the refresh cookie's cap.

**Fixed here**: `POST /auth/refresh` now re-reads the row, tenant-scoped, and takes the new
cookie's claims from it — so a removed user's refresh is the same bare 401 a missing cookie
gets, and a role change takes effect at the next refresh rather than only at the next login.
One database read per refresh, not per request, so `app/auth.py`'s argument survives intact.
Verified on the rebuilt stack: the removed user's refresh is 401 where it was 200.

**Not fixed, and recorded as follow-up 55**: a removed user keeps their *existing* access
cookie until it expires, up to 15 minutes. Demonstrated on the fixed build — a user removed
seconds earlier still got `POST /users` → 201. Closing it needs a read on every request, which
is the round trip this design declined; the options and their costs are in the follow-up.

### The purge

**`#42`'s expand-then-contract, proven both ways on the real store.** One artifact was planted
under the **pre-P5-10** key shape for `acme`'s real run
(`20261104-170707-acme-app-3aa7ad/uat3-pre-migration.txt`, outside any tenant prefix) and it
**downloaded through the portal route, 200, unmigrated** — which is the expand half, and the
reason a deployment can take the re-key at leisure instead of during a deploy.

**"What does this tenant have in the bucket?" answered from the bucket.** By prefix, with no
database: `tenant/2/` held 22 objects — 14 blobs and 8 run artifacts — and the planted legacy
object was visibly *outside* it.

**The gate refuses a mismatched confirmation before anything is touched:**

```
$ python -m app.accounts purge-tenant --slug acme --confirm-slug acme-typo
error: refusing to purge 'acme': the confirmation named 'acme-typo'. Both must be the
same tenant, because this cannot be undone
```

…and `acme`'s two runs were still there afterwards. Named twice, it ran:

```
purged: tenant 2 (acme): 23 object(s), 276 row(s) [artifacts 9, audit_log 14,
  file_index 43, projects 1, prompts 7, revisions 5, run_log 188, run_steps 5,
  runs 2, targets 1, users 1]
```

**23, not 22** — the planted legacy object went too. That is the review fix earning its place:
the purge reads its own run keys *before* deleting the rows and sweeps those prefixes as well,
so an object left under the old shape does not outlive the tenant. Without it, that object
would have sat in the bucket for ever with nothing left to name it.

**Checked directly afterwards, not inferred from the success line:**

```
tenant-owned rows remaining : NONE   (all 12 tables, inside tenant_scope(2))
objects under tenant/2/     : 0
the planted legacy object   : GONE
tenants row for acme        : GONE
```

**And tenant 1 untouched**, compared against a snapshot taken before: 25 artifacts, 34
`file_index`, 1 project, 4 revisions, 30 `run_log`, 23 `run_steps`, 9 runs, 1 target, 1 user,
**796 objects** — every count identical. Objects outside any tenant prefix went 533 → 532,
which is exactly the one planted object and nothing else. Tenant 1 still logs in and serves
`/projects`, `/targets`, `/runs`, `/targets/1/revisions` and `/artifacts/1/content`, all 200.

**A purge interrupted halfway, re-run, completes.** How it was interrupted, precisely: the
pass's own steps 1–3 were run in a process that then exited **without** reaching step 4 (the
`tenants` row) or step 5 (`purge_log`) — which is the state a crash between 3 and 4 leaves, and
the state the order was designed to make the recoverable one. `globex` was left with its rows
and objects gone and its tenant row present:

```
tenant row still present: 1 | its users: 0 | its runs: 0 | purge_log rows: 0
```

The same command, unchanged, then finished it: `purged: tenant 3 (globex): 0 object(s), 0
row(s)`, the tenant row gone and `tenant/3/` empty. **Worth knowing about the log**: that row
records zeros, because it records what *this* pass removed rather than a cumulative total. A
reader reconstructing an offboarding from `purge_log` alone would under-count an interrupted
one.

**The purge is the only path that deletes audit rows**, checked from the strongest place —
`psql`, outside the application entirely, after a purge had disabled and re-enabled the
trigger:

```
qa=# update audit_log set actor='forged' where tenant_id=1;
CONTEXT:  PL/pgSQL function audit_log_refuse_mutation() ...
qa=# delete from audit_log where tenant_id=1;
CONTEXT:  PL/pgSQL function audit_log_refuse_mutation() ...
tenant 1 audit rows intact: 1 | actor=admin@example.com
```

The trigger is back on, and `grep -rn "DISABLE TRIGGER" server/app` finds exactly one
executable occurrence: `app/accounts/purge.py`. The other three hits are prose pointing at it.

**It used no cross-tenant bypass**, which is the criterion's other half and a deviation from
its wording. `grep -c across_tenants app/accounts/purge.py` → 0; the bypass allowlist is the
same four entries it held before wave 3. #44 put ORM `DELETE` under the guard, so a delete
issued inside `tenant_scope(tenant_id)` is *scoped by the guard* to exactly the rows being
purged — strictly stronger than opting out, and what the allowlist's own comment asks for.

**The record that survives all of it.** `purge_log` holds three rows naming three tenants that
no longer exist, and the dev database is back to one tenant.

**What this does not prove.** No browser: every portal action here went through `curl` against
the real routes, which is the same HTTP the browser speaks but not the same rendering, and the
Users panel and the caps editor have been seen only by `vitest`. The purge was run by an
operator with shell access, which is the only way it can be run. And `rekey` was exercised on
this store's 25 real legacy rows, but 532 row-less orphans remain there and no purge will ever
name them, because the tenant they belong to still exists and the runs do not.


## Decisions recorded during this phase

| Decision | Why |
|---|---|
| **`users.email` is unique per tenant, not globally** | An address identifies a person *inside* a tenant. Globally unique meant two customers who both employ the same contractor could not both have an account, and the first tenant to claim an address locked every other tenant out of it. P5-01 shipped the global version knowingly and flagged it |
| **Login takes a tenant slug** | The direct cost of the above: an email alone no longer names an account. The alternatives considered and rejected were resolving across tenants and demanding a slug only on collision (a login whose required fields change with other tenants' data), and keeping email globally unique (declining the change) |
| **The slug is globally unique** | A handle that named two tenants would move the ambiguity up one level rather than remove it |
| **The seeded slug is a constant, not an env knob** | A `QA_SEED_TENANT_SLUG` was written and then removed in review: only the migration read it, so setting it prefilled the login form with a slug no tenant had and made a test fail from ambient environment. The slug is echoed by the form and the tests, so all three must agree |
| **`QA_ENV` defaults to `prod`, and only the exact string `dev` opts out** | The signal both credential fixes read. A default of `dev` would mean a deployment that forgot the variable got no `Secure` flag and a silent envelope-key fallback — which is follow-up 21's own failure mode, reintroduced by the fix for it. So the convenient branch is the one you ask for by name, `devv` and `staging` are deployments, and the dev stack and the suite each say `QA_ENV=dev` out loud. The cost is a bare `uvicorn` over plain HTTP needing the variable set |
| **The envelope's development key is a constant published in `app/envelope.py`** | `DEV_ENVELOPE_KEY`, not a read of `QA_SECRET_KEY`. A dev fallback that read the cookie secret would have left the dev stack in exactly the arrangement follow-up 21 describes, and made the separation real only where somebody had already set the new variable. Being well-known is what forces the companion decision: a deployment may not reach it, so one with no key refuses to boot rather than quietly using it |
| **`QA_ENVELOPE_KEY` may not equal either signing key, in development too** | Setting them to one value is follow-up 21 reintroduced by hand, and the likeliest way to satisfy the boot check by copying a line in a deployment config. Refused for `QA_SECRET_KEY` *and* `QA_RUN_TOKEN_KEY`, and compared against the keys that are **in effect** rather than the raw variables — a review found the first version comparing against a bare `os.environ.get(..., "")`, and therefore allowing the development default, which is a real key that really signs cookies. `config` is now the one place that resolves all three |
| **A historical prompt revision is its own type** | `PromptRevision`, not a widened `ResolvedPrompt` (#39 left the choice open). Only one of the two is ever sent to an agent, so widening would have put a timestamp nothing renders on the type the runner consumes — and, the reason that decides it, would let a historical revision be passed where the live prompt is expected, which is how a run comes to be given revision 2 of a prompt it recorded as revision 5 |
| **A prompt with no overrides has a history of one, not of none** | The shipped default at `SEED_REV`, reported and **not seeded**, with `created_at` as `None`. An empty history reads as "never edited" about a prompt whose body the page is displaying; a seeded row would make a GET a write with no transaction to commit it; and a timestamp of "now" would change on every page load, in the one surface whose job is to say when things changed |
| **The line diff is ours, not a dependency** | Forty lines of LCS in `web/src/diff.js`. "What changed" is a diff question, but the portal has no other use for one, so a library would be a build-size and supply-chain cost carried for a single caller — the same reasoning as hashing with PBKDF2 from the standard library rather than adding passlib |
| **The refresh token is stateless — no token table** | Chosen over a DB-backed rotating design. It keeps "a portal speed bump, not a revocation system" true and adds no migration. The cost is item 1 of §Follow-ups, and it is what forces the access cookie to be short |
| **Refreshing does not re-issue the refresh cookie** | 30 days from *login* is a hard cap. A sliding window on a token nothing can revoke is a session that never ends |
| **Distinct signing salts for the two tokens** | Without it the split is decorative: presenting the 30-day refresh token as a session cookie would restore the old week-long behaviour, worse |
| **`auth.py` owns the cookie contract** | Names, lifetimes, flags and the refresh path in one module. A route setting its own could re-path the refresh cookie and leave a logout that does not log out — a regression every existing test would still pass |
| **`uq_tenants_slug` is named in the model** | An unnamed `unique=True` is `tenants_slug_key` built from the models and `uq_tenants_slug` built from the chain, and `compare_metadata` does not compare constraint names, so `test_migrations.py` structurally cannot see the disagreement |
| **An unknown slug, unknown email and wrong password are one bare 401** | A probe can enumerate neither tenants nor the addresses registered in one |
| **The read filter is enforced by a listener, not by convention** | The write side was always one visible line per insert; the read side was a `.where()` that looked identical whether present or absent, and `repo.py` — the module every route goes through — had none. One `do_orm_execute` listener means a query cannot forget the filter; forgetting becomes *opting out*, which a reviewer and a test can see |
| **The guard is installed at import of `models.py`, with no off switch** | Anything that can query has imported the models, so the API, the orchestrator, the CLI and the suite are all covered by one call. A `QA_TENANT_GUARD=0` would let the suite prove isolation in a configuration production does not run in |
| **`TenantOwned` replaces the `_tenant_col()` helper** | `with_loader_criteria` filters the mapped subclasses of one class, so the mixin is what makes a single listener cover the whole schema — and what makes a new table's coverage a matter of inheritance rather than of remembering a `.where()` |
| **The criteria's tenant id is resolved outside the lambda** | `with_loader_criteria` takes lambda SQL: the body is analysed once and thereafter only its *closure variables* are re-extracted. `current_tenant_id()` called inside would be evaluated once and baked in, every later request reading the first one's tenant — the exact bug the guard exists to prevent, introduced by the guard. SQLAlchemy refuses that form outright, which is how it was found |
| **The reaper iterates tenants instead of reading across them** | Its sweeps are not single queries (`reap_expired` reads locks, then each lock's run, then frees it), so an unfiltered outer query would need every nested read opted out too — and the opt-out would become the normal case in the one module that touches every tenant's rows. `_for_each_tenant` binds each tenant and does ordinary scoped work |
| **A failing sweep for one tenant does not stop the others** | The reaper is the only thing that frees an app lock, so one customer's wedged row must not be able to park every other customer's apps. A noisy neighbour holding a *control*, not just a resource |
| **The bypass is a separate function, not a flag on `get_run`** | An `across_tenants=False` parameter would make the unscoped read reachable from every existing call site by typo, and would not show up in a grep. `get_run_across_tenants` is a name a reviewer notices |
| **The envelope wraps a data key, not the PAT** | A random AES-256 key per secret, encrypted locally, with only the 32-byte key sent to the KMS. The PAT is then never in a KMS request nor in that provider's audit log of them; rotating the KMS key re-wraps small keys instead of re-encrypting rows; and no secret can outgrow the KMS payload limit. Asking the KMS to encrypt the PAT directly would have been shorter code and none of those things |
| **A local in-process wrapper exists, and says so** | The suite and `make up` must work with no cloud account, and a format only exercisable against real KMS is a format nothing tests. `LocalKeyWrapper` is real AES-GCM with an HKDF-derived key, and `describe` reports “not a production configuration” — so a deployment that forgot `QA_KMS_KEY_ID` can be *seen* to have forgotten it rather than silently storing PATs under a key sitting in its own process |
| **Binding the seam and marking a rejected credential are one context manager** | `for_target(tools, app)` does both. They are two halves of one decision — the credential it resolves is the credential whose rejection has to be recorded — and five entry points each able to bind and forget to mark is how §8's fail-loud rule would quietly stop holding |
| **An unbound seam fails loud, naming the call that was missed** | `None` for the GitHub client would have been shorter and much worse: the first use is `AttributeError: 'NoneType' object has no attribute 'repo_has_commits'`, raised from inside a push, with nothing in it to suggest that a credential was never bound |
| **`is_bootstrapped` and the dry runs do not bind** | They answer from Postgres and the blob store and dial out to nothing. Requiring a credential would be requiring the network by another name — the bug `api.get_catalog` exists to avoid — and it would make the `--dry-run` preview impossible for a target just created, which is when it is most useful |
| **`CredentialRejected` is a separate class from `CredentialError`** | 422 against 502. “The token you just typed will not do” and “the token we have stopped working” have different remedies, and one class for both would have told a customer with a scope typo that GitHub was down |
| **`GITHUB_PAT` is deleted, not guarded, and nothing is migrated into the new columns** | One operator token is not *any* tenant's credential: every delivery it authored went into a customer's repository as the same identity. Sealing it per target would have given every customer the same credential under a per-tenant name, which is worse than making them save one |
| **`credential_state` is a column, not inferred from a null ciphertext** | The rejected case *has* ciphertext and is still unusable, and the portal has to say three different things. `invalid` is also **sticky**: it survives until a new token is saved, so a customer is told their token was refused instead of watching the same delivery fail again |
| **`mark_invalid` keeps the ciphertext** | Deleting it would throw away the only evidence of what was rejected, and an operator who fixes the token's scopes on GitHub's side can re-save the same value |
| **The credential surface is absent from `delivery.__init__`'s lazy table** | Lazy keeps a module out of a sandbox's import *graph*; it does not keep the name out of a file every sandbox loads. An entry reading `"decrypt_pat": "credentials"` is one `getattr` away from the function that unwraps a data key. `app/api.py` imports that module by path instead, which is a line a reviewer sees |
| **The expiry warning rounds days up** | `timedelta.days` truncates, which is the wrong direction for a warning: it reported 2 days and 23 hours as “2 days” and 3 hours as “0 days” — a message reading like “no deadline” about the most urgent case the warning exists for |
| **`QA_KMS_KEY_ID` is not on the forbidden-credential list** | It is a key *identifier*; the IAM grant is what authorises its use. That list is also applied to every compose service, so including it would forbid the API from being configured with the key it needs. That a sandbox does not get it is asserted directly instead |
| **404, not 403, for another tenant's row** | A reader who does not own a row should not be able to tell "exists, not yours" from "does not exist", or the small integer ids become an inventory of what other tenants have |

---

## What is covered only by fakes

Named here as P1–P4 each named theirs, so the next ticket inherits a list rather than an
impression.

- ~~**A second real tenant.**~~ **Retired by P5-02, for the duration of the check.** Tenant
  `acme` was created in the dev database, logged into over HTTP against the live stack, given
  a project and a target of its own with revision 1 in blob storage, observed to see none of
  tenant 1's rows and none of its own hidden — and then **deleted again**, so no second
  tenant exists right now. It was created with SQL, was never *logged into in a browser*, and
  never had a run, so "a second tenant with a real run" remains unproven and the UI half
  still waits on follow-up 6. What is no longer a fake is the isolation itself: it has been
  observed against two real sessions rather than only against two rows in a test.
- **The expiry, at its real length.** Proven at a 1-second lifetime. Nothing has observed a
  session actually lasting 15 minutes and then renewing, or a refresh cookie reaching 30 days.
- **The stream reopen.** `RunDetail.stream.test.jsx` drives a stub `EventSource`. A real
  browser hitting a real 401 on `/runs/:id/events` and recovering has not been observed.
- **The login form.** Covered by jsdom. No browser has typed a slug into it.
- **The migration against real data.** *Partly retired.* P5-02's revision ran against the dev
  database, which holds a real project, target, five runs and their artifacts — but that is
  one tenant's data, and the interesting case is collision. A database with several users, or
  two users whose emails collide across tenants, has still not been migrated, and both
  revisions' `downgrade` deliberately fails loudly in that case rather than picking a winner,
  which remains unobserved.
- **A real KMS key.** Every test and the dev stack use `LocalKeyWrapper`. `KmsKeyWrapper` is
  driven by a stub that records what it was asked to wrap — which does prove the thing most
  worth proving, that only a 32-byte data key is ever sent — but **no data key has been
  wrapped by a real cloud KMS**, no IAM grant has been exercised, and the `kms:Encrypt` /
  `kms:Decrypt` call shapes rest on reading the API documentation.
- **A real GitHub PAT.** Save-time scope validation is driven through the injected
  validator, and the `TokenInfo` header parsing through `httpx.MockTransport`. No real token
  has been pasted, so GitHub's actual `x-oauth-scopes` and
  `github-authentication-token-expiration` header values for a classic PAT, and the absence
  of both for a fine-grained one, are **assumed from the documentation and from P1's
  parsing code**, not observed. The expiry parser's date formats are the least-tested thing
  in this slice.
- **A delivery with a per-tenant PAT.** No push has been made with a credential read off a
  target row. The 401-at-delivery path is proven end to end through the route with a GitHub
  client that refuses everything; the *success* path has only ever run with a literal
  `"t0ken"` from the test doubles, against a bare repo on disk.
- **The portal's credential panel.** Covered by jsdom. No browser has typed a PAT into it,
  and the expiry warning has never been seen rendered.
- **P5-01 in its entirety** — see the banner. Its claims rest on its commits.
- **The guard under concurrency.** Proven to re-bind per execution by alternating tenants in
  one process, and by the suite, which runs the whole API in-process. Two tenants issuing
  requests *simultaneously* against a real uvicorn with a connection pool has not been
  observed — the mechanism is a `ContextVar`, which is per-task by construction, but that is
  an argument rather than an observation.
- **The sandbox's reads.** A run executes in a container that talks to Postgres directly and
  binds its tenant from the run row (`launcher._run_tenant_scope`). Every test of that path
  uses `QA_SANDBOX=thread`; no containerised run has been executed since the guard landed,
  for any tenant.

---

## Follow-ups

The reason this file exists. Items 1–8 are consequences of what shipped; 9–13 are scope and
hygiene; 14–47 were added by the slices after the first, each under the heading of the slice
that introduced it. **Items 48–52 are different in kind**: they are not consequences of a
slice but requirements of #30 that no slice implemented, found by the two-axis review at the
end of the phase. They are what #30 is waiting on in code, as opposed to in evidence.

### Introduced by the expiring session

1. **Nothing can be revoked before it expires.** Stateless by choice, so logout clears
   cookies on that browser but would not stop a copy already taken, and a leaked
   `QA_SECRET_KEY` forges any user's session until the key is rotated. The place to add a
   token table is marked in `app/auth.py`. **Revisit if P5 ever needs to kick out a user, or
   alongside #37's audit log** — an audit trail of actions nobody can interrupt is half a
   control.
2. ~~**Neither cookie sets `Secure`.**~~ **Done**, with item 21, in the credential-pair pass
   above. Both cookies carry it outside development, including the renewed access cookie and
   both deletes in `clear_session_cookies` — the two a narrower fix would have missed. The
   env-conditional flag this asked for is `config.cookies_secure()`, reading a `QA_ENV` that
   **defaults to `prod`**, so a deployment that forgets the variable gets the flag rather than
   going without it. Still never seen against a real browser over real TLS.
3. **Artifacts bypass the refresh entirely.** `/artifacts/:id/content` is rendered straight
   into `<img src>` and `<a href>` (`RunDetail.jsx`), and the route is auth-gated
   (`router = APIRouter(dependencies=[AuthDep])`). The browser fetches those itself, so
   `api.js` never sees the 401: once the access cookie expires, screenshot thumbnails break
   and a *View*/*Download* click fails, with no renewal possible. This is the same class of
   bug as the `EventSource` one fixed in `105e9b7`, but it cannot be fixed the same way —
   it wants either a short-lived signed artifact URL or a fetch-and-blob download path.
4. **A role or tenant change takes effect at next login, not next refresh.** `/auth/refresh`
   reconstitutes claims from the token and never re-reads the `users` row, inheriting
   P5-01's trade-off and extending its worst case from one session to 30 days of renewals.
   **This is no longer hypothetical: P5-03 gated PAT save and clear on the admin role**, so
   demoting a tenant admin leaves them able to rotate that tenant's GitHub credential — the
   credential a delivery pushes with — for up to 30 days of refreshes. It is the sharpest
   consequence of the stateless-token decision so far, and it is the same fix as item 1.

   **Closed on 2026-11-05 (UAT 3).** `/auth/refresh` re-reads the `users` row,
   tenant-scoped, and takes the new cookie's claims from it, so a role change takes effect at
   the next refresh — within 15 minutes — rather than at the next login. It was closed not for
   this reason but because the same gap meant a **removed** user kept their access for 30 days
   (§"Verified on 2026-11-05 — P5-20 / #54"), which is the sharper consequence this item did
   not anticipate: it reasoned about demotion, and removal did not exist when it was written.
   What remains of item 1 is follow-up 55.
5. **A cold load of the login page fires one pointless `POST /auth/refresh`.** `api.me()`
   401s when nobody is logged in, which trips the refresh dance. Harmless, one round trip,
   but it puts a 401 and a failed refresh in the log of every first visit.

### Introduced by the enforced read path

15. **The guard is a *read* guard: ORM UPDATE and DELETE are not filtered.** `is_select` is
    false for them, so a bulk `update()`/`delete()` spans tenants. Nothing in the tree is
    exposed by that today — every mutator in `repo.py` resolves its row through a filtered
    `get_run`/`get_target` first (asserted in `test_tenant_isolation_repo.py`), and the one
    bulk delete, `bus.prune_run_logs`, is a retention sweep that *should* span tenants. But
    it is a real edge: **a future bulk write must filter itself**, and no test would catch one
    that did not. The honest fix, if one is wanted, is a second listener on
    `do_orm_execute` for `is_update`/`is_delete`.

    **Closed on 2026-11-04 by #44 (P5-12)**, with exactly that fix, after the two-axis review
    of #30 promoted it from an edge to item 50's write half: a second tenant was shown
    renaming a project to "stolen" and deleting every log line of a run it did not own. The
    guard is no longer a read guard, and the test module is no longer named as if it were.
    `bus.prune_run_logs` joined the bypass allowlist as a result — the one entry that list
    gained in the whole phase, and UAT 1 records why that is not a widening.
16. **A row already in a session's identity map bypasses the filter.** `Session.get()`
    returns it without a SELECT, so a session that read across tenants once can hand that
    object back afterwards. No request does — the bypasses all open their own sessions —
    but it bit the first draft of `test_tenant_isolation_repo.py`, where the fixture wrote
    the estate through the same session the test then read from, and the tests passed while
    proving nothing. That is why those tests read through a separate `mine` session, and it
    is worth knowing before writing the next one.
17. **A lazy load off a row fetched by a bypass is unfiltered.** The listener skips
    `is_relationship_load`, because the criteria propagates from the query that loaded the
    parent — so when the parent was loaded *through* a bypass, there is nothing to
    propagate. Harmless today: both bypass callers read one scalar (`run.tenant_id`) and
    neither touches a relationship. Worth knowing before a third caller is added.
18. **Raw SQL is not covered**, by construction: `session.execute(text(...))` is not an ORM
    statement. The only raw SQL in the tree is the test fixtures' `TRUNCATE`.
19. **`_tenant_of` adds one database round trip per reaped run**, to resolve the
    tenant before destroying its sandbox. Unmeasured and almost certainly irrelevant at this
    scale (a sweep every 30 seconds over the runs it just failed), noted because it is a read
    per run inside a loop and the next person to look at reaper cost should know it is there.
20. **The delivery CLI can only ever deliver tenant 1's targets.** `python -m app.delivery
    push` binds no tenant, so `current_tenant_id()` answers the seeded default and
    `catalog._target()` finds nothing else. **Not a regression** — that filter predates this
    change and the CLI was always tenant 1's — but it was invisible while one tenant
    existed, and `acme` cannot be delivered today. The fix is a `--tenant` option resolving a
    slug and a `tenant_scope` around the command, and it belongs with the tenant-admin
    surface (item 6) rather than here.

### Introduced by the per-tenant PATs

21. ~~**Rotating `QA_SECRET_KEY` destroys every stored PAT**~~ — **done**, in the
    credential-pair pass above. `QA_ENVELOPE_KEY` is now the local wrapper's key and
    `app/envelope.py` does not read `QA_SECRET_KEY` at all, so rotating the cookie secret costs
    sessions and nothing else, and a leak of it no longer opens every customer's credential. A
    deployment with neither key refuses to boot; the two keys set to the same value are refused
    everywhere. The cost, paid once and deliberately: a PAT already sealed under
    `QA_SECRET_KEY` in a dev database must be re-saved, which `decrypt_pat` reports as a loud
    `CredentialError`. **Setting `QA_KMS_KEY_ID` is still the production answer** and still
    unset everywhere. The original text follows.

    **Rotating `QA_SECRET_KEY` destroys every stored PAT**, wherever `QA_KMS_KEY_ID` is unset
    — which is every deployment today, including the dev stack. The local wrapper derives its
    wrapping key from that secret, so the key that signs session cookies is also the key that
    protects credentials, and item 1 already says a leak of it forges any user's session.
    `decrypt_pat` fails loud rather than guessing (`CredentialError`, "could not be
    decrypted"), and the remedy is for each customer to re-save their token — but nothing
    warns that this is what rotation costs, and nothing re-encrypts. **Setting
    `QA_KMS_KEY_ID` in any real deployment is the answer**, and the fact that the fallback is
    silent-but-loud-later rather than refused outright is a deliberate choice recorded in
    §Decisions, not an oversight.
22. **There is no re-wrap or rotation tooling.** A new KMS key leaves existing rows wrapped
    by the old one; they keep decrypting while the old key remains enabled and stop the day
    it does not. Re-wrapping is a loop over `targets` calling unwrap-then-wrap, and it does
    not exist. Nothing needs it yet because nothing has rotated.
23. **A revoked token still reads `valid` until a delivery tries it.** `credential_state` is
    written at save time and at a 401/403 during delivery, and nothing re-validates in the
    background. Expiry is handled — the warning is computed from `pat_expires_at` at read
    time, so it becomes true on its own — but a customer who revokes a PAT on GitHub's side
    sees "valid" in the portal until the next delivery fails. A periodic `GET /user` per
    target would fix it and would also be a per-tenant rate-limit consumer, which is why it
    was not done here.
24. **No audit row for a PAT save or rotation.** #37's acceptance criteria name PAT
    save/rotate explicitly, so the route is deliberately left without one rather than given a
    bespoke log line to be ripped out. **#37 must cover `PUT`/`DELETE /targets/{id}/pat`**;
    they are the two mutations this slice added.
25. **`make deliver` and the delivery CLI cannot deliver anything until a PAT is saved in the
    portal**, and they still bind no tenant (item 20), so they are the seeded tenant's only.
    Together that means the CLI path now depends on a browser session having happened first.
    Not a regression in isolation — it previously depended on an environment variable the
    operator had to set — but the two limits compound, and the fix is the same `--tenant`
    option item 20 names.
26. **The account a token authors as is reported once and not stored.** `login` comes back on
    the save that validated the token and is not a column, because it is GitHub's answer at a
    moment rather than a fact about the row. The cost is that the portal can show "deliveries
    will be authored by X" immediately after saving and never again.

### Carried over or deferred

6. **The tenant-admin surface does not exist.** ~~No way to create a tenant, set its slug, or
   invite a user — `repo.create_user` was deliberately removed in `06a3acd` as out of scope.
   Until it lands, a second tenant can only be made with SQL, which is why "a second real
   tenant" sits in §fakes.~~ **This was the gating item for most of the rest of P5.**

   **Closed on 2026-11-04 (#46 / P5-14).** `app/accounts/` is the one module that creates or
   removes an account, and the surface is split at two altitudes:
   - **A tenant's own users are a portal surface**: `GET/POST /users`, `DELETE /users/{id}`,
     all behind `AdminDep`, with a Users panel on Settings shown to admins. Invite assigns a
     role and returns a **one-time password** — there is no mail path here, so the password
     exists in that one response and nowhere else; the panel says so, and the audit row
     deliberately does not contain it.
   - **Creating a tenant is not a route at all**: `python -m app.accounts create-tenant`.
     Recorded as `docs/adr/0002-tenant-creation-is-an-operator-action.md`, because the
     alternative is reasonable and will be proposed again. Every authenticated surface here
     acts *as a tenant*, and the person creating one belongs to no tenant yet: gated by
     `AdminDep` it would mean "an admin of A may create B", ungated it would let anyone
     create tenants, and a platform-operator role is a bigger change than this ticket with
     its own auth story. The authority is shell access, which on a single-operator
     deployment is who should have it.
   `USER_ADD`/`USER_REMOVE` join the audit vocabulary, so **#37's list of seven is
   complete** — and `tests/test_audit.py`'s tripwire, which was written to fail the moment
   this surface appeared, is now the inverse assertion. A role *change* is deliberately still
   absent: nothing performs one, and an `Action` member nothing can write is what that
   module's rule forbids. Changing a role means remove and re-invite.
   Two answers the ticket asked for by name: **the last admin cannot be removed** (409, with
   "make another admin first" in the body, because a tenant with no admin can never be
   administered again from inside), and **removing yourself needs no special case** — leaving
   is allowed while another admin remains, and the last-admin rule already refuses the one
   departure that matters.
   **What is still not proven**: none of this has been run against the live stack. UAT 1
   (#52) is where two tenants get created with the command rather than with SQL, and where
   the portal panel is used in a browser — the suite cannot do either, and this phase has
   four recorded occasions of a real run finding what a green suite could not.
7. **`/auth/me` does not return the tenant's slug or name**, so the portal cannot show which
   tenant you are signed into — and with per-tenant emails, the same address in two tenants
   now looks identical in the UI. `Login.jsx` hardcodes `DEFAULT_TENANT = "default"`,
   duplicating the migration's `_DEFAULT_TENANT_SLUG`; a third copy lives in
   `test_auth.py`'s `SEED_TENANT_SLUG`. Three places that must agree and no test ties them.
8. **There is no way to discover your slug.** By design an unknown slug and a wrong password
   are the same 401, which is right for security and leaves a user who mistypes their tenant
   with no signal. Worth a thought when the admin surface sends invitations.
9. ~~**#32 is only part-done.**~~ **Done.** Both halves landed: the enforced read path
   (`tenancy.install_read_guard`) and composite uniqueness on `projects.name` and
   `targets.app`. The ticket's own acceptance criterion about backfilling `tenant_id` and
   dropping the server default "in the same revision" was **already satisfied by P2**
   (`8f21c4b07e3a` added the column with a server default, backfilled the existing rows to
   the seeded tenant and dropped the default in that one revision), so P5-02's revision
   attempts no backfill — there is no row without a tenant to repair. `test_tenancy.py`'s
   two structural assertions cover it and still pass.
10. **Review suggestions declined, recorded so they are decisions and not oversights:**
    extracting a `_CookieSpec` to collapse `set_access_cookie`/`set_refresh_cookie` (the two
    differ in a way the docstrings carry — only login calls the second); splitting `auth.py`,
    which now holds password hashing, token minting, the cookie contract and the FastAPI
    dependencies (a pre-existing shape, and a refactor wider than this change); and giving
    the tenant slug its own type rather than passing `str` (the repo passes primitives for
    `email`, `app` and `name` throughout).
10b. **P5-02's review suggestions, and what was done with them.** Accepted and fixed: a
    migration docstring that claimed a `pg_constraint` readback it does not perform; a
    `pragma: no cover` on the one branch the slice added a test for; a comment that
    misdescribed `ACROSS_TENANTS_OPTION`; a database read left on the event loop in
    `reaper_loop` while every sibling call used `asyncio.to_thread`; function-local imports
    with no reason to be local; a bypass scan blind to the hand-written
    `.execution_options(qa_across_tenants=True)` spelling (now covered, with a test of the
    scanner itself); and three missing documentation surfaces (README §9's gotchas,
    DESIGN.md §3's data model and §14's decision log, all now updated).
    **Declined, with reasons:** merging `launcher._run_tenant_scope` and `reaper._tenant_of`
    into one shared helper — they looked like duplicates before the event-loop fix and no
    longer are, one being a context manager that logs and falls back so a run still executes,
    the other a plain function whose failure must propagate; and treating
    `_for_each_tenant`'s per-tenant error isolation as scope creep to be removed — it is
    behaviour #32 did not ask for, but the reaper is the only thing that frees an app lock,
    so one tenant's wedged row parking every other tenant's apps is a multi-tenancy defect
    the ticket's own subject matter implies. It is called out here rather than left silent.
    The extra round trip per reaped run is item 19.

11. **`read_access` reads `ACCESS_MAX_AGE` off the module** so the agreed test seam can
    monkeypatch it. Correct for production too — one place sets the window — but it means an
    expiry test asserts through a module attribute rather than a parameter. Flagged by the
    standards review; left as the user-chosen seam.

27. ~~**P5-03 was not code-reviewed.**~~ **Done.** The first attempt died on an API rate
    limit before either axis reported; it was re-run against `17293a5` and both axes
    reported. What it found and what was done with it is item 27b. The §Decisions rows above
    are now reviewed conclusions rather than only the author's account — with the one
    correction 27b records.

27b. **P5-03's review, and what was done with it.** Two axes, as every prior slice.

    **Accepted and fixed — two of them were real credential leaks:**

    - **The PAT was in `Tools.__repr__`.** `Tools` is a `@dataclass(frozen=True)` and
      `token: str` carried no `field(repr=False)`, so `repr(bound_tools)` printed a tenant's
      plaintext PAT — into any traceback frame dump, any `logger.exception` holding one, any
      failed pytest assertion. `errors.redact` is no defence: it is the choke point for
      messages somebody *builds*, and a generated repr is not one. The slice's own
      documentation (README, `TargetCredential.jsx`) promised the customer the opposite.
      `token` and `credentials` are now `repr=False`, with a test, plus a sibling test that
      the production `GitHubClient` does not print its token either — hiding the field is
      worth nothing if the client built from it leaks instead.
    - **A plaintext data key could reach a `SealError` message.** `KmsKeyWrapper.wrap`
      interpolated `{exc}`, and botocore reports a bad parameter by echoing its value — here
      `Plaintext=<the 32-byte data key>`, the one thing that opens the seal. Both `wrap` and
      `unwrap` now carry the exception's *type* and the key id, never its text; `from exc`
      keeps the full detail in the traceback, which stays in the process. Done for `unwrap`
      too although the review only flagged `wrap`: its *response* is the one carrying a
      plaintext data key, and the type name is the diagnostic part anyway (AccessDenied,
      InvalidCiphertext and KeyUnavailable are three different operator problems).
    - **AC5 was only half true, and the missing half is the common case.** `for_target` keyed
      the fail-loud rule on `CredentialError`, which only `GitHubClient._raise_for_credentials`
      raises — but the PAT also travels in the **clone URL**, and `push_artifacts` clones
      *before* its first REST call. A revoked or under-scoped token is therefore rejected by
      git's HTTPS transport, which reports a failed subprocess rather than a status code, so
      it arrived as a `GitError` — a sibling of `CredentialError` under `DeliveryError`. The
      credential stayed `valid` and the route answered **400 instead of 502**. The existing
      test passed only because it stubs `gh_factory`, so nothing ever exercised a git auth
      failure. Now `GitError.is_credential_rejection` classifies git's own stderr and
      `for_target` translates a match into the same `CredentialError`: one outcome, one
      status, one sticky `credential_state`, whichever layer refused us. Deliberately
      conservative — a non-fast-forward push or a missing ref is re-raised untouched, because
      marking a working credential invalid sends a customer to rotate it for nothing.
    - **`DbCredentials.mark_invalid` swallowed every exception silently.** Never *raising* is
      right (it runs on the failure path of a delivery that is already failing, and a second
      exception there would replace "GitHub rejected your token" with whatever went wrong
      recording it). Never *saying* is not: a failed mark leaves the row reading `valid`, so
      the next delivery fails identically with no warning — the silent retry §8 forbids. It
      now logs, with the app and never the credential.
    - **Three documents disagreed on how many delivery paths do not bind**: `tools.py` said
      two, this record said three-then-four, DESIGN.md §8 named one. The answer is **four**
      (`is_bootstrapped`, the already-bootstrapped arm, and the `--dry-run` arms of bootstrap
      and push); all three now say so. The review also read `plan_reset` as contradicting
      "the dry runs dial out to nothing" — it does not, because `plan_reset` is not on that
      list: it is a dry run that *does* bind, since it makes two authenticated GitHub calls.
      That distinction (the test is whether a path dials out, not whether it writes) is now
      written down in all three places rather than being inferable from the code.
    - **README's P4 paragraph** still described the sandbox's credential safety in terms of
      "no module can read `GITHUB_PAT`", a variable this slice deleted; it now states the
      stronger thing that is actually true.

    **Found while fixing, and worth more than the finding that led to it:** the new
    `mark_invalid` log test passed alone and failed in the suite. `alembic/env.py` called
    `fileConfig(config.config_file_name)`, whose `disable_existing_loggers` defaults to
    **True** — so building the test schema in process disabled every `app.*` logger for the
    rest of the session. Production survives it by accident (migrations run as their own CLI
    process). It **failed open**: a test asserting something was logged saw an empty
    `caplog`, and a test asserting nothing was logged passed for the wrong reason, which
    means no log assertion anywhere in this suite meant anything. Fixed with
    `disable_existing_loggers=False`. The regression test for it is **structural** (it reads
    `env.py` and asserts the argument) after the observable version was written first and
    found to pass with the bug reintroduced: `disable_existing_loggers` only disables loggers
    that already *exist*, so observing one passes or fails on whether some other module
    happened to be imported first — the same order-dependence that hid the bug. The
    structural one was confirmed to fail with the fix reverted and pass with it restored.

    **Declined, recorded so they are decisions and not oversights:** extracting a `Binding`
    type for `token`/`gh`/`app` (a real Data Clump, but `Tools` being both the injection
    bundle and the per-target binding is a shape this slice inherited, and splitting it is
    wider than a review fix); collapsing the two wordings of the unbound-seam message;
    `gh_factory` and `bind` as "Speculative Generality" (both are the agreed test and dry-run
    seams — `bind=False` is what lets a target with no PAT preview a push); renaming
    `applied()` in `TargetCredential.jsx`; and a CHECK constraint on `credential_state` (the
    enum is app-enforced, matching every other enum column in the schema). The review also
    listed `DELETE /targets/{id}/pat`, the `_SEALED_CREDENTIAL` redaction and the
    `CredentialBadge` on `Projects.jsx` as scope creep: kept, the first because a credential
    you cannot remove is worse than one you can, the second because a reader who finds a
    sealed blob in a log cannot tell it is harmless, the third because AC4 asks for expiry to
    be surfaced "before it lapses" and the target row is where an operator looks.

    **What the review did not change:** the fakes. No real KMS, no real GitHub token, no
    browser — items 21–23 below still stand, and AC1/AC3/AC4 remain proven against
    `StubKms`, an httpx `MockTransport` and jsdom respectively.

28. ~~**The portal's quota surface has no test at all.**~~ **Done.** The seam was taken after
    all: **14 frontend tests** (70 → 84), 8 in the new `UsageMeter.test.jsx` and 6 added to
    `Projects.test.jsx`. The component tests cover used-of-limit rendering, the unmetered
    count with no denominator, each cap's own remedy sentence, and both gauges full at once
    (the case that made the `/usage` endpoint report two independent flags rather than deriving
    them from the single breach it would refuse with). The page tests cover the gauges
    appearing, the page still rendering when the usage read fails, a 429 shown **in the
    server's own words**, the usage being re-read after a refusal so the gauge agrees with it,
    and a 409 still getting the queue explanation rather than collapsing into the quota one.

    **Both defects the review had found by reading are now pinned, and both were confirmed to
    fail with the fix reverted** rather than merely passing once written: restoring
    `=== null` makes the undefined-cap test fail with the literal "2 of undefined", and
    restoring the unguarded `onChange={load}` makes the reload test fail. A test that passes
    both with and without the bug it names is worth nothing, so each was checked both ways.

29. ~~**New tenants are unmetered, so "one abusive tenant cannot starve the platform" is not
    yet true.**~~ **Done**, in revision `f1a62c90d4e7`: both cap columns now carry a **server
    default** of `3`/`500`, so a tenant arrives bounded however it was created.

    **Server-side, and that is the whole point rather than an implementation detail.** There
    is no `create_tenant` function anywhere in this application — a tenant comes from the
    users migration's seed or from a hand-written `INSERT`, and the second is how every real
    second tenant has been made so far, since there is still no tenant-admin surface (item 6).
    An application-side default would have covered neither path.

    **The default is kept, not dropped, which departs from this chain's usual pattern** (P2's
    `tenant_id` and P5-03's `credential_state` both add a server default, backfill with it and
    drop it in the same revision, so application code must set the column rather than let the
    database guess). That rule exists to stop a column acquiring a value nobody chose. Here
    the default *is* the choice, and it has to outlive the revision: its job is to apply to
    rows inserted next year by code that does not mention these columns. The departure is
    stated in the revision, in `models.py` and here, so it reads as a decision rather than as
    somebody forgetting the pattern.

    `NULL` still means no cap, so an unmetered enterprise plan is still expressible — it is
    now something a plan **asks for** rather than what a tenant gets by nobody thinking about
    it. Verified by hand on a throwaway database: a bare `INSERT` lands `3`/`500`; an `INSERT`
    naming `NULL, NULL` stays unmetered; after `downgrade -1` the defaults are gone and a bare
    `INSERT` is unmetered again, which is exactly the `e9c41a7d3f28` behaviour. One honest
    edge: altering a default never rewrites existing rows, so a tenant created *during* a
    downgrade window keeps its `NULL`s after the re-upgrade. That is also what protects a
    deliberately unmetered tenant from being re-capped by a later migration.

30. **Lowering a cap does not retroactively bound what is already live.** `resume_run` is not
    quota-checked, correctly — `PAUSED` is in `LIVE`, so a paused run was already counted and
    resuming starts nothing new. But if an operator lowers a cap while runs are paused,
    resuming them takes the tenant over the new cap, and nothing refuses it. The caps are an
    admission check, not a continuous invariant. Worth a decision when the tenant-admin
    surface lands, because that is when lowering a cap becomes a thing people do.

31. **The calendar month is UTC, and nothing says so to the customer.** `tenant_usage` takes
    `now.replace(day=1, ...)` on a UTC clock, so a tenant far from UTC sees their quota reset
    up to most of a day early or late relative to their own calendar. There is also a minor
    skew worth knowing: `month_start` comes from the application clock while `runs.created_at`
    comes from the database's `now()`. Neither matters at the current scale and both would
    matter to a customer reading an invoice.

### Introduced by the run-scoped control-plane API

32. **Serving `/internal` from the main listener puts the whole API on the sandbox network.**
    The routes need to be reachable from a run, so the API joined `qa-sandbox` — and a
    container on that network can therefore reach every other route the API serves,
    `/auth/login` included. Before P5-05 the only things it could reach were Postgres and
    the object store, so this is a *narrower* surface than a database credential and a
    *wider* one than the internal routes alone. What stands in front of it today: a run
    token authorizes nothing on the portal's routes (distinct signing salts, asserted in
    `test_internal_api.py`), a sandbox holds no user credential, and `/internal` is absent
    from both proxy allowlists so none of it is published to the public origin
    (`test_api_proxy_paths.py`). What does *not* stand in front of it: any rate limiting.
    The clean fix is a second listener — `/internal` on its own port, with only that port
    attached to the sandbox network — which is a deployment change rather than a code one,
    and the service layer is already indifferent to which listener reaches it. **Worth
    doing before a real customer's agent runs on this.**

33. **`record_cost` is exempt from the liveness gate and did not have to be.** Three of the
    four exemptions are forced by ordering — a run's last log lines and its exit-code read
    both happen after its final status transition. `record_cost` is a *write*, done by the
    sandbox in `drive_run`'s `finally`, and could have been recorded control-plane-side at
    teardown instead. It is where it is so that "every way out of a run records what it
    cost" stays one statement in one process; the cost is that a token leaked from a
    finished run can rewrite two accounting columns until its signature expires. Recorded
    because it is the one exemption that is a trade rather than a necessity.

34. **The internal API has no request budget of any kind.** A wedged or hostile agent can
    call the control plane as fast as it likes for the length of the run wall clock. Each
    call is cheap and authorized, so the failure mode is noisy-neighbour load on the API and
    on Postgres rather than a data leak — but there is nothing bounding it, and the
    per-tenant quotas P5-04 added count *runs*, not requests. The natural home is the same
    second listener item 32 wants.

### Harness hygiene

12. **`SPEC-P5-multi-tenancy.md` and `.claude/harness/issues/p5/README.md` are both
    zero-byte files**, committed empty in `82542c6` ("add initial multi-tenancy
    specifications and README for P5"). Every prior phase has a real spec file; P5's
    spec lives only in issue #30. Either write them or stop referring to them.
13. ~~**No P5 ticket has been closed on the tracker.**~~ **Partly done.** #31 and #32 are closed as
    `completed`, each with a comment carrying its evidence and its remaining follow-ups.
    #31's comment says in as many words that closing it does **not** upgrade this record's
    refusal to vouch for it — the tracker had simply fallen behind the tree, and that is
    what the close fixes. #34 is closed too, its review having been re-run (items 27 and 27b).
    **Now effectively done:** #33, #35 and #36 are closed, and #37 was closed in this pass with
    a comment carrying its evidence, its two accepted gaps and its remaining follow-ups.
    **Still open: #30 (the parent spec) alone**, plus #39 while its slice above is in review.
    So the tracker and the tree finally agree, and what keeps P5 open is the parent and the
    verification gaps below rather than a ticket nobody closed.
14. **The README still says P4's closeout is pending**, in two places — the P4 paragraph
    near the top and the phase list near the bottom both call the real agent run outstanding
    and say "P4 is implemented and not closed". `VERIFICATION-P4.md`'s own banner records
    the third pass that closed it (run `20261026-055333-saucedemo-e41fa3`, criterion 11,
    ticket #28). Not touched here because it is P4's claim to correct, not P5's; noted so it
    is not mistaken for a live blocker.

### Introduced by the audit log

35. **There is no read surface a customer can reach.** `GET /audit` is admin-gated and
    JSON-only; the question #30's story 26 poses — "who authorized writing this commit into
    our repo?" — is now answerable, but only by someone willing to call the API. A portal
    page is the obvious next step and is deliberately not in this slice (#37 names no portal
    surface). **Check both proxy lists when it is built**, per P5-04's lesson above.
36. **`limit` is a cap, not a cursor.** `GET /audit` answers the most recent 200 rows and
    there is no way to page back. Fine while the trail is young and read newest-first;
    a tenant with a year of deliveries cannot reach the start of it.
37. **Nothing prunes the trail, and nothing may.** `audit_log` grows without bound by
    design — it is the one table whose rows must not be deleted — so the retention story that
    `run_log` has (`prune_run_logs`) has no counterpart here and must not be given one
    casually. A real retention policy is a legal question before it is a technical one.
38. **Tenant purge will meet the trigger.** The spec's one permitted exception (#30, story 32,
    unbuilt) cannot delete these rows: the purge must
    `ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only` inside its transaction. That
    is noted in `app/audit.py` and in the revision, and it is deliberately an explicit,
    reviewable line rather than a quiet capability — but it does mean the purge is the one
    write that can erase part of the trail, and whoever builds it is choosing how much.

    **Resolved on 2026-11-04 by #47**, and the choice it made was "all of that tenant's and
    nothing else": `app/accounts/purge.py` disables the trigger for exactly its own `DELETE`
    and re-enables it in the same transaction, and it holds the only executable
    `DISABLE TRIGGER` in the tree. UAT 3 checked from `psql` — outside the application
    entirely, after a purge had run — that an `UPDATE` and a `DELETE` on another tenant's
    audit rows are both still refused. One thing this item did not anticipate:
    `ALTER TABLE ... DISABLE TRIGGER` needs table-owner rights, which the suite's role has and
    a reduced-privilege production role may not.
39. **`action` is `VARCHAR(20)` and `delivery.approve` is 16 characters.**
    `models._enum_col` is shared by every domain enum here, so the width is not this table's
    to pick freely. `test_every_action_fits_the_enum_column` turns a would-be runtime refusal
    on the first write of a longer action name into a failing test instead.
40. **Still nothing can be revoked.** Follow-up 1 said an audit trail of actions nobody can
    interrupt is half a control, and said to revisit it alongside #37. It was not revisited:
    the trail now records who did what, and a stolen access cookie still cannot be cut short
    inside its 15 minutes. The audit log makes the gap *visible* rather than smaller, which
    is worth something and is not the control.
41. **The CLI and the console cannot name a user, so their rows say `system`.** Three of the
    seven actions are reachable that way — `delivery.approve`, `infra.sync` and `target.reset`
    from `python -m app.delivery`, and `quota.change` from a console — and for those,
    #37's "naming the acting user" is met only in the sense that `system` is the honest name
    for "nobody was authenticated". **The fix belongs with follow-up 20's `--tenant` option**:
    the CLI needs to say who and as whom in one change, because a `--tenant` that did not also
    record an actor would make the trail *more* misleading, not less — attributing a named
    tenant's delivery to nobody.
42. **`audit.record` commits the session it is given.** Not its own transaction: at every call
    site the mutation has already committed, so the row is a second commit on the same
    session, and a caller with unrelated pending ORM work would have that committed as a side
    effect of writing an audit row. Constrained by convention and a docstring rather than by
    the code. A separate session would fix it and would cost the row its ability to see the
    mutation's own state; not worth it until something needs it.

### Introduced by the credential pair

43. **This process logs nothing below `WARNING`, and nothing noticed until now.** The API
    installs no logging configuration: uvicorn configures its own loggers and leaves the root
    logger without a handler, so every `app.*` `logger.info` in the API process — in
    `reaper.py`, `launcher.py`, `sandbox/dispatch.py`, `orchestrator/bus.py` and now
    `main.py` — is dropped before it reaches a terminal. The startup line was written at
    `INFO` and printed nothing at all against a real `uvicorn` boot, which is how this was
    found; that one line is now `WARNING` where it matters, and **the general problem is
    untouched**. It is the sibling of the `fileConfig` bug P5-03's review found (`alembic/env.py`
    disabling every `app.*` logger): both fail *open*, so no log assertion anywhere in this
    suite means what a reader would assume it means. The fix is a `dictConfig` at startup or
    a `--log-config` on the container's uvicorn, and it wants doing before anyone debugs a
    production run by its logs.

44. **A `QA_ENV` typo is silent in the other direction now.** `QA_ENV=prod` is correct and
    `QA_ENV=prdo` behaves identically, which is the safe direction and therefore invisible: a
    deployment that meant to say `dev` and misspelled it gets `Secure` cookies and a boot
    refusal, which it will notice, and one that misspelled `prod` gets the right behaviour by
    accident. Worth knowing before a third value is ever added, at which point the variable
    should be validated against a known set rather than compared to one string.

### Introduced by the prompt history surface

45. **`history` reads every revision in full, and there is no paging.** One query, one row per
    revision, each carrying a whole prompt body — the largest column in this schema. It is
    bounded by how often a customer edits one prompt, so it is fine today and would not be for
    a tenant who has tuned one prompt two hundred times. The route takes no `limit`, which is
    the same shape `GET /audit` has and the same note item 36 makes about it; the fix, when
    something needs it, is to answer the bodies for a page of revs rather than all of them.
46. **The panel has only ever been seen by jsdom.** `web/src/diff.test.js` and
    `Settings.test.jsx` cover the diff and the list, and nothing has opened this in a browser.
    Both P5 slices that *were* checked in a real browser found something the suite could not
    see, one of them the `/usage` proxy omission that made a whole panel invisible. The
    proxy lists were checked by reading them here, which closes that specific hole and not
    the class.
47. **No rollback, by decision.** "Restore revision 2" saves revision 2's body as revision 5,
    which is append-only-friendly, and #39 named it as the obvious next ask once history is
    visible. Deliberately out of scope; the `GET` does not make a sibling `POST` awkward.

### Found by the two-axis review of #30 (2026-11-04)

The review ran both axes against `c99cbef...HEAD`. Its documentation findings are fixed in
the same pass that wrote this section — `DESIGN.md` §6 still described a sandbox holding
`DATABASE_URL` and the `S3_*` credentials that P5-05 removed, §15 left three shipped rows
unmarked, and three docstrings plus `app/delivery/__init__.py` cited functions and an
environment variable that no longer exist. The items below are what it found that is **not**
documentation, and none of them is fixed.

48. **Story 32 — tenant purge — does not exist.** "deleting a tenant to purge that tenant's
    entire storage prefix and rows". There is no `purge` or `delete_tenant` anywhere in
    `server/app/`; `app/audit.py` and `app/models.py` each defer it in a comment naming this
    story, and no ticket of the seven covered it. Offboarding today is raw SQL plus an
    un-swept object-store prefix. **This is the largest missing piece of #30.**

    **Closed on 2026-11-04. Read the two paragraphs below in order**: the storage
    precondition (#40, #42) first, then the purge itself (#47). The first says "the
    purge is still unbuilt" because it was at that commit — a reader skimming should
    not stop there.

    **The storage precondition landed first (#40 and #42).** The two things the purge
    could not have been written against are done:
    `Storage` can delete a key and list a prefix with paging (#40, nothing calls either
    yet), and **artifacts have moved under the tenant prefix** (#42), so "that tenant's
    entire storage prefix" is now a true description rather than half of one.
    Artifacts were keyed `<run_key>/<path>` and a run key carries no tenant, so they sat
    outside the prefix blobs were already inside. That was never a leak — artifact rows
    carry `tenant_id` and the read guard filters them, and the content route resolves the
    row before touching the store — but it meant the purge had no single prefix to delete
    and an operator could not answer "what does this tenant have in the bucket?" from the
    bucket. `app/domain/store_keys.py` now owns the whole layout:
    `tenant/<id>/blobs/<sha>` and `tenant/<id>/runs/<run_key>/<path>`, with the separator on
    the prefix because `tenant/1` is a prefix of `tenant/11` and S3's `Prefix` is a byte
    comparison.
    Expand then contract, so a deploy breaks nothing: an artifact downloads by the `s3_key`
    on its own row, so legacy objects resolve unchanged, and `python -m app.artifacts rekey`
    moves them — per row, in the order copy → row → delete, which makes it both re-runnable
    and safe to interrupt at either point. **Not an Alembic revision**, and the reason is
    worth keeping: a revision can rewrite `artifacts.s3_key` but cannot move bytes, so it
    would point every existing row at nothing and turn a cosmetic inconsistency into an
    outage for every artifact in the system.
    Two things found on the way, both now pinned by tests. The discriminator between a blob
    key and an artifact key used to be "does it start with the run key?", which only worked
    while the two shapes had nothing in common; it is now `blobs/` versus `runs/`, which is
    a property of the layout rather than of the caller. And `rekey_all` first took
    `session_factory=SessionLocal` as a **default argument** — bound at import, so the
    test's monkeypatch did nothing and the pass connected to the *developer's* database and
    read 25 artifact rows from a real October run. It wrote nothing only because the fake
    store held none of those objects. `_no_dev_database`'s docstring claims every such
    caller takes an injectable factory; it resolves `db.SessionLocal` at call time now, and
    a test asserts the guard actually bites this module.
    **Still not proven**: nothing has run `rekey` against a real object store. The paging in
    #40 is driven through a botocore-shaped stub and the move through `FakeStorage`, so what
    is unproven is SeaweedFS's behaviour, not the logic. UAT 3 (#54) is where offboarding
    gets observed end to end.

    **Story 32 itself closed on 2026-11-04 (#47 / P5-15).** `python -m app.accounts
    purge-tenant --slug acme --confirm-slug acme`. The order is the design, because the
    requirement is that a half-finished purge is safe to run again: the store first, then
    the tenant's rows table by table, then the audit rows with the trigger off, then the
    `tenants` row, then the `purge_log` row. **The tenant row goes last** so the slug still
    resolves after any interruption and the same command finishes the job; deleting it first
    would leave an operator holding a slug that resolves to nothing and a bucket prefix
    nobody can name.
    **No tenant bypass, which is a deviation from what the ticket expected.** #47 says the
    purge "must use the documented bypass rather than quietly escaping the guard" — it needs
    neither, because #44 put ORM DELETE under the guard, so a delete issued inside
    `tenant_scope(tenant_id)` is *scoped by the guard* to exactly the rows being purged.
    That is strictly stronger than opting out, and it is what the allowlist's own comment
    asks for ("ask first whether the read can be done inside a tenant scope instead"). The
    bypass allowlist did not grow.
    The table list is derived from the mapped classes, so a table added later is purged
    without anybody remembering this module — the argument `install_tenant_guard` makes for
    the read filter, applied to the delete — and a test asserts the **fixture** populates
    every one of the twelve, because a purge test over two tables would pass while covering
    none of the rest.
    The audit trigger is disabled for one statement and re-enabled in the same transaction;
    a test asserts it is back on by trying to delete another tenant's row afterwards. That
    module holds the only `DISABLE TRIGGER` in the tree, and `app/audit.py` now says so.
    The gate is **naming the tenant twice** (`--slug` and `--confirm-slug`) rather than a
    `--yes`: a flag can be pasted into any invocation, a second spelling cannot be confirmed
    for the wrong tenant by accident, and unlike a prompt it stays scriptable.
    `purge_log` is the record that survives, and is deliberately not tenant-owned — a record
    belonging to the purged tenant would be deleted by the thing it records. **Two structural
    tripwires fired while building it, and both were right.** It first carried a `tenant_id`
    column, which `test_tenant_isolation_repo.py` fails for any mapped class not inheriting
    the mixin; the honest fix was renaming it `purged_tenant_id`, since it names a tenant
    that no longer exists rather than an owner, and exempting the tripwire would have spent
    the guarantee to save a word. Then `test_tenancy.py` fails any table without the column
    at all; that one needed a real exemption, so the test now carries a named set with a
    reason per entry — two so far, and of different kinds: `tenants` *is* the tenant, and
    `purge_log` is ours rather than any customer's.
    `_no_dev_database` caught the CLI's `create-tenant` ignoring its injected session factory
    on the way through, which is the third time that guard has earned its place in this phase.
    **Still not proven**: no purge has run against SeaweedFS or against a real tenant. The
    sweep is driven through `FakeStorage`, and `ALTER TABLE ... DISABLE TRIGGER` needs
    table-owner rights — which the suite's role has and a reduced-privilege production role
    may not. Both belong to UAT 3 (#54).

    **The two-axis review of the wave, applied the same day.** It found one defect that
    would have shipped and several documents claiming more than the code did.

    The defect: `app/accounts/__main__.py` had its `if __name__ == "__main__"` block
    *above* `_purge_tenant`, so `python -m app.accounts purge-tenant` raised `NameError` —
    the only documented path to story 32, broken, with a green suite, because every test
    calls `main()` after the import has finished. Worth recording how it is caught now,
    because the obvious test does not work: `--help`, on the parser or on a subcommand,
    exits inside argparse before any handler is referenced, so the module runs and exits 0
    with the defect in place. `tests/test_cli_entrypoints.py` asserts the invariant itself
    through the AST — the entry block is the last top-level statement — and was checked by
    reintroducing the bug.

    Two places where the purge claimed more than it did, both now true rather than
    reworded. It swept only `tenant/<id>/`, so an object still under the **pre-P5-10 key
    shape** — a deployment that never ran `rekey`, or one interrupted between updating a row
    and deleting the old object — would have stayed in the bucket for ever, with nothing
    left to derive its key from afterwards. The purge now reads its own run keys *before*
    deleting the rows and sweeps those prefixes too, which is also why `rekey`'s docstring
    no longer promises a `--prune-orphans` pass that did not exist. And the object count it
    recorded was the number **listed**, not the number deleted — and `Storage.delete`
    swallows failures by design, so `purge_log` could have claimed objects that were still
    in the bucket, in the one operation with no undo. Each key is re-checked now, survivors
    are logged by name, and the count is what actually went.

    One authorization gap: `authorize_artifact_key` accepted the legacy shape on **writes**
    as well as reads, so a run could still have created an object outside the tenant
    prefix. It takes `allow_legacy`, passed only by `blob_exists` and `read_blob`. The
    two-transport gateway test failed on that change, because it had been spelling a legacy
    key by hand and passing — which is the test doing its job a release late.

    Smaller, and each a case of one rule in two places: an empty `PUT /usage/caps` wrote a
    `QUOTA_CHANGE` row whose `before` equalled its `after` (no-ops are no longer audited,
    fixed in `set_tenant_caps` so the console path gets it too); the user-removal route
    picked 404 versus 409 by matching the exception's *message*, which is simultaneously
    user-facing prose, so rewording it for a human would have flipped a status code (there
    is a `NoSuchUser` type now); and the role probe was copied into two pages, with the
    first page's comment still saying it was the only one that wanted it (one `useIsAdmin`
    hook).
49. **Stories 1, 2 and 5 — no tenant or user administration.** `app/domain/audit.py` states
    there is no user-administration surface at all, which is why `Action` has no
    `USER_ADD`/`USER_REMOVE` and why #37 could not record two of the mutations its own spec
    lists; `app/domain/quotas.py` states there is no `create_tenant` in the application.
    Separately, `repo.set_tenant_caps` has **no route and no role check**, so story 5's "only
    authorized users can … change quotas" is unenforced — `AdminDep` reaches `deliver`,
    `reset`, the `pat` writes and `/audit`, and nothing else.

    **The quota half closed on 2026-11-04 (#45).** `PUT /usage/caps`, behind `AdminDep`:
    under `/usage` on purpose, so it inherits the read's entry in both proxy allowlists
    rather than needing a new first segment in each (a path missing from them answers 200
    with the SPA shell, which is how P5-04's own panel shipped invisible). No tenant in the
    path — `set_tenant_caps` writes to `current_tenant_id()`, so "change another tenant's
    caps" is a request the surface cannot express rather than one it checks for, and a test
    smuggles an id into the body to say so.
    An omitted cap and an explicit `null` stay different requests, through
    `model_fields_set` into the existing `UNSET` sentinel: collapsing them is how raising
    one cap silently deletes the other, which already happened once at the function. The
    portal gets the editor inline with the gauges, shown to an admin only — presentation,
    with the 403 as the enforcement, and the panel renders the caps the **server** returned
    rather than the ones that were typed.
    Role gating is driven through *real* auth and real roles in `tests/test_auth.py` rather
    than an overridden dependency, and the audit row is proven to name the acting admin
    rather than `system` for the same reason. The commit is proven across two sessions.
    **A conflict resolved rather than ignored**: `set_tenant_caps`'s docstring argued
    against ever having this route — "a tenant that could raise its own caps would not have
    caps". That is an argument about a *platform ceiling*, which these columns are not;
    story 5 makes the quota an intra-tenant authorization question. The docstring now says
    so, and says a real ceiling would be a second limit above this one that nothing in P5
    asks for yet. **Worth deciding before there are paying customers.**
    Story 5's remaining half is user administration (#46): there is still no way to make
    the admin who would press this, other than SQL.
50. **Story 6 fails open, not closed.** "a missing filter is a bug that fails closed rather
    than a leak". `tenancy.current_tenant_id()` returns `DEFAULT_TENANT_ID = 1` outside any
    scope, so an unscoped path — a route that forgets `require_auth`, or future background
    work — reads and writes **tenant 1's** rows rather than failing. Relatedly
    `install_read_guard` filters `SELECT` only, as its own docstring says: ORM `UPDATE`/
    `DELETE` and raw SQL are unguarded, so fail-closed does not hold on the write side
    either. Changing the resolver to raise will surface every unscoped call site at once and
    should be its own slice, with `reaper` already known to need the bypass.
51. **Story 22's token outlives its sandbox across a pause.** `control.service.authorized_run`
    treats `paused` as live, so a token copied before a pause stays valid though the sandbox
    it was minted for has been destroyed. Recorded as a trade-off in item 33; it is also a
    deviation from "rejected after the run ends" and belongs in the same list as that story.

    **Closed on 2026-11-04 (#48).** `runs.sandbox_attempt`, carried by the token and moved on by
    `repo.pause_run`; see the struck-through trade-off in §P5-05 for the shape and for the
    two things the first attempt got wrong. Proven at the service
    (`tests/test_control_service.py`: refused during the pause, still refused after the
    resume, and the resumed attempt's own token works) and over HTTP
    (`tests/test_internal_api.py`: 403 on the pre-pause token, 200 on the freshly minted
    one, which is the transport a container actually uses). The four gate exemptions are
    unchanged and are asserted to be: a sandbox torn down at a pause still flushes its last
    log lines and still records what it spent.
    **What is not proven here**: a resume end to end *in a container*. Both dispatch paths
    mint through the one function (`control.factory.mint_for_run`, which reads the row), and
    the HTTP transport is covered above, but the Docker-backed resume is still a
    `QA_REQUIRE_DOCKER=1` check rather than something the default suite runs. UAT 2 (#53) is
    where that is meant to be observed.
52. **The HTTP control-plane seam is never exercised by the real pipeline.** #30 says "The
    run-scoped API is consumed by both the thread and docker paths so the suite exercises
    it." `control.factory.local_for_run` hands the thread path `LocalGateway`, which calls
    the service in process, so `app/internal_api.py` and `app/control/http.py` are covered
    by their own tests and by the container checks in §P5-05 — but no suite run drives the
    HTTP seam through `drive_run`.

    **Closed on 2026-11-04 (#49).** `server/tests/test_pipeline_over_http.py` drives
    `launcher.drive_run` with an `HttpGateway` over the real router through `TestClient`,
    and with the `GatewayLogBus` a sandbox actually writes through — so hydrate's blob
    reads, the step boundary's blob writes and revision commit, the artifact sweep's upload
    and index, and the log all cross the HTTP seam in one composed run. The assertions are
    deliberately the ones `tests/test_docker_sandbox.py` makes about a real container: the
    run row, the step rows, the revisions, the artifacts and the log. No Docker, so it runs
    in the default suite.
    Two things it pins that an operation-by-operation test cannot: the last line a run
    emits (`=== run <key> completed ===`) arrives *after* the final status transition and
    is asserted to be in the log, which is the `publish_log` exemption observed rather than
    reasoned about; and the bus's `close` is part of the path, which is where losing the
    final batch was a real bug.
    **Still not covered, and named rather than implied**: the container, the image and the
    network. `TestClient` is every layer of this except the wire, and the Docker-backed
    tests remain the only thing that proves the rest — which is the honest measure of what
    is left, since P5-05's record says four real bugs here were found by running a
    container and none by the suite.

    The test asserts both halves of each upload — the `artifacts` row **and** the bytes
    under its key in the store — because the two fail separately: an index with no object
    is what a store adapter bound to the wrong one of its two interfaces produces, which is
    one of the four bugs P5-05 found by running a container.
53. **`test_a_resume_that_changes_nothing_does_not_manufacture_a_version` is flaky, and it
    fails in the liveness gate.** Observed on 2026-11-04: one full-suite run failed it with
    `RunNotLive: run 1 is completed; its token no longer authorizes anything` from
    `control.service.authorized_run`, and two further full-suite runs — one of them on an
    otherwise identical tree — passed. Test ordering is deterministic here (`addopts = "-q"`,
    no randomizer), so order is not the variable. The mechanism is visible in the test:
    `_PausesAfter` requests the pause *after* `Step.PLAN` returns, and unlike its sibling
    `test_a_resumed_run_gets_its_session_back_before_the_first_step` — which asserts
    `status is RunStatus.PAUSED` before resuming — this test resumes without checking. When
    the pause does not take, the run runs to `completed`, `resume_run` does not restore it,
    and the next `_drive` is refused by the liveness gate several calls later. So the
    assertion that fires is unrelated to the thing that broke.
    Two separate pieces of work: **assert `PAUSED` before `resume_run`**, which costs one
    line and makes the failure name its own cause; and then find why a requested pause is
    sometimes not honoured, which is the part that might be a real defect in the pause path
    rather than in the test. Worth noting that item 51 is about the same gate reading run
    status, and that this flake was found by a full-suite run rather than by the targeted
    run — the test passes in isolation every time.

    **Answered and closed on 2026-11-04 (#50).** The diagnosis above is wrong in its
    conclusion and right about the symptom: the pause is honoured, every time. Routing all
    five of the file's resumes through a helper that asserts `PAUSED` first — the one-line
    piece of work this item asked for — the assertion has never fired, in the targeted run
    or the full suite.

    **The repeated-run evidence the criterion asked for**, since the original item was
    reported off run counts and a closure that did not give any would be weaker than the
    report. On the finished tree: **three consecutive clean full-suite runs**
    (`QA_REQUIRE_DB=1 uv run pytest`, 1177 → 1183 → 1183 passed as the later tickets added
    tests), plus three consecutive runs of `tests/test_sandbox_session.py` alone while the
    fix was being made. The targeted file had been failing on *every* run before the fix,
    not intermittently — this machine is slow enough that the run's last two archives
    straddled a second boundary every time, which is why "passes in isolation every time"
    had stopped being true and why the cause was reproducible at all.
    One honest caveat about method: two full-suite runs taken in the middle of this work
    failed with 15 and 7 failures and dozens of errors, and that was **test-database
    contention** — a review sub-agent was running its own `pytest` against the same
    `qa_test` database at the same time, and the fixtures `TRUNCATE` between tests. Worth
    writing down because it is a convincing-looking way to misread a green tree as broken,
    and the suite gives no hint that a second runner is present.

    The real cause is that **the session archive was not versioned on its content**.
    `agent_session.save` built the archive with `tarfile.open(path, "w:gz")`, and that
    writes the *current time* into the gzip header's MTIME field. The digest it then hands
    `index_artifact` is therefore a function of the clock at one-second granularity: two
    saves inside the same second produce identical bytes and two either side of a tick do
    not. So `assert artifacts[0].version == before` fails exactly when the run's last two
    archives straddle a second boundary — reproducible here on the targeted run, which is
    why "passes in isolation every time" stopped being true as soon as the machine was a
    little slower. The fix writes the gzip header with `mtime=0` and an empty filename, the
    only two fields in it that are not content; the tar members keep their own mtimes, so a
    restored session's files still carry the times the agent left them with.

    `RunNotLive` was a red herring, and chasing it found a second real defect.
    `launcher._persist_session` skips a run that is no longer live, and its docstring says
    it checks "rather than attempted-and-swallowed so that a run ending normally does not
    log a failure every time". It did both: the check went through `control.run_state()`,
    which is *behind* the liveness gate, so the guard raised `RunNotLive` for precisely the
    runs it exists to skip and was caught by the `except` it was written to avoid. Every
    successful run logged a WARNING with that traceback — which is what appears in this
    item's captured output, and what the report read as the failure. It now asks
    `control.run_status()`, the first of the four operations the service exempts from the
    gate, for the reason the service gives: a read of one field, made after the run ended.

    Lesson, and it is item 53's own: **a digest is only a version if it is a digest of the
    content.** The test said "identical bytes are not a new version" and the bytes were
    never identical; nothing in the suite asserted the premise, so the rule was tested
    against an archive format that quietly disagreed with it. There is now a test that
    saves an unchanged session directory twice a real second apart and asserts the bytes
    match, and its mirror asserting that a session written into *does* bump the version.

---

## Closing

Three tickets are in. The first two moved P5 from "every table has a `tenant_id`" to "a
second customer can exist"; the third moved it from "a second customer can exist" to "a
second customer can deliver as themselves". The claim worth making about each is narrow and was checked by
hand against a real database, because the suite structurally cannot make it: for `users.email`
and again for `projects.name`/`targets.app`, that **the old global unique is replaced, not
left beside the new composite one** — no test in the suite asserts a constraint's absence.

P5-02 also produced the phase's first real evidence that is not a green suite: a second
tenant that exists, logged in over HTTP against the live stack, refused every one of the
other tenant's rows in both directions, and allowed to register an app slug the first tenant
already holds. The largest remaining holes are the ones next to the code rather than in it:
no admin surface to create tenants without SQL (item 6 — closed since, by #46), a 30-day credential travelling
without `Secure` (item 2), and artifact URLs the refresh dance cannot reach (item 3).

Two lessons worth carrying. The first, from `105e9b7`, in P4's spirit: the `EventSource`
regression was found by reading the code for callers that bypass the fetch wrapper, **not** by
the suite and not by either review axis — item 3 is the one of that family still open. The
second, from this slice: **the guard nearly introduced the bug it exists to prevent.**
`with_loader_criteria` takes lambda SQL, and a `current_tenant_id()` call inside the lambda
would have been evaluated once and baked in, serving every later request the first one's
tenant. SQLAlchemy happens to refuse that exact form with an explicit error; had it merely
worked, the suite would have been green — every test in it reads as one tenant at a time —
and the first two-tenant request in production would have crossed the boundary. The test that
would have caught it is the one in §Verified that alternates tenants in a single process, and
it exists because the mechanism was spiked before it was trusted.

P5-03's own lesson is smaller than P5-02's and worth the same kind of attention, because
both are about a guarantee that a green suite cannot see. The redaction regex was named
`_BARE_GITHUB_TOKEN`, and that alone failed a P4 test: `app/delivery/errors.py` is imported
by code a sandbox runs, and the structural assertion is on the module's *source text*, so a
constant's name is a mention. The fix was a rename. What it demonstrated is that the
credential rule in this repo is enforced by reading code rather than by running it — which
is the only way to enforce "this cannot happen" — and that such a test will therefore fire on
things that are not bugs. The temptation in that moment is to loosen the assertion. The
right move was to rename the constant and write down why, which is now a comment beside it.

The same reading-rather-than-running produced the slice's one genuinely structural decision:
`app/delivery/__init__.py`'s lazy export table keeps a module out of a sandbox's import
graph, but the table itself lives in a file every sandbox loads, so an entry naming
`decrypt_pat` would have handed anything running in there the exact string to `getattr`. No
test demanded that; the test demanded only that the module not be imported. It was removed
from the table because the weaker guarantee was not the one worth having.

The largest hole this slice leaves is not in the code. **Where `QA_KMS_KEY_ID` is unset —
every deployment today — `QA_SECRET_KEY` protects every stored PAT as well as every session
cookie**, so follow-up 2's missing `Secure` flag and follow-up 1's unrevocable token now sit
next to a secret that also decrypts customer credentials (follow-up 21). The envelope is
real; the key is in the wrong place until that variable is set.

**P5 is open.** Six of seven tickets are implemented in the tree (#31–#37 less #30's parent
role), all six are now closed on the tracker, and #39 — a read surface #36 deliberately left
out — is in with them. What keeps the phase open is partly evidence and **partly missing
code**, and the earlier version of this paragraph claimed only the first. The evidence half:
**#36 still has no verification section**, #37 and #39 have been seen only by their suites,
and the follow-up list below has grown rather than shrunk. The code half, found by the
two-axis review of #30 recorded in items 48–52: **story 32's tenant purge does not exist at
all**, stories 1 and 2 have no tenant- or user-administration path, and story 6's
fail-closed guarantee does not hold — `current_tenant_id()` answers the seeded default
outside a scope, which fails *open onto tenant 1* rather than closed. Those are not
deferrals this record had written down; they were simply absent, and #30 cannot close over
them.

Two things changed in the closing paragraph above rather than in the list. The largest hole
this phase left was **not in the code** — `QA_SECRET_KEY` protecting every stored PAT as well
as every session cookie — and that one is now closed: the key moved to `QA_ENVELOPE_KEY`, a
deployment with no key refuses to boot, and follow-up 2's missing `Secure` flag went with it,
because the two compounded. The envelope was always real; the key is no longer in the wrong
place. **`QA_KMS_KEY_ID` is still unset everywhere**, and that is still the production answer.

The lesson of this pass is the same one P5-02, P5-03 and P5-05 each recorded in their own
terms, and it arrived again from a direction nobody was watching. The suite proved the startup
check refused a misconfigured deployment and that it logged which key arrangement it had built.
Booting the thing under a real `uvicorn` showed the log line printed **nothing at all**: this
process installs no logging configuration, so an `app.*` record below `WARNING` never reaches
a terminal, and `caplog` installs a handler, which is why the test passed. A line whose entire
purpose was "a deployment running the in-process key can be seen to be running it" was
invisible in precisely that deployment. That is follow-up 43, it is the sibling of the
`fileConfig` bug P5-03's review found, and it is the fourth time in this phase that **running
the real thing found what the suite structurally could not**.
