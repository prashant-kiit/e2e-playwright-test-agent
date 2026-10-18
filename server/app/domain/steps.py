"""The QA pipeline steps and their fixed order.

These mirror Steps 1-5 of prompts/qa_system_prompt.md (Step 6 is just "stop for
review", not agent work). They are the checkpoint boundaries: the orchestrator
runs one step at a time and can pause/resume/stop between them.
"""

from __future__ import annotations

from enum import Enum


class Step(str, Enum):
    READ_STORY = "read_story"   # Step 1: resolve config + read the user story
    PLAN = "plan"               # Step 2: playwright-test-planner -> test plan
    EXPLORE = "explore"         # Step 3: exploratory testing via MCP browser
    GENERATE = "generate"       # Step 4: playwright-test-generator -> *.spec.ts
    HEAL = "heal"               # Step 5: playwright-test-healer -> green on Chromium


# Canonical execution order. Index in this list == step number - 1.
STEP_ORDER: tuple[Step, ...] = (
    Step.READ_STORY,
    Step.PLAN,
    Step.EXPLORE,
    Step.GENERATE,
    Step.HEAL,
)


def first_step() -> Step:
    return STEP_ORDER[0]


def last_step() -> Step:
    return STEP_ORDER[-1]


def step_index(step: Step) -> int:
    """0-based position of a step in the pipeline."""
    return STEP_ORDER.index(step)


def next_step(step: Step) -> Step | None:
    """The step after `step`, or None if `step` is the last one."""
    idx = step_index(step)
    if idx + 1 < len(STEP_ORDER):
        return STEP_ORDER[idx + 1]
    return None


def resume_step(last_completed: Step | None) -> Step | None:
    """Which step to run given the last successfully completed one.

    None last_completed -> start at the first step. If the last step is already
    complete, there is nothing to resume (None).
    """
    if last_completed is None:
        return first_step()
    return next_step(last_completed)


def is_last(step: Step) -> bool:
    return step == last_step()
