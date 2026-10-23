# 07: Verification — a real agent run, and VERIFICATION-P2.md

**Spec:** [SPEC-P2-revisions.md](../../SPEC-P2-revisions.md) (*Acceptance criteria*, *Further
Notes*)

**What to build:** the evidence that P2 is proven rather than merely written. §13 says P2's job is
to prove the revision model "against real runs with zero behavior change". Every ticket before
this one is covered by fakes; this one runs the real agent against a real target and records what
happened, the way P1 was closed out.

Run the pipeline with the real agent runner against the practice target, end to end, and then
establish from the portal and the database that:

- a revision chain exists, starting from a baseline and advancing at the step boundaries that
  changed the tree;
- the head revision's file index matches the tracked tree on disk — parity green;
- the files the portal serves out of blob storage are byte-identical to the files on disk;
- blobs were deduplicated rather than re-uploaded per revision;
- and nothing else changed: delivery still works, artifacts are still collected and still keyed
  as before, run states and pause/resume/stop behave as they did in P1.

Record it as a verification document alongside P1's, in the same shape: what was exercised live
against a real agent and a real object store, what is covered only by fakes, the defects found
while verifying, and the gaps deliberately left open for P3. P1's closeout found five real
defects during verification; expect this one to find some too, and fix them inside this ticket.

Then update the roadmap: P2 moves from "next" to done, with P3 (flip reads to the database and
blobs, make the API stateless, delete the repo mount) named as next.

**Blocked by:** 04 (revision files in the portal), 05 (parity), 06 (step-boundary revisions)

**Status:** ready-for-agent

- [ ] A real agent run against the practice target completes and leaves a revision chain, with
      the sequence of revisions and what each contained recorded.
- [ ] Parity for that target is green after the run, shown from the portal.
- [ ] A file read through the portal out of blob storage is confirmed byte-identical to the file
      on disk.
- [ ] Blob dedup is confirmed against the real object store, not only against a fake.
- [ ] Delivery of a story to a target repo is confirmed still working unchanged.
- [ ] Artifact collection, run states and pause/resume/stop are confirmed unchanged from P1.
- [ ] A verification document exists next to P1's, separating what was proven live from what rests
      on fakes, and listing the gaps left for P3.
- [ ] Any defect found during verification is fixed in this ticket and recorded in that document.
- [ ] The README roadmap records P2 as done and names P3 as next.
- [ ] `make ci-test` green on the integration branch.
