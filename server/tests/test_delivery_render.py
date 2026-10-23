"""Pure tests for the naming contract the delivery tools derive everything from.

No Postgres, no network: these run offline alongside the domain tests.
"""

from __future__ import annotations

import pytest

from app.delivery import errors, render


def test_infra_files_is_the_single_canonical_list():
    files = render.infra_files("saucedemo")
    assert files == (
        "package.json",
        "package-lock.json",
        "playwright.config.ts",
        ".gitignore",
        ".github/workflows/playwright.yml",
        "apps/saucedemo/app.json",
        "apps/saucedemo/seed.spec.ts",
    )


def test_resolve_target_reads_app_json():
    target = render.resolve_target("practice-target")
    assert target.app == "practice-target"
    assert "/" in target.repo
    assert target.branch  # defaults to master when app.json omits it


def test_resolve_target_refuses_the_template_placeholder():
    with pytest.raises(errors.DeliveryError, match="targetRepo"):
        render.resolve_target("_template")


def test_resolve_target_rejects_an_unknown_app():
    with pytest.raises(errors.DeliveryError, match="no such app"):
        render.resolve_target("not-an-app")


def test_resolve_target_requires_an_app():
    with pytest.raises(errors.DeliveryError):
        render.resolve_target("")


def test_resolve_story_derives_every_delivered_path():
    story = render.resolve_story("saucedemo", "SCRUM-101")
    assert story.slug == "checkout"
    assert story.title == "E-commerce Checkout Process"
    assert story.branch == "qa/SCRUM-101-checkout"
    assert story.pr_title == "SCRUM-101: E-commerce Checkout Process E2E test suite"
    assert story.story_rel == "apps/saucedemo/user-stories/SCRUM-101-checkout.md"
    assert story.plan_rel == "apps/saucedemo/specs/SCRUM-101-checkout-test-plan.md"
    assert story.tests_rel == "apps/saucedemo/tests/checkout"


def test_resolve_story_rejects_a_missing_story():
    with pytest.raises(errors.DeliveryError, match="exactly one"):
        render.resolve_story("saucedemo", "SCRUM-999")


def test_resolve_story_requires_a_story_id():
    with pytest.raises(errors.DeliveryError):
        render.resolve_story("saucedemo", "")


def test_story_title_falls_back_to_the_slug(tmp_path, monkeypatch):
    """A story whose heading carries no "- title" still delivers."""
    app_dir = tmp_path / "apps" / "demo"
    (app_dir / "user-stories").mkdir(parents=True)
    (app_dir / "app.json").write_text('{"targetRepo": "o/r"}')
    (app_dir / "user-stories" / "SCRUM-1-plain.md").write_text("# Heading\n")
    monkeypatch.setenv("QA_REPO_ROOT", str(tmp_path))

    story = render.resolve_story("demo", "SCRUM-1")
    assert story.title == "Heading"
    assert story.slug == "plain"


def test_commit_and_pr_body_carry_the_run_id():
    story = render.resolve_story("saucedemo", "SCRUM-101")
    message = render.commit_message(story, run_id="run-7")
    assert "Run-ID: run-7" in message
    assert message.startswith("feat(tests): SCRUM-101 ")
    assert "Resolves SCRUM-101" in message
    assert "Run-ID: run-7" in render.pr_body(story, "run-7")
    assert "Run-ID" not in render.pr_body(story, None)
