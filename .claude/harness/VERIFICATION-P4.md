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
> Two items of the spec's definition of done could not be executed on the machine this was
> verified on, and neither is a code gap:
>
> 1. **The real agent run (`QA_RUNNER=claude`) in the sandbox image has not been
>    performed.** There is no `ANTHROPIC_API_KEY` in the environment, and a real run spends
>    tokens against a live target, which is not a thing to do unasked.
> 2. **The full sandbox image did not finish building.** Its `playwright install` step died
>    with `Read-only file system` on apt's cache: the **host disk was full** — 193 MiB free
>    of 228 GiB, with Docker's own data directory at 64 GiB. The daemon stopped answering
>    `docker ps` shortly afterwards, which also ended the live-stack checks (§"Not yet
>    verified" below has the commands to finish both).
>
> Everything else below was executed and is recorded as observed. The container path, the
> egress control and the credential rule are proven **against real containers, real Docker
> networks and a real object store**, not against fakes — that happened before the disk
> filled. What is missing is the real *agent* inside the sandbox, and the portal-level
> walk-through.

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
| 3 | From inside the sandbox, the target's host, the Anthropic API and the npm registry are reachable; any other host, `169.254.169.254`, and any name resolving to a private address are not | **Proven** against a real internal network and a real proxy |
| 4 | A base URL that does not resolve publicly is refused at save time, and re-resolved when the run starts | **Proven** |
| 5 | The portal streams a live run and replays a finished one after an API restart | **Partly**: proven at the API and bus level; the browser walk-through is outstanding |
| 6 | A run exceeding the step timeout, the run timeout or the spend budget ends `failed` with that reason, the lock freed and the last revision intact | **Proven** |
| 7 | A container killed outright leaves a run the reaper reconciles to `failed`, with the app free | **Proven** at the lease level; see the note in §"What is covered only by fakes" |
| 8 | Pausing destroys the container; resuming re-hydrates, restores the agent session and continues at the next step | **Proven** with the fake runner |
| 9 | The driver still takes exactly one step-boundary callable; hydrate, ingest and teardown are still plain composed functions | **Proven**, structurally |
| 10 | `QA_RUNNER=fake` with `QA_SANDBOX=thread` keeps the full suite green, and the Docker-backed tests run in CI without skipping | **Proven** locally; the CI job is wired and not yet observed green |
| 11 | A real agent run (`QA_RUNNER=claude`) completes in the sandbox image against a live target | **Not performed** — see the box above |

---

## Automated suites

| Check | Result |
|---|---|
| `cd server && uv run pytest` (Docker-backed file excluded) | **723 passed**, 0 skipped (was 534 at the end of P3) |
| `cd server && QA_REQUIRE_DOCKER=1 uv run pytest tests/test_docker_sandbox.py -m docker` | **3 passed**, 0 skipped — real containers |
| `cd server && uv run pytest` over the whole tree | 728 collected |
| `cd web && npm test` | **45 passed**, 7 files (unchanged by this phase) |
| `cd server && uv run ruff check .` | clean |

**Read the first two lines together rather than as one run.** The single combined green run
(all files, `QA_REQUIRE_DOCKER=1`, exit 0, no failures) was recorded *before* the last three
tickets landed; after them the 723 and the 3 were green in two separate runs, and the
combined run could not be repeated because the daemon stopped answering. The arithmetic is
723 + 3 = 726, plus the two structural tests added for the baked npm cache = 728 collected.
A reviewer with a working daemon should expect `make ci-test-docker` to report 728.

### New suites, and what each is for

| File | Tests | What it pins down |
|---|---|---|
| `tests/test_log_stream.py` | 12 | The log is a table read by cursor: lines in order from a cursor, only what is new on the second read, one run's lines are not another's, history surviving a **fresh bus instance**, two readers both seeing every line, a late subscriber getting the history from line one, the events route replaying a finished run from the table with nothing in the API's memory, and the reaper pruning past the retention window while keeping what is inside it |
| `tests/test_sandbox_entrypoint.py` | 12 | One composition, two call sites. Behaviourally: an out-of-process run produces the same run row, step rows, revisions and artifacts, exits zero, exits non-zero on failure, fails before any step on a hydrate failure, still fails the run on a failed ingest, and takes its heartbeat inside the process doing the work. Structurally: the composition is hydrate → `run_pipeline` → teardown **and nothing else**, both call sites reach for `drive_run`, the entrypoint composes nothing of its own, and the driver still takes exactly one step-boundary callable |
| `tests/test_dispatch.py` | 21 | The seam: the protocol is `dispatch`/`destroy` and nothing else, the factory picks thread or docker and **refuses an unknown value rather than guessing**, starting a run dispatches exactly once with the run's id, the handle is persisted and readable through the API, a thread run records none, a dispatch failure ends the run `failed` with that reason and frees the lock, the next run starts, a resume dispatches afresh, stop kills the sandbox and reaches `stopped`, destroy is idempotent, and a paused run that still names a sandbox is the reaper's business |
| `tests/test_sandbox_credentials.py` | 30 | The credential rule, structurally. The environment builder emits the stores and the API key and **no** GitHub or portal credential — by name, by value, and by construction (`os.environ` is never the starting point). No module reachable from the entrypoint's **real import graph** mentions `GITHUB_PAT`, `GITHUB_TOKEN` or `GH_TOKEN`. The image builds from the same server package, carries Node ≥ 22, the CLI and prebaked browsers at a version matching the revision's lockfile, declares no mount and no credential, and has no `git` to push with. The API image carries neither Node nor the CLI. No compose service carries a credential; the sandbox service mounts nothing and is never started |
| `tests/test_egress.py` | 29 | The allowlist is the target's host, the Anthropic API and the npm registry and nothing else; another target's host, a subdomain of an allowed host, and the runtime's telemetry hosts are all refused; a port is not part of a host; the comparison ignores case and a trailing dot. The public-address predicate refuses the metadata endpoint, RFC1918, loopback, unique-local, link-local, CGNAT and multicast, and accepts routable addresses. A name resolving to one public **and** one private address is refused — that shape is the attack — and a name that does not resolve is refused as *that* instead |
| `tests/test_proxy.py` | 21 | The proxy's decision and the refusal a sandbox actually meets: the three rules in order, a 403 with a reason over a real socket, the tunnel opened to the address that was **verified**, an empty allowlist refusing everything, and the host read from a request line including the userinfo trap (`http://good@evil/` names evil) |
| `tests/test_limits.py` | 19 | Each limit, as a wrapper and through a whole run: a step past its wall clock is aborted and fails "timed out", spend accumulates across steps and ends the run naming the budget, the run deadline refuses another step, a runner with nothing to abort is still bounded, each breach frees the lock and leaves the head revision intact with the reason in the log *and* on the run, the cost is recorded, the real runner reports its cost from the `result` event, **a timed-out step takes its process group with it** (a grandchild that outlives it fails the test), the reaper fails and reaps overdue runs, a paused run is not one, and the lock trio mentions none of this |
| `tests/test_sandbox_session.py` | 9 | The session as a run artifact: archived at run end under the reserved name with the CLI's files inside it, versioned rather than duplicated across a resume, nothing archived where there is no sandbox session directory (a developer's `~/.claude` is not one to upload), an archive failure not failing the run, restored before the first step of a resume, and a failed restore completing the run, saying "without session continuity" in the log, and **not** telling the CLI to `--resume` what is gone |
| `tests/test_docker_sandbox.py` | 3 | The only tests that prove the container path at all. Two dispatch real containers; one stands up a real internal network with a real proxy on it |

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
- **Pause and stop against a real container.** Proven through the seam (the recording
  scheduler sees the `destroy`) and through the composition (the container exits at the
  boundary). Not observed as a container disappearing.
- **The CI job.** The workflow is wired — a SeaweedFS started with `docker run` because a
  service container cannot be given command arguments, `QA_REQUIRE_DOCKER=1`, and the
  existing zero-skip check — and has not been observed green on a runner.
- **Multi-replica streaming.** The log table removes the pinning cause and two readers are
  proven to see every line. Two API replicas have not been stood up.

## Not yet verified, and the commands to finish it

```bash
# 1. The sandbox image. Needs disk: the full image is ~2 GB on top of the base.
make sandbox-images
docker run --rm --entrypoint claude qa-sandbox:latest --version     # the CLI is there
docker run --rm --entrypoint npx qa-sandbox:latest playwright --version

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
with these exceptions, all of them in #22, #23 and #28 and all of them the same two
environment facts:

| Ticket | Criterion | State |
|---|---|---|
| #22 | "Running the sandbox entrypoint by hand inside that image completes a run against the dev stack with the real runner available" | The entrypoint is proven in a container built from the same Dockerfile's python stage; running it inside the **full** image needs the image |
| #22 | "No browser download happens at run time" | Structural only: the image installs the browsers at build time, at the version the revision's lockfile pins (asserted). Observing a run not downloading one needs the image |
| #23 | "A run started from the portal with `QA_SANDBOX=docker` executes in its own container and reaches `succeeded`" | Proven through the launcher the portal calls, not through the portal |
| #23 | "`make up` gives container-per-run on a laptop with no extra steps" | The compose file and Makefile are wired for it; not observed |
| #28 | All of it | See the box at the top |

---

## Closing

P4's two clauses are both built, and the half that would have been easy to skip — egress — is
the half proven against a real network rather than a function. A sandbox has no default
route, resolves nothing itself, reaches only what one function put on its allowlist, holds no
GitHub credential by construction, cannot read one from any module it imports, and is
destroyed with its run. The pipeline inside it is the same composition the thread path runs,
and the existing suite staying untouched is the evidence for that.

What is left is the evidence a real agent and a working disk would provide. Until that is
recorded here, **P4 is implemented and not closed**.
