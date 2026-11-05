# A removal revokes the session it leaves behind

#56, the residue of UAT 3 (#54). `app/auth.py` buys cheap authentication by
putting the claims in a signed cookie and not reading the row: "a cheap
stateless check beats a database round-trip per request". UAT 3 found the case
that bargain does not cover, and the ticket asked for a recorded decision
rather than a unilateral one, because closing the window costs a round trip per
request and the module had explicitly declined that.

**Decision.** A removal writes the user's id to a small table, `revoked_users`,
in the same transaction as the `DELETE`. `require_auth` reads that table on
every authenticated request and refuses a user id removed within
`ACCESS_MAX_AGE`. The access cookie stays claim-carrying: what the request
reads is the revocation list, never `users`.

**What was broken.** `/auth/refresh` already re-reads the `users` row (fixed
during UAT 3 itself), so a removed user cannot mint a *new* access cookie. The
one they already hold verifies on its signature alone, so a removed user kept
whatever role they had for up to fifteen minutes. UAT 3 watched a removed admin
spend them reading `/users`, **creating another admin** and changing the
tenant's quotas, with the audit trail as the only control that saw it.

A role *downgrade* taking effect at the next refresh is a fair bargain — the
person still works here. A removal is not: it is an offboarded contractor or a
compromised account, and "they keep admin for a quarter of an hour" is not an
answer worth giving a customer about an offboarding.

**The three alternatives.**

- **Read the `users` row in `require_auth`.** Closes the window too, and costs
  the same single round trip. Rejected because it makes every authenticated
  request depend on the whole of `users` and leaves `app/auth.py`'s stated
  design with no reading under which it still holds, where this leaves it with
  one named exception.
- **Shorten the access cookie to ~2 minutes.** Cheap and needs no table, but it
  only makes the window smaller, and a window that is merely small is still the
  window UAT 3 walked through. It also shifts load onto `/auth/refresh`, which
  *does* read `users`, so the saving is smaller than it looks.
- **Accept it and write it down.** Honest, free, and the thing it writes down
  is that a removal takes up to fifteen minutes.

**Why this is not the token table `app/auth.py` and `app/run_token.py` both
declined.** Those would hold a row per live session for as long as sessions
live. A revocation stops mattering once no cookie minted before it can still
verify — `ACCESS_MAX_AGE` after it is written — so this holds a row per
*removal* for fifteen minutes, and `revocation.revoke` prunes the expired rows
as it writes, so there is no sweep to schedule and nothing to grow unbounded.

**What it does not cover**, each by decision rather than oversight:

- **A role change.** A demotion still takes effect at the next refresh. A
  revocation here means "no access", so using it for a downgrade would log the
  person out for up to fifteen minutes rather than lowering their role — and
  for somebody who still works here, the refresh path already gives the right
  answer.
- **A purged tenant.** `revoked_users` is tenant-owned, so a purge deletes the
  tenant, its users *and* these rows; a purged tenant's user keeps a verifying
  cookie for up to fifteen minutes. What they can reach with it is nothing:
  every read is filtered to a tenant with no rows and every write fails its
  `tenant_id` foreign key. A revocation that survived the purge would have to
  live outside the tenant, which is `purge_log`'s argument — a platform table
  read once per operator action, not once per request.
- **A stolen cookie.** Revocation is of a *user*, not of a token: the server
  never knew the session existed. A copy of somebody's cookie is still worth
  the rest of its fifteen minutes, which is why the access cookie is short.
