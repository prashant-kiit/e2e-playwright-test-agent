# 03: Manual snapshot — an operator snapshots a target and sees its head revision

**Spec:** [SPEC-P2-revisions.md](../../SPEC-P2-revisions.md) (*The tracked tree*, *Content
addressing and the tree hash*, *Writing a revision*, *The baseline revision*, *Read surface*)

**What to build:** the first complete path through the revision model. An operator opens a target
in the portal, asks for a snapshot, and sees a head revision appear with its revision number and
tree hash — backed by real content-addressed blobs in object storage and real rows in Postgres.
Demoable against `saucedemo`, whose tracked tree is a genuine twenty-odd-file suite.

Four pieces make that work.

**The tracked-tree contract.** One definition of what a revision covers, living with the delivery
path contract that already owns "what a story file is called" and the infra file list — so
snapshotting and delivery cannot drift about what the product versions. A target's tracked tree
is its stories, plans, seed and test suite, plus the five repo-level infra files that define a
runnable target repo. It excludes the app's config file (SaaS-internal, never tree content),
the agent's reports and evidence screenshots (run output — which is why delivery already declines
to push them), and everything that is a run artifact: installed packages, test results, the HTML
report, traces, videos and the session log.

Paths are stored **target-relative** — the shape a per-target worktree will have — not
repo-root-relative with the app folder as a prefix. The mapping between a tracked path and its
location on disk is one function, and it is the same function P3's hydrate needs. The root infra
files are shared on disk but logically per-target, so each target's revision includes its own
copy; content addressing makes the duplication free.

**The tree hash.** A deterministic hash over the file list: each file's content hash paired with
its path, sorted by path, concatenated and hashed — like a stripped-down git tree, and
independent of directory iteration order, timestamps and file modes. Two revisions with the same
tree hash hold the same bytes at the same paths, which is what makes both parity (ticket 05) and
skip-if-unchanged cheap. It is a durable format, so pin it with a known-value test.

**Snapshot and commit.** Walk the tracked tree hashing each file; compute the tree hash and stop
without committing if it already matches the head revision; upload each blob under its own
content hash, skipping any the store already holds; then insert the revision row and all its
file-index rows in one transaction. The ordering is the invariant: **blob before row**, so a
crash can leave an unreferenced blob (harmless, and what the future GC sweeps) but never a
revision pointing at bytes that are not there. Dedup needs one new method on the blob-storage
seam — an existence check — and nothing else; uploads keep using the existing one.

**The operator-facing surface.** A snapshot action on a target, and a revision list showing rev,
tree hash, author, the run that produced it and the file count. The portal element stays minimal
here — head rev and tree hash for the target — with the full panel arriving in ticket 04. The
snapshot action is P2-only scaffolding: in P3 the filesystem is not authoritative and "snapshot
the disk" stops meaning anything, so say so where it is defined.

**Blocked by:** 01 (shared fake blob store), 02 (schema)

**Status:** ready-for-agent

- [ ] Snapshotting a target with no history creates revision 1 with no parent, and its file index
      lists exactly the tracked tree at target-relative paths.
- [ ] A snapshot of an unchanged tree commits **no** new revision.
- [ ] A snapshot after one file changed commits revision 2 whose parent is 1, and uploads only
      the blob that changed.
- [ ] Two targets whose infra files are byte-identical share one blob.
- [ ] The tree-hash format is pinned by a known-value test, is identical across two snapshots of
      the same tree, and is unaffected by directory iteration order.
- [ ] A one-byte change to one file changes the tree hash.
- [ ] The app config file, the reports and evidence folder, installed packages, test results, the
      HTML report and the session log are all absent from a snapshot; the five infra files, the
      seed, the stories, the plans and the test suite are all present.
- [ ] A blob store whose upload raises leaves zero revision and zero file-index rows.
- [ ] The blob-storage seam gains exactly one method (an existence check), implemented by the
      shared fake from ticket 01 and by the real S3-backed store.
- [ ] The portal shows a target's head revision number and tree hash, and offers the snapshot
      action; the revision list is reachable.
- [ ] DESIGN.md §4 amended: the generated-config note on the Playwright config is marked as
      arriving with P3's hydrate, since P2 tracks it as the hand-maintained file it is.
- [ ] `make ci-test` green. No change to run behavior, delivery or artifact collection.
