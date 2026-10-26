"""The real Runner: shells out to the `claude` CLI, one step per invocation.

Mirrors the batch runner's proven invocation (`claude -p <prompt>
--output-format stream-json --verbose`, with QA_RUN_DIR/QA_WORKERS), but runs a
single step and carries the Claude Code session across steps with --resume, so
exploratory context (step 3) survives into generation (step 4). stdout is teed
to the run dir's session.jsonl and relayed line-by-line to the log bus.

Two things changed in P3 and both are about where things come from:

- **The working directory is the hydrated worktree** (`ctx.worktree`), built from
  the head revision before the pipeline started. The agent works there and
  nowhere else. Run output -- `session.jsonl`, Playwright's results -- still goes
  to the run directory through QA_RUN_DIR, which the generated config reads.
- **The prompts and the agent runtime ship with this package**, so an API image
  needs no mounted repo to run an agent, and nothing here resolves a path
  relative to a checkout.

The prompt is rendered from the target's row -- `baseURL`, `locators`,
`agentNotes` -- because `app.json` does not exist. Not exercised by the
automated tests end to end (that is the FakeRunner's job), but the two decisions
made before anything is spawned, the prompt text and the invocation, are plain
functions and are tested.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path

from ..delivery.render import StoryRef, resolve_story, tracked_tree
from ..domain.steps import Step
from .runner import Emit, StepContext, StepResult

STEP_FILE = {
    Step.READ_STORY: "1-read_story.md",
    Step.PLAN: "2-plan.md",
    Step.EXPLORE: "3-explore.md",
    Step.GENERATE: "4-generate.md",
    Step.HEAL: "5-heal.md",
}

# server/app/orchestrator/claude.py -> parents: [orchestrator, app, ...]
_PACKAGE_DIR = Path(__file__).resolve().parents[1]


def prompts_dir() -> Path:
    """The step prompts, shipped with the server package.

    Package data, not a path under a checkout: the whole point of P3 is that an
    API image can run an agent with nothing mounted. Prompts move into Postgres
    with tenant overrides in P5 (DESIGN.md §12); code-shipped is this phase.
    """
    return _PACKAGE_DIR / "prompts"


def runtime_dir() -> Path:
    """The agent's shipped Claude Code config: settings, MCP servers, subagents.

    Owned by the application, not the repo-root `.claude/`, which exists only
    for developing this harness.
    """
    return _PACKAGE_DIR / "agent_runtime"


def resolve_run_story(ctx: StepContext) -> StoryRef:
    """The story's worktree-relative paths, from the tree the run works in.

    The orchestrator already knows which story this is, so there is no globbing
    and no guessing: `ctx.story_id` plus the tracked paths of the hydrated tree
    give exactly one story file, or it is an error. The worktree holds exactly
    one target, which is also what makes a project name or a test path unable to
    reach another customer's tests.
    """
    paths = [path for path, _on_disk in tracked_tree(ctx.worktree)]
    return resolve_story(ctx.worktree, ctx.story_id, paths=paths)


def _agent_notes(notes: tuple[str, ...]) -> str:
    if not notes:
        return "(none recorded for this target)"
    return "\n".join(f"- {note}" for note in notes)


def build_message(ctx: StepContext) -> str:
    """The prompt for one step: the shared context header, then the step body.

    Every placeholder is substituted here. A prompt that reached the agent with
    a literal `{PLACEHOLDER}` in it would be a prompt the agent has to guess at,
    which in an unattended session means a wrong guess nobody sees.
    """
    steps = prompts_dir() / "steps"
    header = (steps / "_context.md").read_text()
    body = (steps / STEP_FILE[ctx.step]).read_text()
    text = f"{header}\n\n---\n\n{body}"

    story = resolve_run_story(ctx)
    cfg = ctx.target
    for token, value in {
        "{STORY_ID}": ctx.story_id,
        "{STORY_TITLE}": story.title,
        "{APP}": ctx.app,
        "{NAME}": cfg.name,
        "{MODE}": ctx.mode,
        "{RUN_KEY}": ctx.run_key,
        "{SLUG}": story.slug,
        "{STORY_FILE}": story.story_rel,
        "{PLAN_FILE}": story.plan_rel,
        "{TEST_DIR}": story.tests_rel,
        "{SEED}": story.seed_rel,
        "{BASE_URL}": cfg.base_url,
        "{LOCATORS}": cfg.locators or "(no convention recorded; prefer roles and test ids)",
        "{AGENT_NOTES}": _agent_notes(cfg.agent_notes),
        "{CHROMIUM_PROJECT}": cfg.chromium_project,
        "{TARGET_REPO}": cfg.target_repo,
        "{TARGET_BRANCH}": cfg.target_branch,
        "{BRANCH}": story.branch,
        "{PR_TITLE}": story.pr_title,
    }.items():
        text = text.replace(token, value)
    return text


def _agents_json() -> str:
    """Build the --agents payload from agent_runtime/agents/*.md.

    Passing subagents inline (rather than via a plugin) keeps their names bare
    (e.g. "playwright-test-planner"), matching how the step prompts invoke them;
    a plugin would namespace them as "<plugin>:<name>".
    """
    agents: dict[str, dict] = {}
    for path in sorted((runtime_dir() / "agents").glob("*.md")):
        text = path.read_text()
        meta, _, body = text.partition("---\n")[2].partition("\n---")
        fm: dict[str, str] = {}
        for line in meta.splitlines():
            key, sep, val = line.partition(":")
            if sep:
                fm[key.strip()] = val.strip()
        name = fm.get("name") or path.stem
        entry: dict = {"description": fm.get("description", ""), "prompt": body.strip()}
        if fm.get("tools"):
            entry["tools"] = [t.strip() for t in fm["tools"].split(",") if t.strip()]
        if fm.get("model"):
            entry["model"] = fm["model"]
        agents[name] = entry
    return json.dumps(agents)


def _materialise_settings(ctx: StepContext) -> Path:
    """Write the shipped settings with `{HOOKS_DIR}` resolved, into the run dir.

    The template cannot carry the hook's path: `$CLAUDE_PROJECT_DIR` is the
    worktree now, and the hook script ships with this package rather than with
    the target's tree -- a tree the agent writes is the last place to look for
    something we then execute.

    It lands in the run dir rather than in the worktree for two reasons: the
    worktree is what ingest turns into a revision, and an operator debugging a
    run wants to see exactly the settings the agent ran with, which the artifact
    sweep then gives them.
    """
    template = json.loads((runtime_dir() / "settings.json").read_text())
    rendered = json.dumps(template).replace("{HOOKS_DIR}", str(runtime_dir() / "hooks"))
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.run_dir / "agent-settings.json"
    path.write_text(rendered)
    return path


def _isolation_flags(ctx: StepContext) -> list[str]:
    """Load ONLY the packaged agent config instead of inheriting the repo-root
    `.claude/` used for development.

    --setting-sources "" drops ambient user/project/local .claude discovery; the
    app's permissions/hooks, MCP servers and subagents are then supplied
    explicitly. Verified against claude CLI 2.1.x: ambient skills/settings are
    excluded while these explicit sources load. Set QA_AGENT_ISOLATE=0 to fall
    back to ambient discovery (development only).
    """
    if os.environ.get("QA_AGENT_ISOLATE") == "0":
        return []
    rt = runtime_dir()
    return [
        "--setting-sources", "",
        "--settings", str(_materialise_settings(ctx)),
        "--mcp-config", str(rt / "mcp.json"),
        "--strict-mcp-config",
        "--agents", _agents_json(),
    ]


def step_invocation(
    ctx: StepContext, *, workers: str = "2"
) -> tuple[list[str], dict[str, str], Path]:
    """The command, environment and working directory for one step.

    A plain function so the two decisions that matter can be asserted without
    spawning the CLI: the agent runs **in the hydrated worktree**, and its
    output still goes to **the run directory**.
    """
    cmd = ["claude", "-p", build_message(ctx), "--output-format", "stream-json", "--verbose"]
    cmd += _isolation_flags(ctx)
    if ctx.prev_session_id:
        cmd += ["--resume", ctx.prev_session_id]
    # QA_RUN_DIR/QA_WORKERS reach the generated playwright.config.ts only here.
    env = {**os.environ, "QA_RUN_DIR": str(ctx.run_dir), "QA_WORKERS": workers}
    return cmd, env, ctx.worktree


def _summarise(event: dict) -> str | None:
    """Turn one stream-json event into a short human log line (or None to skip).

    Takes the parsed event, not the line: the reader already needs the object
    for the session id and the result, and parsing each line twice was how the
    two could disagree about what it said.
    """
    kind = event.get("type")
    if kind == "assistant":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "text" and block.get("text", "").strip():
                return block["text"].strip()
        return None
    if kind == "result":
        cost = event.get("total_cost_usd")
        return f"[result] is_error={event.get('is_error')} cost=${cost}"
    if kind == "system":
        return f"[system] {event.get('subtype', '')}".rstrip()
    return None


class ClaudeRunner:
    """The real runner, and the only thing that knows what it started.

    Two P4 additions, both about the limits around a run
    (app/orchestrator/limits.py):

    - **`last_cost_usd`** is read off the `result` event this already parses,
      which is what makes the per-run budget a budget rather than a new
      accounting system.
    - **`abort()`** kills the process group. The CLI spawns node, which spawns
      an MCP server, which spawns a browser; killing the one process this holds
      would leave the expensive half running, so the child gets its own session
      (`start_new_session`) and the whole group is signalled. A browser does not
      stop politely, which is why this is SIGKILL rather than SIGTERM.
    """

    def __init__(self, workers: str | None = None) -> None:
        self.workers = workers or os.environ.get("QA_WORKERS", "2")
        self.last_cost_usd = 0.0
        self._proc: subprocess.Popen | None = None

    def abort(self) -> None:
        """Kill the step's whole process group, if one is running."""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):  # pragma: no cover
            proc.kill()  # already gone, or no group to signal: the process will do

    def run_step(self, ctx: StepContext, emit: Emit) -> StepResult:
        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        cmd, env, cwd = step_invocation(ctx, workers=self.workers)

        session_jsonl = ctx.run_dir / "session.jsonl"
        stderr_log = ctx.run_dir / "stderr.log"

        session_id: str | None = None
        is_error = True
        self.last_cost_usd = 0.0
        with session_jsonl.open("a") as jf, stderr_log.open("a") as ef:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),  # the hydrated worktree: the agent works here only
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=ef,
                text=True,
                bufsize=1,
                # Its own process group, so `abort()` can take the browser with
                # it rather than orphaning the expensive half of the step.
                start_new_session=True,
            )
            self._proc = proc
            assert proc.stdout is not None
            for line in proc.stdout:
                jf.write(line)
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    # Not stream-json (a warning, a crash dump): pass it
                    # through rather than lose it.
                    if line.strip():
                        emit(f"[{ctx.step.value}] {line.rstrip()}")
                    continue
                if event.get("session_id"):
                    session_id = event["session_id"]
                if event.get("type") == "result":
                    is_error = bool(event.get("is_error", True))
                    self.last_cost_usd = float(event.get("total_cost_usd") or 0.0)
                summary = _summarise(event)
                if summary:
                    emit(f"[{ctx.step.value}] {summary}")
            rc = proc.wait()

        ok = rc == 0 and not is_error
        err = None if ok else f"claude step {ctx.step.value} failed (rc={rc}, is_error={is_error})"
        return StepResult(ok=ok, session_id=session_id, error=err)
