"""Target-repo delivery: the Python replacement for scripts/*.sh.

Three of the four shell tools are no longer user-facing (DESIGN.md §11); they are
control-plane functions behind portal actions. The CLI in __main__.py exists for
operators and for parity with the old scripts.

**The entry points are re-exported lazily, and that is a credential decision.**
P4 made §6's rule structural: no GitHub credential may be readable from a
sandbox. But a sandbox runs the same server package as the API, and the modules
that execute a run legitimately need this package's *tracked-tree* definition --
`write_infra` for hydrate's render step, `tracked_tree` for ingest,
`resolve_story` for the agent's prompt. Importing `app.delivery.render` imports
this file, and an eager re-export of `default_tools` here would pull
`app.delivery.github`, the one module that reads `GITHUB_PAT`, into the import
graph of every sandbox.

So the names below resolve on first attribute access instead. Wanting the naming
contract no longer drags the credential reader along, and
tests/test_sandbox_credentials.py walks the entrypoint's real import graph to
keep it that way. Nothing about how the control plane uses this package changes:
`delivery.default_tools()` and `except delivery.DeliveryError` work exactly as
before, and a name missing from the table below fails on first use rather than
silently resolving -- which `test_the_delivery_entry_points_are_still_importable`
checks by reading every one of them.
"""

from __future__ import annotations

# name -> the submodule it lives in. One table, so a reader can see the whole
# surface of the package in one place, as the eager import block used to show.
_EXPORTS: dict[str, str] = {
    "BootstrapResult": "bootstrap",
    "ensure_bootstrapped": "bootstrap",
    "is_bootstrapped": "bootstrap",
    "bootstrap_target": "bootstrap",
    "Catalog": "catalog",
    "DbCatalog": "catalog",
    "DeliveryState": "catalog",
    "ConfirmationMismatch": "errors",
    "CredentialError": "errors",
    "DeliveryError": "errors",
    "GitError": "errors",
    "Git": "git",
    "GitHubClient": "github",
    "PullRequest": "github",
    "TokenInfo": "github",
    "PushResult": "push",
    "push_artifacts": "push",
    "StoryRef": "render",
    "TargetRef": "render",
    "infra_files": "render",
    "resolve_story": "render",
    "target_ref": "render",
    "ResetResult": "reset",
    "plan_reset": "reset",
    "reset_target": "reset",
    "Tools": "tools",
    "default_tools": "tools",
}

# `bootstrap` is exported under another name: the module and the function it
# holds cannot both be `delivery.bootstrap`.
_ALIASES = {"bootstrap_target": "bootstrap"}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    """Resolve one re-exported name, importing its submodule on first use."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module = import_module(f".{module_name}", __name__)
    value = getattr(module, _ALIASES.get(name, name))
    globals()[name] = value  # resolved once; later reads are plain attribute reads
    return value


def __dir__() -> list[str]:
    return __all__
