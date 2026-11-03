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
> Two of seven tickets are in the tree, and **no ticket in P5 has been closed on the
> tracker** — #31 through #37 are all still `OPEN`, including #31, whose code shipped.
>
> | Ticket | State in the tree |
> |---|---|
> | #31 P5-01 — users table + session-resolved `current_tenant_id()` | Implemented (`e492a9d`, review fixes `06a3acd`). **Not independently re-verified in this record** — see the note below |
> | #32 P5-02 — tenant-scoped reads + tenant-scoped uniqueness + fail-closed | **Partial.** Only the `users.email` half, plus token expiry/refresh, which the ticket never asked for (`105e9b7`). The enforced read path and `projects`/`targets` composite uniqueness are untouched |
> | #33 P5-05, #34 P5-03, #35 P5-04, #36 P5-06, #37 P5-07 | Not started |
>
> **What this record does and does not claim.** The §"Verified on 2026-11-03" section below
> covers `105e9b7` only, and every line in it was observed. P5-01's own evidence lives in its
> two commit messages; it has not been re-run here, so this record does not vouch for it.
> Nothing in P5 has been exercised against a live stack, a real browser or a second real
> tenant — the whole phase so far is green suites plus one by-hand database replay.

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

---

## What is covered only by fakes

Named here as P1–P4 each named theirs, so the next ticket inherits a list rather than an
impression.

- **A second real tenant.** Every cross-tenant assertion inserts a second `Tenant` row in a
  test session. No second tenant has been created through a UI, logged into in a browser, or
  given a target and a run of its own.
- **The expiry, at its real length.** Proven at a 1-second lifetime. Nothing has observed a
  session actually lasting 15 minutes and then renewing, or a refresh cookie reaching 30 days.
- **The stream reopen.** `RunDetail.stream.test.jsx` drives a stub `EventSource`. A real
  browser hitting a real 401 on `/runs/:id/events` and recovering has not been observed.
- **The login form.** Covered by jsdom. No browser has typed a slug into it.
- **The migration against real data.** Replayed from zero, where `users` holds exactly the
  one seeded row. A database with several users, or two users whose emails collide across
  tenants, has not been migrated — and the `downgrade` deliberately fails loudly in that case
  rather than picking a winner, which is also unobserved.
- **P5-01 in its entirety** — see the banner. Its claims rest on its commits.

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
   **Relevant to #35's quotas and #34's PATs if either becomes role-gated.**
5. **A cold load of the login page fires one pointless `POST /auth/refresh`.** `api.me()`
   401s when nobody is logged in, which trips the refresh dance. Harmless, one round trip,
   but it puts a 401 and a failed refresh in the log of every first visit.

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
9. **#32 is only part-done.** Its two larger halves remain: the single enforced
   tenant-scoped **read** path (so a new query cannot silently forget the filter) and
   composite uniqueness for `projects.name` and `targets.app`. The `users.email` work in
   `105e9b7` is the pattern for the second; the first is the ticket's real weight and is
   untouched. **Do not close #32 on the strength of this commit.**
10. **Review suggestions declined, recorded so they are decisions and not oversights:**
    extracting a `_CookieSpec` to collapse `set_access_cookie`/`set_refresh_cookie` (the two
    differ in a way the docstrings carry — only login calls the second); splitting `auth.py`,
    which now holds password hashing, token minting, the cookie contract and the FastAPI
    dependencies (a pre-existing shape, and a refactor wider than this change); and giving
    the tenant slug its own type rather than passing `str` (the repo passes primitives for
    `email`, `app` and `name` throughout).
11. **`read_access` reads `ACCESS_MAX_AGE` off the module** so the agreed test seam can
    monkeypatch it. Correct for production too — one place sets the window — but it means an
    expiry test asserts through a module attribute rather than a parameter. Flagged by the
    standards review; left as the user-chosen seam.

### Harness hygiene

12. **`SPEC-P5-multi-tenancy.md` and `.claude/harness/issues/p5/README.md` are both
    zero-byte files**, committed empty in `82542c6` ("add initial multi-tenancy
    specifications and README for P5"). Every prior phase has a real spec file; P5's
    spec lives only in issue #30. Either write them or stop referring to them.
13. **No P5 ticket has been closed on the tracker**, including #31, whose code shipped two
    commits ago. The triage labels still read `ready-for-agent`.
14. **The README still says P4's closeout is pending**, in two places — the P4 paragraph
    near the top and the phase list near the bottom both call the real agent run outstanding
    and say "P4 is implemented and not closed". `VERIFICATION-P4.md`'s own banner records
    the third pass that closed it (run `20261026-055333-saucedemo-e41fa3`, criterion 11,
    ticket #28). Not touched here because it is P4's claim to correct, not P5's; noted so it
    is not mistaken for a live blocker.

---

## Closing

P5's first slice is in, and the one claim worth making about it is narrow: the thing most
likely to have made it silently pointless — an orphaned global unique on `users.email`
sitting beside the new composite one — was checked by hand against a real database in both
directions, because no test in the suite asserts a constraint's absence.

Everything else here is a green suite. The phase has not met a browser, a second real
tenant, or a session that lasted more than a second, and the three largest holes are not in
the code that shipped but next to it: no admin surface to create the tenants this is all
for (item 6), a 30-day credential travelling without `Secure` (item 2), and artifact URLs
the refresh dance cannot reach (item 3).

One lesson worth carrying, in P4's spirit: the `EventSource` regression in this change was
found by reading the code for callers that bypass the fetch wrapper, **not** by the suite and
not by either review axis. Shortening a session's life breaks every long-lived connection
and every browser-initiated request in the app, and those are exactly the paths a unit test
does not hold. Item 3 is the one of that family still open.

**P5 is open. Two of seven tickets are in the tree, and #32 is partial.**
