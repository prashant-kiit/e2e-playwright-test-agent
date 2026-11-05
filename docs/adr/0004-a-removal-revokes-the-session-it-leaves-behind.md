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
**removal** rather than per session, and `revocation.revoke` deletes the
expired ones as it writes the next, so there is no sweep to schedule.

Precisely: that prune is an ORM bulk delete and therefore tenant-scoped like
every other one, so it trims the acting tenant's expired rows and nothing else
— a tenant that removes a user once and never again keeps that row until its
next removal. That is the bound worth claiming, and it is not "the table holds
only the last fifteen minutes". Nothing reads an expired row either way:
`is_revoked` bounds the question by the window rather than trusting the prune,
which is also what stops an unpruned row from locking out an id.

**What it does not cover**, each by decision rather than oversight:

- **A role change, which the ticket's own first line asks for.** #56 opens "A
  removed **or demoted** user loses access **now**", and a demotion still takes
  effect at the user's next refresh rather than at once. Three reasons, in
  order of weight. A revocation here means "no access", so using it for a
  downgrade would log somebody out for up to fifteen minutes instead of
  lowering their role — the wrong answer for a person who still works here,
  and one they cannot work around, because `/auth/refresh` would mint them a
  correct cookie that `require_auth` then refuses until the row expires.
  Distinguishing the two would mean comparing the revocation against the
  *cookie's* issue time rather than against now, which is a different and
  larger mechanism. And there is **no role-change path in the application at
  all** — no route, no function; a demotion happens out of band, in SQL or at
  a console — so what the ticket's first line describes cannot be reached by
  anything a customer presses. `/auth/refresh` re-reads the row, so a demotion
  does take effect within `ACCESS_MAX_AGE` without this table. If a
  role-change surface is ever built, this is the decision to revisit with it,
  and the mechanism to want is the issue-time comparison.
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
