"""Operator writes: creating a target, and editing its stories and config.

With the repo mount gone the portal is not a nicety -- it is the only way a story
gets in. Every write here commits a revision authored by `operator`, so who
changed what and when is answerable from the same history that records agent
work, and a configuration change surfaces as a tree diff rather than as an
invisible row update.

Every write is the same three steps, which is why they share one helper:

    materialize the head revision into a temporary tree
    apply the edit to that tree
    commit it as revision N+1   (nothing, if the tree did not change)

That is deliberately the hydrate/ingest path rather than a shortcut that writes
`file_index` rows directly: an operator edit and an agent edit then produce
revisions by exactly the same mechanism, and neither can produce a revision the
other could not have.

**Writes are refused while the target has a live run.** A live run hydrated from
an older head, and its next ingest would commit a tree that does not contain the
operator's edit -- silently reverting it. Resolving that would need merge logic,
and there is no merge logic anywhere in this system (DESIGN.md invariant 2). The
portal says so rather than queueing the edit.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.orm import Session

from . import repo, revisions, target_config
from .delivery.render import (
    SEED_TEMPLATE,
    STORIES_DIR,
    STORY_FILE,
    TEMPLATES_DIR,
    story_title,
    write_infra,
)
from .models import Revision, Target
from .sandbox import hydrate as hyd
from .sandbox.egress import Resolver
from .storage import Storage
from .target_config import config_of

# The author every operator write is recorded under. Agent work is recorded as
# `run:<run_key>`, so the two are distinguishable in one glance at the history.
OPERATOR = "operator"

# A story id, e.g. SCRUM-201. The same shape render.STORY_FILE expects.
STORY_ID = re.compile(r"^[A-Za-z]+-\d+$")
# A slug is one path segment of safe characters. The story's path is built from
# operator input, so it is validated rather than interpolated: `../../` in a
# slug would write outside the tree.
SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class AuthoringError(Exception):
    """An operator write that cannot be made."""


class InvalidStory(AuthoringError):
    """A story id or slug that is not one."""


class NoSuchStory(AuthoringError):
    """The head revision holds no story with that id."""


def story_path(story_id: str, slug: str) -> str:
    """`user-stories/<ID>-<slug>.md`, validated.

    Both halves are checked because this string becomes a filesystem path inside
    a materialized tree and a `file_index` row that hydrate later writes back
    out. A traversal here would escape the worktree on the next run.
    """
    if not STORY_ID.match(story_id or ""):
        raise InvalidStory(
            f"story id must look like SCRUM-201, got {story_id!r}"
        )
    if not SLUG.match(slug or ""):
        raise InvalidStory(
            f"story slug must be a single path segment of letters, digits, "
            f"'.', '_' or '-', got {slug!r}"
        )
    return f"{STORIES_DIR}/{story_id}-{slug}.md"


@contextmanager
def _edited_tree(
    session: Session, target: Target, store: Storage
) -> Iterator[Path]:
    """The head revision as a temporary tree, for an edit to be applied to."""
    head = revisions.head_revision(session, target.id)
    if head is None:
        raise AuthoringError(
            f"target {target.app!r} has no head revision; it was not created by the portal"
        )
    tmp = Path(tempfile.mkdtemp(prefix="qa-authoring-"))
    try:
        root = tmp / "tree"
        hyd.materialize(session, head, store, root)
        hyd.render_generated(root, config_of(target))
        yield root
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _commit_edit(
    session: Session,
    target: Target,
    store: Storage,
    apply_edit: Callable[[Path], None],
) -> Revision | None:
    """Apply `apply_edit` to the head's tree and commit the result.

    Returns None when the edit changed no tracked file: `rev` counts real
    changes, and saving a form without editing it is not one.
    """
    repo.assert_no_live_run(session, target.id)
    with _edited_tree(session, target, store) as root:
        apply_edit(root)
        return revisions.commit_revision(
            session, target, store, root, author=OPERATOR
        )


# --- creating a target ----------------------------------------------------

def initial_tree(root: Path, target: Target) -> None:
    """A new target's revision 1: the seed, the infra set, the generated config.

    The seed comes from the template; the infra entries come from their sources,
    which for `playwright.config.ts` means the renderer reading this target's
    row. So revision 1 is byte-identical to what hydrate would build from it,
    which is what stops a target's first run committing a revision for the
    config alone.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / STORIES_DIR).mkdir(exist_ok=True)
    write_infra(root, config_of(target))
    shutil.copyfile(TEMPLATES_DIR / SEED_TEMPLATE, root / SEED_TEMPLATE)


def create_target(
    session: Session,
    store: Storage,
    *,
    project_id: int,
    app: str,
    name: str,
    base_url: str,
    target_repo: str,
    target_branch: str | None = None,
    locators: str = "",
    agent_notes: list[str] | None = None,
    resolve: Resolver | None = None,
) -> tuple[Target, Revision]:
    """Create a target and commit its revision 1.

    The configuration is validated before the row is written, and the row is
    written before the revision, so a refused create leaves nothing behind and
    a created target always has a tree to hydrate.
    """
    target = repo.create_target(
        session,
        project_id=project_id,
        app=app,
        name=name,
        base_url=base_url,
        target_repo=target_repo,
        target_branch=target_branch,
        locators=locators,
        agent_notes=agent_notes,
        resolve=resolve,
    )
    tmp = Path(tempfile.mkdtemp(prefix="qa-new-target-"))
    try:
        root = tmp / "tree"
        initial_tree(root, target)
        revision = revisions.commit_revision(
            session, target, store, root, author=OPERATOR
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert revision is not None, "a target's first tree always commits"
    return target, revision


# --- stories --------------------------------------------------------------

def _story_paths(session: Session, target: Target) -> dict[str, str]:
    """{story id: tracked path} from the head revision."""
    head = revisions.head_revision(session, target.id)
    if head is None:
        return {}
    found: dict[str, str] = {}
    for row in revisions.list_files(session, head.id):
        if not row.path.startswith(f"{STORIES_DIR}/") or not row.path.endswith(".md"):
            continue
        match = STORY_FILE.match(Path(row.path).stem)
        if match:
            found[match.group(1)] = row.path
    return found


def list_stories(session: Session, store: Storage, target: Target) -> list[dict]:
    """A target's stories, read from the head revision's `file_index`.

    A query against truth rather than a glob over a directory -- which is also
    why it works at all now that there is no directory. The title comes from
    each story's first heading, so the blobs are read; there are a handful of
    stories per target, and the portal shows the titles.
    """
    head = revisions.head_revision(session, target.id)
    if head is None:
        return []
    out: list[dict] = []
    for story_id, path in sorted(_story_paths(session, target).items()):
        match = STORY_FILE.match(Path(path).stem)
        slug = match.group(2) if match else ""
        out.append(
            {
                "story_id": story_id,
                "slug": slug,
                "title": story_title(_read(session, store, head.id, path)) or slug,
                "file": Path(path).name,
                "path": path,
            }
        )
    return out


def _read(session: Session, store: Storage, revision_id: int, path: str) -> str:
    row = revisions.get_file(session, revision_id, path)
    if row is None:
        return ""
    chunks, _ct = store.get_stream(row.blob_key)
    return b"".join(chunks).decode()


def read_story(
    session: Session, store: Storage, target: Target, story_id: str
) -> dict:
    """One story's stored bytes, for the editor to load."""
    paths = _story_paths(session, target)
    if story_id not in paths:
        raise NoSuchStory(f"target {target.app!r} has no story {story_id}")
    head = revisions.head_revision(session, target.id)
    path = paths[story_id]
    match = STORY_FILE.match(Path(path).stem)
    return {
        "story_id": story_id,
        "slug": match.group(2) if match else "",
        "content": _read(session, store, head.id, path),
        "path": path,
    }


def write_story(
    session: Session,
    store: Storage,
    target: Target,
    *,
    story_id: str,
    slug: str,
    content: str,
) -> Revision | None:
    """Create or replace one story. One revision, or none if unchanged.

    A changed slug is a rename, and a rename is one edit: the old file is
    removed and the new one written in the same revision, rather than leaving
    two files that both claim to be this story -- which story resolution refuses
    to choose between.
    """
    path = story_path(story_id, slug)
    existing = _story_paths(session, target).get(story_id)

    def edit(root: Path) -> None:
        if existing is not None and existing != path:
            (root / existing).unlink(missing_ok=True)
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)

    return _commit_edit(session, target, store, edit)


def delete_story(
    session: Session, store: Storage, target: Target, *, story_id: str
) -> Revision:
    """Remove one story. Its plan and suite are left alone.

    An operator deleting a story has not asked us to destroy a healed suite, and
    doing it silently would be the kind of helpfulness nobody can undo without
    reading the history. Removing the tests too is a deliberate second act.
    """
    existing = _story_paths(session, target).get(story_id)
    if existing is None:
        raise NoSuchStory(f"target {target.app!r} has no story {story_id}")

    revision = _commit_edit(
        session, target, store, lambda root: (root / existing).unlink(missing_ok=True)
    )
    assert revision is not None, "removing a tracked file always changes the tree"
    return revision


# --- configuration --------------------------------------------------------

def update_config(
    session: Session, store: Storage, target: Target, *, resolve: Resolver | None = None, **fields
) -> tuple[Target, Revision | None]:
    """Change a target's configuration, and record the tree diff it causes.

    `base_url` re-renders the generated config, which is a tree diff, which is a
    revision. `locators` and `agent_notes` reach the agent through its prompt
    rather than through a tracked file, so they change the row and commit
    nothing -- there is no tree diff to record, and inventing one would make
    `rev` count edits rather than changes.

    Validation runs before the live-run check so a typo is reported as a typo
    rather than as a conflict.
    """
    given = {field: value for field, value in fields.items() if value is not None}
    if not given:
        return target, None
    # Validate before anything else: `update_target_config` commits, so a
    # refused edit must not have moved the row -- and a typo should be reported
    # as a typo rather than as a conflict. One cleaner map, shared with the
    # write path, so the two cannot disagree about which fields exist.
    target_config.clean_fields(given, resolve=resolve)
    repo.assert_no_live_run(session, target.id)

    target = repo.update_target_config(session, target.id, resolve=resolve, **given)
    revision = _commit_edit(session, target, store, lambda root: None)
    return target, revision


__all__ = [
    "AuthoringError",
    "InvalidStory",
    "NoSuchStory",
    "create_target",
    "delete_story",
    "initial_tree",
    "list_stories",
    "read_story",
    "story_path",
    "update_config",
    "write_story",
]