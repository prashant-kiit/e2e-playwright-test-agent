"""Infra entries carry a source and a destination (DESIGN.md decision 23).

A source is either a file under the delivery templates directory or a
**renderer** -- a function of the target's configuration. The destination is the
path in the hydrated worktree and in the customer's repo. Delivered bytes at
delivered paths are unchanged by the split; what changes is that a template's
location in *our* repo no longer dictates where it lands in theirs.

That is what lets the Playwright workflow move. At `.github/workflows/` it is a
live workflow of this repository, so a push to master made this repo install
browsers and run customers' suites against live external sites. It is a template
now, with its `on:` triggers intact -- neutering them in a harness-side copy
instead would leave the delivered copy inheriting a dead trigger, which is the
exact failure the move prevents.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.delivery import render
from app.target_config import TargetConfig

REPO_ROOT = Path(__file__).resolve().parents[2]


def _config(**overrides) -> TargetConfig:
    return TargetConfig(
        **{
            "app": "demo",
            "name": "Demo",
            "base_url": "https://demo.example.com",
            "locators": "data-testid",
            "agent_notes": (),
            "target_repo": "o/r",
            "target_branch": "master",
            **overrides,
        }
    )


# --- the (source, destination) split -------------------------------------

def test_every_infra_entry_carries_a_source_and_a_destination():
    for entry in render.INFRA_ENTRIES:
        assert entry.destination
        assert entry.template is not None or entry.renderer is not None, entry.destination


def test_the_destinations_are_the_paths_delivery_has_always_used():
    assert render.INFRA_DESTINATIONS == (
        "package.json",
        "package-lock.json",
        "playwright.config.ts",
        ".gitignore",
        ".github/workflows/playwright.yml",
    )


def test_a_sources_location_differs_from_its_destination():
    """The whole point of the split: the workflow's source is not a path GitHub
    Actions treats as a live workflow of this repo."""
    workflow = render.infra_entry(".github/workflows/playwright.yml")
    assert workflow.template == "workflows/playwright.yml"
    assert ".github" not in workflow.template


def test_a_source_may_be_a_renderer():
    generated = render.infra_entry("playwright.config.ts")
    assert generated.renderer is not None
    assert generated.template is None
    assert render.GENERATED_DESTINATIONS == ("playwright.config.ts",)


def test_every_template_source_exists_in_the_package():
    for entry in render.INFRA_ENTRIES:
        if entry.template is not None:
            assert (render.TEMPLATES_DIR / entry.template).is_file(), entry.template


def test_the_entries_land_at_their_destination_paths(tmp_path):
    render.write_infra(tmp_path, _config())

    for destination in render.INFRA_DESTINATIONS:
        assert (tmp_path / destination).is_file(), destination


def test_a_template_entry_is_delivered_byte_identically(tmp_path):
    render.write_infra(tmp_path, _config())

    for entry in render.INFRA_ENTRIES:
        if entry.template is not None:
            assert (tmp_path / entry.destination).read_bytes() == (
                render.TEMPLATES_DIR / entry.template
            ).read_bytes()


# --- the workflow has moved, triggers intact ------------------------------

def test_the_workflow_template_keeps_its_triggers():
    text = (render.TEMPLATES_DIR / "workflows" / "playwright.yml").read_text()
    assert "on:" in text
    assert "push:" in text
    assert "pull_request:" in text
    assert "branches: [ main, master ]" in text
    assert "npx playwright test" in text


def test_the_playwright_workflow_is_no_longer_a_workflow_of_this_repository():
    """A push to master must not make this repo run a customer's suite."""
    assert not (REPO_ROOT / ".github" / "workflows" / "playwright.yml").exists()
    live = {p.name for p in (REPO_ROOT / ".github" / "workflows").glob("*.yml")}
    assert live == {"ci.yml"}, f"unexpected live workflow(s): {live - {'ci.yml'}}"


def test_the_hand_maintained_root_playwright_config_is_gone():
    """It is generated from P3 onward; a checked-in copy would be a second
    author for the same file."""
    assert not (REPO_ROOT / "playwright.config.ts").exists()


# --- the generated Playwright config --------------------------------------

def test_the_generated_config_inlines_the_targets_base_url():
    text = render.render_playwright_config(_config(base_url="https://shop.example.com"))
    assert "https://shop.example.com" in text


def test_the_generated_config_declares_the_four_unprefixed_browser_projects():
    text = render.render_playwright_config(_config())
    for name in ("chromium", "firefox", "webkit", "mobile-chrome"):
        assert f"name: '{name}'" in text
    assert "demo-chromium" not in text


def test_two_different_target_rows_render_different_bytes():
    one = render.render_playwright_config(_config(base_url="https://one.example.com"))
    two = render.render_playwright_config(_config(base_url="https://two.example.com"))
    assert one != two


def test_the_same_target_row_renders_identical_bytes():
    """Hydrate renders it on every run; a second hydrate must be byte-identical
    or every run would commit a revision for the config alone."""
    assert render.render_playwright_config(_config()) == render.render_playwright_config(
        _config()
    )


def test_the_generated_config_sends_playwright_output_to_the_run_dir():
    """Run output goes to the run directory through QA_RUN_DIR, never into the
    worktree, which is the tree ingest commits."""
    text = render.render_playwright_config(_config())
    assert "QA_RUN_DIR" in text


def test_the_generated_config_says_not_to_edit_it():
    """Every hydrate overwrites it and ingest discards edits to it, so an agent
    that edits it has wasted its turn. Say so in the file."""
    text = render.render_playwright_config(_config())
    assert "generated" in text.lower()


@pytest.mark.parametrize(
    "hostile",
    [
        "https://a.example.com/x",
        "https://a.example.com/'+process.exit()+'",
        'https://a.example.com/"x',
        "https://a.example.com/x\\y",
    ],
)
def test_the_base_url_survives_as_a_string_literal_and_nothing_more(hostile):
    """The row is operator input rendered into TypeScript source that lands in a
    customer's repo, so it is escaped rather than interpolated. The literal must
    read back as exactly what was stored -- no more, and no code.
    """
    text = render.render_playwright_config(_config(base_url=hostile))
    literal = next(
        line for line in text.splitlines() if line.startswith("const baseURL = ")
    )
    assert json.loads(literal[len("const baseURL = ") :].rstrip(";")) == hostile
