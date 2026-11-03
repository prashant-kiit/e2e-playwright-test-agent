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

> ## P5 is OPEN. This record is partial.
>
> Three of seven tickets are complete **in the tree**; four are not started. Tree state and
> tracker state are two separate facts and the tracker is the source of the second one
> (`docs/agents/issue-tracker.md`): #31, #32 and #34 are closed `completed` — #34's
> two-axis review was re-run and acted on (§Follow-ups items 27 and 27b), which is what its
> close was waiting on. #30, #33 and #35–#37 are open.
>
> | Ticket | State in the tree |
> |---|---|
> | #31 P5-01 — users table + session-resolved `current_tenant_id()` | Implemented (`e492a9d`, review fixes `06a3acd`). **Not independently re-verified in this record** — see the note below |
> | #32 P5-02 — tenant-scoped reads + tenant-scoped uniqueness + fail-closed | **Complete.** The `users.email` half plus token expiry/refresh landed first (`105e9b7`); the enforced read path and the `projects`/`targets` composite uniqueness landed in the slice below, and were exercised against a live stack with a second real tenant |
> | #34 P5-03 — per-tenant KMS-encrypted PATs, scope/expiry/fail-loud | **Complete, reviewed and closed.** The envelope, the per-target `Tools` binding, the save-time scope check, the portal surface and the structural credential tests. The two-axis review found two real credential leaks (the PAT in `Tools.__repr__`, a data key reachable in a `SealError`) and one half-true acceptance criterion (a git-transport 401/403 did not mark the credential invalid); all fixed — see §Follow-ups 27b. **Still not seen against a real KMS, a real GitHub token or a browser** — see §"What is covered only by fakes" |
> | #33 P5-05, #35 P5-04, #36 P5-06, #37 P5-07 | Not started |
>
> **What this record does and does not claim.** The three §"Verified" sections below each
> cover one slice, and every line in them was observed. P5-01's own evidence lives in its two
> commit messages; it has not been re-run here, so this record does not vouch for it.
> **P5-02's isolation claims were checked against a second real tenant** over HTTP against
> the live stack. That tenant was deleted again afterwards, so the evidence was observed
> and then reverted and no second tenant exists in the dev database now. **P5-03's claims
> rest on the suite, two by-hand migration runs on throwaway databases, and a two-axis
> review that was re-run and acted on**; it has not met the live stack, a real KMS key or a
> real GitHub PAT. A real browser has still not
> been part of any P5 verification.

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

## Decisions recorded during this phase

| Decision | Why |
|---|---|
| **`users.email` is unique per tenant, not globally** | An address identifies a person *inside* a tenant. Globally unique meant two customers who both employ the same contractor could not both have an account, and the first tenant to claim an address locked every other tenant out of it. P5-01 shipped the global version knowingly and flagged it |
| **Login takes a tenant slug** | The direct cost of the above: an email alone no longer names an account. The alternatives considered and rejected were resolving across tenants and demanding a slug only on collision (a login whose required fields change with other tenants' data), and keeping email globally unique (declining the change) |
| **The slug is globally unique** | A handle that named two tenants would move the ambiguity up one level rather than remove it |
| **The seeded slug is a constant, not an env knob** | A `QA_SEED_TENANT_SLUG` was written and then removed in review: only the migration read it, so setting it prefilled the login form with a slug no tenant had and made a test fail from ambient environment. The slug is echoed by the form and the tests, so all three must agree |
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
hygiene.

### Introduced by the expiring session

1. **Nothing can be revoked before it expires.** Stateless by choice, so logout clears
   cookies on that browser but would not stop a copy already taken, and a leaked
   `QA_SECRET_KEY` forges any user's session until the key is rotated. The place to add a
   token table is marked in `app/auth.py`. **Revisit if P5 ever needs to kick out a user, or
   alongside #37's audit log** — an audit trail of actions nobody can interrupt is half a
   control.
2. **Neither cookie sets `Secure`.** Pre-existing (P5-01 set none either), but it now guards
   a 30-day credential rather than a week-long one, and `samesite="lax"` does not substitute.
   Needs an env-conditional flag so dev over plain HTTP still works. **This is the highest-value
   item in the list.**
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

21. **Rotating `QA_SECRET_KEY` destroys every stored PAT**, wherever `QA_KMS_KEY_ID` is unset
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

6. **The tenant-admin surface does not exist.** No way to create a tenant, set its slug, or
   invite a user — `repo.create_user` was deliberately removed in `06a3acd` as out of scope.
   Until it lands, a second tenant can only be made with SQL, which is why "a second real
   tenant" sits in §fakes. **This is the gating item for most of the rest of P5.**
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
    Still open: #30 (the parent spec), #33 and #35–#37, all `ready-for-agent`.
14. **The README still says P4's closeout is pending**, in two places — the P4 paragraph
    near the top and the phase list near the bottom both call the real agent run outstanding
    and say "P4 is implemented and not closed". `VERIFICATION-P4.md`'s own banner records
    the third pass that closed it (run `20261026-055333-saucedemo-e41fa3`, criterion 11,
    ticket #28). Not touched here because it is P4's claim to correct, not P5's; noted so it
    is not mistaken for a live blocker.

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
no admin surface to create tenants without SQL (item 6), a 30-day credential travelling
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

**P5 is open: three of seven tickets are done (#31, #32, #34), and four are not started.**
