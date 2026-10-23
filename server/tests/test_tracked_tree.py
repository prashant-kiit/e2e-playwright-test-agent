"""The tracked-tree contract: what a revision versions, and where it is on disk.

This lives with the delivery path contract (render.py) deliberately -- delivery
and snapshotting must not drift about what the product versions. No Postgres and
no blob store here: the enumeration is a filesystem walk and a mapping, so these
run offline alongside the other pure tests.
"""

from __future__ import annotations

from pathlib import Path

from app.delivery import render
from tests.delivery_helpers import make_workspace


def _tracked(workspace: Path, app: str = "demo") -> dict[str, Path]:
    return dict(render.tracked_tree(app))


def test_the_tracked_tree_is_the_stories_plans_seed_suite_and_infra(tmp_path, monkeypatch):
    workspace = make_workspace(tmp_path, app="demo")
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))

    assert set(_tracked(workspace)) == {
        # The five repo-level infra files that define a runnable target repo...
        "package.json",
        "package-lock.json",
        "playwright.config.ts",
        ".gitignore",
        ".github/workflows/playwright.yml",
        # ...and the app's own tree.
        "seed.spec.ts",
        "user-stories/SCRUM-1-checkout.md",
        "specs/SCRUM-1-checkout-test-plan.md",
        "tests/checkout/cart.spec.ts",
        "tests/checkout/pay.spec.ts",
    }


def test_paths_are_target_relative_not_repo_root_relative(tmp_path, monkeypatch):
    """The shape P3's hydrate builds, so flipping reads needs no path migration."""
    workspace = make_workspace(tmp_path, app="demo")
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))

    tracked = _tracked(workspace)
    assert "seed.spec.ts" in tracked
    assert not any(p.startswith("apps/") for p in tracked)


def test_config_reports_and_run_artifacts_are_not_tracked(tmp_path, monkeypatch):
    """app.json is SaaS-internal config; reports/ is run output; the rest are
    artifacts (DESIGN.md §4)."""
    workspace = make_workspace(tmp_path, app="demo")
    app_dir = workspace / "apps" / "demo"
    (app_dir / "reports" / "evidence").mkdir(parents=True)
    (app_dir / "reports" / "SCRUM-1-test-report.md").write_text("# report\n")
    (app_dir / "reports" / "evidence" / "shot.png").write_bytes(b"png")
    (app_dir / "session.jsonl").write_text('{"x":1}\n')
    (app_dir / "node_modules" / "pkg").mkdir(parents=True)
    (app_dir / "node_modules" / "pkg" / "index.js").write_text("//\n")
    (app_dir / "test-results").mkdir()
    (app_dir / "test-results" / "trace.zip").write_bytes(b"zip")
    (app_dir / "playwright-report").mkdir()
    (app_dir / "playwright-report" / "index.html").write_text("<html>")
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))

    tracked = set(_tracked(workspace))
    assert "app.json" not in tracked
    assert not any(p.startswith("reports/") for p in tracked)
    assert not any(p.startswith("node_modules/") for p in tracked)
    assert not any(p.startswith("test-results/") for p in tracked)
    assert not any(p.startswith("playwright-report/") for p in tracked)
    assert "session.jsonl" not in tracked


def test_each_tracked_path_maps_back_to_its_file_on_disk(tmp_path, monkeypatch):
    """One mapping function -- the one P3's hydrate needs, run backwards."""
    workspace = make_workspace(tmp_path, app="demo")
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))

    for path, on_disk in render.tracked_tree("demo"):
        assert on_disk == render.tracked_path_on_disk("demo", path)
        assert on_disk.is_file()

    # Infra lives at the repo root; app content under apps/<app>/.
    assert render.tracked_path_on_disk("demo", "package.json") == workspace / "package.json"
    assert (
        render.tracked_path_on_disk("demo", "tests/checkout/cart.spec.ts")
        == workspace / "apps" / "demo" / "tests" / "checkout" / "cart.spec.ts"
    )


def test_the_infra_files_are_logically_per_target(tmp_path, monkeypatch):
    """Shared on disk, but each target's revision includes its own copy --
    content addressing makes the duplication free."""
    workspace = make_workspace(tmp_path, app="one")
    (workspace / "apps" / "two" / "user-stories").mkdir(parents=True)
    (workspace / "apps" / "two" / "seed.spec.ts").write_text("// seed\n")
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))

    for app in ("one", "two"):
        tracked = dict(render.tracked_tree(app))
        assert "package.json" in tracked
        assert tracked["package.json"] == workspace / "package.json"


def test_a_target_with_no_app_folder_tracks_only_the_infra_files(tmp_path, monkeypatch):
    workspace = make_workspace(tmp_path, app="demo")
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))

    tracked = set(_tracked(workspace, app="never-created"))
    assert tracked == set(render.INFRA_COMMON)


def test_a_missing_infra_file_is_skipped_not_an_error(tmp_path, monkeypatch):
    """The tracked tree describes what is there. A target repo missing its
    workflow file is a bootstrap problem, not a snapshot failure."""
    workspace = make_workspace(tmp_path, app="demo")
    (workspace / ".github" / "workflows" / "playwright.yml").unlink()
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))

    tracked = set(_tracked(workspace))
    assert ".github/workflows/playwright.yml" not in tracked
    assert "package.json" in tracked


def test_the_enumeration_is_sorted_and_stable(tmp_path, monkeypatch):
    workspace = make_workspace(tmp_path, app="demo")
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))

    paths = [p for p, _ in render.tracked_tree("demo")]
    assert paths == sorted(paths)
    assert paths == [p for p, _ in render.tracked_tree("demo")]
