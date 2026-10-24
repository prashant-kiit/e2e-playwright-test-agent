# Spec: P3 — flip reads to Postgres + blobs, hydrate per run, delete the repo mount

**Triage label:** `ready-for-agent`
**Phase:** P3 of [DESIGN.md §13](DESIGN.md) ("Flip reads to DB + blobs; `apps/` becomes derived;
delete the repo mount. API becomes stateless.")
**Depends on:** P2, landed and verified ([SPEC-P2-revisions.md](SPEC-P2-revisions.md),
[VERIFICATION-P2.md](VERIFICATION-P2.md))
**Authority this phase takes:** all of it. At the end of P3, Postgres and SeaweedFS are the only
things anything reads to make a decision.
**Spec body:** [issue #7](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/7) —
canonical. Issues and specs live in GitHub (see [issue-tracker.md](../../docs/agents/issue-tracker.md));
this file is the signpost from the harness docs, not a second copy.
**Tickets:** nine, sub-issues of #7 (table below).

---

## What this phase does

P2 proved the revision model and the product ignored it: every read still bottoms out in the repo
mount, config is a delivered `app.json`, "is this delivered?" is an `ls-remote`, and all runs share
one worktree. P3 moves truth. The head `revision` plus the target's config row become what
everything reads, and the filesystem becomes per-run scratch space built from the database and
thrown away:

```
hydrate    head revision + target config  →  a per-run worktree
           (blobs from SeaweedFS, generated files rendered from Postgres, deps installed)
run        the agent works in that worktree, and nowhere else
ingest     at each completed step boundary: upload blobs, commit revision N+1
           — and now a failed ingest FAILS THE RUN
teardown   delete the worktree
```

Around that: config moves into `targets` and `playwright.config.ts` becomes generated; the portal
becomes the input surface for targets, stories and config; delivery materializes the head revision,
squashes it into one commit and records `delivered_sha`, so "in sync?" is one query; and the mount,
`apps/`, `config.repo_root()`, parity and the manual-snapshot route are deleted behind a one-shot,
parity-gated cutover command.

P3 adds **no new seam**. Four existing ones carry it: the driver's single step-boundary callable,
delivery's injected `Tools`, `Storage`, and `StepContext`. The full problem statement, the 50 user
stories, the implementation and testing decisions, the acceptance criteria and what stays out of
scope are all in #7.

## Tickets

| # | Ticket | Blocked by |
|---|---|---|
| 01 | [Target config in `targets`, imported by a parity-gated cutover](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/8) (#8) | — |
| 02 | [The tracked tree, root-relative, with `(source, destination)` infra](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/9) (#9) | #8 |
| 03 | [Hydrate and teardown around the pipeline](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/10) (#10) | #8, #9 |
| 04 | [The agent works in the hydrated worktree](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/11) (#11) | #10 |
| 05 | [Ingest from the worktree, and a failed ingest fails the run](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/12) (#12) | #10 |
| 06 | [The portal becomes the input surface](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/13) (#13) | #8, #9 |
| 07 | [Delivery reads the database and records `delivered_sha`](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/14) (#14) | #9, #10 |
| 08 | [Cutover: delete `apps/`, the mount and `config.repo_root()`](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/15) (#15) | #11, #12, #13, #14 |
| 09 | [Verification: a real agent run](https://github.com/prashant-kiit/e2e-playwright-test-agent/issues/16) (#16) | #15 |

The frontier: #8, then #9, then #10 and #13 together, then #11, #12 and #14 in parallel, then #15, then #16.
Blocking edges are GitHub issue dependencies; a ticket is unblocked when every blocker is closed.

## Before reviewing this phase

Re-read §13's sentence: *"Flip reads to DB + blobs; `apps/` becomes derived; delete the repo
mount."* All three clauses are requirements. A P3 that flips the reads but leaves the mount mounted
has kept the drift surface; one that deletes the mount but leaves a read path resolving through a
repo root has not flipped anything. P3 also **inverts P2's central safety property** — a failed
revision write must now fail the run — and that inversion is the phase, not a regression.

Closed out in `VERIFICATION-P3.md`, alongside [P1's](VERIFICATION-P1.md) and
[P2's](VERIFICATION-P2.md).
