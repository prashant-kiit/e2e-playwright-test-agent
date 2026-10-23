# 06: Runs commit revisions at each step boundary

**Spec:** [SPEC-P2-revisions.md](../../SPEC-P2-revisions.md) (*Where sync-out hangs: the
step-boundary seam*, *The baseline revision*)

**What to build:** the thing the phase is for. Every run now leaves a revision chain behind it:
the tree as it stood before the run started, then one revision per step boundary that actually
changed something. After this ticket, the agent's work has history for the first time, and
"what did this run produce, and what did the one before it produce?" is answerable from the
database.

Two wiring points, both in the control plane, neither of them a new seam.

**Sync-out composes behind the driver's existing step-boundary hook.** The driver has exactly one
injected callable fired after each completed step, and artifact collection is already composed
into it. The revision snapshot composes into the same callable. Do **not** add a second driver
parameter for it — DESIGN §13 names this explicitly as the thing not to do, because the driver
keeping one injection point is what has kept it simple.

That composition has two requirements the spec is specific about:

- **Each half isolates its own failures.** The driver wraps the whole callable in a single
  best-effort try/except, so an exception thrown by artifact collection would otherwise skip the
  revision commit entirely, and vice versa. The composed hook must catch per half and report
  both.
- **Artifacts first, then the revision snapshot.** Existing behavior runs first and is never
  delayed by new work.

**A failed revision write must never fail a run.** While the filesystem is authoritative, the
driver's best-effort treatment of the hook is exactly right, and it is load-bearing for the
phase's no-behavior-change promise. P3 inverts this — once truth has moved, a failed sync-out has
to fail the run — so leave a comment saying so, because the instinct on reading a swallowed
exception is to "fix" it.

**The baseline is taken in the launcher, before the pipeline starts**, when a target has no head
revision yet. Not at the first sync-out: that would conflate the tree the run inherited with the
tree its first step produced, and every target's revision 1 would be unreadable. Not a one-shot
backfill script either — code that runs once and is never exercised again. The launcher is also
exactly where P4's hydrate will live.

One consequence worth putting in the portal copy: the first run after this lands produces two
revisions for what feels like one piece of work — the baseline, then the run's changes. That is
intended, and reads like an off-by-one if nobody says so.

**Blocked by:** 03 (manual snapshot end to end)

**Status:** ready-for-agent

- [ ] A run on a target with no history commits the baseline from the pre-run tree as revision 1,
      and the first step that changes the tree commits revision 2 whose parent is 1.
- [ ] A five-step run over a tree that changes once commits exactly one revision beyond the
      baseline, not five.
- [ ] A run that changes the tree at two different step boundaries commits two revisions, chained.
- [ ] A run on a target that already has a head revision does not re-baseline.
- [ ] A blob store whose upload raises leaves zero new revisions, and the run still reaches
      completed.
- [ ] An artifact collector that raises does not prevent the revision commit; a revision write
      that raises does not prevent artifact collection; neither fails the run; both failures are
      reported to the run's log stream.
- [ ] The driver still takes exactly one step-boundary callable — asserted by the driver's
      signature being unchanged.
- [ ] The tests drive a whole run through the pipeline with the fake runner and the shared fake
      blob store, so they cover the composition in the launcher and not only the functions behind
      it, following the existing artifact-collection tests.
- [ ] Portal copy explains the baseline-plus-changes pair on a target's first run.
- [ ] `make ci-test` green. Run states, pause/resume/stop, the lease lock and the reaper are
      untouched.
