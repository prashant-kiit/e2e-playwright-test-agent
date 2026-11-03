# SaaS Architecture Design

Target architecture for turning this harness into a multi-tenant SaaS. Supersedes the
current single-operator, filesystem-backed portal described in
[README §0](../../README.md#0-admin-portal-web-ui).

The product is a hosted service: a customer registers an app under test and a GitHub
repo, writes user stories in the portal, and the agent plans, generates, heals and
**runs** Playwright tests. The customer buys *results*; delivered test code is the
artifact, not the product. Everything a user does happens in the portal — never in an
IDE, never via shell.

---

## 1. Principles

The whole design exists to make one guarantee structurally true:

> **Postgres is the single arbiter of truth. Every other store is either *ephemeral*
> (rebuilt from truth, so it cannot drift) or *write-only output* (whose state is
> recorded back into truth, so it is never read back to learn what is true).**

Five invariants enforce it:

1. **One authoritative holder per fact.** Postgres owns *which revision is current*.
   SeaweedFS owns *the bytes of a revision* (immutable, content-addressed, so it cannot
   diverge from its own hash). GitHub owns nothing we trust.
2. **Sync is one-directional, at explicit boundaries.** Four arrows only —
   `DB→sandbox` (hydrate), `sandbox→SeaweedFS` (upload), `sandbox→DB` (commit revision),
   `DB→GitHub` (deliver). No arrow merges. There is no merge logic anywhere in this system.
3. **Blob before row.** Upload bytes first, commit the referencing row second. Orphan
   blobs are swept by GC; a row never points at a missing blob.
4. **Revisions are immutable and content-addressed.** Nothing is updated in place. A
   crashed run commits nothing and leaves the last good revision intact; retries converge.
5. **"In sync?" is a Postgres query** — compare the head revision's hash against the
   recorded `delivered_sha`. Never a cross-store diff, never a `git fetch`.

Git is used as a *tool* (inside the sandbox, and to deliver), never as the versioning
datastore. Version history, lineage, access control and audit live in Postgres.

---

## 2. Stores

| Store | Role | Lifetime |
|---|---|---|
| **Sandbox + its own git** | Execution. The agent reads, writes and commits the worktree natively. | Ephemeral, per run |
| **SeaweedFS** | Durable bytes: content blobs, git bundles, run artifacts | Permanent (GC'd) |
| **GitHub (customer repo)** | One-way delivery projection | Customer-owned |
| **Postgres** | The arbiter: head pointers, lineage, config, run state, audit | Permanent |

Postgres stores **no file content** — only pointers, metadata and state.

---

## 3. Data model

```
tenants(id, name, created_at)
users(id, tenant_id, email, role, …)
        UNIQUE(tenant_id, email)                  -- an address identifies a
                                                  -- person *inside* a tenant (P5)
projects(id, tenant_id, name)
        UNIQUE(tenant_id, name)                   -- per tenant, not global (P5)
targets(id, tenant_id, project_id, app, name,
        baseURL, locators, agentNotes,            -- config, versioned
        targetRepo, targetBranch,
        github_pat_ciphertext, pat_expires_at, credential_state)
        UNIQUE(tenant_id, app)                    -- per tenant, not global (P5)
        -- the credential trio landed in P5-03: ciphertext (a KMS-wrapped data
        -- key travels with it), the expiry GitHub reported, and
        -- absent|valid|invalid. Decrypted only in the control plane, inside
        -- the delivery Tools seam -- never in a sandbox, never in a log (8)

revision(id, tenant_id, target_id, rev, parent_rev,
         tree_hash, produced_by_run, delivered_sha,
         author, created_at)
         UNIQUE(target_id, rev)                   -- the OCC point; see below

file_index(revision_id, path, blob_key, size)     -- DERIVED, never authoritative

runs(id, tenant_id, target_id, story_id, state, run_key, …)
run_steps(run_id, step, state, started_at, ended_at)
artifact_index(id, tenant_id, run_id, step, name, blob_key, content_type, size)
prompts(id, tenant_id, name, body, rev)           -- defaults seeded from code
audit_log(id, tenant_id, actor, action, target, before, after, at)
```

**A revision is a whole-worktree snapshot**, one row per committed step boundary —
exactly mirroring a git commit. This is the single OCC point per target. `file_index`
exists only so the portal can list and display individual files; it is derived from the
tree and is never the source of truth.

`tenant_id` appears on **every** table from day one (see §13).

**Two columns this table was first specified with were not built, amended here when P2
met code:**

- **`occ_version` — not added. `UNIQUE(target_id, rev)` is the OCC point.** Committing
  revision N+1 inserts `rev = N+1` with `parent_rev = N`, so a concurrent committer
  loses on the unique constraint. A version column alongside it would misdescribe where
  the check actually happens, and nothing would read it. (With one live run per target
  the contention is theoretical today; the constraint is what keeps it theoretical.)
- **`bundle_key` — deferred to P4, with bundles.** Git bundles (§5) presuppose a per-run
  worktree with its own history, which arrives with the sandbox in P4; there is nothing
  in P2 whose history is worth bundling. P2 adds only columns it writes, which is what
  keeps `test_migrations_match_the_models` a meaningful signal rather than a column
  inventory.

  > **P4 built the sandbox and left this deferred, now with its own reason rather than a
  > forward reference.** Nothing in P4 reads a bundle. Revisions reconstruct from deduped
  > content blobs; a crash commits nothing by design (invariant 4), so there is no mid-step
  > history worth recovering; and what a resumed run actually needs is the **agent
  > session**, which P4 persists as a run artifact (§5) — a tar of the CLI's session store,
  > not a git history. The worktree is still a plain directory with no git in it, so a
  > bundle would mean introducing a second history for the sake of a column nobody reads,
  > which is the thing this design rejects. P2's rule — add only columns something writes —
  > is the one being kept.

**The head revision is derived, not stored**: it is the row with the greatest `rev` for
a target. There is no mutable `targets.head_revision_id`, because revisions are
append-only and a second place recording "which is current" is a second thing that can
be wrong.

`delivered_sha` was added by P2 and left null for that whole phase, because delivery
still worked off the filesystem there. **P3-07 writes it**, and it is the only writer:
after a successful push, the commit the push produced is recorded on the revision it
delivered. When the branch already held those bytes and no commit was created, the
existing sha is recorded anyway — "delivered" is about the bytes, not about whether we
happened to create a commit.

That satisfies invariant 5. "In sync?" is now one query: the head is *delivered* if it
carries a `delivered_sha`, otherwise it is *N revisions ahead* of the newest revision
that does. **Bootstrap state is derived from the same column** — a target is bootstrapped
if any of its revisions carries a sha — so the `ls-remote` and the worktree diff are both
gone, and the answer is the same for everyone whether or not GitHub is reachable.

---

## 4. The tracked tree

What is versioned, bundled and delivered — versus what is a run artifact:

| In the tracked tree | Run artifacts (never in the tree) |
|---|---|
| `user-stories/` | `node_modules/` (never stored; reinstalled on hydrate) |
| `specs/` (plans) | `test-results/` |
| `seed.spec.ts` | `playwright-report/` |
| `tests/` | traces, videos, screenshots |
| `playwright.config.ts` *(generated — P3)* | `session.jsonl` |
| `package.json` + lockfile | |
| `.gitignore` | |
| `.github/workflows/playwright.yml` | |

`session.jsonl` is deliberately an **artifact keyed by run**, not tree content: Q2's
resume needs it, but it must never reach a customer repo.

**`playwright.config.ts` is generated — P3-02 implemented it.** P1 and P2 tracked it as
the hand-maintained file it then was, and snapshotted its bytes like any other tracked
file. It is now rendered from the target row by `render_playwright_config` in
[render.py](../../server/app/delivery/render.py), re-rendered on every hydrate and
re-rendered again before every ingest scan, so it has exactly one author. The
hand-maintained copy at the repo root is deleted. It is single-target, which is what makes
the project names bare — `chromium`, not `<app>-chromium` — and what stops a project name
or a test path from reaching another customer's tests.

**A tracked-tree file's source location is not its delivered location — P3-02 separated
them.** Infra was delivered by identical path through P2: the list named a relative path
and delivery read that same path out of the workspace, so a template's source *was* its
destination. For `.github/workflows/playwright.yml` that put harness **output** at a path
GitHub Actions treats as a live workflow of the harness repo, and a push to `master` made
this repo install browsers and run the suite discovered from `apps/*` against live
external sites — a flaky red X for tests that are not the harness's. The authoritative run
belongs in the customer's repo, where the PR is (§7); the harness repo is the one place it
must never execute.

An infra entry therefore carries `(source, destination)` — `InfraEntry` in
[render.py](../../server/app/delivery/render.py) — and the templates live under
`server/app/delivery/templates/`, inside the server package so an API image needs no
mounted repo to deliver one. The workflow's source is `workflows/playwright.yml`, which is
not a path GitHub Actions reads; its destination is unchanged, and so are its bytes and
its `on:` triggers. The generated config is simply the entry whose source is a renderer
rather than a file.

Two things not to do: do not neuter the `on:` triggers in the harness copy instead — the
delivered copy inherits the dead trigger and then never runs in the customer's repo
either, which is the failure the move exists to prevent; and do not reintroduce a
hand-maintained `playwright.config.ts` anywhere, because a second author for a generated
file is a drift surface with nothing to gain.

**Config is not a tree file.** `app.json` no longer exists and is never delivered — it
is SaaS-internal, held in columns on `targets` and validated on the write path by
[target_config.py](../../server/app/target_config.py). At hydrate, config is *rendered*
out of Postgres:

- `baseURL` is inlined into a generated `playwright.config.ts`
- `locators` and `agentNotes` are injected into the agent's **prompt context**

Generated files are regenerated on every hydrate and overwrite whatever is there; agent
edits to them are discarded at ingest. A config change therefore surfaces as a visible
tree diff → new revision → visible in the delivery commit.

---

## 5. Run lifecycle

```
1. Hydrate     Postgres head revision → fetch blobs from SeaweedFS → build git worktree
               → render generated config → npm ci from lockfile (shared cache)
2. Run         Agent works and commits inside the sandbox. Nothing durable yet.
3. Sync-out    (at each step boundary, in this order)
                 a. upload content blobs → SeaweedFS        [blob before row]
                 b. commit Postgres revision N+1
                    (parent = N, OCC check head == N)       ← truth advances here
4. Teardown    Destroy the sandbox.
```

A **full git bundle** is written at run end and at each pause-reap — not per revision,
since a bundle carries full history and per-step bundling would store it N times.
Per-revision reconstruction comes from the deduped content blobs.

**Delivery is not part of this lifecycle.** See §7.

### Run states

```
queued → hydrating → running → paused(live) → reaped → resuming → running
                                                     ↘ abandoned (retention expiry)
       → succeeded | failed | stopped
```

- **Pause** keeps the sandbox alive for a short grace window (5–10 min idle), then
  snapshots (git bundle + `session.jsonl`) to SeaweedFS and reaps it. Resume rehydrates
  and re-seeds the Claude session from the persisted `session.jsonl` rather than a live
  process. A SaaS cannot pay for idle sandboxes.

  > **Amended by P4: pause reaps immediately, with no grace window.** The route that
  > pauses a run destroys its container there and then (`app/api.py`) and moves the row
  > to `paused` itself, because the process that would otherwise have done it is the one
  > just killed; the handle is cleared with it, and the reaper's sweep for idle sandboxes
  > is the net under that rather than the way it normally happens. Waiting for the next
  > step boundary would be a grace window by another name — an agent holding a browser
  > is minutes of billing away from one. The reason it costs nothing is P3: resume
  > already re-hydrates from the head revision and that path is tested, so an idle
  > sandbox's only advantage — a warm worktree — is one the harness no longer needs. "A
  > SaaS cannot pay for idle sandboxes" is the same sentence it always was; the grace
  > window was only ever buying the worktree.
  >
  > What a paused run must not lose is the **agent session**, and that is now explicit
  > rather than incidental: `--resume` worked only because the CLI's session store
  > happened to sit on the host that started the run. The session directory is archived
  > as a run artifact under a reserved name (`<run_key>/agent-session.tar.gz`) **at every
  > step boundary** and at the end of every run, and restored into the next container
  > before the CLI is invoked. At the boundary and not only on the way out, because a
  > sandbox killed outright archives nothing: the boundary is the last moment the session
  > is known good, so a pause — like a crash — costs the exploration of the step it
  > interrupted and no more. **A failed restore does not fail the run**: it continues
  > without session continuity and says so in the log, because the tree is the carrier of
  > the work and the exploration is only context. Not a git bundle: see §3 on
  > `bundle_key`.
- **Crash** commits nothing (invariant 4). The run goes `failed` with the last committed
  revision intact and resumes **from the last completed step boundary**, never mid-step —
  that is what keeps "retries converge" true.
- **Reaped snapshots are retained 7 days**, after which the run becomes `abandoned` and
  its snapshot is GC'd.

### Concurrency

**One active run per target**; the rest queue. One whole-tree head per target plus OCC
means parallel runs would collide, and resolving that requires merge logic this design
rejects. Parallelism lives *across* targets and tenants, which is where throughput
actually matters.

> **Not yet implemented: the queue.** "The rest queue" is the target design, not current
> behavior. Today a second run on a target with a live run is **rejected**, not queued:
> `repo.start_run` raises `RunConflict` → HTTP 409, and the portal shows "This app already
> has a live run." There is no queue table and no scheduler anywhere in the server.
>
> The serialization half *is* real and is the subtlest correct code in the system: the lock
> row is taken `FOR UPDATE`, a lease expired by a crashed run is reaped in place, `pause_run`
> keeps the lock while clearing the lease, and the reaper skips `PAUSED` runs so a deliberate
> pause is never mistaken for a crash. Leave that trio alone; adding the queue means adding a
> scheduler *above* it, not changing it.
>
> **P5-04 is the first thing to take that advice**: the per-tenant quota check runs in
> `repo.start_run` before the lock row is touched, and the trio is byte-for-byte what it was.
> It is the shape a queue would go in too. One consequence is worth stating because it is a
> deliberate ordering and not an accident: a tenant that is over its allowance *and* asking
> for a busy app is told about the allowance, since "wait for this app" is advice that cannot
> help when nothing could be started anyway.

---

## 6. Sandbox and isolation

**Container-per-run** on a managed job scheduler (K8s Job / Fargate / Cloud Run Job),
from a prebaked image carrying the `claude` CLI, Node and Playwright browsers (~1–2 GB).
JS deps come from `npm ci` against the tree's lockfile with a shared npm cache — the
lockfile stays the source of truth for dependencies while the slow-changing, expensive
part is amortized in the image.

### The credential rule

> **No GitHub credentials ever enter a sandbox.**

The agent explores the **customer's live web app**, so page content can carry prompt
injection into an LLM that is writing and executing code. A PAT inside that blast radius
is an exfiltration path. Because delivery is a separate, human-approved step (§7), the
push does not need to happen in the sandbox at all: the sandbox produces a bundle, and
the **control plane** performs the approved push.

### Egress

**Default-deny, with a per-run allowlist**: the target's registered host, the Anthropic
API, and the npm registry. Link-local and private ranges (`169.254.169.254`, RFC1918,
`localhost`) are blocked outright. The registered `baseURL` is validated to resolve to a
public address **at save time and again at run time** (DNS rebinding). Open egress plus
an LLM plus your cloud network is not a combination that can be patched later.

**Built by P4, with two things this paragraph did not say.**

*Enforced at the network layer, not by environment.* The sandbox sits on an internal
network with no default route, and an allowlisting `CONNECT` proxy — one per run, holding
that run's allowlist — is the only way out. An allowlist the agent can unset is a
convention and not a control, so unsetting `HTTP_PROXY` closes the only door rather than
opening the internet. **The proxy resolves, not the sandbox**: an internal network cannot
reach a resolver and `CONNECT` carries a hostname, so name resolution happens in the one
process that also enforces policy, and the tunnel is opened to the address that was
verified rather than to the name again. One function builds the allowlist from the
target's row (`app/sandbox/egress.py`), so "what can this run reach?" is one place to
read, and a run against one target structurally cannot reach another's host. The agent
runtime's telemetry and error reporting are **disabled by environment rather than
allowlisted**, so the list stays the length of what a run genuinely needs.

*The allowlist includes the internal stores, and that is a decision with a successor.*
Postgres and the object store are reachable from the sandbox network by name, because
hydrate reads the head revision and ingest commits N+1 — those **are** the run. So a
sandbox holds `DATABASE_URL` and the `S3_*` credentials, and that is **accepted exposure
for this phase, deliberately**. The credential rule above is specifically about GitHub,
for a stated reason: delivery is human-approved and happens in the control plane, so the
push need not happen where the agent is — and after P4 it cannot, because no sandbox
environment, image or compose service carries a GitHub credential and no module reachable
from the sandbox entrypoint can read one (both enforced by structural tests). The store
credentials have no such argument available to them; what they have is a successor.
**P5 replaces them with a narrow, run-scoped internal control-plane API**, where the token
that authorizes one run's target is the same mechanism that authorizes one tenant's data.
Bundling that into P4 would have been building P5's tenant scoping early and worse.

### Quotas and timeouts

Enforced at enqueue: per-tenant **concurrent-run cap** and **monthly run quota**
(`tenants.max_concurrent_runs`, `tenants.monthly_run_quota`; P5-04).
Enforced at runtime: **per-step and per-run wall-clock timeouts** that reap the sandbox,
plus a **per-run token budget**. The wall-clock timeout is the one that matters — a wedged
agent holding a browser open is the most expensive failure mode in the system.

**The two kinds of breach do not end the same way, and this section used to say they did.**
A *runtime* breach → run `failed` with an explicit reason, last good revision intact: the
work was accepted and started, and the run is the record of it. An *enqueue* breach → a
typed **rejection** (`repo.QuotaExceeded` → HTTP **429**), and **no run row at all**. A
refused start that wrote a `failed` run would be reporting work that never happened, and it
would have spent the monthly quota it was just refused for — so the next attempt would be
refused for the sake of a run nobody ran. 429 rather than the 409 a busy app gets, because
"your tenant is out of allowance" and "this app already has a live run" have different
remedies and an operator who cannot tell them apart can act on neither.

`NULL` on either column means **no cap**, not a cap of zero — but a tenant does not *arrive*
that way. Both columns carry a **server default** (`3` and `500`), kept rather than dropped,
because there is no `create_tenant` in the application at all: a tenant comes from a migration
seed or from raw SQL, and a server default is the only thing on both paths. Without it, "bound
each tenant so one cannot starve the platform" held only for tenants somebody had remembered
to configure, and nothing remembered. An unmetered plan is still expressible by writing
`NULL` on purpose, and the enqueue then skips counting entirely for that tenant.

This is a deliberate departure from the rule that a column's server default is dropped in the
revision that adds it (P2's `tenant_id`, P5-03's `credential_state`). That rule stops a column
acquiring a value nobody chose; here the default *is* the choice and has to outlive the
revision, because its job is to apply to rows inserted by code that does not mention these
columns.

Both caps are the **tenant's**, counted across all of its apps, and the monthly one counts
runs *started* in the calendar month — a failed run still spent its sandbox, and a quota
that only counted successes would make "retry until it works" free. A rejection names one
cap (it is one sentence to one person), while the portal's usage panel asks about each cap
independently, because both can be full at once.

---

## 7. Delivery

Delivery is a **separate, human-approved control-plane action**, never automatic.
"Truth advances" and "we wrote to a customer's repo" must never be the same event.

```
operator approves in portal
  → control plane decrypts the tenant PAT (never in a sandbox)
  → ensure_bootstrapped(): if targetBranch lacks infra, push the bootstrap commit first
  → squash the agent's many sandbox commits into ONE delivery commit
  → append it to branch qa/<STORY_ID>-<slug>  (no force-push)
  → open or update the PR into targetBranch
  → record delivered_sha on the revision row + write audit_log
```

- **Squash means collapsing the agent's internal commits into one commit per approved
  delivery** — *not* rewriting the customer's branch. Re-delivery appends another commit.
  Force-pushing into someone else's repo destroys PR review threads and is a support
  ticket waiting to happen.
- **Bootstrap is folded into the first delivery**, under the same approval — one approval
  means "set up the repo and deliver this story," which is what the operator intends. A
  separate, also-approved **"re-sync infra"** portal action pushes infra/workflow updates
  to already-bootstrapped repos.
- `delivered_sha` is **null until a human approved**, which is what makes "in sync?"
  genuinely informative rather than always-true.
- **Customer drift is a non-event.** If they edit our branch, the next delivery appends
  over it and records the fact. Their own branches are theirs; we only open PRs into them.

### Test execution

Tests run in **our sandbox**, and that is the source of all portal results and artifacts.
The CI workflow is still pushed to the customer repo as a convenience so their own PRs
get checks — but portal data never depends on it, because reading their repo back would
break invariant 5.

---

## 8. Credentials

Per-tenant GitHub PATs (a GitHub App is the better long-term answer; PATs were chosen for
launch).

- **Envelope encryption**: ciphertext in Postgres, data key wrapped by a cloud KMS key.
  Decrypted only in the control plane at push time. Never logged, never in a sandbox.
- **Scope validation at save time**: a live API call confirms `repo` + `workflow`
  (bootstrap pushes `.github/workflows/playwright.yml`); reject otherwise.
- **Expiry**: store `expires_at` when GitHub reports it; warn in-portal before it lapses.
- **Fail loud**: on 401/403 at delivery, set `credential_state = invalid`, fail the
  **delivery only**, and surface it. Never silently retry. A credential problem must
  never cost a customer a run — the results are already durable.

**Landed in P5-03.** Three things about the shape are worth having written down, because
none of them was obvious from the paragraph above:

- **The envelope wraps a *data key*, never the PAT.** `app/envelope.py` generates a random
  AES-256 key per secret, encrypts the PAT under it locally, and asks the KMS only to wrap
  the 32-byte key. So the PAT is never in a KMS request and therefore never in the
  provider's audit log of those requests, rotating the KMS key re-wraps small keys instead
  of re-encrypting rows, and no secret can outgrow the KMS payload limit. The sealed form is
  one self-describing string (`qa-env1$wrapped$nonce$ciphertext`), so the column is text and
  the format can gain a version without a migration.
- **`Tools` is bound to one target before it can push.** There was one `token` on the
  delivery seam, read from `GITHUB_PAT` once per process. It is now what
  `tools.for_app(app)` resolves from that target's row, and `for_target(tools, app)` is the
  context manager every entry point uses — because binding and "GitHub rejected this
  credential" are two halves of one decision, and five entry points each able to do the
  first and forget the second is how the fail-loud rule would quietly stop holding. An
  unbound seam raises a `CredentialError` naming the call that was missed rather than an
  `AttributeError` from inside a push. Four paths deliberately do **not** bind:
  `is_bootstrapped`, the already-bootstrapped arm of `ensure_bootstrapped`, and the
  `--dry-run` arms of bootstrap and push. Those answers are Postgres and blob-store reads,
  and needing a credential for them would be needing the network by another name. `plan_reset`
  is the dry run that *does* bind, because it makes two authenticated GitHub calls — the test
  is whether a path dials out, not whether it writes.
- **A credential rejection is one outcome, whichever layer refuses us.** The PAT travels in
  the clone URL as well as in the REST client's header, and `push_artifacts` clones *before*
  its first REST call — so git's HTTPS transport is where most 401/403s actually land, and it
  reports them as a failed subprocess rather than a status code. `GitError.is_credential_rejection`
  classifies git's own stderr, and `for_target` translates a match into the same
  `CredentialError` the REST client raises: the same sticky `credential_state = invalid`, the
  same 502. A non-fast-forward push or a missing ref is re-raised untouched — marking a working
  credential invalid would send a customer to rotate it for nothing (P5-03 review).
- **A refusal at save time is 422, not 502.** A token missing `workflow`, an empty paste, a
  revoked token: each is the operator's input being refused while they can still fix it, and
  a different paste is the fix. 502 stays for GitHub refusing a credential *at delivery*,
  which is a different event with a different remedy. `CredentialRejected` and
  `CredentialError` are separate classes for exactly this reason — one class for both would
  have told a customer with a scope typo that GitHub was down.
- **`GITHUB_PAT` is retired, not kept as a fallback.** One operator token is not *any*
  tenant's credential: every delivery it authored went into a customer's repository as the
  same identity. Nothing is migrated into the new columns either — sealing that one token
  per target would silently give every customer the same credential under a per-tenant
  name. A deployment that was delivering before this revision saves a PAT per target
  afterwards, and the portal says so.

---

## 9. Storage layout and GC

```
tenant/<tenant_id>/blobs/<sha256>
tenant/<tenant_id>/bundles/<run_id>.bundle
tenant/<tenant_id>/artifacts/<run_id>/<step>/<name>
```

Content-addressing is scoped **per tenant**, not global. Cross-tenant dedup is worth
almost nothing (different customers' tests don't collide) and would make blob existence a
side channel. Every read is authorized: **the Postgres row naming the key must belong to
the requesting tenant.** A blob is never served by key alone.

### Garbage collection

"Blob before row" guarantees orphans, and because blobs are content-addressed **one blob
may be referenced by many revisions** — so lifecycle-based deletion would corrupt live
revisions. GC is therefore a scheduled **mark-and-sweep**:

> A blob is deletable only if **no** `revision` / `file_index` / `artifact_index` row
> references it **and** it is older than a **24 h grace period** (longer than any run, so
> in-flight uploads are not raced).

Cascades: an `abandoned` run drops its bundle and artifacts but **keeps committed
revisions** (those are truth); tenant deletion purges the whole prefix. The reference scan
and the grace period are both load-bearing — dropping either turns GC into a data-loss bug.

---

## 10. Observability and audit

Pushing to customers' repos on a human's approval makes the audit trail a **product
requirement**, not ops hygiene. "Who approved writing this commit into our repo, and
when?" must be answerable from a table, not from logs.

- **`audit_log`** (immutable) covers every control-plane mutation: delivery approvals
  above all, plus PAT save/rotate, infra re-sync, and reset.
- **Structured JSON logs** correlated by `run_id` / `tenant_id`, scrubbed of secrets.
- **Metrics**: run and step duration, token spend, sandbox minutes, queue depth, delivery
  success rate.
- The SSE log bus stays for the live run view; `session.jsonl` remains the durable
  per-run record.

**Amended by P4: the live log is a Postgres table.** The sentence above said "the SSE log
bus stays", and it does — but the bus behind it stopped being an in-process dictionary,
because P4 executes a run in a container that cannot publish into the API's memory. It was
already the wrong place for two reasons that had nothing to do with containers: a restart
erased the history of every run that had ever streamed, including finished ones, and only
the replica that started a run could stream it.

```
run_log(run_id, seq, line, at)      PRIMARY KEY (run_id, seq)
```

`LogBus` is a protocol with two implementations and one read model — append a line, read
forward from a cursor. The in-memory one serves the thread path and the tests; the
Postgres-backed one serves anything out of process. `Emit` did not change shape, so the
driver, the runners and the step-boundary hook were untouched by the move. `seq` is counted
by the **one writer per run** rather than by a database identity, so a second writer loses
on the primary key; the API never publishes on behalf of a run it does not execute.
`/runs/{id}/events` reads forward from a cursor with the keepalive it already sent, so a
late subscriber gets the run's real history and any replica can stream any run.

**These rows are the live view and its recent history, not the archive.** `session.jsonl`
is still the durable per-run record, and the reaper loop prunes `run_log` past a retention
window (7 days by default, matching §9's reaped-snapshot retention) — because an
append-only table nobody prunes is the slowest kind of outage.

---

## 11. Module map (shell → Python)

All shell tooling becomes Python returning typed results. No `gh`, no `jq`; `git` and
`npx` remain as subprocesses (we orchestrate git, we don't reimplement it), and GitHub is
reached over REST via `httpx`.

Two scope notes on "drop `gh` and `jq`" (decision 20), both settled in P1:

- It means **our** tooling. The `jq` in `.github/workflows/playwright.yml` stays: that file
  is harness *output*, pushed into each customer's repo, where it builds the results table
  inside GitHub Actions — an environment that has `jq` and does not have our Python. Removing
  it there would break a customer's CI to tidy a dependency we don't ship. (Where that file
  *lives* in our repo is a separate question, settled in §4: from P3 it is a template under
  `server/app/delivery/templates/`, not a live workflow of the harness repo.)
- Dropping `gh` removed its `gh auth token` fallback with it. `GITHUB_PAT` (environment or
  `.env`) is now the **only** credential source. That is an intentional behavior change, not
  a regression to be "fixed" later: an operator who only ran `gh auth login` now gets a
  `CredentialError` naming `GITHUB_PAT`.

| Today | Becomes |
|---|---|
| `scripts/check-bootstrapped.sh` | `delivery.ensure_bootstrapped()` — no longer user-facing (§7) |
| `scripts/bootstrap-target.sh` | `delivery/bootstrap.py` |
| `scripts/push-artifacts.sh` | `delivery/push.py` |
| `scripts/reset-target.sh` | `delivery/reset.py` — destructive, portal-gated, double-confirm |
| `scripts/qa-lib.sh` | `delivery/git.py`, `delivery/github.py`, `delivery/render.py` |
| `scripts/run-stories.sh` | **dropped in P1** — not ported. See the note below |
| — | new `sandbox/`: `hydrate.py`, `ingest.py`, `lifecycle.py` |

Three of the four shell tools stop being user-facing entirely — they become control-plane
functions behind portal actions.

### `run-stories.sh` was dropped, not superseded

An earlier version of this table called it "already superseded by `orchestrator/driver.py`".
That was wrong, and the capability gap is worth stating plainly:

| `run-stories.sh` did | the driver does |
|---|---|
| run **several stories of one app in parallel** (`-j`, default 3) | runs **exactly one** story per run |
| skip stories already generated, `--force` to redo | no concept of "already generated" |
| `--dry-run` preview of what would run | no preview |
| write a batch summary (`runs/<ts>-<app>/summary.md`) | per-run rows in Postgres |

**Batch operation is gone.** Starting a second run on a target that already has a live one is
*rejected* — `repo.start_run` takes the app's lock row `FOR UPDATE`, reaps an expired lease,
and otherwise raises `RunConflict` (HTTP 409). Reinstating batching is its own piece of work,
not a P1 fix: see the queue note in §5.

---

## 12. What changes from today

- `apps/<app>/*` files → config in `targets`; stories, plans, seed and tests become
  SeaweedFS blobs indexed by `revision`. **Done (P3.)** `apps/` and `app.json` are deleted.
- Prompts → code-shipped defaults seeded into Postgres, tenant-overridable, versioned.
  **Half done (P3):** they are code-shipped package data under `server/app/prompts/`, read
  from the installed package. The `prompts` table, tenant overrides and versioning are P5.
- The long-lived mounted repo (`QA_REPO_ROOT`) disappears. **Done (P3)**, and the sentence
  that followed it here was too strong, so it is corrected rather than deleted: removing the
  mount removed the *shared authoritative* disk — no replica needs another replica's disk to
  answer a question or start a run — but it did **not** make the API horizontally scalable on
  its own. The worktree and the run directory are local scratch and the SSE log bus is
  in-process, so a live run is still pinned to the replica that started it. That is P4's job,
  and `tests/test_no_repo_mount.py` is what keeps the mount from coming back in the meantime.
- The runner moves out of a thread in the API process ([launcher.py](../../server/app/launcher.py))
  into a container-per-run sandbox. **Done (P4.)** It inherited exactly what P3 left it:
  hydrate, ingest and teardown as three plain functions the launcher composes around the
  pipeline, a worktree path travelling through `StepContext`, and dependency install
  isolated as the single step a prebaked image makes fast. The composition was not
  rewritten — `drive_run` is one function with two call sites, a daemon thread
  (`QA_SANDBOX=thread`, for CI and development) and a container
  (`QA_SANDBOX=docker`, `python -m app.sandbox.run <run_id>`), and a structural test fails
  if a second pipeline appears. The egress and isolation half of §6 came with it: an
  internal network, a per-run allowlisting proxy, no GitHub credential, and per-step,
  per-run and per-spend limits.

  The thread path is kept on purpose. It is the same composition invoked without a
  container, it keeps CI fast and token-free, and it is what lets the existing suite prove
  the behaviour did not move when the work did.
- Delivery stops being a shell script a human runs and becomes an approved portal action.
  **Done (P1 for the mechanism, P3 for the reads):** it works through one injected `Tools`
  value, pushes a materialized head revision, and records `delivered_sha`.

---

## 13. Migration plan

Five shippable phases, each safe on its own:

| Phase | Work | Why this order |
|---|---|---|
| **P1** | Shell → Python, in place. No architecture change. | Lowest risk, immediately testable |
| **P2** | Add `revision` / `file_index` / blob storage; **dual-write** from the existing `apps/` filesystem, which stays authoritative | Proves the revision model against real runs with zero behavior change — the safety net is still there |
| **P3** | Flip reads to DB + blobs; `apps/` becomes derived; delete the repo mount | API becomes stateless |
| **P4** | Extract the runner into container-per-run; bring §6 isolation and egress with it | Needs P3's stateless API |
| **P5** | Multi-tenancy: quotas, per-tenant PATs, tenant-scoped reads | Mechanical once the above is stable |

**Carry `tenant_id` on every table from P2 onward**, defaulted to a single tenant. That
makes P5 a backfill rather than a schema migration across the whole system.

P2 is the phase that de-risks everything else.

### The two seams, and keeping them single

P1 added no new seam. It touched two, and both must stay single:

- **Delivery** — the injected `Tools` value (GitHub client + git + token + workspace) that
  every delivery function takes. All four commands and every API route go through it, and it
  is what the tests substitute. No delivery function may reach for credentials or git
  outside it.
- **Step boundary** — `run_pipeline`'s one injected callable, fired after each completed
  step. Artifact collection is composed behind it in the launcher.

**P2's sync-out (upload blobs → commit revision N+1) composes behind that same single
callable.** Do not add a second driver parameter for it: the driver keeps exactly one
injection point, and anything that needs to happen at a step boundary is composed into that
one hook by the caller. Recorded here because the natural way to write P2 is to add a
`sync_out=` next to `collect=`, and that is the thing not to do.

---

## 14. Decision log

| # | Decision |
|---|---|
| 1 | Revision = whole-worktree snapshot, one per committed step; `file_index` is derived |
| 2 | Pause → snapshot and reap after a grace window; resume re-seeds the session from `session.jsonl` |
| 3 | Tests run in our sandbox; customer CI is a convenience, never a data source |
| 4 | Delivery is split from sync-out and human-approved |
| 5 | Per-tenant encrypted PATs (GitHub App deferred) |
| 6 | Tracked tree defined; `session.jsonl` is a run artifact, not tree content |
| 7 | Container-per-run; **no GitHub credentials in a sandbox**; control plane pushes |
| 8 | Default-deny egress with a per-run allowlist; block private/link-local ranges |
| 9 | Crash commits nothing; resume at step boundary; 7-day reaped-snapshot retention |
| 10 | Squash = one delivery commit appended to the story branch; never force-push |
| 11 | KMS envelope encryption, scope validation at save, expiry warnings, fail-loud on 401 |
| 12 | Config rendered from Postgres at hydrate; `app.json` is never delivered |
| 13 | Content blobs per revision; full bundle at run end and each reap |
| 14 | Prebaked browsers in the image; `npm ci` from the lockfile with a shared cache |
| 15 | Serialize runs per target; parallelism across targets and tenants |
| 16 | Bootstrap folded into the first delivery; separate "re-sync infra" action |
| 17 | Per-tenant concurrency caps and quotas; per-step/run wall-clock timeouts; token budget |
| 18 | Per-tenant key prefixes; authorize every blob read through Postgres |
| 19 | Mark-and-sweep GC with reference scan + 24 h grace period |
| 20 | Shell → Python module map; drop `gh` and `jq` |
| 21 | Immutable `audit_log` for every control-plane mutation |
| 22 | Five-phase migration; `tenant_id` carried from P2 |
| 23 | Infra entries carry `(source, destination)` from P3; a delivered workflow is never a live workflow of the harness repo |
| 24 | `get_launcher` stays the one dispatch seam; one `Scheduler` protocol behind it, Docker the only implementation (P4) |
| 25 | Egress enforced at the network layer: an internal network plus a per-run allowlisting proxy that resolves (P4) |
| 26 | The live log is a Postgres table read by cursor; `session.jsonl` is still the durable record (P4) |
| 27 | Pause reaps immediately — the route that pauses destroys the container, not the next step boundary; the **agent session** is a run artifact archived at every boundary, and a failed restore loses context rather than the run (P4) |
| 28 | **Tenant-scoped reads are enforced, not remembered**: one `do_orm_execute` listener adds the filter to every ORM SELECT of a `TenantOwned` row, so a query cannot forget it — only explicitly opt out, and the opt-outs are a pinned allowlist. Installed at import with no off switch, because a flag would let the suite prove isolation in a configuration production does not run in (P5) |
| 29 | Another tenant's row is **404, not 403**: a reader who does not own a row must not be able to tell "exists, not yours" from "does not exist", or the small integer ids become an inventory of what other tenants hold (P5) |
| 30 | Background sweeps **iterate tenants** rather than reading across them. A sweep is not one query (`reap_expired` reads locks, then each lock's run, then frees it), so an unfiltered outer query would need every nested read opted out too — and the opt-out would become the normal case in the one module that touches every tenant's rows. One tenant's failure does not stop the others: the reaper is the only thing that frees an app lock (P5) |
| 31 | **The envelope wraps a data key, not the PAT.** A random AES-256 key per secret, encrypted locally, with only the 32-byte key sent to the KMS — so the PAT is never in a KMS request or its audit log, key rotation re-wraps keys instead of re-encrypting rows, and no secret can outgrow the KMS payload limit (P5-03) |
| 32 | **The delivery seam is bound to one target before it can push.** `for_target(tools, app)` resolves that target's credential *and* marks it invalid if GitHub rejects it, because those are two halves of one decision; an unbound seam fails loud naming the call that was missed. Four paths do not bind — `is_bootstrapped`, the already-bootstrapped arm and the two `--dry-run` arms — because their answers are Postgres and blob-store reads; `plan_reset` binds because it dials out. A rejection reaching us as a git transport failure rather than a REST 401/403 is translated to the same `CredentialError`, so it is one outcome with one status and one sticky state (P5-03) |
| 33 | **A credential refused at save time is 422; one refused at delivery is 502.** Separate exception classes, because one class for both would read to a customer with a scope typo as a GitHub outage — and the two have different remedies (P5-03) |
| 34 | **`GITHUB_PAT` is retired, not kept as a fallback, and nothing is migrated into the new columns.** One operator token is not any tenant's credential; sealing it per target would give every customer the same identity under a per-tenant name (P5-03) |
| 35 | **An enqueue quota breach is a rejection, not a run.** Checked in `repo.start_run` *above* the `AppLock` trio and before any row is written, so a refusal leaves no run and no lock: a `failed` row would report work that never happened and would spend the monthly quota it was just refused for. 429, distinct from the 409 a busy app gets, because the remedies differ (P5-04) |
| 36 | **A rejection names one cap; the usage panel asks about each.** `quotas.breach` returns the single kind to refuse with, monthly first, because a tenant that is both out of quota and at its concurrency cap must hear the one that is true for longer — telling them to wait cannot help. Both caps can be full at once, so the portal reads two independent predicates rather than deriving its gauges from the rejection (P5-04) |
| 37 | **A tenant arrives bounded, and unmetered is something a plan asks for.** The caps carry a server default that is deliberately *not* dropped, because no `create_tenant` exists — a tenant comes from a seed or from raw SQL, and only a server default covers both. `NULL` still means no cap; it just has to be written on purpose now. A cap of `0` is lockout, which is how a tenant is suspended (P5-04) |

---

## 15. Deferrals, with their reasons

Each of these is a decision, not an omission. They are listed together so a later reader
does not have to reconstruct which were considered.

| Deferred | To | Why |
|---|---|---|
| **Git bundles and `bundle_key`** | not scheduled | Nothing reads a bundle. Revisions reconstruct from deduped content blobs, a crash commits nothing by design, and a resumed run needs the *agent session* — which P4 persists as a run artifact — rather than mid-step git history. The worktree is a plain directory; a bundle would mean a second history nobody reads (§3) |
| ~~**Per-tenant concurrency caps and monthly run quotas**~~ | ~~P5~~ | **Done (P5-04).** Enforced in `repo.start_run` above the `AppLock` trio, as a typed 429 rejection that writes no run row; `NULL` means unmetered. See §6 |
| **The run queue and batch runs** | not scheduled | A second run on a busy target is refused with a 409, not queued. The queue is a scheduler *above* the lock trio, and §5 says to leave that trio alone |
| **A K8s or Fargate scheduler** | when there is a cluster | The dispatch seam exists for them; Docker is the one implementation P4 ships, and the dev stack's socket mount is what the seam exists to replace (§6) |
| **The run-scoped internal control-plane API** | P5 | It would remove `DATABASE_URL` and the `S3_*` credentials from a sandbox. It is the same mechanism as P5's tenant-scoped reads, and building it earlier would have meant building that worse (§6) |
| ~~**KMS envelope encryption of PATs**~~ | ~~P5~~ | **Done (P5-03).** See §8 |
| **Prompts in Postgres with tenant overrides** | P5 | A per-tenant mechanism, and there is one tenant (§12) |
| **A GitHub App replacing PATs** | not scheduled | §8 names it the better long-term answer; PATs were chosen for launch and remain the credential after P5-03. The envelope, the scope check and the fail-loud path are all independent of which kind of credential it is |
| **`audit_log`** | P5 | Delivery approvals are the thing it exists to record, and the approving actor is a per-tenant user (§10) |

### What P5 inherits

- **The dispatch seam**, so tenant-aware placement and quotas are enforced where a run is
  dispatched rather than inside the lock trio.
- **One allowlist builder**, so a tenant's allowlist is a change of input rather than of code.
- **A log table already carrying `run_id` and `tenant_id`**, so tenant scoping is a filter.
- **The store-credential decision**, written down in §6 with its successor named, so P5
  inherits a decision rather than a surprise.
