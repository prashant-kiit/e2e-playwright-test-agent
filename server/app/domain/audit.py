"""What a control-plane mutation is called in the audit log.

`Action` is the vocabulary of the trail: one member per mutation the control
plane records, stored as its `.value` in `audit_log.action`. An enum rather
than free strings because the column is what a compliance reader filters on --
a trail holding both `pat.save` and `pat_saved` answers "every PAT rotation
last quarter" wrongly and gives no sign that it has.

**The rule for adding a member is: the mutation has a code path that performs
it.** An action nothing can write is worse than an absence, because it reads as
covered. That rule is why `quota change` was here before it had a route
(`repo.set_tenant_caps` was reachable from a console, and a mutation with no
HTTP surface is still a mutation) and why `user add/remove` was not -- there
was no user-administration surface at all, no route and no function.

P5-14 (#46) built that surface, so `USER_ADD` and `USER_REMOVE` are here now
and #37's list of seven is complete. Both are written by `app/accounts/`,
which is the only module that adds or removes a user; the first admin of a new
tenant is a `USER_ADD` too, recorded against the tenant being created with
`system` as the actor, because the operator CLI that creates a tenant binds no
user and "a human at a console did this, and we cannot say which human" is the
honest answer (the same one `app/delivery/__main__.py` gives).

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
    # P5-14 / #46. One action per direction rather than a single `user.change`
    # with a verb in the payload: "every account added last quarter" is the
    # question a compliance reader asks, and it should be a filter on this
    # column rather than a filter plus a decode of `after`.
    #
    # A role change is deliberately **not** a third action yet: nothing can
    # perform one. `accounts.add_user` assigns a role at creation and there is
    # no update path, so a `USER_ROLE_CHANGE` member would be exactly the
    # "action nothing can write" this module's docstring argues against.
    USER_ADD = "user.add"
    USER_REMOVE = "user.remove"
