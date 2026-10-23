# 02: Schema — tenants, revisions, file_index, and `tenant_id` on every table

**Spec:** [SPEC-P2-revisions.md](../../SPEC-P2-revisions.md) (*Schema*)

**What to build:** the tables P2 writes into, and the tenant column that makes P5 a data backfill
instead of a migration across the whole system. Nothing reads these tables yet and no behavior
changes — this ticket is verifiable on its own by the migration chain running from zero and the
schema agreeing with the models.

Three new tables:

- **`tenants`** — seeded with exactly one row by the migration.
- **`revisions`** — one row per committed snapshot of a target's tracked tree: the owning tenant
  and target, a per-target monotonic `rev` numbered from 1, the `parent_rev` it descends from
  (null for a baseline), the `tree_hash`, the run that produced it (nullable, because a manual
  snapshot has no run), an `author`, a `delivered_sha` that stays null for the whole of P2, and a
  creation timestamp. Unique on (target, rev).
- **`file_index`** — keyed by (revision, path), carrying the blob key and the size. Derived data
  that exists so the portal can list and display files; nothing may treat it as authoritative.

Two decisions this ticket implements, both of which depart from DESIGN.md as written and must be
amended there in the same change:

- **Optimistic concurrency is the unique constraint on (target, rev), not a version column.** The
  `occ_version` column DESIGN §3 lists is deliberately *not* added: committing revision N+1 with
  parent N loses the insert if someone else got there first, so an extra column would
  misdescribe where the check happens.
- **No `bundle_key`.** Git bundles presuppose a per-run worktree with its own history, which
  arrives with the sandbox in P4. P2 adds only columns it writes, so that the
  models-match-migrations check stays a meaningful signal.

`tenant_id` goes on every other table too — projects, targets, runs, run steps, artifacts and
the app lock — added non-null with a server default so existing rows backfill, with that server
default dropped in the same migration. Application code never relies on the default: it sets the
column from a single "current tenant" helper, which is the one call site P5 replaces.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] One Alembic revision adds the three tables, adds `tenant_id` everywhere non-null, backfills
      existing rows, drops the backfill default, and seeds the single tenant row.
- [ ] The migration chain runs from an empty database, and the existing autogenerate check finds
      no remaining difference between models and schema — including no lingering server default.
- [ ] A structural test asserts that every table declared on the ORM metadata has a non-null
      `tenant_id` column. This is the assertion that makes P5 a backfill; it must fail if a
      future table forgets the column.
- [ ] Every existing insert path sets `tenant_id` explicitly through the shared helper, not by
      relying on a database default.
- [ ] A revision row cannot be inserted twice for the same (target, rev) — asserted, since this
      is the phase's concurrency control.
- [ ] `delivered_sha` exists and is never written by any code in this phase.
- [ ] DESIGN.md §3 amended: the unique constraint is named as the OCC point, `occ_version` and
      `bundle_key` are recorded as not-built-in-P2 with the reasons.
- [ ] No change to run behavior, delivery, artifact collection or any portal page. `make ci-test`
      green.
