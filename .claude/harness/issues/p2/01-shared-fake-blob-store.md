# 01: Prefactor — one shared fake blob store for the test suite

**Spec:** [SPEC-P2-revisions.md](../../SPEC-P2-revisions.md) (seam 2, *Blob bytes*)

**What to build:** nothing a user can see. The backend test suite currently carries two
near-identical hand-rolled fakes of the blob-storage protocol — one in the artifact-collection
tests, one in the API tests — and P2 extends that protocol with an existence check that
content-addressed dedup needs. Collapse the two fakes into one shared test double first, the way
the delivery tests already share their helpers, so that extending the seam in ticket 03 is a
change in one place rather than three.

This is the prefactor the rest of the phase rests on: make the change easy, then make the easy
change.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] One fake blob store lives in a shared test helper module, alongside the existing delivery
      helpers rather than inside any one test file.
- [ ] Both the artifact-collection tests and the API tests use it; no test file defines its own
      blob-storage fake any more.
- [ ] The fake still records what was stored under which key, with its content type, so existing
      assertions about uploaded objects keep working unchanged.
- [ ] No production code changes. No test *assertions* change — only where the double comes from.
- [ ] `make ci-test` green, with the same number of tests passing as before.
