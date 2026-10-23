"""Launches the orchestrator for a run on a background thread.

Kept separate from the API so tests can override it with a no-op (they drive the
driver directly with a FakeRunner). The real launcher picks the configured
runner, streams log lines to the bus, and closes the stream when the run ends.
"""

from __future__ import annotations

import threading

from . import config, repo, storage
from .artifacts import ArtifactCollector
from .db import SessionLocal
from .domain.steps import Step
from .orchestrator.bus import bus
from .orchestrator.claude import ClaudeRunner
from .orchestrator.driver import run_pipeline
from .orchestrator.fake import FakeRunner
from .orchestrator.runner import Runner
from .reaper import heartbeat_during


def make_runner() -> Runner:
    if config.runner_kind() == "fake":
        return FakeRunner(delay=config.fake_delay())
    return ClaudeRunner()


def make_collector():
    """A collect(run_id, step) callback that sweeps the run dir into storage."""
    collector = ArtifactCollector(storage.from_env())

    def collect(run_id: int, step: Step) -> None:
        with SessionLocal() as s:
            run = repo.get_run(s, run_id)
            collector.collect(s, run, config.run_dir(run.run_key), step)

    return collect


def launch_run(run_id: int) -> None:
    """Start the pipeline for run_id on a daemon thread."""
    collect = make_collector()

    def _target() -> None:
        try:
            # The lease is otherwise refreshed only at step boundaries, so a step
            # longer than the TTL would look like a crash to the reaper.
            with heartbeat_during(run_id):
                run_pipeline(
                    SessionLocal, run_id, make_runner(), emit=bus.emitter(run_id), collect=collect
                )
        finally:
            bus.close(run_id)

    threading.Thread(target=_target, name=f"run-{run_id}", daemon=True).start()
