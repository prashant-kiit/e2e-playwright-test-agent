"""M4: artifact collection into (fake) storage + the index, and classification."""

import pytest

from app import config, repo
from app.artifacts import ArtifactCollector, NullCollector, classify
from app.domain.steps import STEP_ORDER, Step
from app.models import Artifact
from app.orchestrator.driver import run_pipeline
from app.orchestrator.fake import FakeRunner
from tests.storage_helpers import FakeStorage


@pytest.fixture()
def run_env(session_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("QA_RUNS_DIR", str(tmp_path))
    with session_factory() as s:
        p = repo.create_project(s, name="demo")
        t = repo.create_target(s, project_id=p.id, app="practice-target", name="Practice")
        run = repo.start_run(s, target_id=t.id, story_id="SCRUM-201", mode="full")
        return run.id, run.run_key, tmp_path


def test_classify_maps_extensions_and_paths():
    assert classify("evidence/login.png") == "screenshot"
    assert classify("video/run.webm") == "video"
    assert classify("trace.zip") == "trace"
    assert classify("playwright-report/index.html") == "report"
    assert classify("plan.html") == "report"
    assert classify("session.jsonl") == "log"
    assert classify("notes.bin") == "other"


def test_collector_uploads_and_indexes_new_files(run_env, session_factory):
    run_id, run_key, runs_dir = run_env
    rd = runs_dir / run_key
    (rd / "playwright-report").mkdir(parents=True)
    (rd / "shot.png").write_bytes(b"png")
    (rd / "trace.zip").write_bytes(b"zip")
    (rd / "playwright-report" / "index.html").write_text("<html></html>")

    storage = FakeStorage()
    collector = ArtifactCollector(storage)
    with session_factory() as s:
        run = repo.get_run(s, run_id)
        rows = collector.collect(s, run, rd, Step.HEAL)

    kinds = {r.kind for r in rows}
    assert kinds == {"screenshot", "trace", "report"}
    # Keys are run_key/relpath and the bytes made it into storage.
    assert f"{run_key}/shot.png" in storage.objects
    assert f"{run_key}/playwright-report/index.html" in storage.objects
    with session_factory() as s:
        assert len(list(s.scalars(repo.select(Artifact).where(Artifact.run_id == run_id)))) == 3


def test_recollecting_same_path_bumps_version_not_rows(run_env, session_factory):
    run_id, run_key, runs_dir = run_env
    rd = runs_dir / run_key
    rd.mkdir(parents=True)
    (rd / "shot.png").write_bytes(b"v1")

    storage = FakeStorage()
    collector = ArtifactCollector(storage)
    with session_factory() as s:
        collector.collect(s, repo.get_run(s, run_id), rd, Step.GENERATE)
    (rd / "shot.png").write_bytes(b"v2")
    with session_factory() as s:
        collector.collect(s, repo.get_run(s, run_id), rd, Step.HEAL)

    with session_factory() as s:
        rows = list(s.scalars(repo.select(Artifact).where(Artifact.run_id == run_id)))
        assert len(rows) == 1
        assert rows[0].version == 2
        assert rows[0].step == Step.HEAL.value


def test_driver_collects_after_each_step(run_env, session_factory):
    run_id, run_key, runs_dir = run_env
    storage = FakeStorage()
    collector = ArtifactCollector(storage)

    def collect(rid, step):
        with session_factory() as s:
            run = repo.get_run(s, rid)
            collector.collect(s, run, config.run_dir(run.run_key), step)

    run_pipeline(session_factory, run_id, FakeRunner(), collect=collect)

    # FakeRunner writes <step>.txt each step; all five get indexed as logs.
    with session_factory() as s:
        rows = list(s.scalars(repo.select(Artifact).where(Artifact.run_id == run_id)))
    assert {r.s3_key.split("/")[-1] for r in rows} == {f"{st.value}.txt" for st in STEP_ORDER}
    assert all(r.kind == "log" for r in rows)


def test_null_collector_is_noop(run_env, session_factory):
    run_id, run_key, runs_dir = run_env
    with session_factory() as s:
        assert NullCollector().collect(s, repo.get_run(s, run_id), runs_dir, Step.HEAL) == []
