# 04: A revision's files, readable from blob storage in the portal

**Spec:** [SPEC-P2-revisions.md](../../SPEC-P2-revisions.md) (*Read surface*)

**What to build:** the operator can pick a revision in the portal, see every file it contains with
its size, and open one of those files and read it — with the bytes coming out of blob storage
rather than off the shared disk. This is the first time the portal displays the product's own
output from the database's copy of it, which is what makes the revision model believable before
P3 relies on it.

The reads are authorized through the database, never by key: a request names a revision and a
tracked path, the server finds the row for that revision and path, checks it belongs to the
requesting tenant, and only then streams the blob it names. Knowing a blob key must not be enough
to read bytes. The tenant is always the single seeded one today; filtering anyway is the
structural half of P5, so leave it in.

The whole surface is read-only. Nothing here may write a revision, a file index row or a blob —
that would let the portal make the database disagree with the authoritative filesystem, which is
the one thing this phase must not do.

A tracked path contains slashes, so the file request takes the path as a query parameter rather
than a path segment and needs no escaping scheme.

**Blocked by:** 03 (manual snapshot end to end)

**Status:** ready-for-agent

- [ ] Selecting a revision in the portal lists its files with their sizes, matching exactly what
      the snapshot committed.
- [ ] Opening a file shows its contents, byte-identical to what was stored, fetched from blob
      storage.
- [ ] A request for a path that the named revision does not contain is refused, and does not
      stream anything.
- [ ] A revision belonging to another tenant is not readable, asserted with a second tenant row.
- [ ] No route in this ticket writes to the database or to blob storage.
- [ ] The file list and the file viewer are covered by frontend tests, following the existing
      bootstrap-form tests that assert both the success and the failure rendering.
- [ ] `make ci-test` green.
