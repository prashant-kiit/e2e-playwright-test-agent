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

import dataclasses
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app import apphub, package_data, prompt_store, repo
from app.control import service
from app.delivery.errors import DeliveryError
from app.domain.steps import STEP_ORDER, Step
from app.models import Prompt, Tenant
from app.orchestrator import claude
from app.orchestrator.runner import StepContext
from app.run_token import RunScope
from app.tenancy import DEFAULT_TENANT_ID, tenant_scope
from tests.delivery_helpers import make_worktree
from tests.target_helpers import CONFIG, create_target

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
        # A run is handed its prompts (P5-06); these are the versions a tenant
        # that has overridden nothing resolves to, so the rendering tests below
        # still assert against the bytes the package ships.
        prompts=prompt_store.shipped_at_seed_rev(),
    )


# --- package data ---------------------------------------------------------

def test_the_prompts_resolve_from_package_data(tmp_path, monkeypatch):
    """Not from a path relative to a checkout: that is the mount, by another
    name."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("QA_REPO_ROOT", raising=False)

    prompts = package_data.prompts_dir()
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


def test_the_prompt_names_the_target_scoped_branch(ctx):
    """#51: the agent is told the branch delivery will actually push to.

    `{BRANCH}` is rendered from the same `resolve_story` the delivery uses, so
    the two cannot name different branches -- which they would have if this
    caller had kept relying on the old `app=""` default.
    """
    assert "qa/demo/SCRUM-1-checkout" in claude.build_message(ctx)


def test_a_slug_no_branch_can_hold_fails_the_run_rather_than_the_delivery(ctx):
    """The read-path refusal reaches a run, not only a delivery.

    A target whose slug cannot be part of a ref is one whose suite could be
    generated and never delivered, so it fails at the run's first step rather
    than after the tokens are spent. Asserted because it is a failure mode #51
    did not contemplate, and the honest place to find out is here.
    """
    bad = dataclasses.replace(ctx, app="two words")

    with pytest.raises(DeliveryError, match="cannot be part of a branch name"):
        claude.resolve_run_story(bad)


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
    root = package_data.prompts_dir()
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


# --- prompts resolve from Postgres, per tenant (P5-06) --------------------
#
# The prompts the agent is sent are rows now, seeded from the code-shipped
# files under server/app/prompts/ and overridable per tenant. The files stay
# the *seed source*: once a tenant has a row for a prompt, editing the file
# changes nothing for that tenant, which is what "not a live second author"
# means. See app/prompt_store.py.

def test_a_tenant_with_no_rows_inherits_the_code_shipped_defaults(session):
    """#36: "a new tenant inherits defaults with no override rows"."""
    resolved = prompt_store.resolve_all(session)

    assert {name: r.body for name, r in resolved.items()} == prompt_store.shipped_defaults()
    # Seeded, so every one is revision 1 -- the default, not an override.
    assert {r.rev for r in resolved.values()} == {prompt_store.SEED_REV}


def test_a_tenant_override_beats_the_seeded_default(session):
    """The point of the ticket: a customer's bytes, not the package's."""
    before = prompt_store.resolve(session, "steps/2-plan.md")
    saved = prompt_store.save_override(session, "steps/2-plan.md", "Plan it my way.\n")

    after = prompt_store.resolve(session, "steps/2-plan.md")
    assert after.body == "Plan it my way.\n"
    assert after.rev == saved.rev == before.rev + 1
    # and the prompt next door is untouched
    assert prompt_store.resolve(session, "steps/3-explore.md").body != "Plan it my way.\n"


def test_overrides_are_versioned_and_the_history_is_kept(session):
    """"my prompt overrides versioned, so I can see what changed and when"
    (#30, story 24): a save appends a row, it does not rewrite one."""
    default = prompt_store.resolve(session, "qa_system_prompt.md")
    prompt_store.save_override(session, "qa_system_prompt.md", "first\n")
    prompt_store.save_override(session, "qa_system_prompt.md", "second\n")

    history = prompt_store.history(session, "qa_system_prompt.md")
    assert [p.rev for p in history] == [prompt_store.SEED_REV, 2, 3]
    # The history begins with the bytes the tenant started from, so "what
    # changed" has something to have changed from.
    assert history[0].body == default.body
    assert [p.body for p in history[1:]] == ["first\n", "second\n"]
    assert prompt_store.resolve(session, "qa_system_prompt.md").rev == 3


def test_one_tenants_override_does_not_touch_another_tenants_prompt(session):
    """`Prompt` is TenantOwned, so the read guard scopes resolution; this is the
    behavioural half of that."""

    session.add(Tenant(id=77, slug="second", name="Second"))
    session.commit()

    with tenant_scope(DEFAULT_TENANT_ID):
        prompt_store.save_override(session, "steps/5-heal.md", "tenant one only\n")
        session.commit()

    with tenant_scope(77):
        theirs = prompt_store.resolve(session, "steps/5-heal.md")
        # A new tenant inherits the default, not the neighbour's override.
        assert theirs.body != "tenant one only\n"
        assert theirs.rev == prompt_store.SEED_REV


# --- a run records the version it used ------------------------------------

def test_starting_a_run_pins_the_prompt_version_it_will_use(session):
    """#36: "a run records the prompt version it used; the recorded version
    matches what ran". Pinned at the start, so there is one answer."""

    project = repo.create_project(session, name="demo")
    target = create_target(session, project.id, app="demo", name="Demo")
    prompt_store.save_override(session, "steps/4-generate.md", "generate my way\n")
    session.commit()

    run = repo.start_run(session, target_id=target.id, story_id="SCRUM-1", mode="full")

    assert run.prompt_revs, "a run must record which prompt versions it used"
    # Every prompt the agent can be sent is pinned, not just the overridden one.
    assert set(run.prompt_revs) == set(prompt_store.shipped_defaults())
    # The override is pinned at its own rev; everything else at the seeded one.
    assert run.prompt_revs["steps/4-generate.md"] == prompt_store.SEED_REV + 1
    assert run.prompt_revs["steps/3-explore.md"] == prompt_store.SEED_REV


def test_an_override_saved_after_a_run_starts_does_not_change_that_run(session):
    """What pinning buys: the recorded version is the version that ran, not
    whatever the head happened to be when the sandbox got round to asking."""

    project = repo.create_project(session, name="demo")
    target = create_target(session, project.id, app="demo", name="Demo")
    session.commit()

    run = repo.start_run(session, target_id=target.id, story_id="SCRUM-1", mode="full")
    pinned_rev = run.prompt_revs["steps/1-read_story.md"]

    prompt_store.save_override(session, "steps/1-read_story.md", "changed mid-run\n")
    session.commit()

    served = prompt_store.pinned(session, run.prompt_revs)
    assert served["steps/1-read_story.md"].rev == pinned_rev
    assert served["steps/1-read_story.md"].body != "changed mid-run\n"


def test_the_run_facts_carry_the_pinned_prompt_bodies(session):
    """How a prompt reaches an agent that has no database.

    After P5-05 a sandbox holds a run-scoped token and no `DATABASE_URL`, so the
    prompts travel with the run's other immutable facts -- the same route the
    target's row already takes, and for the same reason."""

    project = repo.create_project(session, name="demo")
    target = create_target(session, project.id, app="demo", name="Demo")
    prompt_store.save_override(session, "steps/_context.md", "My context.\n")
    session.commit()

    run = repo.start_run(session, target_id=target.id, story_id="SCRUM-1", mode="full")
    repo.begin_run(session, run.id)
    scope = RunScope(
        run_id=run.id,
        target_id=target.id,
        tenant_id=run.tenant_id,
        sandbox_attempt=run.sandbox_attempt,
    )

    facts = service.run_facts(session, scope)

    assert facts.prompts["steps/_context.md"].body == "My context.\n"
    assert facts.prompts["steps/_context.md"].rev == run.prompt_revs["steps/_context.md"]
    # and it survives the round trip the container path makes it take
    from app.control.model import RunFacts

    assert RunFacts.from_dict(facts.as_dict()).prompts == facts.prompts


# --- the runner renders what it was handed, not what is on disk -----------

def test_the_rendered_prompt_uses_the_context_prompts_not_the_files(ctx):
    """The runner is handed its prompts and renders those.

    The structural half of "the code-shipped files are the seed source, not a
    live second author": with an override in the context, the file's bytes do
    not appear in the message at all."""
    import dataclasses

    from app.prompt_store import ResolvedPrompt

    overridden = dataclasses.replace(
        ctx,
        prompts={
            "steps/_context.md": ResolvedPrompt(
                name="steps/_context.md", body="CONTEXT for {APP}.\n", rev=2
            ),
            "steps/1-read_story.md": ResolvedPrompt(
                name="steps/1-read_story.md", body="Read {STORY_ID} my way.\n", rev=2
            ),
        },
    )

    message = claude.build_message(overridden)

    assert "CONTEXT for demo." in message
    assert "Read SCRUM-1 my way." in message
    # The shipped bytes are nowhere in it.
    shipped = (package_data.prompts_dir() / "steps" / "1-read_story.md").read_text()
    assert shipped.strip() not in message


def test_the_runner_module_reads_no_prompt_file_at_all(ctx):
    """#36's last criterion, structurally: "the code-shipped files remain only
    the seed source, not a live second author".

    The runner is handed its prompts and has no path back to the package -- not
    even a fallback, because a fallback is a second reader and a second reader
    is how a file becomes an author again. `app/prompt_store.py` is the one
    module that opens a prompt file, and it does so only to seed a row."""
    source = Path(claude.__file__).read_text()
    assert "prompts_dir" not in source
    assert ".read_text()" not in source.split("def _agents_json")[0]


def test_a_prompt_the_run_was_not_given_is_an_error_not_a_file_read(ctx):
    """An agent sent a step with no instructions is worse than a run that
    stops, so a gap in the pinned set fails loudly."""
    import dataclasses

    from app.prompt_store import ResolvedPrompt

    short = dataclasses.replace(
        ctx,
        prompts={
            "steps/_context.md": ResolvedPrompt(name="steps/_context.md", body="h\n", rev=1),
        },
    )
    with pytest.raises(KeyError, match="1-read_story"):
        claude.build_message(short)


# --- the writes actually land ---------------------------------------------
#
# Two sessions, deliberately: a flush is visible to the session that made it,
# so a single-session test cannot tell a committed row from one that will be
# discarded when the request ends. `app.db.get_session` never commits and no
# route does either -- every write in this codebase commits in the module that
# performs it (repo.py's mutators, revisions.commit_revision) -- so that is
# where a prompt override has to commit too.
#
# Only `session_factory` here, never alongside the `session` fixture: the two
# together deadlock on teardown's TRUNCATE.

def test_an_override_survives_the_session_that_saved_it(session_factory):
    """The bug a shared-session test cannot see: a PUT that answers 200 and
    then throws the row away."""
    with session_factory() as writer:
        saved = prompt_store.save_override(writer, "steps/5-heal.md", "mine\n")
        assert saved.rev == 2

    with session_factory() as reader:
        assert prompt_store.resolve(reader, "steps/5-heal.md").body == "mine\n"


def test_the_prompts_page_does_not_write(session_factory):
    """A GET that seeds would be a write with no transaction to commit it, and
    a side effect nobody asked for. The page reports what *would* resolve."""

    with session_factory() as s:
        shown = apphub.read_prompts(s)
        assert {p["rev"] for p in shown} == {prompt_store.SEED_REV}
        assert len(shown) == len(prompt_store.shipped_defaults())

    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(Prompt)) == 0


def test_a_run_started_concurrently_with_another_still_seeds_once(session_factory):
    """Two first runs for one tenant race to insert the same rev-1 rows.

    They are not serialised by the per-target lock -- two different targets of
    one tenant take different lock rows -- so the loser of the unique index
    must recover by reading the winner's row, not fail the run."""

    with session_factory() as a, session_factory() as b:
        first = prompt_store.resolve_all(a)
        a.commit()
        # `b` began before `a` committed and has already missed the rows.
        second = prompt_store.resolve_all(b)
        b.commit()

    assert set(first) == set(second)
    assert {p.rev for p in second.values()} == {prompt_store.SEED_REV}

    with session_factory() as s:
        rows = s.scalar(select(func.count()).select_from(Prompt))
        assert rows == len(prompt_store.shipped_defaults()), "seeded twice"


# --- the history read surface (#39) ---------------------------------------
#
# P5-06 built the versioning and the run recording; the "see what changed and
# when" half of #30's story 24 had no surface. `history` existed, was called by
# nothing outside these tests, and dropped `created_at` on the floor -- so even
# a caller that wanted a timestamp could not get one through the type.


def test_a_revision_carries_when_it_was_saved(session):
    """The missing half of "what changed **and when**".

    `PromptRevision` rather than a widened `ResolvedPrompt`: only one of the
    two is ever sent to an agent, and a resolved prompt carrying a timestamp
    nothing renders invites a caller to pass a historical revision where the
    runner expects the live one.
    """
    prompt_store.save_override(session, "qa_system_prompt.md", "mine\n")

    history = prompt_store.history(session, "qa_system_prompt.md")

    assert [r.rev for r in history] == [prompt_store.SEED_REV, 2]
    assert all(r.created_at is not None for r in history)
    # Oldest first, and time agrees with the revision order -- the two are
    # independent facts about the row and a page sorted by one while labelled
    # by the other would be quietly wrong.
    assert history[0].created_at <= history[1].created_at


def test_a_prompt_with_no_overrides_reports_its_seeded_default(session):
    """#39's fourth acceptance criterion, and the one with a trap in it.

    A tenant that has never overridden this prompt has no rows at all, so the
    obvious implementation answers an empty tuple -- a page that says "no
    history" about a prompt that demonstrably has a current body. It reports
    the shipped default instead, the same bytes `current_all` shows, **without
    writing a row**: this is a GET's read path, and seeding here would make a
    page load a write with no transaction to commit it (the bug `read_prompts`
    exists to avoid).
    """
    before = session.query(Prompt).count()

    history = prompt_store.history(session, "steps/3-explore.md")

    assert [r.rev for r in history] == [prompt_store.SEED_REV]
    assert history[0].body == prompt_store.shipped_defaults()["steps/3-explore.md"]
    assert session.query(Prompt).count() == before, "a read seeded a row"


def test_an_unseeded_default_has_no_timestamp_rather_than_a_pretended_one(session):
    """It is not a row yet, so there is no "when" to report.

    `None` rather than "now": a shipped default's timestamp would otherwise
    change on every page load, and the one question this surface exists to
    answer is when something changed. The portal renders it as the release
    rather than a date.
    """
    history = prompt_store.history(session, "steps/3-explore.md")

    assert history[0].created_at is None


def test_an_unknown_prompt_name_is_not_found(session):
    """The same answer `resolve` gives, for the same reason: the name is wrong
    and the client can fix it. An empty history would read as "this prompt has
    never been edited", which is a different and wrong statement."""
    with pytest.raises(prompt_store.PromptNotFound):
        prompt_store.history(session, "steps/no-such-prompt.md")


def test_one_tenants_history_is_invisible_to_another(session):
    """#39's third acceptance criterion. Inherited from `TenantOwned`, asserted
    because "inherited" is exactly the kind of claim that stops being true."""
    session.add(Tenant(id=78, slug="third", name="Third"))
    session.commit()

    with tenant_scope(DEFAULT_TENANT_ID):
        prompt_store.save_override(session, "qa_system_prompt.md", "tenant one\n")

    with tenant_scope(78):
        theirs = prompt_store.history(session, "qa_system_prompt.md")

    # The other tenant sees the shipped default and nothing of the override.
    assert [r.rev for r in theirs] == [prompt_store.SEED_REV]
    assert all("tenant one" not in r.body for r in theirs)
