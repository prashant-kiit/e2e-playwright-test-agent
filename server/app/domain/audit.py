"""What a control-plane mutation is called in the audit log.

`Action` is the vocabulary of the trail: one member per mutation the control
plane records, stored as its `.value` in `audit_log.action`. An enum rather
than free strings because the column is what a compliance reader filters on --
a trail holding both `pat.save` and `pat_saved` answers "every PAT rotation
last quarter" wrongly and gives no sign that it has.

**Two of the mutations #37 lists are missing here, deliberately.** `user add/
remove` and `quota change` are named in the spec's list, and:

* there is **no user-administration surface at all** -- no route, no repo
  function, nothing that adds or removes a user outside the migration that
  seeds the single operator (DESIGN.md §13's tenant-admin surface is story 2 of
  #30 and unbuilt). A member here would be an action nothing can write, which
  is worse than an absence: it would read as covered.
* `quota change` **is** here (`QUOTA_CHANGE`), because `repo.set_tenant_caps`
  exists and is reachable from a console even though no route is -- a mutation
  with no HTTP surface is still a mutation.

So the rule for adding a member is: the mutation has a code path that performs
it. `USER_ADD`/`USER_REMOVE` belong to whichever ticket builds that surface,
and `tests/test_audit.py` records the gap so it is not mistaken for an
oversight.

`(str, Enum)` rather than `StrEnum`, like every other domain enum here -- see
`app/models._enum_col` and the UP042 note in pyproject.toml.
"""

from __future__ import annotations

from enum import Enum


class Action(str, Enum):
    # The one P5-07 exists for: a write into the customer's own repo. DESIGN.md
    # §13 and #30's story 26 name it "delivery approval" -- the admin approving
    # it is the authorization being recorded, which is why the action is named
    # for the approval and not for the push it causes.
    DELIVERY_APPROVE = "delivery.approve"
    # Save and rotate are one action, not two. The row's `before` carries the
    # credential state that was replaced, so "was this a first save or a
    # rotation?" is answered by the data rather than by picking the right verb
    # at the call site -- where the caller does not reliably know either.
    PAT_SAVE = "pat.save"
    PAT_CLEAR = "pat.clear"
    INFRA_SYNC = "infra.sync"
    TARGET_RESET = "target.reset"
    QUOTA_CHANGE = "quota.change"
    # Not in #37's list, and recorded on purpose: #39 asks whether a prompt save
    # is a control-plane mutation and where its actor lives. It is one -- it
    # changes what an unattended agent is told to do against a customer's
    # application -- and `prompts` rows carry no actor column, so this is the
    # only place the acting user is captured. Confirmed on #37 rather than left
    # for a third ticket, which is what #39 asked for.
    PROMPT_SAVE = "prompt.save"
