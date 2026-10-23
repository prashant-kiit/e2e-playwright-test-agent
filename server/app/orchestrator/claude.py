"""The real Runner: shells out to the `claude` CLI, one step per invocation.

Mirrors the batch runner's proven invocation (`claude -p <prompt>
--output-format stream-json --verbose`, with QA_RUN_DIR/QA_WORKERS), but runs a
single step and carries the Claude Code session across steps with --resume, so
exploratory context (step 3) survives into generation (step 4). stdout is teed
to the run dir's session.jsonl and relayed line-by-line to the log bus.

Requires the claude CLI and the repo checkout (apps/, prompts/) to be present in
the execution environment; DESIGN.md P4 moves that into a prebaked per-run
sandbox image. Not exercised by the automated tests (that is the FakeRunner's job).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .. import config
from ..domain.steps import Step
from .runner import Emit, StepContext, StepResult

_STEP_FILE = {
    Step.READ_STORY: "1-read_story.md",
    Step.PLAN: "2-plan.md",
    Step.EXPLORE: "3-explore.md",
    Step.GENERATE: "4-generate.md",
    Step.HEAL: "5-heal.md",
}


def _build_message(ctx: StepContext) -> str:
    steps_dir = config.repo_root() / "prompts" / "steps"
    header = (steps_dir / "_context.md").read_text()
    body = (steps_dir / _STEP_FILE[ctx.step]).read_text()
    text = f"{header}\n\n---\n\n{body}"
    for token, value in {
        "{STORY_ID}": ctx.story_id,
        "{APP}": ctx.app,
        "{MODE}": ctx.mode,
        "{RUN_KEY}": ctx.run_key,
    }.items():
        text = text.replace(token, value)
    return text


def runtime_dir() -> Path:
    """The app's shipped agent config, owned by the application (not the
    repo-root .claude/, which exists only for development)."""
    return config.repo_root() / "apps" / "agent" / "runtime"


def _agents_json() -> str:
    """Build the --agents payload from runtime/agents/*.md.

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


def _isolation_flags() -> list[str]:
    """Load ONLY the app's shipped agent config (apps/agent/runtime) instead of
    inheriting the repo-root .claude/ used for development.

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
        "--settings", str(rt / "settings.json"),
        "--mcp-config", str(rt / "mcp.json"),
        "--strict-mcp-config",
        "--agents", _agents_json(),
    ]


def _summarise(line: str) -> str | None:
    """Turn one stream-json line into a short human log line (or None to skip)."""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return line.rstrip()
    kind = obj.get("type")
    if kind == "assistant":
        for block in obj.get("message", {}).get("content", []):
            if block.get("type") == "text" and block.get("text", "").strip():
                return block["text"].strip()
        return None
    if kind == "result":
        cost = obj.get("total_cost_usd")
        return f"[result] is_error={obj.get('is_error')} cost=${cost}"
    if kind == "system":
        return f"[system] {obj.get('subtype', '')}".rstrip()
    return None


class ClaudeRunner:
    def __init__(self, workers: str | None = None) -> None:
        self.workers = workers or os.environ.get("QA_WORKERS", "2")

    def run_step(self, ctx: StepContext, emit: Emit) -> StepResult:
        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        message = _build_message(ctx)

        cmd = ["claude", "-p", message, "--output-format", "stream-json", "--verbose"]
        cmd += _isolation_flags()
        if ctx.prev_session_id:
            cmd += ["--resume", ctx.prev_session_id]

        env = {**os.environ, "QA_RUN_DIR": str(ctx.run_dir), "QA_WORKERS": self.workers}
        session_jsonl = ctx.run_dir / "session.jsonl"
        stderr_log = ctx.run_dir / "stderr.log"

        session_id: str | None = None
        is_error = True
        with session_jsonl.open("a") as jf, stderr_log.open("a") as ef:
            proc = subprocess.Popen(
                cmd,
                cwd=str(config.repo_root()),
                env=env,  # QA_RUN_DIR/QA_WORKERS reach playwright.config.ts only via this
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=ef,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                jf.write(line)
                try:
                    obj = json.loads(line)
                    if obj.get("session_id"):
                        session_id = obj["session_id"]
                    if obj.get("type") == "result":
                        is_error = bool(obj.get("is_error", True))
                except json.JSONDecodeError:
                    pass
                summary = _summarise(line)
                if summary:
                    emit(f"[{ctx.step.value}] {summary}")
            rc = proc.wait()

        ok = rc == 0 and not is_error
        err = None if ok else f"claude step {ctx.step.value} failed (rc={rc}, is_error={is_error})"
        return StepResult(ok=ok, session_id=session_id, error=err)
