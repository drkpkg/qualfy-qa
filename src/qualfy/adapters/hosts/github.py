from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import ClassVar

import httpx

from qualfy.adapters.claude_cli import resolve_dir
from qualfy.adapters.github import GitHubClient, GitHubOptions
from qualfy.core.errors import SinkError, SourceError


@dataclass
class GitHubHostOptions(GitHubOptions):
    base: str = "main"
    remote: str = "origin"
    workdir: str = "."
    base_dir: str = "."
    draft: bool = False


class GitHubHost:
    """Pushes the agent's branch and opens a pull request on the test repository."""

    kind: ClassVar[str] = "github"
    Options: ClassVar[type] = GitHubHostOptions

    def __init__(self, options: GitHubHostOptions,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.options = options
        self.client = GitHubClient(options, transport=transport)
        self.workdir = resolve_dir(options.workdir, options.base_dir)

    async def push(self, branch: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "git", "push", "-u", self.options.remote, branch, cwd=self.workdir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        output, _ = await proc.communicate()
        if proc.returncode != 0:
            raise SinkError(f"git push {branch} failed: {output.decode().strip()[-400:]}")

    async def open_pull_request(self, branch: str, title: str, body: str) -> str:
        await self.push(branch)
        try:
            pull = await self.client.create_pull(branch, self.options.base, title, body)
        except SourceError as exc:
            if "-> 422" not in str(exc):
                raise
            pull = await self.client.find_pull(branch)
            if pull is None:
                raise
        return pull["html_url"]
