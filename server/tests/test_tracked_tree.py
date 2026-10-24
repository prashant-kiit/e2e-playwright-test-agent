"""The tracked-tree contract: what a revision versions, inside a worktree root.

One definition, shared by hydrate, ingest and delivery, so the three cannot
disagree about what the product versions. P3 made it root-relative: the
enumeration takes a worktree root and returns target-relative paths, because the
on-disk shape and the stored shape are now the same shape. The apps/<app/>
mapping function is gone -- this is why P2 stored target-relative paths.

This lives with the delivery path contract (render.py) deliberately. No Postgres
and no blob store here: the enumeration is a filesystem walk, so these run
offline alongside the other pure tests.
"""

from __future__ import annotations

from pathlib import Path

from app.delivery import render
from tests.delivery_helpers import make_worktree


def _tracked(root: Path) -> dict[str, Path]:
    return dict(render.tracked_tree(root))


def test_the_tracked_tree_is_the_stories_plans_seed_suite_and_infra(tmp_path):
    root = make_worktree(tmp_path / "wt")

    assert set(_tracked(root)) == {
        # The five infra files that define a runnable target repo...
        "package.json",
        "package-lock.json",
        "playwright.config.ts",
        ".gitignore",
        ".github/workflows/playwright.yml",
        # ...and the target's own tree.
        "seed.spec.ts",
        "user-stories/SCRUM-1-checkout.md",
        "specs/SCRUM-1-checkout-test-plan.md",
        "tests/checkout/cart.spec.ts",
        "tests/checkout/pay.spec.ts",
    }


def test_every_tracked_path_is_relative_to_the_worktree_root(tmp_path):
    root = make_worktree(tmp_path / "wt")

    for path, on_disk in render.tracked_tree(root):
        assert on_disk == root / path
        assert on_disk.is_file()
    assert not any(p.startswith("apps/") for p in _tracked(root))


def test_the_enumeration_takes_a_root_and_nothing_else(tmp_path):
    """Two worktrees of the same shape enumerate the same paths: the walk knows
    nothing about which target it is looking at."""
    one = make_worktree(tmp_path / "one")
    two = make_worktree(tmp_path / "two")
    assert set(_tracked(one)) == set(_tracked(two))


def test_reports_and_run_artifacts_are_not_tracked(tmp_path):
    """reports/ is run output; the rest are artifacts (DESIGN.md §4). app.json
    has left the exclusion list by ceasing to exist."""
    root = make_worktree(tmp_path / "wt")
    (root / "reports" / "evidence").mkdir(parents=True)
    (root / "reports" / "SCRUM-1-test-report.md").write_text("# report\n")
    (root / "reports" / "evidence" / "shot.png").write_bytes(b"png")
    (root / "session.jsonl").write_text('{"x":1}\n')
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "index.js").write_text("//\n")
    (root / "test-results").mkdir()
    (root / "test-results" / "trace.zip").write_bytes(b"zip")
    (root / "playwright-report").mkdir()
    (root / "playwright-report" / "index.html").write_text("<html>")

    tracked = set(_tracked(root))
    assert not any(p.startswith("reports/") for p in tracked)
    assert not any(p.startswith("node_modules/") for p in tracked)
    assert not any(p.startswith("test-results/") for p in tracked)
    assert not any(p.startswith("playwright-report/") for p in tracked)
    assert "session.jsonl" not in tracked


def test_a_missing_infra_file_is_skipped_not_an_error(tmp_path):
    """The tracked tree describes what is there. A worktree missing its workflow
    file is a hydrate problem, not a snapshot failure."""
    root = make_worktree(tmp_path / "wt")
    (root / ".github" / "workflows" / "playwright.yml").unlink()

    tracked = set(_tracked(root))
    assert ".github/workflows/playwright.yml" not in tracked
    assert "package.json" in tracked


def test_a_worktree_with_only_infra_tracks_only_the_infra_files(tmp_path):
    root = tmp_path / "bare"
    for rel in render.INFRA_DESTINATIONS:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n")

    assert set(_tracked(root)) == set(render.INFRA_DESTINATIONS)


def test_stories_and_plans_are_markdown_only(tmp_path):
    """The spec's table says `user-stories/*.md` and `specs/*.md`, not `**`.

    Walking those folders wholesale would version whatever else landed in them,
    and hydrate would write it back into the next worktree.
    """
    root = make_worktree(tmp_path / "wt")
    (root / "user-stories" / "notes.txt").write_text("scratch\n")
    (root / "specs" / "draft.docx").write_bytes(b"\x00binary")

    tracked = set(_tracked(root))
    assert "user-stories/notes.txt" not in tracked
    assert "specs/draft.docx" not in tracked
    assert "user-stories/SCRUM-1-checkout.md" in tracked
    assert "specs/SCRUM-1-checkout-test-plan.md" in tracked


def test_editor_and_os_junk_is_never_tracked(tmp_path):
    """artifacts.py skips .DS_Store for the same reason; a snapshot must too,
    or a stray file becomes versioned content hydrate writes back out."""
    root = make_worktree(tmp_path / "wt")
    tests_dir = root / "tests" / "checkout"
    (tests_dir / ".DS_Store").write_bytes(b"junk")
    (tests_dir / "cart.spec.ts~").write_text("// backup\n")
    (tests_dir / ".cart.spec.ts.swp").write_bytes(b"vim")

    tracked = set(_tracked(root))
    assert ".DS_Store" not in {p.rsplit("/", 1)[-1] for p in tracked}
    assert not any(p.endswith("~") for p in tracked)
    assert not any(p.endswith(".swp") for p in tracked)
    assert "tests/checkout/cart.spec.ts" in tracked


def test_a_nested_node_modules_inside_the_suite_is_excluded(tmp_path):
    root = make_worktree(tmp_path / "wt")
    nested = root / "tests" / "checkout" / "node_modules" / "p"
    nested.mkdir(parents=True)
    (nested / "index.js").write_text("//\n")

    assert not any("node_modules" in p for p in _tracked(root))


def test_the_enumeration_is_sorted_and_stable(tmp_path):
    root = make_worktree(tmp_path / "wt")

    paths = [p for p, _ in render.tracked_tree(root)]
    assert paths == sorted(paths)
    assert paths == [p for p, _ in render.tracked_tree(root)]
