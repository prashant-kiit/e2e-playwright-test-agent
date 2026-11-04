"""M4: artifact collection into (fake) storage + the index, and classification.

P5-05 split the sweep from the index: the collector uploads through the run's
gateway and asks the control plane to record each row, because a run in a
sandbox has no database. So these drive it through a `LocalGateway` -- a real
token against the fixtures' database -- and read the rows back the way they
always did.
"""

import pytest

from app import config, repo
from app.artifacts import ArtifactCollector, NullCollector, classify
from app.control.gateway import GatewayStorage
from app.domain.steps import STEP_ORDER, Step
from app.models import Artifact
from app.orchestrator.driver import run_pipeline
from app.orchestrator.fake import FakeRunner
from tests.control_helpers import control_for
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target


@pytest.fixture()
def run_env(session_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("QA_RUNS_DIR", str(tmp_path))
    with session_factory() as s:
        p = repo.create_project(s, name="demo")
        t = create_target(s, p.id, app="practice-target", name="Practice")
        run = repo.start_run(s, target_id=t.id, story_id="SCRUM-201", mode="full")
        return run.id, run.run_key, tmp_path


@pytest.fixture()
def control(run_env, session_factory, monkeypatch):
    """The run's gateway, holding the fake store the assertions read back."""
    run_id, _run_key, _runs_dir = run_env
    store = FakeStorage()
    return control_for(run_id, session_factory, store, monkeypatch), store


def test_classify_maps_extensions_and_paths():
    assert classify("evidence/login.png") == "screenshot"
    assert classify("video/run.webm") == "video"
    assert classify("trace.zip") == "trace"
    assert classify("playwright-report/index.html") == "report"
    assert classify("plan.html") == "report"
    assert classify("session.jsonl") == "log"
    assert classify("notes.bin") == "other"


def test_collector_uploads_and_indexes_new_files(run_env, session_factory, control):
    run_id, run_key, runs_dir = run_env
    rd = runs_dir / run_key
    (rd / "playwright-report").mkdir(parents=True)
    (rd / "shot.png").write_bytes(b"png")
    (rd / "trace.zip").write_bytes(b"zip")
    (rd / "playwright-report" / "index.html").write_text("<html></html>")

    gateway, storage = control
    collector = ArtifactCollector(GatewayStorage(gateway), gateway)

    keys = collector.collect(run_key, rd, Step.HEAL)

    assert len(keys) == 3
    # Keys are run_key/relpath and the bytes made it into storage.
    assert f"{run_key}/shot.png" in storage.objects
    assert f"{run_key}/playwright-report/index.html" in storage.objects
    with session_factory() as s:
        rows = list(s.scalars(repo.select(Artifact).where(Artifact.run_id == run_id)))
    assert len(rows) == 3
    assert {r.kind for r in rows} == {"screenshot", "trace", "report"}


def test_recollecting_same_path_bumps_version_not_rows(
    run_env, session_factory, control
):
    run_id, run_key, runs_dir = run_env
    rd = runs_dir / run_key
    rd.mkdir(parents=True)
    (rd / "shot.png").write_bytes(b"v1")

    gateway, storage = control
    collector = ArtifactCollector(GatewayStorage(gateway), gateway)

    collector.collect(run_key, rd, Step.GENERATE)
    (rd / "shot.png").write_bytes(b"v2")
    collector.collect(run_key, rd, Step.HEAL)

    with session_factory() as s:
        rows = list(s.scalars(repo.select(Artifact).where(Artifact.run_id == run_id)))
        assert len(rows) == 1
        assert rows[0].version == 2
        assert rows[0].step == Step.HEAL.value


def test_driver_collects_after_each_step(run_env, session_factory, control):
    run_id, run_key, runs_dir = run_env
    gateway, _storage = control
    collector = ArtifactCollector(GatewayStorage(gateway), gateway)

    def collect(rid, step):
        collector.collect(run_key, config.run_dir(run_key), step)

    run_pipeline(gateway, run_id, FakeRunner(), collect=collect)

    # FakeRunner writes <step>.txt each step; all five get indexed as logs.
    with session_factory() as s:
        rows = list(s.scalars(repo.select(Artifact).where(Artifact.run_id == run_id)))
    assert {r.s3_key.split("/")[-1] for r in rows} == {f"{st.value}.txt" for st in STEP_ORDER}
    assert all(r.kind == "log" for r in rows)


def test_null_collector_is_noop(run_env):
    _run_id, run_key, runs_dir = run_env

    assert NullCollector().collect(run_key, runs_dir, Step.HEAL) == []
