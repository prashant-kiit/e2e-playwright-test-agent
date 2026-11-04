"""HTTP API for projects, targets, their trees and their runs.

Thin layer over app/repo.py and app/authoring.py. Exceptions map to status
codes: NotFound -> 404, RunConflict -> 409 (a live run holds the target, for a
second run *or* for an operator write), a refused configuration or story ->
422, a delivery problem -> 400/502.

P3 collapsed apps and targets into one concept. There is no filesystem-backed
app list, no story list read off a directory and no snapshot-the-disk action:
a target is a row, its tree is a revision, and the portal is the only way a
story gets in.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import (
    apphub,
    audit,
    authoring,
    delivery,
    envelope,
    prompt_store,
    repo,
    revisions,
    storage,
    target_config,
)
from .auth import AdminDep, AuthDep
from .db import SessionLocal, get_session
from .delivery import credentials as pats
from .domain import quotas
from .domain.credentials import CredentialState
from .domain.status import RunStatus, is_live, is_terminal
from .models import Artifact
from .orchestrator.bus import LogBus, bus_from_env
from .sandbox import dispatch, egress
from .schemas import (
    ArtifactOut,
    AuditEntryOut,
    CapsBody,
    CredentialOut,
    DeliverBody,
    DeliveryOut,
    DeliveryStateOut,
    FileIndexOut,
    PatBody,
    ProjectCreate,
    ProjectOut,
    PromptOut,
    PromptRevisionOut,
    PromptSave,
    ResetBody,
    RevisionOut,
    RunCreate,
    RunOut,
    StepOut,
    StoryBody,
    StoryContentOut,
    StoryOut,
    TargetConfigUpdate,
    TargetCreate,
    TargetCreatedOut,
    TargetOut,
    UsageOut,
    WriteOut,
)
from .storage import Storage

# Everything on this router requires a valid session cookie (tests override
# require_auth to a no-op). Health and /auth/* live off this router.
router = APIRouter(dependencies=[AuthDep])


def get_launcher() -> Callable[[int], None]:
    """The background run launcher: "start working on this run".

    Still the only injection point for that, and still a plain
    `Callable[[int], None]`, which is what keeps the tests' override a no-op
    lambda. What changed in P4 is behind it: `make_launcher` picks a daemon
    thread or a container per run from `QA_SANDBOX`, the way `make_runner` picks
    `fake` or `claude` (app/sandbox/dispatch.py).
    """
    return dispatch.make_launcher()


def get_scheduler() -> dispatch.Scheduler | None:
    """The same dispatch seam, for the paths that *end* a run's work.

    Not a second seam: one `Scheduler` protocol and one factory, exposed here as
    well because pause and stop have to be able to reap a sandbox and a route
    needs something a test can substitute. `get_launcher` remains the only
    injection point for starting a run.

    `None` on the thread path, where there is no sandbox to schedule -- the
    paths that reap one ask without having to catch anything.
    """
    return dispatch.make_scheduler()


def get_storage() -> Storage:
    """The artifact blob store. Overridden with a fake in tests."""
    return storage.from_env()


def get_resolver() -> egress.Resolver:
    """The DNS resolver the write path checks a base URL with.

    A dependency rather than a module default because the check is load-bearing
    (DESIGN.md §6: a base URL must resolve to a **public** address) and a check
    nothing can substitute is a check nothing can test. Overridden in tests; the
    suite also refuses the real resolver outright, so forgetting the override
    fails loudly instead of depending on DNS.
    """
    return egress.system_resolver


def get_log_bus() -> LogBus:
    """Where a run's live log lines are read from.

    The same factory the launcher publishes through, so the reader and the
    writer cannot disagree about where a run's lines are: in-process for a
    thread run, `run_log` for a run in a container.
    """
    return bus_from_env()


def get_bootstrap_runner() -> Callable[[str], apphub.BootstrapOutcome]:
    """The optional "sync infra to the target repo" step. Overridden in tests
    (no git, no network)."""
    return apphub.run_bootstrap


def get_catalog(store: Storage = Depends(get_storage)) -> delivery.Catalog:
    """Just the database half of the delivery seam: no git, no GitHub, no PAT.

    "Is this delivered?" is a Postgres question (invariant 5), so answering it
    must not need a credential. Hanging it off `get_delivery_tools` meant an
    operator with no credential configured got a 503 for an answer that never
    leaves the database -- found in a real browser, where the portal could not
    show the badge at all.

    P5-03 makes that split matter more rather than less: a credential is now
    per target and saved in the portal, so "a target with no PAT yet" is the
    *normal* state of a newly created target, and it must still be able to say
    where it stands.
    """
    return delivery.DbCatalog(SessionLocal, store)


def get_token_validator():
    """The live GitHub call that validates a pasted PAT's scopes and expiry.

    A dependency for the same reason `get_resolver` is one: the check is
    load-bearing -- it is what turns "your delivery will fail in four hours"
    into "this token is missing `workflow`" -- and a check nothing can
    substitute is a check nothing tests. No route touches the network in the
    suite because every test overrides this.
    """
    return pats.validate_with_github


def get_key_wrapper() -> envelope.KeyWrapper:
    """What wraps the data key a PAT is sealed under.

    `wrapper_from_env` picks the cloud KMS when `QA_KMS_KEY_ID` is set and an
    in-process key otherwise, so the dev stack works offline -- see
    app/envelope.py, which also explains why the second is not a production
    configuration.
    """
    return envelope.wrapper_from_env()


def get_delivery_tools() -> delivery.Tools:
    """git + GitHub + the catalog + the credential seam, **unbound**.

    Overridden in tests so no route touches the network. Building it here (not
    at import) keeps an environment problem from breaking unrelated endpoints:
    dependencies resolve before the handler body runs, so a failure here would
    escape the routes' own exception handling as a bare 500, and a missing
    `git` is reported as 503 with the reason instead.

    Since P5-03 a *missing credential* is no longer one of those failures. There
    is nothing process-wide left to be missing: the seam carries no token until
    a delivery binds it to a target (`tools.for_app`), and a target with no PAT
    saved fails inside the route, where it becomes a message about that target
    rather than a 503 about the service.
    """
    try:
        return delivery.default_tools()
    except delivery.DeliveryError as exc:
        raise HTTPException(
            status_code=503, detail=f"delivery is unavailable: {exc}"
        ) from exc


# --- prompts + settings --------------------------------------------------

@router.get("/prompts", response_model=list[PromptOut])
def list_prompts(session: Session = Depends(get_session)):
    return apphub.read_prompts(session)


@router.get(
    "/prompts/{name:path}/history", response_model=list[PromptRevisionOut]
)
def prompt_history(name: str, session: Session = Depends(get_session)):
    """Every revision of one prompt, oldest first (#39).

    The read half of #30's story 24: P5-06 made the rows append-only and
    recorded which revision a run used, and left "so that I can see what
    changed and when" with no surface at all -- the data was there and nothing
    could reach it.

    **Declared before `PUT /prompts/{name:path}`** and sharing its path
    converter. `:path` is greedy because a prompt's name carries slashes
    (`steps/2-plan.md`), and the literal `/history` suffix is what keeps this
    unambiguous: the name is everything before it.

    A name the package never shipped is a 404, the same answer the `PUT`
    gives. An empty list would be a worse answer than a 404 here, because it
    reads as "this prompt has never been edited" -- a true-sounding statement
    about a prompt that does not exist.

    No new proxy entry: `/prompts` is already in `docker/nginx.conf` and
    `web/vite.config.js`, both of which match on the first path segment, so
    this sub-path is forwarded by the entries that already exist. Checked
    rather than assumed, because P5-04 shipped a panel that was invisible in
    the real app for exactly this reason while 84 frontend tests passed.
    """
    try:
        return apphub.read_prompt_history(session, name)
    except prompt_store.PromptNotFound as exc:
        raise HTTPException(status_code=404, detail=f"no such prompt: {name}") from exc


@router.put("/prompts/{name:path}", response_model=PromptOut)
def save_prompt(
    name: str, body: PromptSave, session: Session = Depends(get_session)
):
    """Record this tenant's version of one prompt.

    `{name:path}` because a prompt's name carries a slash (`steps/2-plan.md`):
    it is the file's path relative to the prompts directory, which is the name
    the page has always shown and the key the rows use.

    A name the package never shipped is a 404. Accepting it would create a row
    nothing resolves -- a prompt a customer could carefully tune and never have
    sent -- which is a worse outcome than being told the name is wrong.
    """
    try:
        saved = apphub.save_prompt(session, name, body.content)
    except prompt_store.PromptNotFound as exc:
        raise HTTPException(status_code=404, detail=f"no such prompt: {name}") from exc
    except IntegrityError as exc:
        # unique(tenant_id, name, rev): a concurrent save took this revision.
        # Same answer as every other racing write here -- there is no merge for
        # two people editing one prompt, so the later one reloads and re-edits.
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="another save recorded a revision first; reload and try again",
        ) from exc

    # Not one of the mutations #37 enumerates, and audited deliberately: #39
    # asks where a prompt revision's *actor* lives, since `prompts` records
    # when a revision was saved but not by whom. It lives here, so the two
    # tickets are one answer rather than two halves. The revision, not the
    # body: the body is already in `prompts` at that rev, and copying it would
    # put an unbounded blob in a table nothing prunes.
    audit.record(
        session,
        action=audit.Action.PROMPT_SAVE,
        target=audit.prompt_ref(name),
        after={"rev": saved["rev"]},
    )
    return saved


# --- the audit trail (P5-07) ---------------------------------------------

# How much program output an audit row will carry. Bounded because `audit_log`
# is the one table nothing may prune, so an unbounded field on it is unbounded
# growth that cannot be reclaimed.
_AUDIT_TEXT_LIMIT = 2000


def _audit_text(text: str) -> str:
    """Make program output safe to store in the trail: redacted, then bounded.

    `infra.sync` is the only audited action whose payload is built from a
    subprocess and an exception rather than from values we chose, and a failing
    git push echoes the argv that failed -- which carries the PAT. `redact` is
    the same choke point `app/delivery/credentials.py` puts in front of every
    message bound for a human (DESIGN.md §8); this table deserves it more than
    a log line does, because nothing here can be deleted afterwards.
    """
    cleaned = delivery.redact(text or "")
    if len(cleaned) <= _AUDIT_TEXT_LIMIT:
        return cleaned
    return cleaned[:_AUDIT_TEXT_LIMIT] + "… (truncated)"

@router.get("/audit", response_model=list[AuditEntryOut], dependencies=[AdminDep])
def list_audit_entries(
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    """This tenant's control-plane mutations, most recent first.

    **Tenant-admin only.** Every surface that writes these rows is already
    admin-gated, and the trail collects them: who approved which delivery into
    the customer's repo, who rotated which credential. That is an admin's view
    of their own organisation rather than something every member reads.

    Scoped to the caller's tenant by `tenancy.install_tenant_guard`, like every
    other read -- there is no `.where(tenant_id == ...)` here because a filter
    a route remembers is a filter a route can forget (P5-02, #32).

    `limit` is a plain cap rather than a cursor, and is itself bounded: the
    trail is append-only and read newest-first, so "the last 200 things that
    happened" is the question the page asks, while an unbounded `limit` would
    let one request ask for a table that only ever grows. Paginating back
    through it is a different feature and no portal surface asks for it yet.
    """
    return audit.entries(session, limit=limit)


@router.get("/settings")
def get_settings():
    return apphub.settings()


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, session: Session = Depends(get_session)):
    return repo.create_project(session, name=body.name)


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(get_session)):
    return repo.list_projects(session)


@router.post(
    "/projects/{project_id}/targets", response_model=TargetCreatedOut, status_code=201
)
def create_target(
    project_id: int,
    body: TargetCreate,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
    run_sync=Depends(get_bootstrap_runner),
    resolve: egress.Resolver = Depends(get_resolver),
):
    """Create a target, its configuration, and its revision 1.

    Revision 1 comes from the templates and the renderer, so a new target has a
    tree to hydrate and a history to show before its first run -- which is what
    let the baseline-from-disk hook go.

    A configuration the write path refuses is the operator's typo, not a server
    fault, so it answers 422 with the reason rather than 500. The optional infra
    sync is reported as an outcome rather than raised: the target exists either
    way, and the form shows the failure next to the target it did create.
    """
    try:
        target, revision = authoring.create_target(
            session,
            store,
            project_id=project_id,
            app=body.app,
            name=body.name,
            base_url=body.base_url,
            target_repo=body.target_repo,
            target_branch=body.target_branch,
            locators=body.locators,
            agent_notes=body.agent_notes,
            resolve=resolve,
        )
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except target_config.ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        # The one route where IntegrityError is not the revision race: a brand
        # new target has no rev to lose, so this is unique(project_id, app).
        session.rollback()
        raise HTTPException(
            status_code=409, detail=f"a target named {body.app!r} already exists"
        ) from exc

    bootstrap = run_sync(target.app) if body.sync_infra else None
    if bootstrap is not None:
        # An audited mutation even though the route it rides on is a create:
        # the create writes our database, the sync writes the *customer's*
        # repo. Recorded whether or not it succeeded, with the outcome in the
        # row -- a failed push is something an operator may well be asked
        # about later, and it is not what the create's own 201 reports.
        audit.record(
            session,
            action=audit.Action.INFRA_SYNC,
            target=audit.target_ref(target.app),
            after={"ok": bootstrap.ok, "output": _audit_text(bootstrap.output)},
        )
    return TargetCreatedOut(
        target=target,
        revision=_revision_out(revision, revisions.count_files(session, revision.id)),
        bootstrap=bootstrap,
    )


@router.patch("/targets/{target_id}/config", response_model=WriteOut)
def update_target_config(
    target_id: int,
    body: TargetConfigUpdate,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
    resolve: egress.Resolver = Depends(get_resolver),
):
    """Edit a target's configuration. A changed base URL commits a revision.

    `base_url` re-renders the generated Playwright config, which is a tree diff,
    which is a revision -- a configuration change as reviewable as a code
    change. `locators` and `agent_notes` reach the agent through its prompt, so
    they change the row and commit nothing.
    """
    target = _target_or_404(session, target_id)
    with _authoring_errors(session):
        _target, revision = authoring.update_config(
            session,
            store,
            target,
            resolve=resolve,
            **body.model_dump(exclude_none=True),
        )
    return _write_out(session, store, target, revision)


# --- story authoring: the only way a story gets in -----------------------

@contextmanager
def _authoring_errors(session: Session) -> Iterator[None]:
    """Translate an authoring failure into a status code.

    Every operator write refuses for the same reasons, so the mapping lives
    once: a story or configuration the write path rejects is 422, a story that
    is not there is 404, a live run holding the target is 409, and losing the
    race on `unique(target_id, rev)` is 409. One route having the OCC case and
    the next one not is how that race turns into a 500.
    """
    try:
        yield
    except (authoring.InvalidStory, target_config.ConfigError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except authoring.NoSuchStory as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except repo.RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        # unique(target_id, rev): a concurrent writer got there first. Losing is
        # the designed outcome -- there is no merge (DESIGN.md invariant 2).
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="another write committed a revision first; reload and try again",
        ) from exc


def _write_out(session: Session, store: Storage, target, revision) -> WriteOut:
    return WriteOut(
        revision=(
            _revision_out(revision, revisions.count_files(session, revision.id))
            if revision is not None
            else None
        ),
        stories=authoring.list_stories(session, store, target),
    )


@router.get("/targets/{target_id}/stories", response_model=list[StoryOut])
def list_stories(
    target_id: int,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
):
    """A target's stories, from the head revision's file_index."""
    target = _target_or_404(session, target_id)
    return authoring.list_stories(session, store, target)


@router.get("/targets/{target_id}/stories/{story_id}", response_model=StoryContentOut)
def read_story(
    target_id: int,
    story_id: str,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
):
    target = _target_or_404(session, target_id)
    with _authoring_errors(session):
        return authoring.read_story(session, store, target, story_id)


@router.put("/targets/{target_id}/stories/{story_id}", response_model=WriteOut)
def write_story(
    target_id: int,
    story_id: str,
    body: StoryBody,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
):
    """Create or replace one story, committing one operator-authored revision."""
    target = _target_or_404(session, target_id)
    if body.story_id != story_id:
        raise HTTPException(
            status_code=422,
            detail=f"story id in the path ({story_id}) and body ({body.story_id}) differ",
        )
    with _authoring_errors(session):
        revision = authoring.write_story(
            session,
            store,
            target,
            story_id=body.story_id,
            slug=body.slug,
            content=body.content,
        )
    return _write_out(session, store, target, revision)


@router.delete("/targets/{target_id}/stories/{story_id}", response_model=WriteOut)
def delete_story(
    target_id: int,
    story_id: str,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
):
    """Remove one story. Its plan and suite are left alone."""
    target = _target_or_404(session, target_id)
    with _authoring_errors(session):
        revision = authoring.delete_story(session, store, target, story_id=story_id)
    return _write_out(session, store, target, revision)


@router.get("/targets", response_model=list[TargetOut])
def list_targets(project_id: int | None = None, session: Session = Depends(get_session)):
    return repo.list_targets(session, project_id=project_id)


# --- delivery: bootstrap-check / deliver / reset (P1) --------------------

@router.get("/targets/{target_id}/delivery", response_model=DeliveryStateOut)
def target_delivery_state(
    target_id: int,
    session: Session = Depends(get_session),
    catalog: delivery.Catalog = Depends(get_catalog),
):
    """Delivered, or N revisions ahead. One Postgres query, no network call.

    It depends on the catalog rather than the whole delivery seam, because it
    needs no credential: the answer is in the database, and requiring a PAT to
    read it would be requiring the network by another name.
    """
    target = _target_or_404(session, target_id)
    try:
        ref = delivery.target_ref(catalog.config(target.app))
        state = catalog.state(target.app)
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    credential = pats.credential_status(target)
    return DeliveryStateOut(
        app=ref.app,
        repo=ref.repo,
        branch=ref.branch,
        bootstrapped=state.bootstrapped,
        delivered=state.delivered,
        rev=state.rev,
        delivered_sha=state.delivered_sha,
        revisions_ahead=state.revisions_ahead,
        summary=state.describe(),
        credential_state=credential.state,
        pat_expires_at=credential.expires_at,
        credential_warning=credential.warning,
    )


# --- the tenant's own GitHub credential (P5-03) --------------------------
#
# Through P4 there was one operator `GITHUB_PAT` in the API's environment, so
# every delivery into every customer's repository was authored by the same
# identity. These three routes are how a credential becomes the customer's:
# sealed onto their target's row, validated the moment they paste it, and
# reported back without the token or the ciphertext ever reaching the browser.
#
# Saving and clearing are tenant-admin actions, beside approving a delivery:
# all three write into -- or authorise writing into -- a customer's repository.
# *Reading* the state is not, because a member has to be able to see why
# delivery is refused.

def _credential_audit_state(state) -> dict:
    """A credential's state as an audit payload. **Never the token.**

    Named once because both PAT routes build it, on both sides of their
    mutation, and the one thing that must stay true of all four is that it
    carries the *state* and nothing else (app/audit.py).
    """
    return {"credential_state": CredentialState(state).value}


def _credential_out(target, status, *, login: str | None = None) -> CredentialOut:
    return CredentialOut(
        app=target.app,
        state=status.state,
        expires_at=status.expires_at,
        days_until_expiry=status.days_until_expiry,
        expiring_soon=status.expiring_soon,
        warning=status.warning,
        login=login,
    )


@router.get("/targets/{target_id}/credential", response_model=CredentialOut)
def target_credential(target_id: int, session: Session = Depends(get_session)):
    """Is there a credential, does GitHub still accept it, is it about to lapse.

    Every field is a function of the row, so this costs no KMS call and no
    GitHub call -- the same reason "is this delivered?" is a Postgres question.
    """
    target = _target_or_404(session, target_id)
    return _credential_out(target, pats.credential_status(target))


@router.put(
    "/targets/{target_id}/pat",
    response_model=CredentialOut,
    dependencies=[AdminDep],
)
def save_target_pat(
    target_id: int,
    body: PatBody,
    session: Session = Depends(get_session),
    validate=Depends(get_token_validator),
    wrapper: envelope.KeyWrapper = Depends(get_key_wrapper),
):
    """Store a tenant's GitHub PAT for this target, sealed.

    **422, not 502, for every refusal here.** A token missing `workflow`, an
    empty paste, a token GitHub has revoked: each is the operator's input being
    refused while they can still fix it, and a different paste is the fix. 502
    is reserved for GitHub refusing a credential *at delivery*, which is a
    different event with a different remedy (DESIGN.md §8). Telling a customer
    with a scope typo that GitHub was down is how they stop reading the message.

    The row is not touched unless the token passed validation, so a failed
    rotation leaves the working credential in place rather than a broken one.
    """
    target = _target_or_404(session, target_id)
    # Read before the write: `before` is what distinguishes a first save from a
    # rotation, and after `save_pat` has run the old state is gone.
    previous_state = target.credential_state
    try:
        info = pats.save_pat(
            session, target, body.token, validate=validate, wrapper=wrapper
        )
    except pats.CredentialRejected as exc:
        # No row: the rejection left the stored credential untouched, so there
        # is no mutation to record. A row here would report a rotation that did
        # not happen.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # The token is never in this row -- only the state either side of the save,
    # and the login GitHub reported. See app/audit.py.
    audit.record(
        session,
        action=audit.Action.PAT_SAVE,
        target=audit.target_ref(target.app),
        before=_credential_audit_state(previous_state),
        after={
            **_credential_audit_state(target.credential_state),
            "login": info.login,
            "expires_at": info.expires_at.isoformat() if info.expires_at else None,
        },
    )
    return _credential_out(
        target, pats.credential_status(target), login=info.login
    )


@router.delete(
    "/targets/{target_id}/pat",
    response_model=CredentialOut,
    dependencies=[AdminDep],
)
def clear_target_pat(target_id: int, session: Session = Depends(get_session)):
    """Remove this target's credential. Delivery then cannot run until a new
    one is saved, which is what `absent` says and what the portal shows."""
    target = _target_or_404(session, target_id)
    previous_state = target.credential_state
    pats.clear_pat(session, target)
    audit.record(
        session,
        action=audit.Action.PAT_CLEAR,
        target=audit.target_ref(target.app),
        before=_credential_audit_state(previous_state),
        after=_credential_audit_state(target.credential_state),
    )
    return _credential_out(target, pats.credential_status(target))


@router.post("/targets/{target_id}/deliver", response_model=DeliveryOut, dependencies=[AdminDep])
def deliver_story(
    target_id: int,
    body: DeliverBody,
    session: Session = Depends(get_session),
    tools: delivery.Tools = Depends(get_delivery_tools),
):
    """Deliver one story's artifacts as a PR.

    Bootstrap is folded in under the same action (DESIGN.md decision 16), so an
    operator approving a delivery is approving "set the repo up and deliver".

    Delivery approval is the tenant-admin action P5 cares most about -- it is
    the write into a customer's repo -- so it is gated on the admin role
    (DESIGN.md §13). A non-admin is refused before any push happens.
    """
    target = _target_or_404(session, target_id)
    try:
        if not body.dry_run:
            delivery.ensure_bootstrapped(target.app, tools=tools)
        result = delivery.push_artifacts(
            target.app,
            body.story_id,
            run_id=body.run_id,
            dry_run=body.dry_run,
            tools=tools,
        )
    except delivery.CredentialError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # The audit row P5-07 exists for, written *after* the push succeeded: a
    # trail that recorded an approval before the work would claim deliveries
    # that never happened, and a missing row is a gap an auditor can see where
    # a false one is not (app/audit.py).
    #
    # **A dry run writes no row.** It touches nothing in the customer's repo,
    # so it is not the mutation story 26 asks about, and recording it under the
    # same action would make `delivery.approve` a filter whose rows a reader
    # has to check a flag on before believing -- which is the question the
    # table exists to answer plainly. An earlier version of this did record
    # them, flagged; the flag was the tell that they did not belong.
    if not body.dry_run:
        audit.record(
            session,
            action=audit.Action.DELIVERY_APPROVE,
            target=audit.target_ref(target.app),
            after={
                "story_id": body.story_id,
                "run_id": body.run_id,
                "branch": result.branch,
                "committed": result.committed,
                "delivered_sha": result.delivered_sha,
                "pr_url": result.pr_url,
                "pr_number": result.pr_number,
            },
        )
    return DeliveryOut(
        ok=True,
        message=result.message,
        pr_url=result.pr_url,
        pr_number=result.pr_number,
        detail={
            "branch": result.branch,
            "committed": result.committed,
            "delivered_sha": result.delivered_sha,
        },
    )


@router.post("/targets/{target_id}/reset", response_model=DeliveryOut, dependencies=[AdminDep])
def reset_target_repo(
    target_id: int,
    body: ResetBody,
    session: Session = Depends(get_session),
    tools: delivery.Tools = Depends(get_delivery_tools),
):
    """DESTRUCTIVE: wipe the target repo. Requires the repo name echoed back.

    A write into the customer's repo, so it is gated on the admin role like
    delivery approval: a non-admin is refused."""
    target = _target_or_404(session, target_id)
    try:
        result = delivery.reset_target(
            target.app,
            confirm_repo=body.confirm_repo,
            dry_run=body.dry_run,
            tools=tools,
        )
    except delivery.ConfirmationMismatch as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except delivery.CredentialError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Recorded after the fact, like the delivery approval above, and with what
    # was destroyed rather than just that a reset happened: "which branches did
    # that wipe take?" is the question this row has to answer on its own. A dry
    # run deletes nothing and writes no row, for the reason given there.
    if not body.dry_run:
        audit.record(
            session,
            action=audit.Action.TARGET_RESET,
            target=audit.target_ref(target.app),
            after={
                "repo": result.repo,
                "branch": result.branch,
                "already_empty": result.already_empty,
                "reset_branch": result.reset_branch,
                "deleted_branches": list(result.deleted_branches),
                "failed_branches": list(result.failed_branches),
            },
        )
    return DeliveryOut(
        ok=True,
        message=result.message,
        detail={
            "deleted_branches": list(result.deleted_branches),
            "failed_branches": list(result.failed_branches),
            "already_empty": result.already_empty,
        },
    )


def _target_or_404(session: Session, target_id: int):
    try:
        return repo.get_target(session, target_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --- revisions / file_index ----------------------------------------------
#
# Read-only: the revisions panel is the operator's window into a target's tree,
# and the only writers of a revision are ingest (at a run's step boundaries) and
# the operator writes above. There is no snapshot-the-disk action, because there
# is no authoritative disk left to snapshot, and no parity route, because there
# is no second copy of the truth to compare against.
#
# Every route resolves through a row and filters by the request's tenant, so a
# blob is never served by key alone (DESIGN.md §9). The tenant is always 1
# today; filtering anyway is the structural half of P5.

# Tracked files are displayed as source, so they stream as text whatever their
# extension implies. See revision_file_content.
TRACKED_FILE_MEDIA_TYPE = "text/plain; charset=utf-8"

# How often the events route reads forward from its cursor, and how long it
# stays silent before reassuring the browser that the connection is alive.
POLL_INTERVAL_S = 0.5
KEEPALIVE_S = 15.0


def _revision_out(rev, file_count: int) -> RevisionOut:
    return RevisionOut(
        id=rev.id,
        rev=rev.rev,
        parent_rev=rev.parent_rev,
        tree_hash=rev.tree_hash,
        produced_by_run_id=rev.produced_by_run_id,
        author=rev.author,
        created_at=rev.created_at,
        file_count=file_count,
    )


@router.get("/targets/{target_id}/revisions", response_model=list[RevisionOut])
def list_target_revisions(target_id: int, session: Session = Depends(get_session)):
    _target_or_404(session, target_id)
    return [
        _revision_out(rev, count)
        for rev, count in revisions.list_revisions_with_file_counts(session, target_id)
    ]


def _revision_or_404(session: Session, revision_id: int):
    rev = revisions.get_revision(session, revision_id)
    if rev is None:
        raise HTTPException(status_code=404, detail=f"no revision {revision_id}")
    return rev


@router.get("/revisions/{revision_id}/files", response_model=list[FileIndexOut])
def list_revision_files(revision_id: int, session: Session = Depends(get_session)):
    _revision_or_404(session, revision_id)
    return revisions.list_files(session, revision_id)


@router.get("/revisions/{revision_id}/file")
def revision_file_content(
    revision_id: int,
    path: str,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
):
    """Stream one tracked file's bytes out of blob storage.

    `path` is a query parameter rather than a wildcard path segment so tracked
    paths with slashes need no escaping scheme.

    The row is found first and its tenant checked, and only then is the blob it
    names read: knowing a blob key is not enough to read bytes.
    """
    _revision_or_404(session, revision_id)
    row = revisions.get_file(session, revision_id, path)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"revision {revision_id} has no file {path!r}"
        )
    try:
        chunks, _ = store.get_stream(row.blob_key)
    except Exception as exc:  # object missing / store down
        raise HTTPException(status_code=502, detail=f"storage error: {exc}") from exc
    # A tracked file is source text to read, never a document to re-encode, so
    # it is always served as text rather than under the type its extension
    # guesses. Two reasons, both found by review: `application/json` makes a
    # browser parse package.json and re-serialise it, which is no longer the
    # bytes that were stored (ticket 04 asks for byte-identical); and
    # mimetypes guesses `video/mp2t` for .ts, which is the bulk of a suite.
    return StreamingResponse(chunks, media_type=TRACKED_FILE_MEDIA_TYPE)


@router.post("/targets/{target_id}/runs", response_model=RunOut, status_code=201)
def start_run(
    target_id: int,
    body: RunCreate,
    session: Session = Depends(get_session),
    launcher: Callable[[int], None] = Depends(get_launcher),
):
    try:
        run = repo.start_run(
            session, target_id=target_id, story_id=body.story_id, mode=body.mode
        )
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except repo.QuotaExceeded as exc:
        # 429, and deliberately not the 409 a busy app gets: "your tenant is
        # out of allowance" and "this app is busy" are different problems with
        # different remedies, and an operator who cannot tell them apart cannot
        # act on either. The detail carries the numbers, so the portal can say
        # "3 of 3" without a second request.
        #
        # Order against the `RunConflict` arm below does not matter: both are
        # siblings under `RepoError` and neither catches the other. It would
        # start mattering the day something caught `RepoError` here, so the
        # narrow arms stay above the broad ones out of habit rather than need.
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except repo.RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    launcher(run.id)  # kick off the orchestrator in the background
    return run


@router.get("/usage", response_model=UsageOut)
def get_usage(session: Session = Depends(get_session)):
    """This tenant's usage against its plan caps (P5-04).

    Not per target and not per project: both caps are the tenant's, so this
    reads the same two counts the enqueue checks. Tenant-scoped by the ordinary
    read guard, like every other read -- there is no tenant id in the path
    because there is no tenant to name but your own.
    """
    caps = repo.tenant_caps(session)
    usage = repo.tenant_usage(session)
    return UsageOut(
        live_runs=usage.live_runs,
        runs_this_month=usage.runs_this_month,
        max_concurrent_runs=caps.max_concurrent_runs,
        monthly_run_quota=caps.monthly_run_quota,
        # The two caps asked about **independently**, and from the same
        # predicates `quotas.breach` is built on. Both can be full at once --
        # `breach` picks one to refuse with, which is the right answer for a
        # rejection message and the wrong one for a pair of gauges.
        at_concurrency_cap=quotas.at_concurrency_cap(caps, usage),
        at_monthly_quota=quotas.at_monthly_quota(caps, usage),
    )


@router.put("/usage/caps", response_model=UsageOut, dependencies=[AdminDep])
def set_usage_caps(body: CapsBody, session: Session = Depends(get_session)):
    """Change this tenant's plan caps. Tenant-admin only (P5-13, story 5).

    **Under `/usage` on purpose**: this is the write half of a surface that
    already reads, so it shares the read's prefix, its response shape and --
    free, and the reason it matters -- its entry in both proxy allowlists
    (`docker/nginx.conf` and `web/vite.config.js`). A new first segment would
    have needed adding to both, and a path missing from them does not 404: it
    answers 200 with the SPA shell, which is how P5-04's quota panel shipped
    invisible.

    **No tenant in the path**, like the read above: there is no tenant to name
    but your own. `repo.set_tenant_caps` writes to `current_tenant_id()`, which
    `require_auth` bound from the session, so "change another tenant's caps" is
    not a request this surface can express rather than one it checks for.

    Returns the same `UsageOut` the read returns, recomputed, so the panel can
    render the result of the change without a second round trip -- and so the
    caps an admin sees afterwards are the stored ones rather than the ones they
    typed.

    The audit row is written by `repo.set_tenant_caps` rather than here, which
    is where it already was: that function is also reached from a console, and
    auditing the function covers both callers. The actor comes from the request
    scope (`tenancy.current_actor()`), so this route names the admin who
    pressed it without passing anything.

    One thing worth stating, because the function's own docstring argues the
    other way. It says a route was declined because "a tenant that could raise
    its own caps would not have caps", and that is true of a *platform* ceiling
    -- which this is not. Story 5 makes quota change an intra-tenant
    authorization question (admin yes, member no), and that is what this
    implements. A ceiling the tenant cannot raise would be a second, separate
    limit above this one, and nothing in P5 asks for one yet.
    """
    try:
        provided = body.model_fields_set
        caps = repo.set_tenant_caps(
            session,
            **{
                name: getattr(body, name)
                for name in ("max_concurrent_runs", "monthly_run_quota")
                if name in provided
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    usage = repo.tenant_usage(session)
    return UsageOut(
        live_runs=usage.live_runs,
        runs_this_month=usage.runs_this_month,
        max_concurrent_runs=caps.max_concurrent_runs,
        monthly_run_quota=caps.monthly_run_quota,
        at_concurrency_cap=quotas.at_concurrency_cap(caps, usage),
        at_monthly_quota=quotas.at_monthly_quota(caps, usage),
    )


@router.get("/runs", response_model=list[RunOut])
def list_runs(target_id: int | None = None, session: Session = Depends(get_session)):
    return repo.list_runs(session, target_id=target_id)


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, session: Session = Depends(get_session)):
    try:
        return repo.get_run(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/pause", response_model=RunOut)
def pause_run(
    run_id: int,
    session: Session = Depends(get_session),
    scheduler: dispatch.Scheduler | None = Depends(get_scheduler),
):
    """Pause a run, and destroy the sandbox at once.

    Pause exists to stop costing money, so it cannot wait for a step boundary
    that an agent holding a browser may be minutes of billing away from. The
    container is killed here and the row is moved to `paused` here, because the
    process that would otherwise have done it is the one just killed.

    What a paused run must not lose is the agent session, and that is why the
    session is archived at **every step boundary** rather than on the way out
    (app/launcher.py): a sandbox that dies without warning cannot archive
    anything, so the boundary is the last moment the session is known good. A
    pause therefore costs the exploration of the step it interrupted and no
    more.

    The driver's flag-at-a-boundary path stays for the thread path and for a run
    with no sandbox.
    """
    try:
        run = repo.request_pause(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if run.sandbox_handle and run.status is RunStatus.RUNNING:
        dispatch.destroy_handle(run.sandbox_handle, scheduler)
        run = repo.pause_run(session, run_id)
        # So "a paused run has no sandbox" is true of the row as well: the
        # reaper's sweep for idle sandboxes is the net under this, not the way
        # it normally happens.
        repo.set_sandbox_handle(session, run_id, None)
        session.refresh(run)
    return run


@router.post("/runs/{run_id}/stop", response_model=RunOut)
def stop_run(
    run_id: int,
    session: Session = Depends(get_session),
    scheduler: dispatch.Scheduler | None = Depends(get_scheduler),
):
    """Stop a run, and kill the sandbox doing the work.

    "Stop" has to mean the work stops rather than the status changes, so a
    running sandbox is destroyed here rather than asked to notice a flag at its
    next step boundary -- which, for an agent holding a browser, may be minutes
    of billing away. Mid-step work is lost, which is invariant 4 (a crash
    commits nothing) and not a regression.

    The driver's flag-at-a-boundary path stays for the thread path and for a run
    with no sandbox, and `repo.request_stop` already stops a PENDING or PAUSED
    run outright.
    """
    try:
        run = repo.request_stop(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if run.sandbox_handle:
        dispatch.destroy_handle(run.sandbox_handle, scheduler)
        if is_live(run.status):
            # A PENDING run was already stopped outright by `request_stop`; a
            # RUNNING one has just lost the process that would have done it.
            run = repo.stop_run(session, run_id)
    return run


@router.post("/runs/{run_id}/resume", response_model=RunOut)
def resume_run(
    run_id: int,
    session: Session = Depends(get_session),
    launcher: Callable[[int], None] = Depends(get_launcher),
):
    try:
        run = repo.resume_run(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except repo.RepoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    launcher(run.id)  # a fresh orchestrator re-begins from the last checkpoint
    return run


@router.get("/runs/{run_id}/steps", response_model=list[StepOut])
def get_run_steps(run_id: int, session: Session = Depends(get_session)):
    try:
        run = repo.get_run(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return sorted(run.steps, key=lambda s: s.id)


@router.get("/runs/{run_id}/artifacts", response_model=list[ArtifactOut])
def list_artifacts(run_id: int, session: Session = Depends(get_session)):
    try:
        repo.get_run(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return list(
        session.scalars(
            select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.id)
        )
    )


@router.get("/artifacts/{artifact_id}/content")
def artifact_content(
    artifact_id: int,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
):
    """Stream an artifact's bytes through the API (avoids presigned-URL host
    mismatch between the container and the browser in local dev)."""
    art = session.get(Artifact, artifact_id)
    if art is None:
        raise HTTPException(status_code=404, detail=f"no artifact {artifact_id}")
    try:
        chunks, content_type = store.get_stream(art.s3_key)
    except Exception as exc:  # object missing / store down
        raise HTTPException(status_code=502, detail=f"storage error: {exc}") from exc
    return StreamingResponse(chunks, media_type=content_type)


@router.get("/runs/{run_id}/events")
def run_events(
    run_id: int,
    session: Session = Depends(get_session),
    bus: LogBus = Depends(get_log_bus),
):
    """Server-sent events of the run's live log, read forward from a cursor.

    A cursor rather than a subscription, because P4 moved the run out of this
    process: the lines are appended by whatever executes the run, and a reader
    that polls a cursor is a reader that works on any replica, for any run, and
    for a run that finished before the last deploy. A late subscriber therefore
    receives the run's real history rather than whatever one process remembers.

    A finished run replays its history and closes; a live run streams until the
    bus says the stream is over -- which, for a run in a container, means its
    status reached a terminal state or a pause, because that is the only
    end-of-stream marker another process can see.
    """
    try:
        run = repo.get_run(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    terminal = is_terminal(run.status)

    def _event(line: str) -> str:
        return f"data: {json.dumps(line)}\n\n"

    def gen():
        cursor = 0
        silent_for = 0.0
        while True:
            lines, cursor = bus.read_from(run_id, cursor)
            for line in lines:
                yield _event(line)
            if terminal:
                # Read once, at the top: a run that was already finished when
                # the reader arrived has nothing more to send.
                yield 'event: end\ndata: ""\n\n'
                return
            if lines:
                silent_for = 0.0
                continue
            if bus.is_closed(run_id):
                # One more pass has already run above, so everything the writer
                # appended before it finished has been sent.
                yield 'event: end\ndata: ""\n\n'
                return
            time.sleep(POLL_INTERVAL_S)
            silent_for += POLL_INTERVAL_S
            if silent_for >= KEEPALIVE_S:
                silent_for = 0.0
                yield ": keepalive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
