""""Whose credential pushed this?" — per-tenant PATs, and what holds them.

Through P4 there was one operator `GITHUB_PAT` in the API's environment, so
every delivery into every customer's repository was authored by the same
identity. P5-03 makes the credential a property of the *target row*: ciphertext
in Postgres, the data key wrapped by a KMS key, decrypted only in the control
plane and only inside the delivery `Tools` seam.

These tests are about external behaviour, per the spec's testing decisions: a
PAT round-trips, a token missing a scope is refused at save time while the
operator can still fix it, GitHub rejecting a token marks the credential
invalid, and nothing reads the plaintext out of the row. How the cipher is
built is tests/test_envelope.py's business.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app import envelope, repo
from app.delivery import credentials as creds
from app.delivery import tools as tools_mod
from app.delivery.git import Git
from app.delivery.github import TokenInfo
from app.delivery.tools import Tools
from app.domain.credentials import CredentialState
from app.models import Target, Tenant
from app.tenancy import tenant_scope
from tests.target_helpers import create_target

PAT = "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
OTHER_PAT = "ghp_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


@pytest.fixture()
def wrapper():
    return envelope.LocalKeyWrapper(b"the-suite-wrapping-key")


@pytest.fixture()
def target(session):
    project = repo.create_project(session, name="demo")
    return create_target(session, project.id, app="demo", name="Demo")


def token_info(
    *, scopes=("repo", "workflow"), expires_at=None, login="octocat"
) -> TokenInfo:
    return TokenInfo(login=login, scopes=frozenset(scopes), expires_at=expires_at)


def validator(info: TokenInfo):
    """The save path's live GitHub call, injected. Records what it was given so
    a test can assert the token really was validated."""
    seen: list[str] = []

    def validate(token: str) -> TokenInfo:
        seen.append(token)
        return info

    validate.seen = seen
    return validate


# --- a target starts with no credential ----------------------------------

def test_a_new_target_has_no_credential(target):
    """Absent is a state, not a null to be guessed at: the portal can say "no
    PAT yet" rather than "unknown"."""
    assert target.credential_state is CredentialState.ABSENT
    assert target.github_pat_ciphertext is None
    assert target.pat_expires_at is None


# --- saving one ----------------------------------------------------------

def test_a_saved_pat_round_trips_through_encrypt_and_decrypt(session, target, wrapper):
    creds.save_pat(
        session, target, PAT, validate=validator(token_info()), wrapper=wrapper
    )

    assert creds.decrypt_pat(target, wrapper=wrapper) == PAT


def test_the_row_holds_ciphertext_and_never_the_token(session, target, wrapper):
    """The claim a database dump has to survive, asserted on the column itself."""
    creds.save_pat(
        session, target, PAT, validate=validator(token_info()), wrapper=wrapper
    )
    session.refresh(target)

    assert PAT not in (target.github_pat_ciphertext or "")
    assert target.github_pat_ciphertext.startswith(envelope.SEAL_PREFIX)
    assert target.credential_state is CredentialState.VALID


def test_saving_a_pat_validates_the_token_that_was_pasted(session, target, wrapper):
    validate = validator(token_info())

    creds.save_pat(session, target, PAT, validate=validate, wrapper=wrapper)

    assert validate.seen == [PAT], "validated the pasted token, not a stored one"


def test_the_expiry_github_reports_is_stored(session, target, wrapper):
    expires = datetime(2027, 3, 1, 12, 0, tzinfo=UTC)

    creds.save_pat(
        session,
        target,
        PAT,
        validate=validator(token_info(expires_at=expires)),
        wrapper=wrapper,
    )
    session.refresh(target)

    assert target.pat_expires_at == expires


def test_replacing_a_pat_replaces_the_ciphertext(session, target, wrapper):
    """Rotation: the new token is what delivery decrypts afterwards."""
    creds.save_pat(session, target, PAT, validate=validator(token_info()), wrapper=wrapper)
    creds.save_pat(
        session, target, OTHER_PAT, validate=validator(token_info()), wrapper=wrapper
    )

    assert creds.decrypt_pat(target, wrapper=wrapper) == OTHER_PAT


# --- save-time scope validation ------------------------------------------

def test_a_token_missing_workflow_is_refused_at_save_time(session, target, wrapper):
    """Bootstrap pushes .github/workflows/playwright.yml, so `repo` alone is a
    token that will fail hours later at a delivery. Refuse it now, while the
    operator still has the paste buffer open."""
    with pytest.raises(creds.CredentialRejected, match="workflow"):
        creds.save_pat(
            session,
            target,
            PAT,
            validate=validator(token_info(scopes=("repo",))),
            wrapper=wrapper,
        )

    session.refresh(target)
    assert target.credential_state is CredentialState.ABSENT
    assert target.github_pat_ciphertext is None


def test_a_fine_grained_token_reporting_no_scopes_is_accepted(session, target, wrapper):
    """GitHub reports no x-oauth-scopes at all for a fine-grained PAT, so an
    empty set means "cannot tell", not "insufficient". Rejecting a valid token
    here is worse than failing loud at push, which the delivery path does."""
    creds.save_pat(
        session, target, PAT, validate=validator(token_info(scopes=())), wrapper=wrapper
    )
    session.refresh(target)

    assert target.credential_state is CredentialState.VALID
    assert creds.decrypt_pat(target, wrapper=wrapper) == PAT


def test_an_empty_token_is_refused_without_a_github_call(session, target, wrapper):
    validate = validator(token_info())

    with pytest.raises(creds.CredentialRejected):
        creds.save_pat(session, target, "   ", validate=validate, wrapper=wrapper)

    assert validate.seen == []


def test_a_token_github_itself_rejects_is_refused_at_save_time(session, target, wrapper):
    """A 401 on /user at save time is the operator's typo, not an outage."""

    def validate(token: str) -> TokenInfo:
        raise creds.CredentialError("GitHub rejected the token (401) for GET /user")

    with pytest.raises(creds.CredentialRejected, match="401"):
        creds.save_pat(session, target, PAT, validate=validate, wrapper=wrapper)

    session.refresh(target)
    assert target.credential_state is CredentialState.ABSENT


# --- clearing one --------------------------------------------------------

def test_clearing_a_pat_returns_the_target_to_absent(session, target, wrapper):
    creds.save_pat(session, target, PAT, validate=validator(token_info()), wrapper=wrapper)

    creds.clear_pat(session, target)
    session.refresh(target)

    assert target.credential_state is CredentialState.ABSENT
    assert target.github_pat_ciphertext is None
    assert target.pat_expires_at is None


# --- expiry, as the portal needs it --------------------------------------

def test_a_credential_expiring_soon_carries_a_warning(session, target, wrapper):
    soon = datetime.now(UTC) + timedelta(days=3)
    creds.save_pat(
        session,
        target,
        PAT,
        validate=validator(token_info(expires_at=soon)),
        wrapper=wrapper,
    )

    status = creds.credential_status(target)

    assert status.expiring_soon is True
    assert status.days_until_expiry == 3
    assert "3 days" in (status.warning or "")


def test_a_credential_with_a_distant_expiry_carries_no_warning(session, target, wrapper):
    creds.save_pat(
        session,
        target,
        PAT,
        validate=validator(token_info(expires_at=datetime.now(UTC) + timedelta(days=90))),
        wrapper=wrapper,
    )

    status = creds.credential_status(target)

    assert status.expiring_soon is False
    assert status.warning is None


def test_an_already_expired_credential_says_so(session, target, wrapper):
    creds.save_pat(
        session,
        target,
        PAT,
        validate=validator(token_info(expires_at=datetime.now(UTC) - timedelta(days=1))),
        wrapper=wrapper,
    )

    status = creds.credential_status(target)

    assert status.expiring_soon is True
    assert "expired" in (status.warning or "").lower()


def test_a_target_with_no_pat_warns_that_delivery_needs_one(target):
    status = creds.credential_status(target)

    assert status.state is CredentialState.ABSENT
    assert status.expires_at is None
    assert "no github credential" in (status.warning or "").lower()


def test_an_invalid_credential_warns_that_github_rejected_it(session, target, wrapper):
    creds.save_pat(session, target, PAT, validate=validator(token_info()), wrapper=wrapper)
    creds.mark_invalid(session, target)

    status = creds.credential_status(target)

    assert status.state is CredentialState.INVALID
    assert "rejected" in (status.warning or "").lower()


# --- DbCredentials: the credential half of the delivery seam -------------

def _saved(session_factory, wrapper, *, app="demo", token=PAT):
    """A target with a stored PAT, through its own session, and its id."""
    from app import repo as repo_mod

    with session_factory() as s:
        project = repo_mod.create_project(s, name=app)
        tgt = create_target(s, project.id, app=app, name=app.title())
        creds.save_pat(s, tgt, token, validate=validator(token_info()), wrapper=wrapper)
        return tgt.id


def test_the_seam_decrypts_the_targets_own_token(session_factory, wrapper):
    _saved(session_factory, wrapper)

    assert creds.DbCredentials(session_factory, wrapper).token_for("demo") == PAT


def test_each_target_gets_its_own_token(session_factory, wrapper):
    """The whole point of the ticket: two targets, two credentials, and a
    delivery authored by the right one."""
    _saved(session_factory, wrapper, app="demo", token=PAT)
    _saved(session_factory, wrapper, app="other", token=OTHER_PAT)
    seam = creds.DbCredentials(session_factory, wrapper)

    assert seam.token_for("demo") == PAT
    assert seam.token_for("other") == OTHER_PAT


def test_a_target_with_no_credential_fails_loud_and_names_itself(
    session_factory, wrapper
):
    from app import repo as repo_mod

    with session_factory() as s:
        project = repo_mod.create_project(s, name="bare")
        create_target(s, project.id, app="bare", name="Bare")

    with pytest.raises(creds.CredentialError, match="bare"):
        creds.DbCredentials(session_factory, wrapper).token_for("bare")


def test_a_credential_github_has_rejected_is_not_handed_out_again(
    session_factory, wrapper
):
    """Sticky invalid: the next delivery is refused with a reason rather than
    pushing with a token we already know GitHub refuses."""
    seam = creds.DbCredentials(session_factory, wrapper)
    _saved(session_factory, wrapper)

    seam.mark_invalid("demo")

    with pytest.raises(creds.CredentialError, match="rejected"):
        seam.token_for("demo")


def test_marking_invalid_leaves_the_ciphertext_in_place(session_factory, wrapper):
    """So an operator who fixes the token's scopes on GitHub's side can re-save
    the same value, and so the evidence of what was rejected survives."""
    target_id = _saved(session_factory, wrapper)

    creds.DbCredentials(session_factory, wrapper).mark_invalid("demo")

    with session_factory() as s:
        row = s.get(Target, target_id)
        assert row.credential_state is CredentialState.INVALID
        assert row.github_pat_ciphertext


def test_another_tenants_target_has_no_credential_here(session_factory, wrapper):
    """The credential lookup is tenant-scoped like every other read: a tenant
    cannot name another tenant's target and be handed its PAT.

    The failure is "no such target", **not** "no credential for that target":
    the same choice P5-02 made in refusing another tenant's row with a 404
    rather than a 403. A credential-shaped error would confirm that the slug
    names something somewhere, which is an inventory of other customers.
    """
    _saved(session_factory, wrapper)
    with session_factory() as s:
        s.add(Tenant(id=2, slug="second", name="Second"))
        s.commit()

    with tenant_scope(2), pytest.raises(creds.DeliveryError, match="no such target"):
        creds.DbCredentials(session_factory, wrapper).token_for("demo")


# --- the Tools seam: bound to one target, and nothing else ---------------

class StubCredentials:
    """A `Credentials` built from a dict, like `DictCatalog` is from a directory."""

    def __init__(self, tokens: dict[str, str]) -> None:
        self.tokens = tokens
        self.invalidated: list[str] = []

    def token_for(self, app: str) -> str:
        try:
            return self.tokens[app]
        except KeyError as exc:
            raise creds.CredentialError(f"no credential for {app!r}") from exc

    def mark_invalid(self, app: str) -> None:
        self.invalidated.append(app)


def unbound_tools(credentials=None) -> Tools:
    """A `Tools` as `default_tools()` builds it: no credential bound yet."""
    return Tools(
        gh=tools_mod.UNBOUND_GITHUB,
        git=Git(),
        token="",
        catalog=object(),
        credentials=credentials,
        gh_factory=lambda token: f"client-for:{token}",
    )


def test_binding_to_a_target_resolves_that_targets_token(session):
    seam = StubCredentials({"demo": PAT, "other": OTHER_PAT})

    bound = unbound_tools(seam).for_app("other")

    assert bound.token == OTHER_PAT
    assert bound.gh == f"client-for:{OTHER_PAT}"


def test_binding_builds_the_github_client_from_that_targets_token(session):
    """Not from a process-wide one: the client carries the Authorization header,
    so a shared client would push to every customer's repo as one identity."""
    seam = StubCredentials({"demo": PAT})

    assert unbound_tools(seam).for_app("demo").gh == f"client-for:{PAT}"


def test_an_unbound_seam_refuses_to_be_used_and_says_what_is_missing():
    """The failure mode worth designing for: a delivery function that forgot to
    bind would otherwise get an AttributeError on None halfway through a push."""
    unbound = unbound_tools(StubCredentials({}))

    with pytest.raises(creds.CredentialError, match="for_app"):
        unbound.gh.repo_has_commits("o/r")
    with pytest.raises(creds.CredentialError, match="for_app"):
        unbound.clone_url("o/r")


def test_a_seam_with_no_credential_source_binds_to_itself():
    """The test doubles' path: `LocalTools` carries a literal token and no
    credential source, so binding is a no-op and every existing delivery test
    keeps exercising the same thing."""
    static = Tools(gh="gh", git=Git(), token="t0ken", catalog=object())

    assert static.for_app("demo") is static


def test_a_credential_failure_during_delivery_marks_the_credential_invalid():
    seam = StubCredentials({"demo": PAT})

    with pytest.raises(creds.CredentialError):
        with tools_mod.for_target(unbound_tools(seam), "demo"):
            raise creds.CredentialError("GitHub rejected the token (401) for GET /repos")

    assert seam.invalidated == ["demo"]


def test_a_non_credential_delivery_failure_leaves_the_credential_alone():
    """A missing test suite or a git conflict says nothing about the token, and
    marking it invalid would send the customer to rotate a working credential."""
    seam = StubCredentials({"demo": PAT})

    with pytest.raises(creds.DeliveryError):
        with tools_mod.for_target(unbound_tools(seam), "demo"):
            raise creds.DeliveryError("no test suite at tests/checkout")

    assert seam.invalidated == []


def test_a_successful_delivery_leaves_the_credential_valid():
    seam = StubCredentials({"demo": PAT})

    with tools_mod.for_target(unbound_tools(seam), "demo") as bound:
        assert bound.token == PAT

    assert seam.invalidated == []


def test_a_dry_run_needs_no_credential():
    """A `--dry-run` push or bootstrap reads the row and the head revision and
    reports what it *would* do; it opens no connection to GitHub. Requiring a
    credential would make the preview impossible for a target that has just
    been created and has no PAT yet -- which is when it is most useful."""
    seam = StubCredentials({})  # nothing saved for any target

    with tools_mod.for_target(unbound_tools(seam), "demo", bind=False) as bound:
        assert bound.token == ""

    assert seam.invalidated == []
