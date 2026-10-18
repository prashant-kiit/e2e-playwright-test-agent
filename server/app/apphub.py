"""Read/write the file-owned config: apps/<app>/ (app.json, stories, seed) and
prompts/. Files remain the source of truth for config; this module lets the
portal read them and bootstrap a new target app.

Bootstrapping writes apps/<app>/app.json + seed.spec.ts from a form, then runs
scripts/bootstrap-target.sh. The shell step is injectable so tests don't need
gh/git or a real target repo.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from . import config

_HEADING = re.compile(r"#\s*(?:User Story:\s*)?([A-Za-z]+-\d+)\s*[-–]\s*(.+)")
_APP_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# Story file names are "<ID>-<slug>", where the ID itself contains a hyphen
# (e.g. SCRUM-201-auth -> id "SCRUM-201", slug "auth").
_STORY_FILE = re.compile(r"^([A-Za-z]+-\d+)-(.+)$")

_SEED_TEMPLATE = """import { test, expect } from '@playwright/test';

test.describe('Seed', () => {
  test('seed', async ({ page }) => {
    // Bring the app to the state every agent session starts from.
    // Use relative URLs: baseURL comes from this app's app.json.
    await page.goto('/');
    await expect(page).toHaveURL(/.*/);
  });
});
"""


def apps_dir() -> Path:
    return config.repo_root() / "apps"


def list_apps() -> list[dict]:
    out: list[dict] = []
    d = apps_dir()
    if not d.exists():
        return out
    for sub in sorted(d.iterdir()):
        if not sub.is_dir() or sub.name.startswith("_"):
            continue
        aj = sub / "app.json"
        if not aj.exists():
            continue
        try:
            data = json.loads(aj.read_text())
        except json.JSONDecodeError:
            data = {}
        repo = data.get("targetRepo") or ""
        out.append(
            {
                "app": sub.name,
                "name": data.get("name") or sub.name,
                "baseURL": data.get("baseURL") or "",
                "targetRepo": repo,
                "targetBranch": data.get("targetBranch") or "master",
                "repoUrl": f"https://github.com/{repo}" if "/" in repo else None,
                "storyCount": len(list((sub / "user-stories").glob("*.md")))
                if (sub / "user-stories").exists()
                else 0,
            }
        )
    return out


def list_stories(app: str) -> list[dict]:
    sd = apps_dir() / app / "user-stories"
    if not sd.exists():
        return []
    out: list[dict] = []
    for f in sorted(sd.glob("*.md")):
        m = _STORY_FILE.match(f.stem)
        story_id, slug = (m.group(1), m.group(2)) if m else (f.stem, "")
        title = _first_title(f) or f.stem
        out.append({"story_id": story_id, "slug": slug, "title": title, "file": f.name})
    return out


def _first_title(path: Path) -> str | None:
    for line in path.read_text().splitlines():
        if line.startswith("#"):
            m = _HEADING.match(line)
            return m.group(2).strip() if m else line.lstrip("# ").strip()
    return None


def read_prompts() -> list[dict]:
    root = config.repo_root() / "prompts"
    files: list[Path] = []
    for name in ("qa_system_prompt.md", "qa_user_prompt.md"):
        p = root / name
        if p.exists():
            files.append(p)
    steps = root / "steps"
    if steps.exists():
        files.extend(sorted(steps.glob("*.md")))
    return [
        {"name": p.relative_to(root).as_posix(), "content": p.read_text()} for p in files
    ]


def settings() -> dict:
    return {
        "runner": config.runner_kind(),
        "fake_delay": config.fake_delay(),
        "repo_root": str(config.repo_root()),
        "runs_dir": str(config.runs_dir()),
        "model": os.environ.get("ANTHROPIC_MODEL") or os.environ.get("CLAUDE_MODEL") or "default",
        "anthropic_api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


class BootstrapError(Exception):
    pass


def run_bootstrap_script(app: str) -> dict:
    """Run scripts/bootstrap-target.sh <app> from the repo root."""
    proc = subprocess.run(
        ["./scripts/bootstrap-target.sh", app],
        cwd=str(config.repo_root()),
        capture_output=True,
        text=True,
    )
    return {"rc": proc.returncode, "output": (proc.stdout + proc.stderr).strip()}


def bootstrap_app(data: dict, run=run_bootstrap_script, do_bootstrap: bool = True) -> dict:
    """Create apps/<app>/ from a form and (optionally) run the bootstrap script."""
    app = (data.get("app") or "").strip()
    if not _APP_NAME.match(app):
        raise BootstrapError("app folder must be lower-case letters, digits or hyphens")
    target = apps_dir() / app
    if target.exists():
        raise BootstrapError(f"app '{app}' already exists")

    (target / "user-stories").mkdir(parents=True)
    app_json = {
        "name": data.get("name") or app,
        "baseURL": data.get("baseURL") or "",
        "targetRepo": data.get("targetRepo") or "",
        "targetBranch": data.get("targetBranch") or "master",
        "locators": data.get("locators") or "",
        "agentNotes": data.get("agentNotes") or [],
    }
    (target / "app.json").write_text(json.dumps(app_json, indent=2) + "\n")
    (target / "seed.spec.ts").write_text(_SEED_TEMPLATE)

    result = run(app) if do_bootstrap else None
    return {"app": app, "created": True, "bootstrap": result}
