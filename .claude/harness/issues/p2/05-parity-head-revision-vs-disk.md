# 05: Parity — the portal says whether the head revision matches disk

**Spec:** [SPEC-P2-revisions.md](../../SPEC-P2-revisions.md) (*Parity*)

**What to build:** the safety net, made visible. For any target, the operator can see whether the
database's head revision agrees with the authoritative files on disk, and when it does not, which
paths are at fault.

Dual-write is only worth a whole phase if someone checks the two copies agree. Without this
ticket, a revision write that silently stopped working would look exactly like one that was
working, and P2 would prove nothing. With it, "a run finished and parity is green" is the evidence
that P3's read-flip is safe to make.

The comparison is a pure function over two inputs — the head revision's file index, and a scan of
the on-disk tracked tree — returning the paths present only in the database, the paths present
only on disk, the paths whose contents differ, and whether the two are in sync. No I/O inside the
comparison, so it tests without a database or a filesystem.

Surfaced as a parity route per target and a banner in the portal, which must render in both
directions: green when in sync, and clearly not-green when not, naming the offending paths. A
mismatch should read as a bug report, not a mystery.

**Blocked by:** 03 (manual snapshot end to end)

**Status:** ready-for-agent

- [ ] A target snapshotted and left alone reports in sync.
- [ ] A file added on disk after the snapshot is reported as on-disk-only, by exact path.
- [ ] A file deleted from disk after the snapshot is reported as database-only, by exact path.
- [ ] A file edited on disk after the snapshot is reported as differing, by exact path, and is
      not reported as missing or extra.
- [ ] All three kinds of difference are reported in one response when all three are present.
- [ ] A target with no revisions at all reports a distinguishable state — not a false "in sync"
      and not a server error.
- [ ] The comparison itself is tested as a pure function, with no database and no filesystem.
- [ ] The portal banner is covered in both the in-sync and out-of-sync renderings, following the
      existing bootstrap-form tests that assert both directions.
- [ ] The route is read-only: parity never repairs, re-snapshots or writes anything.
- [ ] `make ci-test` green.
