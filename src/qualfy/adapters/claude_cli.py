"""Thin async wrapper around the `claude` CLI (Claude Code) in print mode."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from qualfy.core.errors import AgentError, SchemaError
from qualfy.core.schema import from_dict, inline_schema

T = TypeVar("T")
STREAM_LIMIT = 16 * 1024 * 1024
READ_ONLY_TOOLS = ["Read", "Glob", "Grep"]


@dataclass
class ClaudeOptions:
    binary: str = "claude"
    model: str | None = None
    workdir: str = "."
    base_dir: str = "."
    timeout_s: float = 600
    max_budget_usd: float | None = None


def resolve_dir(path: str, base_dir: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (Path(base_dir) / p).resolve()


async def spawn(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None
                ) -> asyncio.subprocess.Process:
    try:
        return await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env={**os.environ, **(env or {})}, limit=STREAM_LIMIT,
        )
    except FileNotFoundError as exc:
        raise AgentError(f"claude binary not found: {cmd[0]} (install Claude Code)") from exc


async def stream(cmd: list[str], prompt: str, *, cwd: Path, env: dict[str, str] | None,
                 timeout_s: float, on_message: Callable[[dict, bytes], Awaitable[None]]
                 ) -> tuple[int | None, str, bool]:
    """Run a stream-json session. Returns (returncode, stderr, timed_out)."""
    proc = await spawn(cmd, cwd=cwd, env=env)
    assert proc.stdin and proc.stdout and proc.stderr
    proc.stdin.write(prompt.encode())
    await proc.stdin.drain()
    proc.stdin.close()
    stderr_task = asyncio.create_task(proc.stderr.read())
    try:
        async with asyncio.timeout(timeout_s):
            async for line in proc.stdout:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict):
                    await on_message(msg, line)
            await proc.wait()
            return proc.returncode, (await stderr_task).decode(), False
    except (TimeoutError, asyncio.CancelledError) as exc:
        with suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        stderr_task.cancel()
        if isinstance(exc, asyncio.CancelledError):
            raise
        return proc.returncode, "", True


async def ask_json[T](options: ClaudeOptions, prompt: str, model_cls: type[T], *,
                   tools: list[str] | None = None) -> tuple[T, float | None]:
    """One-shot structured answer validated against `model_cls`. Returns (value, cost_usd)."""
    schema = inline_schema(model_cls)
    tools = READ_ONLY_TOOLS if tools is None else tools
    cmd = [options.binary, "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
           "--tools", ",".join(tools) if tools else ""]
    if tools:
        cmd += ["--allowedTools", *tools]
    if options.model:
        cmd += ["--model", options.model]
    if options.max_budget_usd:
        cmd += ["--max-budget-usd", str(options.max_budget_usd)]
    proc = await spawn(cmd, cwd=resolve_dir(options.workdir, options.base_dir))
    try:
        async with asyncio.timeout(options.timeout_s):
            stdout, stderr = await proc.communicate(prompt.encode())
    except TimeoutError as exc:
        with suppress(ProcessLookupError):
            proc.kill()
        raise AgentError(f"claude timed out after {options.timeout_s}s") from exc
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        detail = stderr.decode().strip()[-400:] or stdout.decode()[-400:]
        raise AgentError(f"claude returned no JSON (exit {proc.returncode}): {detail}") from exc
    if envelope.get("is_error"):
        raise AgentError(f"claude failed: {envelope.get('result') or envelope.get('subtype')}")
    data = envelope.get("structured_output") or extract_json(envelope.get("result") or "")
    try:
        return from_dict(model_cls, data), envelope.get("total_cost_usd")
    except SchemaError as exc:
        raise AgentError(f"claude answer did not match the expected schema:\n{exc}") from exc


def extract_json(text: str) -> Any:
    fenced = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def available(binary: str = "claude") -> bool:
    return shutil.which(binary) is not None
