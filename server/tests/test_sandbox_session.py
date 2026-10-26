"""Pause stops costing money, and a paused run stops losing what it learned.

Two things that were free before P4 and are not any more.

**Pause destroys the container** (amending DESIGN.md §5, which kept it alive for
a grace window). The reason is P3: resume already re-hydrates from the head
revision and that path is tested, so an idle sandbox's only advantage -- a warm
worktree -- is one the harness no longer needs, while "a SaaS cannot pay for idle
sandboxes" is the same sentence it always was.

**But the agent session must survive.** `--resume` works today only because the
CLI's session store happens to sit on the host that started the run; the moment a
run executes in a container destroyed on pause, that store is gone and step 4
generates tests from an exploration it cannot remember. So the session is
persisted as a run artifact under a reserved name and restored into the next
container before the CLI is invoked.

And if the restore fails, the run **continues without session continuity and says
so in the log**: the tree is the carrier of the work and it is intact, the
exploration is only context, and losing context loudly beats failing a run that
can still finish.
"""

from __future__ import annotations

import tarfile

import pytest

from app import launcher, repo, revisions
from app.domain.status import RunStatus
from app.domain.steps import Step
from app.models import Artifact
from app.orchestrator.bus import InMemoryLogBus
from app.orchestrator.fake import FakeRunner
from app.sandbox import session as agent_session
from tests.delivery_helpers import make_worktree
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    """A sandbox's CLI state directory, as app/sandbox/env.py sets it up."""
    path = tmp_path / "claude-config"
    (path / "projects" / "qa").mkdir(parents=True)
    (path / "projects" / "qa" / "session.json").write_text('{"id": "abc"}')
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(path))
    return path


@pytest.fixture()
def run_env(session_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("QA_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("QA_WORKTREES_DIR", str(tmp_path / "worktrees"))
    monkeypatch.setenv("QA_RUNNER", "fake")
    store = FakeStorage()
    source = make_worktree(tmp_path / "source")
    with session_factory() as s:
        project = repo.create_project(s, name="demo")
        target = create_target(s, project.id, app="demo", name="Demo")
        revisions.commit_revision(s, target, store, source, author="operator")
        run = repo.start_run(s, target_id=target.id, story_id="SCRUM-1", mode="full")
        return run.id, run.run_key, target.id, store


def _drive(session_factory, run_id, store, runner=None, bus=None):
    bus = bus or InMemoryLogBus()
    launcher.drive_run(
        run_id,
        runner=runner or FakeRunner(),
        bus=bus,
        session_factory=session_factory,
        store=store,
    )
    return bus.read_from(run_id, 0)[0]


def _session_artifacts(session_factory, run_id):
    with session_factory() as s:
        return [
            a
            for a in s.scalars(repo.select(Artifact).where(Artifact.run_id == run_id))
            if a.s3_key.endswith(agent_session.ARCHIVE_NAME)
        ]


# --- the session is a run artifact under a reserved name -----------------

def test_the_agent_session_is_archived_at_run_end(
    run_env, session_factory, config_dir
):
    run_id, run_key, _target_id, store = run_env

    _drive(session_factory, run_id, store)

    artifacts = _session_artifacts(session_factory, run_id)
    assert len(artifacts) == 1
    assert artifacts[0].s3_key == f"{run_key}/{agent_session.ARCHIVE_NAME}"
    assert artifacts[0].kind == "session"
    assert store.objects[artifacts[0].s3_key][0], "the archive has bytes"


def test_the_session_is_archived_at_every_step_boundary(
    run_env, session_factory, config_dir, tmp_path
):
    """Pause destroys the container at once (DESIGN.md §5), so the way out of a
    run cannot be the only place the session is saved: a sandbox killed without
    warning archives nothing.

    Asserted from *inside* a later step, which is the instant a pause lands: by
    then the previous boundary's archive is already in the store, so what a
    pause costs is the exploration of the step it interrupted and no more.
    """
    run_id, run_key, _target_id, store = run_env
    key = f"{run_key}/{agent_session.ARCHIVE_NAME}"
    seen: list[tuple[Step, bool]] = []

    class ExploresAndLooks(FakeRunner):
        def run_step(self, ctx, emit):
            seen.append((ctx.step, key in store.objects))
            # As the CLI does while it works, so each boundary has something new
            # to archive and the versions are not a formality.
            (config_dir / "projects" / "qa" / f"{ctx.step.value}.json").write_text("{}")
            return super().run_step(ctx, emit)

    _drive(session_factory, run_id, store, ExploresAndLooks())

    assert len(seen) > 1, "the pipeline ran more than one step"
    assert seen[0][1] is False, "nothing to restore before the first boundary"
    assert all(archived for _step, archived in seen[1:]), seen


def test_the_archive_holds_what_the_cli_keeps(run_env, session_factory, config_dir, tmp_path):
    run_id, run_key, _target_id, store = run_env

    _drive(session_factory, run_id, store)

    archive = tmp_path / "out.tgz"
    archive.write_bytes(store.objects[f"{run_key}/{agent_session.ARCHIVE_NAME}"][0])
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert any(name.endswith("projects/qa/session.json") for name in names), names


def test_the_archive_is_rewritten_rather_than_duplicated_on_resume(
    run_env, session_factory, config_dir
):
    """One reserved name per run, versioned: the newest session is the one a
    resume restores, and the history is kept the way every other artifact's is.

    Versioned on *content*, like the artifact sweep, so the count is the number
    of boundaries whose bytes differed and not one per attempt -- the session is
    archived at every step boundary (DESIGN.md §5), which is why this asserts
    that a resume moved the version on rather than naming a number. The
    no-change half of the rule is the next test."""
    run_id, _run_key, _target_id, store = run_env

    _drive(session_factory, run_id, store, _PausesAfter(Step.PLAN, session_factory))
    paused = _session_artifacts(session_factory, run_id)
    assert len(paused) == 1, "the interrupted attempt left one archive"
    before = paused[0].version

    with session_factory() as s:
        repo.resume_run(s, run_id)

    class ExploresFurther(FakeRunner):
        """Writes into the session store, as the CLI does while it works."""

        def run_step(self, ctx, emit):
            (config_dir / "projects" / "qa" / f"{ctx.step.value}.json").write_text("{}")
            return super().run_step(ctx, emit)

    _drive(session_factory, run_id, store, ExploresFurther())

    artifacts = _session_artifacts(session_factory, run_id)
    assert len(artifacts) == 1, "one reserved name, not one archive per attempt"
    assert artifacts[0].version > before, (
        "a resumed run that explored further archives a new version"
    )


def test_a_resume_that_changes_nothing_does_not_manufacture_a_version(
    run_env, session_factory, config_dir
):
    """The other half of "versioned on content", and the half the per-boundary
    archive made load-bearing: the archive is now written at *every* step
    boundary, so an agent that explores nothing would bump the version once per
    step for identical bytes if the digest were not what decides."""
    run_id, _run_key, _target_id, store = run_env

    _drive(session_factory, run_id, store, _PausesAfter(Step.PLAN, session_factory))
    before = _session_artifacts(session_factory, run_id)[0].version

    with session_factory() as s:
        repo.resume_run(s, run_id)
    _drive(session_factory, run_id, store)  # the plain fake writes no session state

    artifacts = _session_artifacts(session_factory, run_id)
    assert len(artifacts) == 1
    assert artifacts[0].version == before, "identical bytes are not a new version"


def test_nothing_is_archived_where_there_is_no_sandbox_session_directory(
    run_env, session_factory, monkeypatch
):
    """The thread path on a developer's laptop. `CLAUDE_CONFIG_DIR` is set by
    the sandbox environment builder and nowhere else, so an unset one means
    there is no per-run session store -- and the developer's own `~/.claude` is
    emphatically not one to upload."""
    run_id, _run_key, _target_id, store = run_env
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    _drive(session_factory, run_id, store)

    assert _session_artifacts(session_factory, run_id) == []


def test_an_archive_failure_does_not_fail_the_run(run_env, session_factory, config_dir):
    """The session is context; the tree is the work."""
    run_id, _run_key, _target_id, store = run_env

    class RefusesTheArchive(FakeStorage):
        def __init__(self, seeded):
            super().__init__()
            self.objects = seeded.objects

        def put_file(self, key, path, content_type=None):
            if key.endswith(agent_session.ARCHIVE_NAME):
                raise OSError("store is down")
            super().put_file(key, path, content_type)

    _drive(session_factory, run_id, RefusesTheArchive(store))

    with session_factory() as s:
        assert repo.get_run(s, run_id).status is RunStatus.COMPLETED


# --- restored before the CLI is invoked ----------------------------------

class _PausesAfter(FakeRunner):
    def __init__(self, step, session_factory, **kw):
        super().__init__(**kw)
        self.step = step
        self._sf = session_factory

    def run_step(self, ctx, emit):
        result = super().run_step(ctx, emit)
        if ctx.step is self.step:
            with self._sf() as s:
                repo.request_pause(s, ctx.run_id)
        return result


def test_a_resumed_run_gets_its_session_back_before_the_first_step(
    run_env, session_factory, config_dir
):
    run_id, _run_key, _target_id, store = run_env
    _drive(session_factory, run_id, store, _PausesAfter(Step.PLAN, session_factory))
    with session_factory() as s:
        assert repo.get_run(s, run_id).status is RunStatus.PAUSED
        repo.resume_run(s, run_id)
    # The next container starts with an empty session directory, as a fresh
    # container does.
    (config_dir / "projects" / "qa" / "session.json").unlink()
    seen: list[bool] = []

    class ChecksTheSession(FakeRunner):
        def run_step(self, ctx, emit):
            seen.append((config_dir / "projects" / "qa" / "session.json").is_file())
            return super().run_step(ctx, emit)

    _drive(session_factory, run_id, store, ChecksTheSession())

    assert seen and all(seen), "the session was restored before any step ran"


def test_a_resume_whose_restore_fails_still_completes_and_says_so(
    run_env, session_factory, config_dir
):
    run_id, _run_key, _target_id, store = run_env
    _drive(session_factory, run_id, store, _PausesAfter(Step.PLAN, session_factory))
    with session_factory() as s:
        repo.resume_run(s, run_id)
    # The archive is gone from the store: a lost blob, a pruned bucket.
    for key in [k for k in store.objects if k.endswith(agent_session.ARCHIVE_NAME)]:
        del store.objects[key]

    lines = _drive(session_factory, run_id, store)

    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.COMPLETED, run.error
    assert any("without session continuity" in line for line in lines), lines


def test_a_failed_restore_stops_the_cli_being_told_to_resume_a_lost_session(
    run_env, session_factory, config_dir
):
    """`--resume <id>` against a store that does not have it is a failed step;
    continuing without continuity means continuing without the flag."""
    run_id, _run_key, _target_id, store = run_env
    _drive(session_factory, run_id, store, _PausesAfter(Step.PLAN, session_factory))
    with session_factory() as s:
        repo.resume_run(s, run_id)
        assert repo.get_run(s, run_id).claude_session_id is not None
    for key in [k for k in store.objects if k.endswith(agent_session.ARCHIVE_NAME)]:
        del store.objects[key]
    resumed_with: list[str | None] = []

    class RecordsTheFlag(FakeRunner):
        def run_step(self, ctx, emit):
            resumed_with.append(ctx.prev_session_id)
            return super().run_step(ctx, emit)

    _drive(session_factory, run_id, store, RecordsTheFlag())

    assert resumed_with[0] is None, "the first resumed step was not told to --resume"


def test_a_first_run_restores_nothing_and_says_nothing(
    run_env, session_factory, config_dir
):
    """There is no session to lose before step 1, so there is nothing to
    report: a log line about continuity on every fresh run would be noise."""
    run_id, _run_key, _target_id, store = run_env

    lines = _drive(session_factory, run_id, store)

    assert not any("session continuity" in line for line in lines)
