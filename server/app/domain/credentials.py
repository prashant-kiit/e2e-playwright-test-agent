"""The state of a target's GitHub credential.

Three states, because the portal has to say three different things and because
"delivery is impossible right now" and "delivery will stop working soon" are
not the same message:

* `ABSENT` -- no PAT has been saved. Delivery cannot run at all, and the fix is
  for the customer to paste one.
* `VALID` -- a PAT is stored and GitHub accepted it the last time we looked. It
  may still be approaching its expiry, which is `targets.pat_expires_at` and a
  warning rather than a state: the credential works today.
* `INVALID` -- GitHub answered 401 or 403 at delivery. This is set by the
  delivery path, never guessed, and it is deliberately **sticky**: the
  credential stays invalid until somebody saves a new one, so a customer sees
  "your token was rejected" instead of the same delivery failing silently
  again. Marking it must never fail the *run* -- the run's results are already
  durable (DESIGN.md §8).

A column rather than an inference from `github_pat_ciphertext is None`: the
rejected case has ciphertext and is still unusable, and an operator reading the
row should not have to reconstruct that.

`(str, Enum)` rather than `StrEnum`, like every other domain enum here -- see
`app/models._enum_col` and the UP042 note in pyproject.toml.
"""

from __future__ import annotations

from enum import Enum


class CredentialState(str, Enum):
    ABSENT = "absent"
    VALID = "valid"
    INVALID = "invalid"
