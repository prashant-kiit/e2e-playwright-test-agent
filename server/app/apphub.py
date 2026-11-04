"""Prompts, settings, and the optional infra sync.

What is left of a module that used to read apps/<app>/: the portal's Prompts
page, the Settings page, and the "sync infra to the target repo" step the
new-target form offers. A target's configuration is a row (app/target_config.py),
its stories are revision content (app/authoring.py), and neither is a file this
module can read any more.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy.orm import Session

from . import config, prompt_store


def read_prompts(session: Session) -> list[dict]:
    """Every prompt the agent can be given, for the portal's Prompts page.

    Rows now, not files (P5-06): the tenant's own version of each prompt, at
    the revision it is on, which is what the runner will actually be sent. The
    page is the authoring surface for the overrides, so it shows the thing a
    customer would edit rather than the bytes the package shipped.

    **Writes nothing**, which took two goes to get right. A tenant that has
    never run anything has no rows, and the page still has to show them the
    defaults they have inherited -- but seeding to achieve that would make a
    GET a write, and a GET has no transaction of its own to commit it, so the
    rows would be created and silently discarded on every page load.
    `prompt_store.current_all` reports what *would* resolve instead: the
    shipped bytes at the seed revision until something seeds them for real.

    Ordered overview first, then the steps in their numbered order, as the page
    has always shown them.
    """
    resolved = prompt_store.current_all(session)

    def order(name: str) -> tuple[int, str]:
        # The overview above the steps; the steps sort lexically, which is what
        # their numeric prefixes are for.
        return (1, name) if name.startswith("steps/") else (0, name)

    return [
        {"name": p.name, "content": p.body, "rev": p.rev}
        for p in sorted(resolved.values(), key=lambda p: order(p.name))
    ]


def read_prompt_history(session: Session, name: str) -> list[dict]:
    """Every revision of one prompt, oldest first, for the portal (#39).

    The counterpart of `read_prompts`: that answers "what is this prompt now",
    this answers "what has it been, and when did it change" -- the half of
    #30's story 24 that P5-06 recorded without ever showing.

    **Writes nothing**, for the reason `read_prompts` has a paragraph about: a
    tenant with no rows still gets their inherited default back, reported
    rather than seeded, because a GET has no transaction of its own to commit
    a row with.

    `prompt_store.PromptNotFound` propagates; the route maps it to a 404.
    """
    return [
        {
            "name": revision.name,
            "content": revision.body,
            "rev": revision.rev,
            "created_at": revision.created_at,
        }
        for revision in prompt_store.history(session, name)
    ]


def save_prompt(session: Session, name: str, content: str) -> dict:
    """Record this tenant's new version of one prompt.

    Appends a revision and commits it; see `prompt_store.save_override`.
    Raises `prompt_store.PromptNotFound` for a name the package never shipped,
    which the route turns into a 404 -- a typo must not create a prompt nothing
    will ever send -- and lets an `IntegrityError` from a concurrent save at
    the same revision through for the route to answer 409.
    """
    saved = prompt_store.save_override(session, name, content)
    return {"name": saved.name, "content": saved.body, "rev": saved.rev}


def settings() -> dict:
    """What the Settings page shows.

    There is no repo root here. P3 removed the shared authoritative mount, and a
    UI that still reported one would be describing a disk that does not exist --
    the runs dir and the worktrees dir are per-run scratch, which is what is
    left.
    """
    return {
        "runner": config.runner_kind(),
        "fake_delay": config.fake_delay(),
        "runs_dir": str(config.runs_dir()),
        "worktrees_dir": str(config.worktrees_dir()),
        "model": os.environ.get("ANTHROPIC_MODEL") or os.environ.get("CLAUDE_MODEL") or "default",
        "anthropic_api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


@dataclass(frozen=True)
class BootstrapOutcome:
    """The portal-facing result of the optional infra sync.

    A DeliveryError is an outcome, not a server error, so the new-target form
    can report a failed sync next to the target it did create.
    """

    ok: bool
    output: str


def run_bootstrap(app: str, *, tools=None) -> BootstrapOutcome:
    """Push the infra entries to the target repo, through app/delivery.

    `tools` is the delivery seam; left unset it is built from the environment.
    Tests pass one backed by a bare repo on disk, so this needs neither network
    nor credentials.
    """
    from .delivery import DeliveryError, bootstrap_target

    try:
        result = bootstrap_target(app, tools=tools)
    except DeliveryError as exc:
        return BootstrapOutcome(ok=False, output=str(exc))
    lines = [
        f"Target: {result.repo} ({result.branch})",
        *([result.changes.strip()] if result.changes.strip() else []),
        result.message,
    ]
    return BootstrapOutcome(ok=True, output="\n".join(lines))
