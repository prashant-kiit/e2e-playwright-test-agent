"""M6: repo/file introspection and bootstrap (no DB, no gh)."""

import json

import pytest

from app import apphub


@pytest.fixture()
def repo_root(tmp_path, monkeypatch):
    monkeypatch.setenv("QA_REPO_ROOT", str(tmp_path))
    (tmp_path / "apps").mkdir()
    (tmp_path / "prompts" / "steps").mkdir(parents=True)
    return tmp_path


def _make_app(root, app, repo="owner/repo", stories=()):
    d = root / "apps" / app
    (d / "user-stories").mkdir(parents=True)
    (d / "app.json").write_text(
        json.dumps({"name": app.title(), "baseURL": "https://x", "targetRepo": repo})
    )
    for sid, title in stories:
        (d / "user-stories" / f"{sid}-slug.md").write_text(f"# User Story: {sid} - {title}\n")


def test_list_apps_skips_template_and_counts_stories(repo_root):
    _make_app(repo_root, "foo", stories=[("SCRUM-1", "Login")])
    (repo_root / "apps" / "_template").mkdir()  # must be skipped
    apps = apphub.list_apps()
    assert [a["app"] for a in apps] == ["foo"]
    assert apps[0]["repoUrl"] == "https://github.com/owner/repo"
    assert apps[0]["storyCount"] == 1


def test_list_apps_null_repo_url_when_unset(repo_root):
    _make_app(repo_root, "foo", repo="")
    assert apphub.list_apps()[0]["repoUrl"] is None


def test_list_stories_parses_id_and_title(repo_root):
    _make_app(repo_root, "foo", stories=[("SCRUM-201", "Authentication and Dashboard")])
    s = apphub.list_stories("foo")
    assert s[0]["story_id"] == "SCRUM-201"
    assert s[0]["title"] == "Authentication and Dashboard"


def test_read_prompts(repo_root):
    (repo_root / "prompts" / "qa_system_prompt.md").write_text("# system")
    (repo_root / "prompts" / "steps" / "1-read_story.md").write_text("step1")
    names = [p["name"] for p in apphub.read_prompts()]
    assert "qa_system_prompt.md" in names
    assert "steps/1-read_story.md" in names


def test_bootstrap_writes_files_and_runs_script(repo_root):
    calls = []

    def fake(app):
        calls.append(app)
        return {"rc": 0, "output": "bootstrapped"}

    res = apphub.bootstrap_app(
        {"app": "newapp", "name": "New", "baseURL": "https://n", "targetRepo": "o/r"},
        run=fake,
    )
    assert calls == ["newapp"]
    d = repo_root / "apps" / "newapp"
    assert (d / "app.json").exists() and (d / "seed.spec.ts").exists()
    assert json.loads((d / "app.json").read_text())["targetRepo"] == "o/r"
    assert res["bootstrap"] == {"rc": 0, "output": "bootstrapped"}


def test_bootstrap_can_skip_the_script(repo_root):
    res = apphub.bootstrap_app({"app": "n2", "name": "N"}, do_bootstrap=False)
    assert res["bootstrap"] is None


def test_bootstrap_rejects_bad_name(repo_root):
    with pytest.raises(apphub.BootstrapError):
        apphub.bootstrap_app({"app": "Bad Name"}, do_bootstrap=False)


def test_bootstrap_rejects_existing_app(repo_root):
    _make_app(repo_root, "foo")
    with pytest.raises(apphub.BootstrapError):
        apphub.bootstrap_app({"app": "foo", "name": "x"}, do_bootstrap=False)
