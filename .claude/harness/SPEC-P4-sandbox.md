# Spec: P4 — container-per-run sandbox, with §6 isolation, egress and limits

**Triage label:** `ready-for-agent`
**Phase:** P4 of [DESIGN.md §13](DESIGN.md#13-migration-plan) ("Extract the runner into
container-per-run; bring §6 isolation and egress with it. Needs P3's stateless API.")
**Depends on:** P3, landed and verified ([SPEC-P3-flip-reads.md](SPEC-P3-flip-reads.md),
[VERIFICATION-P3.md](VERIFICATION-P3.md))
**Spec body:** [issue #18](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/18) —
canonical. Issues and specs live in GitHub (see [issue-tracker.md](../../docs/agents/issue-tracker.md));
this file is the signpost from the harness docs, not a second copy.
**Tickets:** ten, sub-issues of #18 — see [Tickets](#tickets) below.

---

## What this phase does

A run still executes **inside the API process**: `launch_run` starts a daemon thread, and the agent
that explores a customer's live app and then writes and runs TypeScript shares a process tree, a
filesystem and an environment with the thing holding the PAT, the database URL and the object-store
keys. P4 puts a wall there, and brings the three things P3 deliberately left out.

```
API      takes the lock, writes the run row, dispatches a sandbox   ← the launcher seam
───────────────────────── container boundary ─────────────────────────
hydrate  head revision + target row → worktree     (same function, new location)
run      driver → ClaudeRunner → claude CLI        (same functions)
boundary artifacts, then ingest: revision N+1      (same hook)
teardown worktree deleted with the container
──────────────────────────────────────────────────────────────────────
         log lines append to Postgres; the portal reads them by cursor
```

Around that: a prebaked image carrying the CLI, Node and the browsers; **default-deny egress at the
network layer** — an internal network with no default route and an allowlisting `CONNECT` proxy
built from the target's row, which resolves on the sandbox's behalf and refuses anything private,
link-local or loopback; a log stream that is a Postgres table rather than an in-process dictionary,
so any replica can stream any run and history survives a restart; and per-step, per-run and
per-spend limits that end a run `failed` with a reason and the last revision intact.

P4 adds **no new injected seam**. `get_launcher` stays the one injection point for "a run starts
working" and gains a factory that picks `docker` or `thread` from the environment, exactly as
`make_runner` picks `claude` or `fake`; a `Scheduler` protocol sits behind it with one real
implementation. The driver keeps its single step-boundary callable, hydrate/ingest/teardown stay
plain composed functions, `StepContext` still carries the worktree, and `LogBus` becomes a protocol
with the in-memory implementation kept for tests. The problem statement, the 50 user stories, the
implementation and testing decisions, the definition of done and what stays out of scope are all in
#18.

## The four decisions that shaped it

| Decision | Taken |
|---|---|
| What moves into the container | **The whole per-run pipeline.** §12 promised the sandbox *inherits* hydrate, ingest and teardown; the entrypoint is today's `launch_run` body without the thread. The sandbox therefore holds store credentials — accepted here, with the run-scoped internal API recorded as P5's successor — and never a GitHub credential |
| The live log | **Appended to Postgres, read by cursor.** No new store, replica-agnostic, and history survives a restart (today it does not) |
| Pause and bundles | **Session continuity only.** Pause reaps the container at once and persists the agent session; git bundles and `bundle_key` stay deferred, because nothing in P4 reads a bundle and resume needs the session, not mid-step history |
| Egress | **Internal network plus an allowlisting proxy.** Enforced where an agent that writes and runs code cannot opt out, with the public-address check in the one process that resolves |

## Tickets

| # | Ticket | Blocked by |
|---|---|---|
| 01 | [Log lines in Postgres, read by cursor](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/19) (#19) | — |
| 02 | [One composition, two call sites: the sandbox entrypoint](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/20) (#20) | #19 |
| 03 | [The dispatch seam: `Scheduler`, the launcher factory, the sandbox handle](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/21) (#21) | #20 |
| 04 | [The sandbox image, and the credential rule made structural](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/22) (#22) | #20 |
| 05 | [The Docker scheduler: a real container per run](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/23) (#23) | #21, #22 |
| 06 | [The public-address rule: save-time resolution and the allowlist builder](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/24) (#24) | — |
| 07 | [Default-deny egress: the internal network and the allowlisting proxy](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/25) (#25) | #23, #24 |
| 08 | [Limits: step timeout, run timeout, spend budget](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/26) (#26) | #21 |
| 09 | [Pause, resume and the agent session](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/27) (#27) | #23 |
| 10 | [Verification: a real agent run in the sandbox](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/28) (#28) | #25, #26, #27 |

The frontier: #19 and #24 can start immediately; then #20; then #21 and #22 together; then #23;
then #25, #26 and #27 in parallel; then #28. Blocking edges are GitHub issue dependencies; a
ticket is unblocked when every blocker is closed.

Two things were sliced deliberately. The **§5, §6 and §10 design amendments ride with the tickets
that make them true** (#27, #25, #19) rather than forming a documentation ticket of their own — a
docs-only ticket is the horizontal slice this phase exists to avoid; §3 and §12 ride with
verification because they describe the finished phase. And **egress is split at the seam the spec
itself draws**: the allowlist builder and the public-address rule (#24) are pure functions that
need no container and so unblock immediately, while enforcing them at the network layer (#25)
genuinely needs a container on a network.

---
## Before reviewing this phase

Re-read §13's sentence: *"Extract the runner into container-per-run; bring §6 isolation and egress
with it."* Both clauses are requirements. A P4 that ships the container but leaves egress open has
shipped the cheap half — §6 calls open egress plus an LLM plus your cloud network the combination
that cannot be patched later. And a P4 that rewrites the pipeline to fit a container has broken the
promise P3 was written to keep: this is a change of *where* three functions run, not of *what* they
do, and the existing suite staying green on the thread path is the evidence for it.

This phase also **amends the design document** in five places — §5 (pause reaps immediately, no
grace window), §6 (the allowlist includes the internal stores, with the credential decision), §3
(`bundle_key` still deferred, now with P4's reason), §10 (the live log is a table) and §12 (the
runner line marked done). Those amendments are part of the work, so a later reader can tell a
decision from an omission.
