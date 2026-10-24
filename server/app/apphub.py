"""Read/write the file-owned config: apps/<app>/ (app.json, stories, seed) and
prompts/. Files remain the source of truth for config; this module lets the
portal read them and bootstrap a new target app.

Bootstrapping writes apps/<app>/app.json + seed.spec.ts from a form, then calls
app/delivery to sync the infra to the target repo. The target-repo step is
injectable so tests need neither git nor a real repo.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from . import config
from .delivery.render import APP_NAME as _APP_NAME
from .delivery.render import HEADING as _HEADING
from .delivery.render import STORY_FILE as _STORY_FILE
from .orchestrator.claude import prompts_dir

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
    """Every prompt the agent can be given, for the portal's Prompts page.

    Read from package data (the same directory the runner reads), so what the
    portal shows is what the agent is actually sent. Prompts move into Postgres
    with tenant overrides in P5 (DESIGN.md §12).
    """
    root = prompts_dir()
    files: list[Path] = []
    overview = root / "qa_system_prompt.md"
    if overview.exists():
        files.append(overview)
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


@dataclass(frozen=True)
class BootstrapOutcome:
    """The portal-facing result of the target-repo bootstrap step.

    This replaces the shell-shaped {"rc": int, "output": str} the step returned
    while it was still a script: `ok` is the outcome, `output` is the text the
    form shows. A DeliveryError is an outcome, not a server error, so the form
    can report a failed bootstrap next to the app it did create.
    """

    ok: bool
    output: str


def run_bootstrap(app: str, *, tools=None) -> BootstrapOutcome:
    """Bootstrap the app's target repo through app/delivery (was a shell script).

    `tools` is the delivery seam (GitHub client + git + token + workspace); left
    unset it is built from the environment. Tests pass one backed by a bare repo
    on disk, so this needs neither network nor credentials.
    """
    from .delivery import DeliveryError, bootstrap_target

    try:
        result = bootstrap_target(app, tools=tools)
    except DeliveryError as exc:
        return BootstrapOutcome(ok=False, output=str(exc))
    lines = [
        f"App:    {result.app}",
        f"Target: {result.repo} ({result.branch})",
        *([result.changes.strip()] if result.changes.strip() else []),
        result.message,
    ]
    return BootstrapOutcome(ok=True, output="\n".join(lines))


def bootstrap_app(data: dict, run=run_bootstrap, do_bootstrap: bool = True) -> dict:
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
