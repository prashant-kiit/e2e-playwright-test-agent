# P2 tickets — revisions, file_index and content-addressed blobs

Seven tickets implementing [SPEC-P2-revisions.md](../../SPEC-P2-revisions.md). Numbered in
dependency order: blockers first.

| # | Ticket | Blocked by |
|---|---|---|
| 01 | [Prefactor: one shared fake blob store](01-shared-fake-blob-store.md) | — |
| 02 | [Schema: tenants, revisions, file_index, `tenant_id`](02-schema-revisions-and-tenant-id.md) | — |
| 03 | [Manual snapshot, end to end](03-manual-snapshot-end-to-end.md) | 01, 02 |
| 04 | [A revision's files, readable in the portal](04-revision-files-in-the-portal.md) | 03 |
| 05 | [Parity: head revision vs. disk](05-parity-head-revision-vs-disk.md) | 03 |
| 06 | [Runs commit revisions at each step boundary](06-step-boundary-revisions.md) | 03 |
| 07 | [Verification: a real agent run](07-verification-p2.md) | 04, 05, 06 |

The frontier: 01 and 02 start together, then 03, then 04, 05 and 06 all in parallel, then 07.

These are a task graph, not a list of steps. There is no issue tracker configured for this repo
(see the note at the end of the P2 spec), so "resolved" means the ticket's acceptance criteria
are met on the integration branch.
