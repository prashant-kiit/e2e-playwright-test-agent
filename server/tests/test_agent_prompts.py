"""The agent works in the hydrated worktree, and reads no config file.

Two things are pinned here. First, the prompts and the agent runtime resolve
from **package data**: an API image needs no mounted repo to run an agent, and a
path relative to a checkout is exactly the dependency P3 removes. Second, the
rendered prompt carries the target row's `baseURL`, `locators` and `agentNotes`
and worktree-relative paths, because `app.json` does not exist and `apps/<app>/`
is not a shape the agent should know about.

The ClaudeRunner's `run_step` is not exercised here -- that is the FakeRunner's
job -- but the two decisions it makes before spawning anything, the prompt text
and the working directory, are plain functions and are.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.steps import STEP_ORDER, Step
from app.orchestrator import claude
from app.orchestrator.runner import StepContext
from tests.delivery_helpers import make_worktree
from tests.target_helpers import CONFIG

PACKAGE_DIR = Path(claude.__file__).resolve().parents[1]


@pytest.fixture()
def ctx(tmp_path):
    worktree = make_worktree(tmp_path / "wt", story="SCRUM-1", slug="checkout")
    return StepContext(
        run_id=7,
        run_key="20261024-120000-demo-abc123",
        app="demo",
        story_id="SCRUM-1",
        mode="full",
        step=Step.READ_STORY,
        run_dir=tmp_path / "runs" / "20261024-120000-demo-abc123",
        worktree=worktree,
        target=CONFIG,
        prev_session_id=None,
    )


# --- package data ---------------------------------------------------------

def test_the_prompts_resolve_from_package_data(tmp_path, monkeypatch):
    """Not from a path relative to a checkout: that is the mount, by another
    name."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("QA_REPO_ROOT", raising=False)

    prompts = claude.prompts_dir()
    assert prompts.is_relative_to(PACKAGE_DIR)
    assert (prompts / "steps" / "_context.md").is_file()
    for step in STEP_ORDER:
        assert (prompts / "steps" / claude.STEP_FILE[step]).is_file()


def test_the_agent_runtime_resolves_from_package_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("QA_REPO_ROOT", raising=False)

    runtime = claude.runtime_dir()
    assert runtime.is_relative_to(PACKAGE_DIR)
    assert (runtime / "settings.json").is_file()
    assert (runtime / "mcp.json").is_file()
    assert sorted(p.name for p in (runtime / "agents").glob("*.md"))


def test_neither_resolves_through_a_repo_root_helper():
    """The structural half: the API image has no repo to resolve against."""
    source = Path(claude.__file__).read_text()
    assert "repo_root" not in source
    assert "QA_REPO_ROOT" not in source


# --- the working directory is the worktree --------------------------------

def test_the_agent_runs_in_the_hydrated_worktree(ctx):
    """The agent works in that tree and nowhere else."""
    _cmd, _env, cwd = claude.step_invocation(ctx)
    assert cwd == ctx.worktree


def test_run_output_still_goes_to_the_run_directory(ctx):
    """Session log and Playwright results are run output, not tree content, and
    the generated config reads QA_RUN_DIR to honour it."""
    _cmd, env, _cwd = claude.step_invocation(ctx)
    assert env["QA_RUN_DIR"] == str(ctx.run_dir)


def test_the_isolation_flags_point_at_the_packaged_runtime(ctx):
    cmd, _env, _cwd = claude.step_invocation(ctx)
    assert "--setting-sources" in cmd
    assert "--strict-mcp-config" in cmd
    assert "--agents" in cmd
    mcp = cmd[cmd.index("--mcp-config") + 1]
    assert Path(mcp).is_relative_to(PACKAGE_DIR)


def test_the_settings_handed_to_the_cli_name_the_packaged_hook(ctx):
    """`$CLAUDE_PROJECT_DIR` is the worktree now, and the hook script is not in
    it, so the shipped settings are rendered with an absolute path."""
    import json

    cmd, _env, _cwd = claude.step_invocation(ctx)
    settings = json.loads(Path(cmd[cmd.index("--settings") + 1]).read_text())
    hook = settings["hooks"]["SessionEnd"][0]["hooks"][0]["command"]
    assert Path(hook.strip('"')).is_file()
    assert "apps/agent" not in hook


def test_the_settings_permit_edits_at_worktree_relative_paths(ctx):
    import json

    cmd, _env, _cwd = claude.step_invocation(ctx)
    settings = json.loads(Path(cmd[cmd.index("--settings") + 1]).read_text())
    allow = settings["permissions"]["allow"]
    assert "Edit(specs/**)" in allow
    assert "Edit(tests/**)" in allow
    assert not any("apps/" in rule for rule in allow)


# --- the rendered prompt --------------------------------------------------

def test_the_prompt_carries_the_rows_base_url_locators_and_agent_notes(ctx):
    message = claude.build_message(ctx)

    assert CONFIG.base_url in message
    assert CONFIG.locators in message
    for note in CONFIG.agent_notes:
        assert note in message


def test_a_changed_row_changes_the_rendered_prompt(ctx):
    import dataclasses

    before = claude.build_message(ctx)
    moved = dataclasses.replace(
        ctx, target=dataclasses.replace(CONFIG, base_url="https://moved.example.com")
    )

    after = claude.build_message(moved)
    assert before != after
    assert "https://moved.example.com" in after


def test_the_story_plan_test_dir_and_seed_are_worktree_relative(ctx):
    message = claude.build_message(ctx)

    assert "user-stories/SCRUM-1-checkout.md" in message
    assert "specs/SCRUM-1-checkout-test-plan.md" in message
    assert "tests/checkout" in message
    assert "seed.spec.ts" in message
    assert "apps/" not in message


def test_the_worktree_relative_paths_resolve_inside_the_hydrated_tree(ctx):
    story = claude.resolve_run_story(ctx)

    assert (ctx.worktree / story.story_rel).is_file()
    assert (ctx.worktree / story.tests_rel).is_dir()
    assert (ctx.worktree / "seed.spec.ts").is_file()


def test_the_browser_project_matches_the_generated_single_target_config(ctx):
    message = claude.build_message(ctx)

    assert "chromium" in message
    assert "demo-chromium" not in message


def test_a_story_that_is_not_in_the_tree_is_an_error_not_a_guess(ctx):
    import dataclasses

    missing = dataclasses.replace(ctx, story_id="SCRUM-999")
    with pytest.raises(Exception, match="SCRUM-999"):
        claude.build_message(missing)


def test_two_files_for_one_story_is_still_a_hard_error(ctx):
    (ctx.worktree / "user-stories" / "SCRUM-1-duplicate.md").write_text("# dup\n")
    with pytest.raises(Exception, match="exactly one"):
        claude.build_message(ctx)


# --- what no prompt may say any more --------------------------------------

def _prompt_texts() -> dict[str, str]:
    root = claude.prompts_dir()
    return {
        p.relative_to(root).as_posix(): p.read_text()
        for p in sorted(root.rglob("*.md"))
    }


@pytest.mark.parametrize("forbidden", ["app.json", "{APP_DIR}", "apps/"])
def test_no_prompt_references_the_app_directory_or_its_config_file(forbidden):
    """The file does not exist and the directory is not a shape the agent should
    know about: there is exactly one target in the tree."""
    for name, text in _prompt_texts().items():
        assert forbidden not in text, f"{name} still says {forbidden!r}"


@pytest.mark.parametrize("script", ["run-stories.sh", "push-artifacts.sh"])
def test_no_prompt_names_a_shell_script_that_has_not_existed_since_p1(script):
    """VERIFICATION-P1 known gap 0, closed in the pass that rewrote them."""
    for name, text in _prompt_texts().items():
        assert script not in text, f"{name} still names {script}"


def test_no_prompt_tells_the_agent_to_find_its_story_by_matching_a_pattern():
    """The orchestrator already knows the story and resolves it, so the prompts
    name one file rather than describing a search."""
    for name, text in _prompt_texts().items():
        assert "*/user-stories" not in text, name
        assert "Find the one file matching" not in text, name
        assert "folders starting with" not in text, name


def test_the_prompt_the_agent_receives_names_its_story_file_outright(ctx):
    """The positive half: the story arrives as a path, not as a procedure."""
    message = claude.build_message(ctx)
    assert "user-stories/SCRUM-1-checkout.md" in message
    assert "-*.md" not in message


def test_every_placeholder_in_every_step_prompt_is_rendered(ctx):
    """A prompt reaching the agent with a literal {PLACEHOLDER} in it is a
    prompt the agent has to guess at."""
    import dataclasses
    import re

    for step in STEP_ORDER:
        message = claude.build_message(dataclasses.replace(ctx, step=step))
        leftover = re.findall(r"\{[A-Z_]+\}", message)
        assert leftover == [], f"{step.value}: unrendered {leftover}"
