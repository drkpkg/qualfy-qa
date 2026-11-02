"""Shared GitHub REST client (github.com or GitHub Enterprise)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from qualfy.core.errors import SourceError
from qualfy.core.schema import Secret

API_VERSION = "2022-11-28"
ISSUE_REF_RE = re.compile(r"^(?:(?P<repo>[\w.-]+/[\w.-]+)#|#|[\w.-]+-)?(?P<number>\d+)$")
REMOTE_RE = re.compile(r"github\.com[:/](?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?$")


@dataclass
class GitHubOptions:
    owner: str
    repo: str
    token: Secret
    base_url: str = "https://api.github.com"
    key_prefix: str | None = None
    timeout: float = 30.0


def parse_remote(url: str) -> tuple[str, str] | None:
    match = REMOTE_RE.search(url.strip())
    return (match.group("owner"), match.group("repo")) if match else None


class GitHubClient:
    def __init__(self, options: GitHubOptions, transport: httpx.AsyncBaseTransport | None = None):
        self.owner, self.repo = options.owner, options.repo
        self.key_prefix = options.key_prefix or options.repo
        self._client = httpx.AsyncClient(
            base_url=f"{options.base_url.rstrip('/')}/repos/{options.owner}/{options.repo}",
            headers={
                "Authorization": f"Bearer {Secret.reveal(options.token)}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
            },
            timeout=options.timeout,
            transport=transport,
        )

    def key(self, number: int) -> str:
        return f"{self.key_prefix}-{number}"

    def parse_number(self, key: str) -> int:
        """Accept `123`, `#123`, `<prefix>-123` or `owner/repo#123` (repo must match)."""
        match = ISSUE_REF_RE.match(key.strip())
        if not match:
            raise SourceError(f"not a GitHub issue reference: {key!r}")
        repo = match.group("repo")
        if repo and repo.lower() != f"{self.owner}/{self.repo}".lower():
            raise SourceError(f"{key} belongs to another repository than {self.owner}/{self.repo}")
        return int(match.group("number"))

    async def get_repo(self) -> dict:
        return await self._request("GET", "")

    async def get_issue(self, number: int) -> dict:
        return await self._request("GET", f"/issues/{number}")

    async def list_issues(self, labels: list[str] | None = None, state: str = "open",
                          limit: int = 50) -> list[dict]:
        params: dict[str, Any] = {"state": state, "per_page": min(limit, 100)}
        if labels:
            params["labels"] = ",".join(labels)
        issues = await self._request("GET", "/issues", params=params)
        return [i for i in issues if "pull_request" not in i]

    async def add_comment(self, number: int, body: str) -> dict:
        return await self._request("POST", f"/issues/{number}/comments", json={"body": body})

    async def add_labels(self, number: int, labels: list[str]) -> None:
        await self._request("POST", f"/issues/{number}/labels", json={"labels": labels})

    async def remove_label(self, number: int, label: str) -> None:
        try:
            await self._request("DELETE", f"/issues/{number}/labels/{quote(label, safe='')}")
        except SourceError as exc:
            if "-> 404" not in str(exc):
                raise

    async def list_labels(self) -> list[str]:
        return [label["name"] for label in await self._request("GET", "/labels",
                                                               params={"per_page": 100})]

    async def create_label(self, name: str, color: str, description: str = "") -> None:
        await self._request("POST", "/labels",
                            json={"name": name, "color": color, "description": description})

    async def create_pull(self, head: str, base: str, title: str, body: str) -> dict:
        return await self._request("POST", "/pulls", json={
            "title": title, "head": head, "base": base, "body": body})

    async def find_pull(self, head: str) -> dict | None:
        pulls = await self._request("GET", "/pulls",
                                    params={"head": f"{self.owner}:{head}", "state": "open"})
        return pulls[0] if pulls else None

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, url, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SourceError(
                f"GitHub {method} {url or '/'} -> {exc.response.status_code}: "
                f"{exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SourceError(f"GitHub {method} {url or '/'} failed: {exc}") from exc
        return response.json() if response.content else {}

    async def aclose(self) -> None:
        await self._client.aclose()
