"""The mount is gone, and this is what keeps it gone.

P3's third clause -- *"delete the repo mount"* -- is the one a later change can
undo by accident. A new module that needs "the templates" or "the prompts" and
reaches for a path relative to the checkout has reacquired a dependency on a
shared disk without anybody noticing, and the symptom shows up one phase later
as "why does the second replica behave differently?".

So these are structural tests over the source tree rather than behavioural ones.
They are the assertion the phase's contract half rests on.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import app as app_package

PACKAGE_DIR = Path(app_package.__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]

# Modules under the server package, excluding the Alembic revisions (which are
# a historical record and may legitimately mention what they migrated away from).
MODULES = sorted(PACKAGE_DIR.rglob("*.py"))


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def code_of(path: Path) -> str:
    """A module's code with its comments and docstrings removed.

    The checks below are about what the code *does*, not about what its prose
    says. Explaining in a docstring that `repo_root()` was deleted and why is
    exactly the comment a future reader needs; a call to it is the thing to
    catch. Parsing and unparsing drops comments, and the walk drops docstrings.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(ast.fix_missing_locations(tree))


def test_there_are_modules_to_check():
    """A pass because the glob found nothing would be the worst outcome."""
    assert len(MODULES) > 15


@pytest.mark.parametrize("module", MODULES, ids=_rel)
def test_no_module_references_a_repo_root_helper(module: Path):
    """`config.repo_root()` does not exist; nothing may reintroduce it."""
    assert "repo_root" not in code_of(module), (
        f"{_rel(module)} references a repo-root helper. A target's "
        f"configuration is a row, its tree is a revision, and the templates, "
        f"prompts and agent runtime are package data -- there is nothing left "
        f"that a repo root is the answer to."
    )


@pytest.mark.parametrize("module", MODULES, ids=_rel)
def test_no_module_reads_the_removed_environment_variable(module: Path):
    assert "QA_REPO_ROOT" not in code_of(module), _rel(module)


def test_the_config_module_offers_no_repo_root(monkeypatch):
    """Including via the environment: setting it must change nothing."""
    from app import config

    assert not hasattr(config, "repo_root")
    monkeypatch.setenv("QA_REPO_ROOT", "/somewhere/shared")
    assert "/somewhere/shared" not in str(config.runs_dir())
    assert "/somewhere/shared" not in str(config.worktrees_dir())


@pytest.mark.parametrize("module", MODULES, ids=_rel)
def test_no_module_names_the_deleted_apps_directory(module: Path):
    """`apps/<app>/` is deleted. A path string naming it is a read that cannot
    succeed, and a comment naming it as a live location is a lie."""
    code = code_of(module)
    for literal in ("'apps/", "'apps'"):
        assert literal not in code, f"{_rel(module)} names {literal}"


def test_parity_is_deleted_rather_than_left_passing_trivially():
    """Parity compared the database against an authoritative filesystem. With
    one copy of the truth left there is nothing to compare against, so keeping
    it would mean keeping a second copy for it to compare -- the thing the phase
    exists to remove. Its last act was gating the cutover."""
    assert not (PACKAGE_DIR / "parity.py").exists()
    assert not (PACKAGE_DIR.parent / "tests" / "test_parity.py").exists()
    from app import revisions

    assert not hasattr(revisions, "target_parity")


def test_the_cutover_is_deleted_with_the_parity_check_it_gated_on():
    """It read app.json under the repo root and refused to proceed unless parity
    was green. Both are gone, so it cannot run -- and it has run."""
    assert not (PACKAGE_DIR / "cutover.py").exists()
    assert not (PACKAGE_DIR / "monorepo.py").exists()


# --- what replaced the mount: package data --------------------------------

def test_the_prompts_resolve_from_package_data():
    from app.orchestrator.claude import prompts_dir

    prompts = prompts_dir()
    assert prompts.is_relative_to(PACKAGE_DIR)
    assert (prompts / "steps" / "_context.md").is_file()


def test_the_agent_runtime_resolves_from_package_data():
    from app.orchestrator.claude import runtime_dir

    runtime = runtime_dir()
    assert runtime.is_relative_to(PACKAGE_DIR)
    assert (runtime / "settings.json").is_file()
    assert (runtime / "mcp.json").is_file()
    assert list((runtime / "agents").glob("*.md"))
    assert (runtime / "hooks" / "close-test-browsers.sh").is_file()


def test_the_delivery_templates_resolve_from_package_data():
    from app.delivery.render import INFRA_ENTRIES, SEED_TEMPLATE, TEMPLATES_DIR

    assert TEMPLATES_DIR.is_relative_to(PACKAGE_DIR)
    assert (TEMPLATES_DIR / SEED_TEMPLATE).is_file()
    for entry in INFRA_ENTRIES:
        if entry.template is not None:
            assert (TEMPLATES_DIR / entry.template).is_file(), entry.template


def test_package_data_is_inside_the_installed_package(tmp_path, monkeypatch):
    """The point of "package data": it is found from the module, not from the
    working directory, so an API image with nothing mounted still finds it."""
    from app.delivery.render import TEMPLATES_DIR
    from app.orchestrator.claude import prompts_dir, runtime_dir

    monkeypatch.chdir(tmp_path)

    for path in (prompts_dir(), runtime_dir(), TEMPLATES_DIR):
        assert path.is_dir(), path


# --- the repo itself ------------------------------------------------------

def test_the_apps_directory_is_deleted_from_the_repository():
    """There is no unreferenced second copy of the truth left to rot."""
    assert not (REPO_ROOT / "apps").exists()


def test_no_app_json_exists_anywhere_in_the_repository():
    """Config is SaaS-internal and is never delivered."""
    found = [
        p for p in REPO_ROOT.rglob("app.json")
        if ".venv" not in p.parts and "node_modules" not in p.parts
    ]
    assert found == [], found


def test_the_hand_maintained_playwright_config_is_deleted():
    """It is generated from P3 onward; a checked-in copy would be a second
    author for a generated file."""
    assert not (REPO_ROOT / "playwright.config.ts").exists()


def test_the_compose_file_declares_no_workspace_mount():
    compose = (REPO_ROOT / "docker-compose.yml").read_text()
    assert "/workspace" not in compose
    assert "QA_REPO_ROOT" not in compose


def test_the_repository_runs_no_customers_suite_from_its_own_ci():
    """The delivered workflow is a template now. A push to master must not make
    this repo install browsers and run a customer's tests against live sites."""
    workflows = REPO_ROOT / ".github" / "workflows"
    assert {p.name for p in workflows.glob("*.yml")} == {"ci.yml"}
    assert "playwright test" not in (workflows / "ci.yml").read_text()
