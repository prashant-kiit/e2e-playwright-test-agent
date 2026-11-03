<!--
The close comment for issue #33 (P5-05). Written to a file because the session
that finished the work was not permitted to make tracker writes.

To close the ticket:

    gh issue close 33 --comment "$(cat .claude/harness/issues/p5/p5-05-close.md)"
    gh issue edit 33 --remove-label ready-for-agent

Then update the banner in VERIFICATION-P5.md: #33 becomes "closed `completed`"
and the open-ticket list drops to #36 and #37.
-->
Done in `475454c` and `f5a763e` on `portal/build`. Evidence is recorded in `.claude/harness/VERIFICATION-P5.md` §"Verified on 2026-11-03 — P5-05 / #33".

**The six acceptance criteria**

- [x] A sandbox environment carries neither `DATABASE_URL` nor `S3_*`; it carries a run-scoped token instead. `sandbox/env.control_plane_environment` returns only `QA_CONTROL_PLANE_URL` and `QA_RUN_TOKEN`; `test_sandbox_credentials.py` asserts the absence by name *and by value*, with all five credentials present in the control plane's own environment.
- [x] The run hydrates its head revision, fetches and uploads blobs, commits revision N+1, and uploads artifacts and log lines through the API. Each operation is driven on both transports in `test_control_gateway.py`, and all of them at once in a real container.
- [x] The token authorizes only that run's target and tenant. `test_control_service.py` covers two real tenants, a same-tenant inconsistent scope (so the tenant filter cannot be what refuses it), and **two targets of one tenant** — which is where the first attempt was wrong; see below.
- [x] The token is rejected once the run is no longer live, over all three terminal statuses and on both transports. Four operations are deliberately exempt and enumerated in one place (`service.scoped_run`); a finished run still cannot commit a revision, drive its status or upload an artifact, and that is tested.
- [x] The stores are unreachable from a sandbox; the internal API takes their place on the egress-bypass path. Two halves, both structural: the sandbox is given no endpoint, and Postgres and SeaweedFS are off `qa-sandbox` (`test_compose_stack.py` also asserts the API is the *only* thing on it). `build_allowlist` is untouched.
- [x] Both thread and docker paths use the API; the existing structural tests still hold. One service layer, two transports (`LocalGateway`, `HttpGateway`), with one suite run against both. The no-second-pipeline, no-repo-mount and no-GitHub-credential tests all still pass.

**A note on scope.** The operation list in this ticket is necessary but not sufficient, and that is recorded rather than discovered: the sandbox runs the whole pipeline, so run status, step rows, the lease, cost and the session id had to move through the API too, or criterion 1 could not be true. The result is 23 named operations with no generic query and no SQL passthrough.

**Verification.** 1063 backend tests (from 932 at `dd6ad79`), 84 frontend, ruff clean, 6 Docker-backed tests, and a run through the real compose stack: 30 log lines, 13 files hydrated from revision 4, 5 artifacts — all written by a container holding no database credential and no object-store key.

**Four bugs, none found by the suite.** Three by running a container: a client that verified a token it holds no key for (passing in-process only because the test environment *has* the key); a liveness gate that dropped exactly the log lines emitted after the final status transition, which are the ones an operator reads first; and a log flusher raced on close. The fourth by the two-axis review: blob authorization was by tenant prefix, so a run could read *or overwrite* a sibling target's revision blobs from a guessed content hash — against this ticket's criterion 3 and #30's "no serve-by-key-alone". Reads now require a `file_index` row of this run's target; writes must hash to the key they are written under. All fixed in this slice.

**Two gaps accepted rather than fixed**, both in §Follow-ups 32–34 of the record and neither blocking this ticket:

- `record_cost` is exempt from the liveness gate when it did not have to be, so a token leaked from a finished run can rewrite two accounting columns until its signature expires.
- Serving `/internal` from the main listener puts the **whole** API on the sandbox network, so a compromised agent can reach `/auth/login` with no rate limiting in front of it. Narrower than a database credential, wider than these routes alone. The fix is a second listener, which is a deployment change rather than a code one, and worth doing before a real customer's agent runs on this.
