"""The git/GitHub/credential/catalog set the delivery tools work through.

Bundling them makes every tool injectable in one argument: tests pass a Tools
built from an httpx.MockTransport client, a throwaway local remote and a
dict-backed catalog, so the whole delivery surface runs without network,
credentials or a database.

**No delivery function may reach for config, credentials or git outside this
value.** Each phase has changed what its fields *mean* rather than adding
another seam beside it. P3 replaced the long-lived `workspace` with
`catalog.materialize(app)` and made the catalog the source of a target's
configuration. P5-03 does the same to the credential, and that is the change
worth reading carefully:

**A `Tools` is bound to one target before it can push.** Through P4 there was
one `token` here, read from `GITHUB_PAT` once per process, so every delivery
into every customer's repository was authored by the same identity. Now the
credential belongs to the target's row -- sealed, KMS-wrapped -- and `token`
plus `gh` are what `for_app(app)` *resolves* for one target. An unbound Tools
has no credential and says so loudly if used (see `UNBOUND_GITHUB`), rather
than failing somewhere inside a push with an AttributeError on None.

`for_target` is how the delivery entry points do it, because binding is not
the only thing that has to happen per target: if GitHub rejects the credential
mid-delivery, that target's `credential_state` becomes `invalid`. Both halves
in one context manager means an entry point cannot do the first and forget the
second -- and the five entry points that need a credential all read
`with for_target(tools, app) as tools:` identically.

Two paths deliberately do **not** bind: `is_bootstrapped` and the
already-bootstrapped arm of `ensure_bootstrapped`. "Has anything been delivered
to this repo?" is a Postgres query (invariant 5), and requiring a credential to
answer it would be requiring the network by another name -- the same bug
`api.get_catalog` exists to avoid.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace

from .catalog import Catalog
from .credentials import Credentials
from .errors import CredentialError
from .git import Git, require_git
from .github import GitHubClient, clone_url


class _UnboundGitHub:
    """Stands in for the GitHub client a `Tools` has not resolved yet.

    `None` would have been shorter and much worse: the first use would be
    `AttributeError: 'NoneType' object has no attribute 'repo_has_commits'`,
    raised from inside a push, with nothing in it to suggest that a credential
    was never bound. This raises the error the situation actually is, naming
    the call that was missed.
    """

    def __getattr__(self, name: str):
        raise CredentialError(
            f"the delivery tools are not bound to a target, so there is no "
            f"GitHub credential to call {name!r} with; bind them first with "
            f"tools.for_app(app) -- or, in a delivery entry point, "
            f"`with for_target(tools, app) as tools:`"
        )


UNBOUND_GITHUB = _UnboundGitHub()


@dataclass(frozen=True)
class Tools:
    gh: GitHubClient
    git: Git
    token: str
    catalog: Catalog
    # Where a target's credential comes from. `None` is the test doubles' path:
    # a `Tools` carrying a literal `token` is already bound to whatever it is
    # going to push with, so `for_app` has nothing to resolve. Production
    # always has one (`default_tools`), which is what retires the process-wide
    # `GITHUB_PAT` -- there is no longer anywhere for it to be read into.
    credentials: Credentials | None = None
    # How a resolved token becomes a client. A field rather than a direct call
    # so a test can observe what `for_app` built without a real httpx client.
    gh_factory: Callable[[str], GitHubClient] = GitHubClient.from_token
    # Which target this seam is bound to, if any. It makes `for_app` idempotent,
    # which matters because the entry points nest: `reset_target` calls
    # `plan_reset`, and re-binding there would mean a second KMS unwrap and a
    # second httpx client per reset.
    app: str | None = None

    def clone_url(self, repo: str) -> str:
        """The one method here that does something: it adds the credential.

        Everything delivery asks the database it asks `tools.catalog` directly
        -- `config`, `materialize`, `state`, `record_delivered` -- so the call
        site names its source instead of this class forwarding four times.
        """
        if not self.token:
            raise CredentialError(
                "the delivery tools are not bound to a target, so there is no "
                "credential to clone with; bind them first with tools.for_app(app)"
            )
        return clone_url(repo, self.token)

    def for_app(self, app: str) -> Tools:
        """This same seam, carrying `app`'s own credential.

        Returns `self` when there is no credential source, so every existing
        delivery test -- which builds a `Tools` with a literal token and no
        `credentials` -- keeps exercising exactly what it did before.
        """
        if self.credentials is None or self.app == app:
            return self
        token = self.credentials.token_for(app)
        return replace(self, token=token, gh=self.gh_factory(token), app=app)


@contextmanager
def for_target(tools: Tools | None, app: str, *, bind: bool = True) -> Iterator[Tools]:
    """The delivery seam, bound to one target, with the fail-loud rule attached.

    Binding and "GitHub rejected this credential" are one step because they are
    two halves of the same decision: the credential this resolves is the
    credential whose rejection has to be recorded. Separating them would leave
    five entry points each able to bind and forget to mark.

    The `CredentialError` is **re-raised**, never swallowed. §8's rule is that a
    401/403 fails the *delivery* and surfaces it -- the route turns it into a
    502 the operator reads, and the run whose results are already durable is
    untouched because delivery is a separate control-plane action.

    `bind=False` is for the dry runs. A `--dry-run` bootstrap or push reads the
    target's row, materializes its head revision and reports what it *would*
    push: it opens no connection to GitHub and clones nothing, so requiring a
    credential would make the preview impossible in the exact state it is most
    useful -- a target just created, with no PAT saved yet. The same reasoning
    keeps `is_bootstrapped` unbound.
    """
    tools = tools or default_tools()
    if not bind:
        yield tools
        return
    bound = tools.for_app(app)
    try:
        yield bound
    except CredentialError:
        if bound.credentials is not None:
            bound.credentials.mark_invalid(app)
        raise


def default_tools() -> Tools:
    """Built from the configured database, the key wrapper, and git.

    **Unbound**: there is no process-wide credential left to put in it. The
    `.env`-beside-the-workspace fallback went in P3 (the workspace is a tree an
    LLM wrote while reading a live customer website, so a credential lookup
    inside agent-produced content is an exfiltration path), and `GITHUB_PAT`
    from the environment goes here: a single operator token is not any tenant's
    credential, and sealing it per target would silently give every customer
    the same identity under a per-tenant name. A target's token comes from its
    own row, through `for_app`.
    """
    from .. import storage
    from ..db import SessionLocal
    from .catalog import DbCatalog
    from .credentials import DbCredentials

    require_git()
    return Tools(
        gh=UNBOUND_GITHUB,
        git=Git(),
        token="",
        catalog=DbCatalog(SessionLocal, storage.from_env()),
        credentials=DbCredentials(SessionLocal),
    )
