from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from qualfy.adapters.agents.prompt import GitMode, build_prompt
from qualfy.adapters.claude_cli import resolve_dir, stream
from qualfy.core.errors import AgentError, SchemaError
from qualfy.core.events import RunEmitter
from qualfy.core.models import AgentReport, TestSpec
from qualfy.core.ports import AgentContext, AgentRun
from qualfy.core.schema import field, loads

DEFAULT_TOOLS = [
    "Read", "Edit", "Write", "Glob", "Grep", "TodoWrite",
    "Bash(npx playwright:*)", "Bash(npm run:*)", "Bash(npm test:*)", "Bash(npx tsc:*)",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git checkout:*)", "Bash(git switch:*)",
    "Bash(git add:*)", "Bash(git commit:*)", "Bash(git log:*)", "Bash(ls:*)",
    "mcp__playwright",
]


@dataclass
class ClaudeCodeOptions:
    workdir: str = "."
    base_dir: str = "."
    binary: str = "claude"
    model: str | None = None
    permission_mode: str = "acceptEdits"
    allowed_tools: list[str] = field(default_factory=lambda: list(DEFAULT_TOOLS))
    disallowed_tools: list[str] = field(default_factory=list)
    mcp_config: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    timeout_s: float = 3600
    git: GitMode = "branch"
    instructions: str = ""
    env: dict[str, str] = field(default_factory=dict)


class ClaudeCodeAgent:
    """Runs Claude Code headless (`claude -p --output-format stream-json`) inside the test repo."""

    kind: ClassVar[str] = "claude-code"
    Options: ClassVar[type] = ClaudeCodeOptions

    def __init__(self, options: ClaudeCodeOptions) -> None:
        self.options = options
        self.workdir = resolve_dir(options.workdir, options.base_dir)

    def command(self, ctx: AgentContext) -> list[str]:
        o = self.options
        cmd = [o.binary, "-p", "--output-format", "stream-json", "--verbose",
               "--permission-mode", o.permission_mode, "--add-dir", str(ctx.run_dir)]
        if o.model:
            cmd += ["--model", o.model]
        if o.max_turns:
            cmd += ["--max-turns", str(o.max_turns)]
        if o.max_budget_usd:
            cmd += ["--max-budget-usd", str(o.max_budget_usd)]
        if o.mcp_config:
            cmd += ["--mcp-config", str(resolve_dir(o.mcp_config, o.base_dir))]
        if o.allowed_tools:
            cmd += ["--allowedTools", *o.allowed_tools]
        if o.disallowed_tools:
            cmd += ["--disallowedTools", *o.disallowed_tools]
        return cmd

    async def automate(self, spec: TestSpec, ctx: AgentContext, emit: RunEmitter) -> AgentRun:
        if not self.workdir.is_dir():
            raise AgentError(f"agent workdir does not exist: {self.workdir}")
        prompt = build_prompt(spec, ctx.report_path, git=self.options.git,
                              extra=self.options.instructions, env_names=sorted(ctx.env))
        (ctx.run_dir / "prompt.md").write_text(prompt)
        final: dict[str, Any] = {}

        with (ctx.run_dir / "transcript.jsonl").open("w") as transcript:
            async def on_message(msg: dict, line: bytes) -> None:
                transcript.write(line.decode())
                if msg.get("type") == "result":
                    final.update(msg)
                await _forward(msg, emit)

            returncode, stderr, timed_out = await stream(
                self.command(ctx), prompt, cwd=self.workdir,
                env={**self.options.env, **ctx.env}, timeout_s=self.options.timeout_s,
                on_message=on_message)

        if timed_out:
            return AgentRun(report=None, error=f"agent timed out after {self.options.timeout_s}s")
        error = None
        if returncode != 0 or final.get("is_error"):
            error = final.get("result") or final.get("subtype") or stderr.strip()[-500:] or (
                f"claude exited with {returncode}")
        report, report_error = _load_report(ctx.report_path)
        return AgentRun(report=report, cost_usd=final.get("total_cost_usd"),
                        turns=final.get("num_turns"), error=error or report_error)


async def _forward(msg: dict, emit: RunEmitter) -> None:
    kind = msg.get("type")
    if kind == "system" and msg.get("subtype") == "init":
        await emit("log", f"session {msg.get('session_id')} ({msg.get('model')})",
                   session_id=msg.get("session_id"))
    elif kind == "assistant":
        for block in (msg.get("message") or {}).get("content", []):
            if block.get("type") == "text" and block.get("text", "").strip():
                await emit("agent.message", block["text"].strip())
            elif block.get("type") == "tool_use":
                name = block.get("name", "?")
                await emit("agent.tool", f"{name} {_summarize(block.get('input') or {})}",
                           tool=name)
    elif kind == "result":
        await emit("agent.result", msg.get("subtype", ""), cost_usd=msg.get("total_cost_usd"),
                   turns=msg.get("num_turns"), is_error=msg.get("is_error", False))


def _summarize(data: dict) -> str:
    for key in ("command", "file_path", "pattern", "url", "path"):
        if key in data:
            return str(data[key])[:160]
    return json.dumps(data, ensure_ascii=False)[:160] if data else ""


def _load_report(path: Path) -> tuple[AgentReport | None, str | None]:
    if not path.exists():
        return None, f"agent did not write its report to {path}"
    try:
        return loads(AgentReport, path.read_text()), None
    except SchemaError as exc:
        return None, f"agent report is invalid:\n{exc}"
