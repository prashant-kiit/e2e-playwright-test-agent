"""The one-shot cutover: snapshot every target, gate on parity, import config.

Run once, with the repo mount still present, as the last thing before P3's
deletions:

    for each target:
        snapshot its tracked tree        (the P2 path, unchanged)
        require parity green             <- refuses to proceed otherwise
        import app.json into the target row
    verify: every target has a head revision and a complete config row

**Parity's last act is to gate its own removal.** A target whose head revision
disagrees with the files on disk is exactly the target whose `app.json` must not
be trusted, so the command refuses and names it rather than importing a
configuration from a tree it cannot vouch for. After this succeeds, `apps/`, the
mount, `config.repo_root()` and parity itself are deleted.

**Re-running is a no-op, not an error.** A snapshot of an unchanged tree commits
nothing and the config import is idempotent, so an operator unsure whether it
ran can simply run it again. That is what keeps it a reviewable operation rather
than a runbook with a "did you already do step 2?" footnote.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from . import config, monorepo, repo, revisions, storage, target_config
from .delivery.errors import DeliveryError
from .models import Target
from .storage import Storage

# How a target's configuration is read during the cutover. Injected so the
# command is testable without a particular on-disk layout, and so the one place
# that still reads app.json is visible from here.
ConfigReader = Callable[[str], dict]


def app_json_path(app: str) -> Path:
    return config.repo_root() / "apps" / app / "app.json"


def read_app_json(app: str) -> dict:
    """The configuration file this command exists to import.

    It lives here rather than in app/delivery because delivery does not read it
    any more: a target's configuration reaches delivery through `Tools` as a row
    (P3-07). This is the last reader, and it goes with the mount.
    """
    path = app_json_path(app)
    if not path.exists():
        raise DeliveryError(f"no such app: apps/{app}/app.json not found")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise DeliveryError(f"apps/{app}/app.json is not valid JSON: {exc}") from exc


class CutoverError(Exception):
    """The cutover cannot proceed."""


class ParityNotGreen(CutoverError):
    """A target's head revision disagrees with the files on disk."""

    def __init__(self, app: str, detail: str) -> None:
        super().__init__(
            f"target {app!r}: parity is not green, so its tree is not safe to cut over "
            f"from ({detail}). Resolve the drift, then re-run the cutover."
        )
        self.app = app


class CutoverIncomplete(CutoverError):
    """The cutover ran but left a target without a head revision or a full row."""


@dataclass(frozen=True)
class TargetOutcome:
    """What the cutover did to one target."""

    app: str
    rev: int | None
    committed: bool  # a new revision was written (False when the tree was unchanged)
    imported: bool   # the config row changed (False on a re-run)


@dataclass(frozen=True)
class CutoverResult:
    targets: tuple[TargetOutcome, ...]

    @property
    def committed(self) -> int:
        return sum(1 for t in self.targets if t.committed)

    @property
    def imported(self) -> int:
        return sum(1 for t in self.targets if t.imported)


def _config_from_app_json(app: str, read_config: ConfigReader) -> dict:
    """The five configuration values app.json holds, cleaned.

    Cleaned by the same functions the write path uses, so the cutover cannot
    import a configuration the portal would refuse.
    """
    try:
        data = read_config(app)
    except DeliveryError as exc:
        raise CutoverError(f"target {app!r}: {exc}") from exc
    return {
        "name": data.get("name") or app,
        "base_url": str(data.get("baseURL") or "").strip(),
        "target_repo": str(data.get("targetRepo") or "").strip(),
        "target_branch": target_config.clean_target_branch(data.get("targetBranch")),
        "locators": target_config.clean_locators(data.get("locators")),
        "agent_notes": target_config.clean_agent_notes(data.get("agentNotes")),
    }


def _import_config(session: Session, target: Target, config: dict) -> bool:
    """Write the configuration onto the row. True if anything changed.

    Assignment is unconditional-looking but compared first: "re-running changes
    no row" is a property of the data, not of an UPDATE that happens to write
    the same bytes, and the difference is what the operator is told.
    """
    changed = any(getattr(target, field) != value for field, value in config.items())
    if not changed:
        return False
    for field, value in config.items():
        setattr(target, field, value)
    session.commit()
    session.refresh(target)
    return True


def _cut_over_target(
    session: Session, target: Target, store: Storage, read_config: ConfigReader
) -> TargetOutcome:
    config = _config_from_app_json(target.app, read_config)

    # The P2 path, unchanged -- over `apps/<app>/` staged as the worktree the
    # tracked tree is now defined against. The generated entry is rendered from
    # the configuration being imported, so the snapshot is the tree this target
    # will hydrate once the cutover has written that configuration down.
    staged_config = target_config.TargetConfig(
        app=target.app,
        name=config["name"],
        base_url=config["base_url"],
        locators=config["locators"],
        agent_notes=tuple(config["agent_notes"]),
        target_repo=config["target_repo"],
        target_branch=config["target_branch"],
    )
    with monorepo.staged_tree(target.app, staged_config) as root:
        committed = revisions.commit_revision(
            session, target, store, root, author="cutover"
        )
        parity = revisions.target_parity(session, target, root)
        if not parity.in_sync:
            raise ParityNotGreen(target.app, _describe(parity))

    imported = _import_config(session, target, config)
    head = revisions.head_revision(session, target.id)
    return TargetOutcome(
        app=target.app,
        rev=head.rev if head is not None else None,
        committed=committed is not None,
        imported=imported,
    )


def _describe(parity) -> str:
    if not parity.has_revision:
        return "no head revision"
    parts = [
        f"{label}: {', '.join(paths)}"
        for label, paths in (
            ("only in the database", parity.diff.only_in_db),
            ("only on disk", parity.diff.only_on_disk),
            ("different contents", parity.diff.modified),
        )
        if paths
    ]
    return "; ".join(parts) or "unknown difference"


def _verify(session: Session, targets: list[Target]) -> None:
    """Every target has a head revision and a configuration the write path
    accepts. Asserted here so a green exit means it, rather than meaning that
    somebody read the output and agreed."""
    problems: list[str] = []
    for target in targets:
        session.refresh(target)
        if revisions.head_revision(session, target.id) is None:
            problems.append(f"{target.app}: no head revision")
            continue
        try:
            target_config.clean_base_url(target.base_url)
            target_config.clean_target_repo(target.target_repo)
        except target_config.ConfigError as exc:
            problems.append(f"{target.app}: {exc}")
    if problems:
        raise CutoverIncomplete(
            "the cutover left these targets unready:\n  " + "\n  ".join(problems)
        )


def run_cutover(
    session: Session,
    store: Storage | None = None,
    *,
    read_config: ConfigReader = read_app_json,
) -> CutoverResult:
    """Snapshot, gate and import every target. Raises rather than half-finishing.

    The loop is per target and raises on the first bad one: the targets already
    cut over keep their imported configuration, which is safe because the import
    is idempotent -- re-running after the fix finishes the job without undoing
    any of it.
    """
    store = store or storage.from_env()
    targets = repo.list_targets(session)
    outcomes = tuple(
        _cut_over_target(session, target, store, read_config) for target in targets
    )
    _verify(session, list(targets))
    return CutoverResult(targets=outcomes)


# --- CLI: python -m app.cutover -----------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Run the cutover against the configured database and blob store.

    Exit 0 on success (including a no-op re-run) and 2 on refusal, matching the
    delivery CLI's convention, so a wrapper script can tell "nothing to do" from
    "this target is not safe to cut over".
    """
    import argparse

    from .db import SessionLocal

    parser = argparse.ArgumentParser(
        prog="python -m app.cutover",
        description=(
            "Snapshot every target, require parity green, and import its app.json "
            "into the target row. Safe to re-run."
        ),
    )
    parser.parse_args(argv)

    with SessionLocal() as session:
        try:
            result = run_cutover(session)
        except CutoverError as exc:
            print(f"cutover refused: {exc}", file=sys.stderr)
            return 2

    for outcome in result.targets:
        snapshot = f"rev {outcome.rev}" + (" (new)" if outcome.committed else " (unchanged)")
        config = "config imported" if outcome.imported else "config already current"
        print(f"{outcome.app}: {snapshot}, {config}")
    print(
        f"done: {len(result.targets)} target(s), {result.committed} revision(s) committed, "
        f"{result.imported} config row(s) imported"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
