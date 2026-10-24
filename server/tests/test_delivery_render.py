"""Pure tests for the naming contract the delivery tools derive everything from.

No Postgres, no network: these run offline alongside the domain tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.delivery import errors, render


def test_infra_files_is_the_single_canonical_list():
    """app.json and the seed have left it: config is never delivered, and the
    seed is tracked tree content that arrives with the revision."""
    assert render.infra_files() == (
        "package.json",
        "package-lock.json",
        "playwright.config.ts",
        ".gitignore",
        ".github/workflows/playwright.yml",
    )


# --- delivery coordinates come from the row, not from a file --------------
#
# `resolve_target` read apps/<app>/app.json and refused an empty or placeholder
# target repo at read time. P3 moved both halves: the values come from the
# `targets` row through delivery's `Tools`, and the refusal happens on the write
# path (app/target_config.py), where the operator who typed it is still around.

def test_target_ref_is_a_projection_of_the_rows_configuration():
    from app.target_config import TargetConfig

    ref = render.target_ref(
        TargetConfig(
            app="saucedemo",
            name="SauceDemo",
            base_url="https://www.saucedemo.com",
            locators="data-test",
            agent_notes=(),
            target_repo="owner/tests",
            target_branch="trunk",
        )
    )
    assert (ref.app, ref.repo, ref.branch) == ("saucedemo", "owner/tests", "trunk")


def test_delivery_no_longer_reads_a_configuration_file():
    """Structural: no module under app/delivery names app.json as a path.

    Prose about the file it replaced is fine and useful; a string literal would
    mean something still goes looking for it.
    """
    from pathlib import Path as _Path

    from app import delivery as delivery_pkg

    for module in _Path(delivery_pkg.__file__).parent.rglob("*.py"):
        text = module.read_text()
        assert '"app.json"' not in text, module.name
        assert "'app.json'" not in text, module.name


# --- story resolution: a query over a path set, not a glob ----------------
#
# P3 made every derived path worktree-relative and the matching a query against
# the paths the tree holds -- `file_index` for delivery, a scan for a run. The
# "exactly one match or error" rule is unchanged.

def _worktree(tmp_path, *names: str) -> Path:
    root = tmp_path / "wt"
    (root / "user-stories").mkdir(parents=True)
    for name in names:
        (root / "user-stories" / name).write_text(
            "# User Story: SCRUM-101 - E-commerce Checkout Process\n"
        )
    return root


def _paths(root: Path) -> list[str]:
    return [p for p, _on_disk in render.tracked_tree(root)]


def test_resolve_story_derives_every_delivered_path(tmp_path):
    root = _worktree(tmp_path, "SCRUM-101-checkout.md")

    story = render.resolve_story(root, "SCRUM-101", paths=_paths(root))

    assert story.slug == "checkout"
    assert story.title == "E-commerce Checkout Process"
    assert story.branch == "qa/SCRUM-101-checkout"
    assert story.pr_title == "SCRUM-101: E-commerce Checkout Process E2E test suite"
    assert story.story_rel == "user-stories/SCRUM-101-checkout.md"
    assert story.plan_rel == "specs/SCRUM-101-checkout-test-plan.md"
    assert story.tests_rel == "tests/checkout"
    assert story.seed_rel == "seed.spec.ts"


def test_resolve_story_rejects_a_missing_story(tmp_path):
    root = _worktree(tmp_path, "SCRUM-101-checkout.md")
    with pytest.raises(errors.DeliveryError, match="exactly one"):
        render.resolve_story(root, "SCRUM-999", paths=_paths(root))


def test_two_files_for_one_story_is_a_hard_error(tmp_path):
    """Picking either is worse than stopping: nobody would know which suite was
    delivered."""
    root = _worktree(tmp_path, "SCRUM-101-checkout.md", "SCRUM-101-checkout-v2.md")
    with pytest.raises(errors.DeliveryError, match="exactly one"):
        render.resolve_story(root, "SCRUM-101", paths=_paths(root))


def test_resolve_story_requires_a_story_id(tmp_path):
    root = _worktree(tmp_path, "SCRUM-101-checkout.md")
    with pytest.raises(errors.DeliveryError):
        render.resolve_story(root, "", paths=_paths(root))


def test_the_path_set_is_what_decides_not_the_filesystem(tmp_path):
    """Delivery passes `file_index`, a run passes a scan. A file on disk that
    the tree does not name is not a match."""
    root = _worktree(tmp_path, "SCRUM-101-checkout.md")
    (root / "user-stories" / "SCRUM-101-stray.md").write_text("# stray\n")

    story = render.resolve_story(
        root, "SCRUM-101", paths=["user-stories/SCRUM-101-checkout.md"]
    )
    assert story.slug == "checkout"


def test_story_title_falls_back_to_the_slug(tmp_path):
    """A story whose heading carries no "- title" still delivers."""
    root = tmp_path / "wt"
    (root / "user-stories").mkdir(parents=True)
    (root / "user-stories" / "SCRUM-1-plain.md").write_text("# Heading\n")

    story = render.resolve_story(root, "SCRUM-1", paths=_paths(root))
    assert story.title == "Heading"
    assert story.slug == "plain"


def test_commit_and_pr_body_carry_the_run_id(tmp_path):
    root = _worktree(tmp_path, "SCRUM-101-checkout.md")
    story = render.resolve_story(root, "SCRUM-101", paths=_paths(root))
    message = render.commit_message(story, run_id="run-7")
    assert "Run-ID: run-7" in message
    assert message.startswith("feat(tests): SCRUM-101 ")
    assert "Resolves SCRUM-101" in message
    assert "Run-ID: run-7" in render.pr_body(story, "run-7")
    assert "Run-ID" not in render.pr_body(story, None)
