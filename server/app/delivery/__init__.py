"""Target-repo delivery: the Python replacement for scripts/*.sh.

Three of the four shell tools are no longer user-facing (DESIGN.md §11); they are
control-plane functions behind portal actions. The CLI in __main__.py exists for
operators and for parity with the old scripts.
"""

from __future__ import annotations

from .bootstrap import (
    BootstrapResult,
    ensure_bootstrapped,
    is_bootstrapped,
    require_bootstrapped,
)
from .bootstrap import bootstrap as bootstrap_target
from .errors import (
    ConfirmationMismatch,
    CredentialError,
    DeliveryError,
    GitError,
    NotBootstrapped,
)
from .git import Git
from .github import GitHubClient, PullRequest, TokenInfo
from .push import PushResult, push_artifacts
from .render import StoryRef, TargetRef, infra_files, resolve_story, resolve_target
from .reset import ResetResult, plan_reset, reset_target
from .tools import Tools, default_tools

__all__ = [
    "BootstrapResult",
    "ConfirmationMismatch",
    "CredentialError",
    "DeliveryError",
    "Git",
    "GitError",
    "GitHubClient",
    "NotBootstrapped",
    "PullRequest",
    "PushResult",
    "ResetResult",
    "StoryRef",
    "TargetRef",
    "TokenInfo",
    "Tools",
    "bootstrap_target",
    "default_tools",
    "ensure_bootstrapped",
    "infra_files",
    "is_bootstrapped",
    "plan_reset",
    "push_artifacts",
    "require_bootstrapped",
    "reset_target",
    "resolve_story",
    "resolve_target",
]
