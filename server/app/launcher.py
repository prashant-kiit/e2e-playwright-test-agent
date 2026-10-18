"""Launches the orchestrator for a run on a background thread.

Kept separate from the API so tests can override it with a no-op (they drive the
driver directly with a FakeRunner). The real launcher picks the configured
runner, streams log lines to the bus, and closes the stream when the run ends.
"""

from __future__ import annotations

import threading

from . import config
from .db import SessionLocal
from .orchestrator.bus import bus
from .orchestrator.claude import ClaudeRunner
from .orchestrator.driver import run_pipeline
from .orchestrator.fake import FakeRunner
from .orchestrator.runner import Runner


def make_runner() -> Runner:
    return FakeRunner() if config.runner_kind() == "fake" else ClaudeRunner()


def launch_run(run_id: int) -> None:
    """Start the pipeline for run_id on a daemon thread."""

    def _target() -> None:
        try:
            run_pipeline(SessionLocal, run_id, make_runner(), emit=bus.emitter(run_id))
        finally:
            bus.close(run_id)

    threading.Thread(target=_target, name=f"run-{run_id}", daemon=True).start()
