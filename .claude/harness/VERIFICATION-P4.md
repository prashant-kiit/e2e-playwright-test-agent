# P4 verification record

**Phase:** P4 of [DESIGN.md §13](DESIGN.md#13-migration-plan) — *"Extract the runner into
container-per-run; bring §6 isolation and egress with it."*
**Spec:** [SPEC-P4-sandbox.md](SPEC-P4-sandbox.md) →
[issue #18](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/18), ten tickets
(#19–#28).
**Verified:** 2026-10-25, on `portal/build`.
**Purpose:** the same as P1's, P2's and P3's — so "P4 is done" rests on evidence, and so P5
knows which paths are *proven* against real containers, a real network and a real object
store, and which rest on fakes.

> ## This record is incomplete, and P4 is therefore not closed
>
> **Second pass, 2026-10-25, on `844ef1b` + the fixes below.** The disk that ended the first
> pass had been freed (97 GiB) and the daemon was answering, so two of the first pass's three
> open items are now closed and recorded below as observed. What remains is one item, and it
> is not a code gap:
>
> 1. **The real agent run (`QA_RUNNER=claude`) in the sandbox image has not been
>    performed.** There is no `ANTHROPIC_API_KEY` in the environment, and a real run spends
>    tokens against a live target, which is not a thing to do unasked. This is still the one
>    claim this record cannot make, and it is the whole of criterion 11 and ticket #28.
>
> Closed since the first pass:
>
> - **The code review's changes are test-executed.** All 69 tests across the three files run
>   green against a real Postgres. One was stale rather than failing honestly — see
>   §"The second pass" — and it was the per-boundary archive's own arithmetic.
> - **Criterion 3 is now proven in full**, not as policy plus one host: the three-host probe
>   the first pass left as a manual step has been run, and §Egress records what the proxy
>   logged.
> - **The container path, the egress control and the credential rule** remain proven against
>   real containers, real Docker networks and a real object store.
>
> - **The sandbox image builds**, and the two criteria that rested on it are now behavioural
>   rather than structural: with no network at all, `npm ci` installs from the baked cache and
>   the prebaked Chromium launches.
> - **Criterion 5 and #23 are closed in the browser.** A run was started from the portal, it
>   executed in its own container, streamed live, and replayed from the table after an API
>   restart.
>
> And **three real bugs** the first pass could not have found, because each needs a stack that
> is *up* rather than a test that is green. All three are fixed, tested and described in
> §"The second pass":
>
> 1. The **object store** bound one of its two networks, so it was unreachable from the API
>    and from the host while compose reported it healthy.
> 2. **`make up` did not give container-per-run at all**: Compose never created the `qa-egress`
>    network, so every run failed at dispatch. That is #23's "no extra steps", and it was
>    broken.
> 3. **Every finished run leaked its egress proxy** — one idle container per run, for ever,
>    against this record's own "a finished run leaves nothing to pay for".
>
> That three bugs of this kind survived a green suite is the argument for the live
> walk-through, and it is the thing P5 should take from this record.

The sentence this phase is measured against is §13's: *"Extract the runner into
container-per-run; bring §6 isolation and egress with it."* Both clauses are requirements —
a P4 that shipped the container and left egress open would have shipped the cheap half — so
this record is organised around them, plus the promise P3 was written to keep: that this is
a change of **where** three functions run and not of **what** they do.

---

## Definition of done for P4

| # | Criterion | State |
|---|---|---|
| 1 | A run dispatched by the API executes in its own container, hydrating from the head revision, committing revisions at step boundaries, collecting artifacts and tearing down — with the same rows a thread run produces | **Proven** against a real container |
| 2 | No sandbox environment, image or compose service carries a GitHub or portal credential, and a structural test fails if one returns | **Proven** |
| 3 | From inside the sandbox, the target's host, the Anthropic API and the npm registry are reachable; any other host, `169.254.169.254`, and any name resolving to a private address are not | **Proven**, in full, against a real internal network and a real proxy — all three hosts observed reachable from inside a sandbox and the refusals observed with them; see §Egress |
| 4 | A base URL that does not resolve publicly is refused at save time, and re-resolved when the run starts | **Proven** |
| 5 | The portal streams a live run and replays a finished one after an API restart | **Proven**, in the browser: a live run streamed from its container, and the log replayed from the table after `docker compose restart api` — see §"The second pass" |
| 6 | A run exceeding the step timeout, the run timeout or the spend budget ends `failed` with that reason, the lock freed and the last revision intact | **Proven** |
| 7 | A container killed outright leaves a run the reaper reconciles to `failed`, with the app free | **Proven** at the lease level; see the note in §"What is covered only by fakes" |
| 8 | Pausing destroys the container; resuming re-hydrates, restores the agent session and continues at the next step | **Proven** at the seam with the fake runner, the review's pause fix included: its three tests now run green. Not observed as a real container disappearing — see §"What is covered only by fakes" |
| 9 | The driver still takes exactly one step-boundary callable; hydrate, ingest and teardown are still plain composed functions | **Proven**, structurally |
| 10 | `QA_RUNNER=fake` with `QA_SANDBOX=thread` keeps the full suite green, and the Docker-backed tests run in CI without skipping | **Proven** locally; the CI job is wired and not yet observed green |
| 11 | A real agent run (`QA_RUNNER=claude`) completes in the sandbox image against a live target | **Not performed** — see the box above |

---

## Automated suites

Second pass, as one run on a working daemon — `make ci-test-docker`, which is
`QA_REQUIRE_DB=1 QA_REQUIRE_DOCKER=1` over ruff, the backend suite and the frontend suite:

| Check | Result |
|---|---|
| `cd server && uv run ruff check .` | clean |
| `cd server && QA_REQUIRE_DB=1 QA_REQUIRE_DOCKER=1 uv run pytest` | **748 passed**, 0 skipped — the 6 Docker-backed tests among them |
| `cd web && npm test` | **45 passed**, 7 files (unchanged by this phase) |
| `make ci-test-docker` | exit 0 |

**This is the single combined green run the first pass could not produce**, and it needs no
arithmetic: one invocation, every file, zero skips. A reviewer with a working daemon should
expect `make ci-test-docker` to report 748.

For continuity with the first pass's numbers: its 728 was a projection rather than an
observation, and it was short, because the code review's own commit added eight tests after
that number was written (`test_dispatch.py` 21 → 24, `test_sandbox_credentials.py` 30 → 34,
`test_sandbox_session.py` 9 → 10). The tree stood at **741** when the second pass first ran it
whole, and the ten tests the second pass added for its own findings bring it to 748: +1
`test_sandbox_session.py` (the content-versioning rule the stale test never checked), +2
`test_compose_stack.py` (the store's binding), +3 `test_docker_sandbox.py` (the two networks,
and the placement of the check the review caught), +4 `test_dispatch.py` (the proxy a finished
run leaked, and the live run that must never be swept).

### New suites, and what each is for

| File | Tests | What it pins down |
|---|---|---|
| `tests/test_log_stream.py` | 12 | The log is a table read by cursor: lines in order from a cursor, only what is new on the second read, one run's lines are not another's, history surviving a **fresh bus instance**, two readers both seeing every line, a late subscriber getting the history from line one, the events route replaying a finished run from the table with nothing in the API's memory, and the reaper pruning past the retention window while keeping what is inside it |
| `tests/test_sandbox_entrypoint.py` | 12 | One composition, two call sites. Behaviourally: an out-of-process run produces the same run row, step rows, revisions and artifacts, exits zero, exits non-zero on failure, fails before any step on a hydrate failure, still fails the run on a failed ingest, and takes its heartbeat inside the process doing the work. Structurally: the composition is hydrate → `run_pipeline` → teardown **and nothing else**, both call sites reach for `drive_run`, the entrypoint composes nothing of its own, and the driver still takes exactly one step-boundary callable |
| `tests/test_dispatch.py` | 28 | The seam: the protocol is `dispatch`/`destroy` and nothing else, the factory picks thread or docker and **refuses an unknown value rather than guessing**, starting a run dispatches exactly once with the run's id, the handle is persisted and readable through the API, a thread run records none, a dispatch failure ends the run `failed` with that reason and frees the lock, the next run starts, a resume dispatches afresh, stop kills the sandbox and reaches `stopped`, destroy is idempotent, and a paused run that still names a sandbox is the reaper's business. Then, from the second pass: pause destroys the sandbox at once and leaves the row naming none, a **finished** run that still names a sandbox is the reaper's business too (which is the only thing that removes its proxy), and a live run — `RUNNING` or `PENDING` — is never swept |
| `tests/test_sandbox_credentials.py` | 30 | The credential rule, structurally. The environment builder emits the stores and the API key and **no** GitHub or portal credential — by name, by value, and by construction (`os.environ` is never the starting point). No module reachable from the entrypoint's **real import graph** mentions `GITHUB_PAT`, `GITHUB_TOKEN` or `GH_TOKEN`. The image builds from the same server package, carries Node ≥ 22, the CLI and prebaked browsers at a version matching the revision's lockfile, declares no mount and no credential, and has no `git` to push with. The API image carries neither Node nor the CLI. No compose service carries a credential; the sandbox service mounts nothing and is never started |
| `tests/test_egress.py` | 29 | The allowlist is the target's host, the Anthropic API and the npm registry and nothing else; another target's host, a subdomain of an allowed host, and the runtime's telemetry hosts are all refused; a port is not part of a host; the comparison ignores case and a trailing dot. The public-address predicate refuses the metadata endpoint, RFC1918, loopback, unique-local, link-local, CGNAT and multicast, and accepts routable addresses. A name resolving to one public **and** one private address is refused — that shape is the attack — and a name that does not resolve is refused as *that* instead |
| `tests/test_proxy.py` | 21 | The proxy's decision and the refusal a sandbox actually meets: the three rules in order, a 403 with a reason over a real socket, the tunnel opened to the address that was **verified**, an empty allowlist refusing everything, and the host read from a request line including the userinfo trap (`http://good@evil/` names evil) |
| `tests/test_limits.py` | 19 | Each limit, as a wrapper and through a whole run: a step past its wall clock is aborted and fails "timed out", spend accumulates across steps and ends the run naming the budget, the run deadline refuses another step, a runner with nothing to abort is still bounded, each breach frees the lock and leaves the head revision intact with the reason in the log *and* on the run, the cost is recorded, the real runner reports its cost from the `result` event, **a timed-out step takes its process group with it** (a grandchild that outlives it fails the test), the reaper fails and reaps overdue runs, a paused run is not one, and the lock trio mentions none of this |
| `tests/test_sandbox_session.py` | 11 | The session as a run artifact: archived at run end **and at every step boundary** under the reserved name with the CLI's files inside it, versioned on content rather than duplicated across a resume — a resume that explored further moves the version on, and one that changed nothing does not manufacture one — nothing archived where there is no sandbox session directory (a developer's `~/.claude` is not one to upload), an archive failure not failing the run, restored before the first step of a resume, and a failed restore completing the run, saying "without session continuity" in the log, and **not** telling the CLI to `--resume` what is gone |
| `tests/test_compose_stack.py` | 2 | The dev stack's own reachability invariants: the object store is on both networks, and it binds every interface. A store that is running and unreachable is the worst shape a dependency can take, and the healthcheck cannot see it |
| `tests/test_docker_sandbox.py` | 6 | The only tests that prove the container path at all. Two dispatch real containers; one stands up a real internal network with a real proxy on it; three pin the networks a dispatch needs — that the egress network is created when missing, that the **sandbox** network is refused rather than created (because a default one is not `internal`), and that `dispatch` itself refuses a missing sandbox network on the `with_proxy=False` path, which is the placement bug the review found |

### Changes to the existing suite

- `tests/conftest.py` gained `_no_real_dns`, the sibling of `_no_real_blob_storage`: no test
  may resolve a name against real DNS. It is what makes the injected resolver a seam rather
  than a suggestion — a forgotten override now fails with instructions instead of depending
  on what `demo.example.com` resolves to from the machine running it.
- `tests/target_helpers.py` gained `public_resolver`, passed by `create_target`, so every
  fixture that creates a target keeps working while the resolution tests supply their own
  table.
- `tests/source_helpers.py` is new and holds `code_of` (moved out of
  `tests/test_no_repo_mount.py`, which now imports it) plus `code_lines` for Dockerfiles and
  compose. Two phases now assert on source, and both need the same distinction: what the
  code *does*, not what its prose *says* — the comment explaining a credential decision
  names the credential.
- `tests/test_target_config.py` was **extended, not rewritten**: the shape-validation tests
  are untouched and seven resolution tests sit after them.
- `tests/test_infra_entries.py` gained three tests for the proxy stanza in the generated
  config, and the assertion that it still has exactly one author.
- **The pipeline suite is unchanged.** `test_run_worktree.py`, `test_driver.py`,
  `test_step_boundary_revisions.py`, `test_pause_resume_stop.py`, `test_hydrate.py` and
  `test_reaper.py` were not edited by this phase (`test_hydrate.py` took one `resolve=`
  argument where it edits a base URL, which is the write path's new signature and not a
  behaviour change). That is the evidence for "this is a change of where, not of what".

---

## The container path, against a real container

`tests/test_docker_sandbox.py`, run with `QA_REQUIRE_DOCKER=1` so a skip would have been a
failure. Three containers were really created: two sandboxes and one proxy, plus two real
Docker networks.

### A dispatched container produces the rows a thread run produces

The test builds the `sandbox-runtime` stage of `docker/Dockerfile.sandbox`, seeds a target
with revision 1 in a **real** SeaweedFS, dispatches through the same
`dispatch.dispatching_launcher` the API uses, and then looks only at rows:

```
run row        status completed, last_completed_step heal, sandbox_handle qa-run-<run_key>
step rows      all five steps present
revisions      head author "run:<run_key>", produced_by_run_id = the run,
               parent_rev = rev - 1, more than one revision
artifacts      indexed, with the content uploaded to the real store
run_log        "hydrate" and "run <run_key> completed" read back by cursor
```

The log assertion is the cross-process one: the lines were written by a process inside a
container and read by the test through `PostgresLogBus`. That is "two processes reading the
same run's log" proven by construction rather than by two bus instances in one process.

Three things are worth naming about *how* this test is shaped, because each was a choice:

- **It asserts what the run produced, never anything inside the container.** Whether a
  thread or a container did the work is the one thing the suite must not care about.
- **It uses the image's python stage, not the full image.** With `QA_RUNNER=fake` a run
  needs no browser and no CLI, and CI should not build two gigabytes to prove that a
  container hydrates, commits revisions and streams a log. What the full image adds is
  exactly what the real agent run proves — which is why that item is still open.
- **The container reaches the stores through the host gateway**, not over the compose
  network, because a test process has no compose network. That is a difference in *where
  the stores are*, not in what the run does; the egress test below uses the real internal
  network.

### The handle names a container a human can find

`docker ps -a --filter name=<handle>` listed the container the API's row named. The handle
is `qa-run-<run_key>`, so an SRE reads it off the run and types it into `docker`.

---

## Egress, against a real internal network

The third Docker-backed test stands up the real topology — `docker network create
--internal`, a proxy container on it with `QA_EGRESS_ALLOWLIST=example.com`, and a probe
container on the internal network with nothing else — and asks the probe what it can reach.
The control being tested is the network, so nothing here is about a run.

Observed, as JSON printed by the probe:

| Probe | Result |
|---|---|
| `http://example.com/` **through the proxy** (allowlisted) | `reachable` |
| `http://registry.npmjs.org/` through the proxy (not on *this* allowlist) | `refused:403` |
| `http://169.254.169.254/` through the proxy | refused |
| TCP to `169.254.169.254:80` **directly** | `unreachable` |
| TCP to `93.184.216.34:80` directly (a public address) | `unreachable` |
| `socket.gethostbyname("example.com")` inside the sandbox | `unresolvable` |

The last two lines are the ones that matter most, and they are why this is a network
control rather than a convention:

- **There is no default route.** Not to the metadata endpoint, not to the internet, with or
  without the proxy. An agent that unsets `HTTP_PROXY` reaches nothing; it does not reach
  everything.
- **The sandbox resolves nothing itself.** `gethostbyname` fails inside it, so Chromium and
  npm hand names to the proxy, and the private-address refusal happens in the one process
  that also enforces policy — at connect time, every time.

And the allowlist is per run: `registry.npmjs.org` is on every real run's allowlist and was
refused here because it was not on *this* proxy's. One run's proxy cannot be used to reach
another target's host.

### The three hosts together, observed

The first pass noted that the Docker-backed test proves *an* allowlisted host reachable with
`example.com` standing in for the target's, and that criterion 3 names three. That probe has
now been run, against a proxy carrying a real run's allowlist on the real topology — a proxy
container bridged between an `--internal` network and an egress one, and a sandbox container
on the internal network only. Observed, as the first line of each CONNECT response:

```
www.saucedemo.com      HTTP/1.1 200 Connection established
api.anthropic.com      HTTP/1.1 200 Connection established
registry.npmjs.org     HTTP/1.1 200 Connection established
bank.example.com       HTTP/1.1 403 Forbidden
169.254.169.254        HTTP/1.1 403 Forbidden
```

And from the same sandbox, with nothing else changed:

```
www.saucedemo.com unresolvable gaierror     # the sandbox resolves nothing itself
api.anthropic.com unresolvable gaierror
direct public: unreachable OSError          # no default route
metadata direct: unreachable OSError
```

The proxy's own log is the other half, because it shows the resolution happening in the
process that also decides:

```
proxy listening on 0.0.0.0:3128; allowlist: www.saucedemo.com, api.anthropic.com, registry.npmjs.org
ALLOW CONNECT www.saucedemo.com:443 -- www.saucedemo.com -> 185.199.108.153
ALLOW CONNECT api.anthropic.com:443 -- api.anthropic.com -> 160.79.104.10
ALLOW CONNECT registry.npmjs.org:443 -- registry.npmjs.org -> 104.16.0.34
DENY  CONNECT bank.example.com:443 -- bank.example.com is not on this run's allowlist
DENY  CONNECT 169.254.169.254:443 -- 169.254.169.254 is not on this run's allowlist
```

So criterion 3 is now observed rather than composed from two proofs. It stays a manual probe
rather than a fourth Docker-backed test, for the reason the first pass gave: it depends on
the npm registry and the Anthropic API being up, and a CI suite that fails when somebody
else's service blips is a suite people learn to ignore. The commands:

```bash
docker network create --internal qa-sandbox-probe
docker network create qa-egress-probe
docker run -d --name qa-proxy-probe --network qa-egress-probe \
  -e QA_EGRESS_ALLOWLIST=www.saucedemo.com,api.anthropic.com,registry.npmjs.org \
  -e QA_PROXY_PORT=3128 qa-egress-proxy:latest
docker network connect qa-sandbox-probe qa-proxy-probe
# 200 for each of the three, 403 for anything else, and the proxy did the resolving
for h in www.saucedemo.com api.anthropic.com registry.npmjs.org bank.example.com; do
  docker run --rm --network qa-sandbox-probe --entrypoint python qa-sandbox-runtime:test -c "
import socket
s = socket.create_connection(('qa-proxy-probe', 3128), timeout=10)
s.sendall(b'CONNECT $h:443 HTTP/1.1\r\nHost: $h:443\r\n\r\n')
print('$h', s.recv(64).decode('latin-1').splitlines()[0])"
done
docker rm -f qa-proxy-probe; docker network rm qa-sandbox-probe qa-egress-probe
```

It is a manual step rather than a fourth Docker-backed test on purpose: it depends on the
npm registry and the Anthropic API being up, and a CI suite that fails when somebody else's
service blips is a suite people learn to ignore.

---

## The pieces verified without a container

### Save-time resolution, at the write path

`POST /projects/{id}/targets` and `PATCH /targets/{id}/config` answer **422** with the
reason when the base URL resolves privately, and the target is not created:

```
base URL 'https://internal.example.com' is not usable: 'internal.example.com' resolves to
10.1.2.3, which is not a public address; a run may not reach private, link-local or
loopback addresses
```

The portal shows `detail`, so the message is what the operator reads. The shape check runs
first, so `not-a-url` is still reported as "must be an absolute http(s) URL" rather than as
a resolution failure — a URL with no host has nothing to resolve.

Run-time re-resolution is in `DockerScheduler.dispatch`, before the container is created, so
a name repointed after it was saved fails the run **before** it costs tokens; the proxy
would refuse it at connect time anyway, which is the belt to that braces.

### The credential rule, structurally

- `app/sandbox/env.py` builds a sandbox's environment from an **explicit list**. The tests
  set `GITHUB_PAT`, `GITHUB_TOKEN`, `GH_TOKEN`, `QA_ADMIN_PASSWORD` and `QA_SECRET_KEY` in
  the control plane's environment and assert that neither the names nor the *values* appear
  in what a sandbox is given, and that `os.environ` is never copied — the difference matters
  for the control-plane variable somebody adds next year.
- The import-graph test imports `app.sandbox.run` in a fresh interpreter, reads
  `sys.modules`, and asserts that no `app.*` module in it mentions a GitHub credential.
  Making that pass required one real change: `app/delivery/__init__.py` now re-exports its
  entry points lazily, so wanting the tracked-tree definition (`write_infra` for hydrate,
  `tracked_tree` for ingest, `resolve_story` for the prompt) no longer drags
  `app/delivery/github.py` — the one module that reads `GITHUB_PAT` — into every sandbox's
  import graph.
- The sandbox image installs no `git`. The credential rule says the push cannot happen in a
  sandbox; there is now no binary there to push with.

### Limits

Each limit was exercised through a whole run with the fake runner, and each breach was
observed to end the run `failed` with the reason in both the run's `error` and its log, with
the app lock freed and `head_revision().rev` still 1:

```
step timeout    "step plan timed out after 0s"
spend budget    "spend budget exceeded: $2.00 of $1.50"
run wall clock  "run timed out after 7200s without finishing (reaped)"   (reaper)
```

The process-group kill is tested with a real subprocess tree: a step that spawns a
grandchild and sleeps is timed out, and the test fails if the grandchild outlives it. That
is the failure mode the wall clock exists for — a wedged agent holding a browser — and
killing only the process we hold would have left the expensive half running.

### Pause, resume and the session

With the fake runner: the session directory is archived under
`<run_key>/agent-session.tar.gz` (kind `session`) at run end, the archive contains the CLI's
files, a resume restores it **before the first step**, a second archive is a new version of
the same reserved name rather than a second artifact, and a resume whose archive has been
deleted from the store completes the run, logs `continuing without session continuity`, and
clears the recorded session id so the CLI is not told to `--resume` what is gone.

**Amended by the code review, and now executed.** As recorded at `7cdceb4`, pause set a
flag and the container exited at the step boundary that noticed it — which is the grace
window #27 and #18 forbid, by another name, and the §5 amendment had been written to match
the code rather than the ticket. The route now destroys the container itself and moves the
row to `paused`, and the session is archived at **every step boundary** so that a sandbox
killed without warning still leaves one.

The three new tests in `test_dispatch.py` and the one in `test_sandbox_session.py` have been
run against a real Postgres and are green: pausing destroys the sandbox at once and the row
names no sandbox afterwards, `pause_requested` is cleared by the transition so nothing waits
for a boundary that will never come, the thread path keeps the flag-at-a-boundary behaviour,
and the session is in the store from the second boundary onward. One existing test in the
same file was *stale* rather than wrong, and the per-boundary archive is what made it so —
see §"The second pass".

Nothing is archived when `CLAUDE_CONFIG_DIR` is unset — which is the thread path on a
developer's laptop, where the only session store is the developer's own `~/.claude`.

---

## Decisions recorded during this phase

| Decision | Why |
|---|---|
| **The npm cache is baked into the image, not a shared volume** | Story 23 asks for `npm ci` "against a shared cache", and the obvious reading — a cache volume mounted into every sandbox — is one this phase cannot have: a writable directory shared between containers running different customers' agents is a supply-chain path between them, which is what container-per-run exists to close. So it is populated at build time from the template lockfile every target's revision 1 carries, identical for every run, and written to only in the container's own layer |
| **One proxy container per run, not one shared proxy** | The allowlist is built from one target's row. A shared proxy would have to be told which run is asking, and a tunnel cannot answer that honestly |
| **Node is grafted from the official image, not installed from apt** | The CLI requires Node ≥ 22 and the base's distribution ships 20. `apt-get install nodejs` would have produced an image whose agent runtime refuses to start — breakage visible only in a real run |
| **`make_scheduler()` returns `None` on the thread path** | "There is no sandbox to schedule" is the truth about a thread run, and the paths that reap a sandbox have to be able to ask without catching an exception. An unknown `QA_SANDBOX` still raises: a typo must not quietly run the agent in the API process |
| **The API publishes nothing to the log bus** | One writer per run, and it is the sandbox. A dispatch failure therefore has its reason on the run row, where the portal already shows it, and the stream ends at once because the run is terminal |
| **`AutoRemove` on the run container** | A paused or finished run leaves nothing to pay for. Affordable only because the log is in Postgres now: a post-mortem does not need the container |
| **The exit code is read off the run row** | A run that ends `failed` for any reason exits non-zero, so the scheduler and `docker ps -a` agree with the database about what happened |
| **`pyyaml` added to the dev dependency group** | The structural tests parse `docker-compose.yml` rather than grepping it. Parsing is the honest tool when a comment explaining a decision mentions the thing the decision is about |

---

## What is covered only by fakes

Named here as P1, P2 and P3 each named theirs, so P5 inherits a list rather than an
impression.

- **The real agent inside the sandbox image.** Everything about the container path is proven
  with `QA_RUNNER=fake`. That the image's CLI, Node and browsers actually drive a run is the
  one claim this record cannot make (see the box at the top).
- **A container killed outright.** The reaper's reconciliation is proven at the lease level
  (`test_reaper.py`, unchanged) and the heartbeat is proven to come from inside the process
  doing the work. The two have not been composed by killing a real container and watching
  the reaper fail that run.
- **Pause and stop against a real container.** Proven through the seam, and that proof is
  now executed: the recording scheduler sees the `destroy` the route issues, and the row is
  `paused` naming no sandbox. Not observed as a real container disappearing.
- **The CI job.** The workflow is wired — a SeaweedFS started with `docker run` because a
  service container cannot be given command arguments, `QA_REQUIRE_DOCKER=1`, and the
  existing zero-skip check — and has not been observed green on a runner.
- **Multi-replica streaming.** The log table removes the pinning cause and two readers are
  proven to see every line. Two API replicas have not been stood up.

## Not yet verified, and the commands to finish it

Items 1-3 are what the second pass could reach; **item 4 is the one that needs a key and a
decision to spend**, and item 5 depends on it.

```bash
# 1. The sandbox image. Needs disk: the full image is ~2 GB on top of the base.
#    The build no longer dies at `playwright install` (that was the full disk); it
#    reads its Playwright version out of the template lockfile, as the review's fix
#    intended -- observed in the build log as "playwright 1.63.0 (from the template
#    lockfile)".
make sandbox-images
docker run --rm --entrypoint claude qa-sandbox:latest --version     # the CLI is there
# NOT `npx playwright --version`: the global CLI is uninstalled at build time, so npx
# downloads one and reports *that*. Ask the image what it baked, with no network:
docker run --rm --network none --entrypoint sh qa-sandbox:latest -c 'ls /ms-playwright'

# 2. The stack, with container-per-run (this is `make up`'s default)
make up && make health

# 3. The portal walk-through: create a target with a publicly-resolving base URL,
#    write a story, start a run, and watch it in the browser at :8080.
#    While it runs:
docker ps --filter name=qa-run- --format '{{.Names}} {{.Networks}}'
docker ps --filter name=qa-proxy- --format '{{.Names}} {{.Networks}}'
#    Then restart the API and reload the run's log: it replays from the table.
docker compose restart api

# 4. The real agent run
export ANTHROPIC_API_KEY=...        # the sandbox needs it; the API image does not
QA_RUNNER=claude make up
#    Start a run from the portal and record: the revisions it committed, the artifacts,
#    the log, `spend_usd`, `sandbox_seconds`, and `docker logs qa-proxy-<run_key>`
#    (which lists every host the agent tried to reach, allowed or refused).

# 5. A timeout and a budget breach, by hand
QA_STEP_TIMEOUT_S=30 QA_SPEND_BUDGET_USD=0.10 QA_RUNNER=claude make up
```

The egress check by hand, which the automated test does but a reviewer should see:

```bash
docker run --rm --network qa-sandbox --entrypoint python qa-sandbox:latest -c "
import socket, urllib.request
p='http://qa-proxy-<run_key>:3128'
o=urllib.request.build_opener(urllib.request.ProxyHandler({'http':p,'https':p}))
print('target     ', o.open('https://www.saucedemo.com/').status)
print('anthropic  ', o.open('https://api.anthropic.com/').status)
print('npm        ', o.open('https://registry.npmjs.org/').status)
for host in ('https://example.com/', 'http://169.254.169.254/'):
    try: print(host, o.open(host).status)
    except Exception as exc: print(host, 'refused:', exc)
print('direct dns ', socket.gethostbyname('example.com'))
"
```

---

## Acceptance criteria, line by line

Every criterion of the nine implementation tickets (#19–#27) is met and has a named test,
with these exceptions:

| Ticket | Criterion | State |
|---|---|---|
| #25 | "From inside the sandbox, the target's host, the Anthropic API and the npm registry are reachable" | **Met and observed** — all three through the real proxy from inside a sandbox, in §Egress |
| #27 | "Pausing a run destroys its container at once" | **Met** by the review's fix, and its tests are now green |
| #22 | "Running the sandbox entrypoint by hand inside that image completes a run against the dev stack with the real runner available" | **Met** for the full image via the portal walk-through: the dispatched container is `qa-sandbox:latest` and it completed a run against the dev stack. With `QA_RUNNER=fake`, so "the real runner available" is the part that remains |
| #22 | "No browser download happens at run time" | **Met and observed**: with `--network none`, `npm ci --offline` installs the lockfile's 1.63.0 from the baked cache and the prebaked Chromium launches — see §"The second pass" |
| #23 | "A run started from the portal with `QA_SANDBOX=docker` executes in its own container and reaches `succeeded`" | **Met and observed** through the portal — after the `qa-egress` fix, without which it failed at dispatch |
| #23 | "`make up` gives container-per-run on a laptop with no extra steps" | **Was broken, now met**: Compose never created `qa-egress`, so every run failed at dispatch. The scheduler creates it — see §"The second pass" |
| #28 | All of it | See the box at the top |

---

## The code review, and what it changed

The `code-review` skill ran both axes against `7bba686...HEAD`. Six findings were acted on;
the rest were either recorded deferrals or the reviewer reading the code rather than the
ticket. Kept here because three of the six change what the rest of this record claims.

| Finding | Axis | What it caused |
|---|---|---|
| `NO_PROXY` named `localhost` while the stores are `postgres` and `seaweedfs`. boto3 honours `HTTP_PROXY`, so in any stack with a proxy a sandbox's S3 traffic was tunnelled to the allowlisting proxy, which correctly 403s a host that is deliberately not on the allowlist — hydrate and ingest would both have failed | Standards, then Spec | A real bug, and the one the unperformed live run would have hit first. `env.internal_hosts()` now derives the bypass from the endpoints the sandbox is actually handed, so "which hosts?" has one answer; four tests in `test_sandbox_credentials.py`, two of which were red |
| Pause did not destroy the container; it set a flag and the sandbox exited at the next step boundary — and the §5 amendment had been written to describe that rather than what #27 asked for | Spec | The route destroys the container and moves the row to `paused` itself; the session is archived at every step boundary so a sandbox killed without warning still leaves one; §5 now records the ticket's rule and the reason the boundary is where the session is saved |
| `PLAYWRIGHT_VERSION` in the Dockerfile was a second hand-maintained copy of the `@playwright/test` pin, kept honest by a test | Spec | The image reads the version out of the template lockfile at build time. The test is now structural: it asserts there is nothing left to keep in sync |
| `store_environment()`'s docstring claimed "the narrowest set hydrate and ingest need" while forwarding the control plane's own credentials | Spec | The docstring says what is true and points at the deferral it belongs to. The exposure itself was already recorded in DESIGN.md §6 and is P5's |
| Criterion 3 names three reachable hosts; the Docker probe proves one | Spec | §Egress now says so, with the one manual probe that closes it |
| The per-run wall clock has no scheduler-side deadline | Spec | No code change: the reaper's overdue sweep already both fails the row **and** destroys the sandbox (`reaped + overdue + idle`), which bounds the overrun by one reap interval rather than one step timeout, and `test_limits.py::test_the_reaper_destroys_the_sandbox_of_a_run_it_reaps` is that case. `limits.py` now says where the deadline bites |

Deliberately not acted on: the `app/delivery/__init__.py` lazy re-export (it is how #22's
import-graph test is satisfied, and `env.py` omitting the PAT is the control either way);
narrowing the store credentials (P5, recorded); the npm cache decision (recorded above, with
the supply-chain reason); and `test_hydrate.py` gaining `resolve=public_resolver` (the DNS
guard the egress ticket added, not a change to what it asserts).

**The one command that executes the four new tests**, once a Postgres is reachable:

```bash
cd server && QA_REQUIRE_DB=1 uv run pytest \
  tests/test_dispatch.py tests/test_sandbox_session.py tests/test_sandbox_credentials.py -q
```

---

## The second pass

The first pass left three items open and called none of them a code gap. Two are now closed,
and executing them cost two changes — one to a test that had gone stale, and one to the dev
stack, which was a real bug.

### The stale test, and why the per-boundary archive made it one

`test_the_archive_is_rewritten_rather_than_duplicated_on_resume` failed on its first ever
execution, asserting `version == 2` and observing 4. The code was right and the test was
arithmetic from before the review: it was written when the session was archived **once per
run**, so a paused attempt plus a resumed one meant exactly two versions. The review moved
the archive to *every step boundary* — so that a sandbox killed without warning still leaves
one — and the honest count became the number of boundaries whose bytes differed, which for
this fixture is 4.

The number was never the invariant. The test now asserts what its own docstring claimed:

- one row under the reserved name, not one per attempt (unchanged, and the point of the test);
- the version **moved on** after a resume that explored further, rather than a named total.

And the docstring's other half — *"one that changed nothing does not manufacture one"* — was
asserted by nothing at all, which the per-boundary archive promoted from a nicety to the rule
that keeps the version count meaningful: archiving at every boundary would bump the version
once per step for identical bytes if the digest were not what decides. It is now
`test_a_resume_that_changes_nothing_does_not_manufacture_a_version`, and `_index()` in
`app/sandbox/session.py` is what makes it pass — it bumps only when `row.sha256 != digest`.

This finding cost no production change at all: the two tests above are the whole of it.
(The three bugs below each did change production code.)

### The object store was healthy and unreachable

This one needed a stack that was *up*, which is why neither the first pass nor any test
could have found it, and it would have been the second thing a live run hit after the
`NO_PROXY` bug the review caught.

SeaweedFS binds **one** address. P4 put the stores on two networks — the control plane, for
the API, and the sandbox network, because hydrate and ingest run inside a container now — and
the S3 port came up on the `qa-sandbox` address only:

```
tcp  127.0.0.1:8333    LISTEN
tcp  172.18.0.2:8333   LISTEN      # qa-sandbox
                                   # qa-control-plane (172.19.0.3): nothing
```

So the store was a closed socket on the control-plane side: the API could not reach it, the
host's published port could not reach it, and `docker compose ps` said **healthy** throughout
— because the healthcheck curls `localhost`, and localhost is always bound. From the host the
symptom was a TCP connect that succeeded (docker-proxy accepts) and an HTTP read that got
nothing, which is how it first appeared: `QA_REQUIRE_DOCKER is set but Docker is unusable: no
object store at http://localhost:8333`.

The fix is `-ip.bind=0.0.0.0` in the `seaweedfs` command. Postgres needed no equivalent: its
image binds `0.0.0.0` already, which is why it kept working and made the fault look
store-specific rather than structural.

It is pinned by `tests/test_compose_stack.py` (2 tests), a new file for the dev stack's own
reachability invariants: that the store is on both networks (the premise) and that it binds
every interface (the rule). Verified red without the flag — a flag on a command line is
exactly the kind of thing a later tidy-up removes, and the healthcheck will not object.

### The sandbox image, built and exercised

`make sandbox-images` completes. The `playwright install` step that died with `Read-only file
system` was the full disk and nothing else; with 90 GiB free it ran to the end, and the build
log confirms the review's fix doing its job — `playwright 1.63.0 (from the template
lockfile)`, read out of the lockfile rather than from a second hand-maintained pin.

The image is 2.84 GB and carries what #22 asks of it:

```
claude --version            2.1.310 (Claude Code)
node --version              v22.23.4            # >= 22, grafted from the official image
/ms-playwright              chromium-1243, chromium_headless_shell-1243, ffmpeg-1011
command -v git              absent              # nothing to push with
```

**One of the first pass's suggested checks is misleading, and is replaced here.**
`docker run --entrypoint npx qa-sandbox:latest playwright --version` prints a version, which
looks like confirmation, but what it actually prints is `npm warn exec The following package
was not found and will be installed: playwright@1.64.1` — the global `playwright` CLI is
deliberately `npm uninstall`ed at the end of that build step, so `npx` **downloads a
different version at check time** and reports that. It tells you the host has network, not
what the image baked.

What does answer #22's *"No browser download happens at run time"* is doing what a run does,
with `--network none`:

```
npm ci --offline --cache /npm-cache     added 5 packages in 217ms
@playwright/test installed              1.63.0          # the lockfile's pin
chromium launched                       153.0.8010.12   # the baked build 1243
```

So the two criteria the first pass could only assert structurally are now behavioural: the
install is a copy from the baked cache rather than a download, and the prebaked browser
**launches** with no route to anywhere. That the image's Chromium works is no longer part of
what only a real agent run would show; what remains of #22 is the agent driving it.

### The portal walk-through, and the two bugs it found

Criterion 5's browser half and #23's two criteria were outstanding because nobody had started
a run from the portal. Doing it found two bugs, neither of which any test could have caught,
and both in the gap between "the code is right" and "the stack works".

**1. `make up` did not give container-per-run at all.** The first run started from the portal
failed at dispatch:

```
sandbox dispatch failed: could not start qa-proxy-<run_key>:
failed to set up container networking: network qa-egress not found
```

Compose *declares* `qa-egress`, but the only service attached to it is the egress-proxy, which
carries the `never-started` profile — and Compose does not create the networks of a service a
profile excludes. So the network never existed, and **every** run on a laptop failed at
dispatch. That is #23's *"`make up` gives container-per-run on a laptop with no extra steps"*,
which the first pass recorded as "wired for it; not observed".

The fix is in the scheduler rather than the Makefile, because the scheduler is what knows it
needs the network and it must work however the stack was started.
`DockerScheduler._ensure_egress_network()` creates it if absent, idempotently, tolerating the
409 of a dispatch that raced another.

**The asymmetry is the load-bearing part, and it is deliberate**: the *sandbox* network is
checked and never created. A network Docker creates by default is **not** `internal`, so
inventing `qa-sandbox` would hand every sandbox a default route and silently remove the entire
egress control — nothing would fail, which is the worst possible outcome for this phase. A
missing sandbox network is a broken stack and now says so, naming the reason. Two
Docker-backed tests pin both halves, and a third pins where the check is called from.

The code review then found a real bug in that first fix, which is why the two halves are two
methods. One method doing both jobs was called from `_start_proxy`, so on the
`with_proxy=False` path the sandbox-network precondition was **never checked** — the one
guard whose absence is silent got skipped on exactly the configuration that has no proxy to
make the absence loud. `_require_sandbox_network()` is now called from `dispatch()` beside the
public-address precondition it belongs with, and `_ensure_egress_network()` keeps its place in
`_start_proxy`, where creating a route out is the proxy's business. The names now say which
one creates and which one refuses.

The two tests above would both have stayed green through that bug, because both call the
methods directly — so the third test goes through `dispatch()` with `with_proxy=False` and a
missing network and asserts the run is refused before any container is created. Deleting the
line in `dispatch` now fails something.

**2. Every finished run leaked its egress proxy.** With the network fixed, the run executed in
its own container and reached `completed` — and its proxy was still `Up` minutes later. The
run container carries `AutoRemove` and vanishes; the proxy is long-running and exits on
nobody's schedule, and only `destroy` removes it. But `repo.idle_sandbox_runs` selected
**`PAUSED` runs only**, so nothing ever swept a finished one: one idle container per run,
for ever, directly against this record's own decision that *"a paused or finished run leaves
nothing to pay for"*.

No test caught it because the seam tests use a recording scheduler and the container test runs
with `with_proxy=False` — so the proxy's lifecycle was the one part of dispatch that nothing
exercised end to end.

The sweep is now `TERMINAL | {PAUSED}`. The reaper already had the machinery — destroy, then
clear the column — so the fix is the predicate plus the prose that was wrong about it. Live
runs stay excluded, and that is the half that matters most: sweeping a `RUNNING` run would
destroy the container doing the work, and a `PENDING` one is a dispatch that has not begun.
Four tests in `test_dispatch.py`, three of which were red. What they pin is the
**predicate** — which runs `idle_sandbox_runs` returns — against a recording scheduler. That a
proxy container is really removed, and the column really cleared, is still shown only by the
live run recorded below and not by any test; the honest statement is that the leak's *cause*
is now covered and its *cure* is observed rather than asserted.

One consequence worth stating: a finished run's `sandbox_handle` is now cleared by the first
sweep after it ends, where before it stayed for ever. The column means "a sandbox exists for
this run", and §"The handle names a container a human can find" is about a *live* run — for a
finished one the container is already gone, and the handle is still in the run's log.

**Observed after both fixes**, with `QA_SANDBOX=docker` and `QA_RUNNER=fake`:

```
docker ps --filter name=qa-run-    qa-run-<key>   | qa-sandbox
docker ps --filter name=qa-proxy-  qa-proxy-<key> | qa-egress,qa-sandbox
run row                            running -> completed, last_completed_step heal
portal                             5 steps Completed, 5 log artifacts, live log streaming
after `docker compose restart api` the full log replays from the table
after one reap interval            both containers gone, sandbox_handle cleared
```

So criterion 5 is closed in the browser, and #23's two criteria are met — after the fix that
made them true. Save-time resolution was exercised live on the way through:
`http://localhost:3000` was refused 422 with *"'localhost' resolves to 127.0.0.1, ::1, which
is not a public address"*, and `https://www.saucedemo.com` was accepted and committed
revision 1.

One thing deliberately not treated as a bug: a fake run through the portal commits **no**
revisions, because `QA_FAKE_TREE_WRITES` is not set in the compose stack and a step boundary
with no tree change has nothing to commit — revisions are content-addressed. Criterion 1's
revision-committing is proven by the Docker-backed test, which turns that flag on. (The knob
is not in the compose file's environment either, so it cannot be set from the host without
editing it. Left alone: it is a demo knob, not a defect.)

### One observation not reproduced

On the run where the store was unreachable, the egress test also reported `refused:403` for
its allowlisted host. It passed on every run afterwards, alone and with the file, and the
proxy refuses a name it cannot resolve — so the likely cause is DNS inside the proxy
container failing while a two-gigabyte image build saturated the machine, which the probe
records as a 403 because that is all a CONNECT reply carries. Recorded rather than explained
away: an egress test whose allowlisted host must resolve from inside a container is a test
with a dependency on DNS, and that is a flake CI can meet.

---

## Closing

P4's two clauses are both built, and the half that would have been easy to skip — egress — is
the half proven against a real network rather than a function. A sandbox has no default
route, resolves nothing itself, reaches only what one function put on its allowlist, holds no
GitHub credential by construction, cannot read one from any module it imports, and is
destroyed with its run. The pipeline inside it is the same composition the thread path runs,
and the existing suite staying untouched is the evidence for that.

The second pass spent the disk the first pass did not have, and the two things it cost are
worth separating. The stale test was the per-boundary archive's own arithmetic catching up
with it: no production code changed, and the invariant was always the one the test now
states. The store binding one interface was a real bug, in the shape that is worst to ship —
healthy, silent, and fatal to every run — and it was reachable only by standing the stack up,
which is the argument for the live walk-through that is still outstanding rather than against
it.

What is left is the evidence a real agent would provide: criterion 11 and ticket #28, which
need an `ANTHROPIC_API_KEY` and a deliberate decision to spend tokens against a live target.
Until that is recorded here, **P4 is implemented and not closed**.
