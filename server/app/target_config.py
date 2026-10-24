"""A target's configuration: the columns that replaced apps/<app>/app.json.

P3 moves config into Postgres (DESIGN.md §4). `app.json` carried `baseURL`,
`locators`, `agentNotes`, `targetRepo` and `targetBranch`; those are now columns
on `targets`, and this module owns what a valid value is.

**Validation belongs on the write path.** Target resolution used to refuse an
empty or placeholder `targetRepo` when delivery read the file -- which is hours
or days after somebody typed it, with nobody around to be told. The same refusal
lives here instead, at the moment of the write, plus the base-URL format check
the generated Playwright config needs in order to mean anything.

Validating that the host resolves to a **public** address is egress work and
lands with P4 (DESIGN.md §6); this is format validation only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# The placeholder the template set ships with; never a real target.
PLACEHOLDER_REPO = "owner/repo-that-receives-the-tests"
DEFAULT_BRANCH = "master"

# A GitHub owner/repo: two non-empty segments of the characters GitHub allows,
# and no third segment (a/b/c is a path, not a repo).
OWNER_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")

HTTP_SCHEMES = frozenset({"http", "https"})


class ConfigError(ValueError):
    """A configuration value a target may not be saved with."""


def clean_base_url(value: object) -> str:
    """An absolute http(s) URL with a host.

    Relative URLs are what the *tests* use (`page.goto('/')`); the target's
    `baseURL` is what makes them resolve, so it has to be absolute. A scheme we
    cannot drive a browser to -- `ftp:`, `javascript:` -- is refused for the
    same reason.
    """
    text = str(value or "").strip()
    if not text:
        raise ConfigError("base URL is required (an absolute http(s) URL)")
    parsed = urlparse(text)
    if parsed.scheme not in HTTP_SCHEMES or not parsed.netloc:
        raise ConfigError(
            f"base URL must be an absolute http(s) URL, got {text!r}"
        )
    return text


def clean_target_repo(value: object) -> str:
    """The `owner/repo` that receives the delivered tests."""
    text = str(value or "").strip()
    if not text:
        raise ConfigError("target repo is required (owner/repo)")
    if text == PLACEHOLDER_REPO:
        raise ConfigError(
            f"target repo is still the template placeholder {PLACEHOLDER_REPO!r}; "
            "set the repo that receives the tests"
        )
    if not OWNER_REPO.match(text):
        raise ConfigError(f"target repo must be owner/repo, got {text!r}")
    return text


def clean_target_branch(value: object) -> str:
    """The branch delivery pushes into. Defaults here, not in the database."""
    return str(value or "").strip() or DEFAULT_BRANCH


def clean_locators(value: object) -> str:
    """Free text: how elements are best located in this app."""
    return str(value or "").strip()


def clean_agent_notes(value: object) -> list[str]:
    """A list of notes. It is a list today and is injected as a list, so a bare
    string is a mistake rather than a one-element list we should guess at."""
    if value is None:
        return []
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ConfigError("agent notes must be a list of strings")
    notes = [str(note).strip() for note in value]
    return [note for note in notes if note]


@dataclass(frozen=True)
class TargetConfig:
    """One target's configuration, detached from the ORM row.

    The runner, the prompt renderer and delivery all need these five values and
    none of them should hold a Session open to read them, so the row is read
    once and travels as this.
    """

    app: str
    name: str
    base_url: str
    locators: str
    agent_notes: tuple[str, ...]
    target_repo: str
    target_branch: str

    @property
    def chromium_project(self) -> str:
        """The generated config is single-target, so project names carry no app
        prefix (DESIGN.md §4)."""
        return "chromium"


def config_of(target) -> TargetConfig:
    """The configuration a `targets` row holds."""
    return TargetConfig(
        app=target.app,
        name=target.name,
        base_url=target.base_url,
        locators=target.locators or "",
        agent_notes=tuple(target.agent_notes or ()),
        target_repo=target.target_repo,
        target_branch=target.target_branch,
    )
