"""The prompts the agent is sent: rows, per tenant, versioned.

Through P3 the prompts were code-shipped package data and nothing else: the
runner read `server/app/prompts/steps/*.md` off the installed package and the
portal's Prompts page displayed the same files. That is one set of bytes for
every customer, changeable only by shipping an image. P5-06 makes a prompt a
row (`models.Prompt`), so "tune the agent for my application" is a write a
customer can make -- DESIGN.md §12's "code-shipped defaults seeded into
Postgres, tenant-overridable, versioned".

**The three rules this module exists to hold.**

1. *The files are the seed source, not a live second author.* A file is read
   only to insert a tenant's missing `SEED_REV` row. Once that row exists the
   file is never consulted for that tenant again, so editing a `.md` changes
   nothing for a tenant that has already resolved it. Without this the table
   would be a cache in front of the files and there would be two places a
   prompt could come from -- which is the arrangement a customer's override has
   to win against, and it is much easier to reason about if it simply does not
   exist.

2. *Resolution is "the highest rev", not "the row flagged as an override".* The
   seeded default is rev 1 and each override is the next rev, so an override
   beats the default because it is later. One rule covers both the first
   override and the ninth, and there is no flag to get wrong.

3. *Rows are append-only.* `save_override` inserts; it never updates. The
   history is the versioning, and `UNIQUE(tenant_id, name, rev)` makes the
   insert itself the concurrency check -- two saves that compute the same next
   rev cannot both land.

**Seeding is lazy, and that is a decision rather than an omission.** The
alternative was to seed every tenant's rows in the migration and again whenever
a tenant is created. That needs a backfill, a hook on tenant creation, and a
third thing to remember when a prompt file is added to the package -- and it
still leaves a tenant created by a path that forgot the hook with no prompts at
all, which is a run that cannot build a message. Seeding at the resolution seam
means a tenant that has never been heard of resolves correctly on its first
read, a prompt file added in a later release is picked up by the next resolve
that misses it, and there is exactly one place that knows how a default becomes
a row.

The cost is that `resolve_all` writes, so it needs a session it may flush --
which is why it is called from `repo.start_run` (already a write transaction)
and from the portal's Prompts page, and why the run-serving path uses
`pinned()` instead. `pinned()` reads and nothing more: it is the one a sandbox's
request reaches, and it must not be able to seed a row on a tenant's behalf
halfway through their run.

**Tenant scoping is inherited, not implemented here.** `Prompt` is
`TenantOwned`, so `tenancy.install_read_guard` filters every SELECT below by
`current_tenant_id()` and the inserts set the column from the same function.
There is no tenant argument in this module's signatures on purpose: a second
way to say which tenant is acting is the thing DESIGN.md §13 carried one column
for five phases to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Prompt
from .package_data import prompts_dir
from .tenancy import current_tenant_id

# The rev a seeded default gets. Overrides start at SEED_REV + 1, so "the
# highest rev wins" makes an override beat the default without a flag.
SEED_REV = 1


class PromptNotFound(KeyError):
    """No such prompt name -- the package never shipped one by that name.

    A `KeyError` because that is what a caller asking for a prompt by name is
    doing, and the API layer translates it to a 404: the name is wrong and the
    client can fix it. Raised rather than answered with an empty body: a prompt
    the agent receives as "" is a step with no instructions, which in an
    unattended session is worse than a run that refuses to start.
    """


class PromptVersionMissing(LookupError):
    """A run's pinned `(name, rev)` is not in the table.

    Deliberately **not** a `PromptNotFound`. The name is fine; the version the
    run was pinned to has gone, which means rows were deleted under a live run
    -- a broken deployment, not a bad request. They are separate types because
    the API maps `PromptNotFound` to a 404, and answering "404, no such prompt"
    to a server-side integrity failure would send a client looking for a
    mistake it did not make.
    """


@dataclass(frozen=True)
class ResolvedPrompt:
    """One prompt as the agent will receive it, and the version it came from.

    Both halves travel together because every consumer needs both: the runner
    renders `body`, and the run records `rev`. Handing back a bare string and
    making the caller ask again for the version is how the two come to disagree.
    """

    name: str
    body: str
    rev: int


def shipped_defaults() -> dict[str, str]:
    """The code-shipped prompt files, keyed by the name a row uses.

    The name is the path relative to the prompts directory, posix style, which
    is the string the portal's Prompts page has always displayed -- so a row
    and the file it was seeded from are visibly the same prompt.
    """
    root = prompts_dir()
    return {
        path.relative_to(root).as_posix(): path.read_text()
        for path in sorted(root.rglob("*.md"))
    }


def shipped_at_seed_rev() -> dict[str, ResolvedPrompt]:
    """The shipped defaults as resolved prompts, without touching the database.

    What a run started before P5-06 is served: its `prompt_revs` is null, so
    there is no pinned version to look up, and the files are precisely what it
    *was* given when it started. Reported at `SEED_REV` because that is the rev
    those bytes have wherever they are a row.

    Here rather than in the runner so this module stays the only thing in the
    application that reads a prompt file -- which is what makes "the
    code-shipped files are the seed source, not a live second author" a
    property of the layering and not a claim in a docstring.
    """
    return {
        name: ResolvedPrompt(name=name, body=body, rev=SEED_REV)
        for name, body in shipped_defaults().items()
    }


def _heads(session: Session, names: list[str] | None = None) -> dict[str, Prompt]:
    """The highest-rev row per name for the current tenant.

    One query rather than one per name: the head of each name is the row whose
    rev equals the max rev for that name, which `row_number()` would also give
    but a correlated max keeps readable. The tenant filter is the read guard's,
    not written here.
    """
    stmt = select(Prompt.name, func.max(Prompt.rev)).group_by(Prompt.name)
    if names is not None:
        stmt = stmt.where(Prompt.name.in_(names))
    pairs = [(name, rev) for name, rev in session.execute(stmt)]
    if not pairs:
        return {}
    # Fetch the head rows and only those. Selecting every rev of each name and
    # dropping all but the newest in Python would pull every superseded body
    # over the wire, and a prompt body is the one genuinely large column here.
    rows = session.scalars(
        select(Prompt).where(tuple_(Prompt.name, Prompt.rev).in_(pairs))
    ).all()
    return {row.name: row for row in rows}


def _seed(session: Session, name: str, body: str) -> Prompt | None:
    """Insert this tenant's `SEED_REV` row for `name`, or `None` if it lost a race.

    Two first runs for one tenant are **not** serialised by anything: the
    per-target lock trio in `repo.start_run` covers one target, and a tenant's
    two targets take two different lock rows. So both can reach here with the
    same missing names, and `UNIQUE(tenant_id, name, rev)` will refuse one of
    them.

    Losing has to be survivable, not fatal, because the loser is a run that is
    starting and the winner has written exactly the row the loser wanted --
    there is nothing to reconcile. The insert therefore goes in a SAVEPOINT, so
    the `IntegrityError` rolls back the failed insert alone and leaves the
    caller's transaction (which in `start_run` is holding an app lock `FOR
    UPDATE`) intact and usable. `None` tells the caller to re-read.

    Under READ COMMITTED the conflicting insert blocks on the unique index
    until the other transaction ends, so by the time this raises, the winner's
    row is committed and the caller's re-read will see it.
    """
    row = Prompt(
        tenant_id=current_tenant_id(),
        name=name,
        body=body,
        rev=SEED_REV,
    )
    try:
        with session.begin_nested():
            session.add(row)
    except IntegrityError:
        return None
    return row


def resolve_all(session: Session) -> dict[str, ResolvedPrompt]:
    """Every prompt for the current tenant: its override, or its seeded default.

    **Writes, and does not commit.** A name the tenant has no row for is seeded
    from the shipped file here (see the module docstring on why seeding is
    lazy), so this belongs on a write path -- and it leaves the commit to that
    path on purpose. Its one caller is `repo.start_run`, which is mid
    transaction holding the app lock `FOR UPDATE`; committing here would
    release that lock early and undo the serialisation the lock trio exists
    for. `start_run`'s own commit at the end covers these rows.

    A caller that wants to *display* the prompts wants `current_all`, which
    writes nothing; the run-serving read is `pinned`.
    """
    shipped = shipped_defaults()
    heads = _heads(session, list(shipped))

    missing = [name for name in shipped if name not in heads]
    if missing:
        lost = []
        for name in missing:
            seeded = _seed(session, name, shipped[name])
            if seeded is None:
                lost.append(name)
            else:
                heads[name] = seeded
        session.flush()
        # Whoever won the race has committed the rows we failed to insert, so
        # one re-read finishes the set. See `_seed`.
        if lost:
            heads.update(_heads(session, lost))

    return {
        name: ResolvedPrompt(name=name, body=row.body, rev=row.rev)
        for name, row in heads.items()
    }


def current_all(session: Session) -> dict[str, ResolvedPrompt]:
    """What each prompt would resolve to right now, **without writing anything**.

    The portal's Prompts page. It has to show a tenant their defaults before
    they have ever run anything, and seeding to achieve that would make a GET a
    write -- with no transaction of its own to commit it, which is precisely
    the bug this function exists instead of. A tenant on defaults sees the
    shipped bytes at `SEED_REV`, which is the row they will get the moment
    anything seeds; a tenant with an override sees the override.
    """
    current = shipped_at_seed_rev()
    for name, row in _heads(session, list(current)).items():
        current[name] = ResolvedPrompt(name=name, body=row.body, rev=row.rev)
    return current


def resolve(session: Session, name: str) -> ResolvedPrompt:
    """One prompt for the current tenant. Seeds, and does not commit; see `resolve_all`."""
    head = _heads(session, [name]).get(name)
    if head is None:
        shipped = shipped_defaults()
        if name not in shipped:
            raise PromptNotFound(name)
        head = _seed(session, name, shipped[name])
        session.flush()
        if head is None:  # lost the race; the winner's row is committed
            head = _heads(session, [name])[name]
    return ResolvedPrompt(name=head.name, body=head.body, rev=head.rev)


def save_override(session: Session, name: str, body: str) -> ResolvedPrompt:
    """Record a tenant's new version of a prompt, as a new row.

    Appends at the next rev rather than updating the current one: the history
    *is* the versioning (#30, story 24). Seeds the default first, through
    `resolve`, so an override is always at least rev 2 and a tenant's history
    begins with the bytes they started from rather than with their edit -- "see
    what changed" needs the thing it changed from to be in the table.
    """
    current = resolve(session, name)
    if body == current.body:
        # Nothing changed, so there is no version to record. Returning the
        # current one rather than appending a duplicate keeps the history a
        # list of changes instead of a list of saves. Still commits, because
        # `resolve` above may have seeded this tenant's default row.
        session.commit()
        return current
    row = Prompt(
        tenant_id=current_tenant_id(),
        name=name,
        body=body,
        rev=current.rev + 1,
    )
    session.add(row)
    # **Commits**, unlike `resolve_all`. This is a whole write on its own,
    # reached from a route, and the layer below the route is where this
    # codebase commits -- `repo.py`'s mutators and `revisions.commit_revision`
    # all end this way, and `db.get_session` deliberately does not, so a flush
    # here would answer the request with a revision number and then discard the
    # row. An `IntegrityError` from `UNIQUE(tenant_id, name, rev)` means a
    # concurrent save took this rev; it propagates, and the route turns it into
    # a 409 as every other racing write in `api.py` does.
    session.commit()
    return ResolvedPrompt(name=row.name, body=row.body, rev=row.rev)


def history(session: Session, name: str) -> tuple[ResolvedPrompt, ...]:
    """Every version of one prompt for the current tenant, oldest first."""
    rows = session.scalars(
        select(Prompt).where(Prompt.name == name).order_by(Prompt.rev)
    ).all()
    return tuple(
        ResolvedPrompt(name=r.name, body=r.body, rev=r.rev) for r in rows
    )


def pinned(session: Session, revs: dict[str, int]) -> dict[str, ResolvedPrompt]:
    """Exactly the versions `revs` names: the prompts a given run was given.

    **Reads only.** This is the path a sandbox's `run_facts` request reaches,
    and it must not seed a row on a tenant's behalf mid-run -- which is also
    why a rev that is not there is an error rather than a silent fall back to
    the current head. A run whose pinned version has gone missing is a broken
    deployment, and a run that quietly used a different version than the one
    recorded against it would make the record worthless.
    """
    if not revs:
        return {}
    rows = session.scalars(
        select(Prompt).where(Prompt.name.in_(list(revs)))
    ).all()
    found = {(r.name, r.rev): r for r in rows}
    out: dict[str, ResolvedPrompt] = {}
    for name, rev in revs.items():
        row = found.get((name, rev))
        if row is None:
            raise PromptVersionMissing(f"{name} rev {rev}")
        out[name] = ResolvedPrompt(name=name, body=row.body, rev=rev)
    return out


def revs_of(resolved: dict[str, ResolvedPrompt]) -> dict[str, int]:
    """The `{name: rev}` map a run records, from what was resolved for it."""
    return {name: r.rev for name, r in resolved.items()}
