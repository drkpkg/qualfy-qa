"""Shared Jira Cloud REST v3 client and Atlassian Document Format helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from qualfy.core.errors import SourceError
from qualfy.core.schema import Secret


@dataclass
class JiraOptions:
    base_url: str
    email: str
    token: Secret
    timeout: float = 30.0


class JiraClient:
    def __init__(self, options: JiraOptions, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = options.base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=f"{self.base_url}/rest/api/3",
            auth=(options.email, Secret.reveal(options.token)),
            headers={"Accept": "application/json"},
            timeout=options.timeout,
            transport=transport,
        )

    def browse_url(self, key: str) -> str:
        return f"{self.base_url}/browse/{key}"

    async def myself(self) -> dict:
        return await self._request("GET", "/myself")

    async def get_issue(self, key: str,
                        fields: str = "summary,description,status,priority,labels,created") -> dict:
        return await self._request("GET", f"/issue/{key}", params={"fields": fields})

    async def search(self, jql: str, fields: str = "summary,status,priority,labels",
                     limit: int = 50) -> list[dict]:
        payload = {"jql": jql, "fields": fields.split(","), "maxResults": limit}
        data = await self._request("POST", "/search/jql", json=payload)
        return data.get("issues", [])

    async def add_comment(self, key: str, body: dict) -> dict:
        return await self._request("POST", f"/issue/{key}/comment", json={"body": body})

    async def set_priority(self, key: str, priority: str) -> None:
        fields = {"priority": {"name": priority}}
        await self._request("PUT", f"/issue/{key}", json={"fields": fields})

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, url, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SourceError(
                f"Jira {method} {url} -> {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SourceError(f"Jira {method} {url} failed: {exc}") from exc
        return response.json() if response.content else {}

    async def aclose(self) -> None:
        await self._client.aclose()


def adf_code_blocks(node: Any) -> list[tuple[str | None, str]]:
    """Return (language, text) for every codeBlock in an ADF document."""
    found: list[tuple[str | None, str]] = []

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            if n.get("type") == "codeBlock":
                text = "".join(c.get("text", "") for c in n.get("content", []))
                found.append(((n.get("attrs") or {}).get("language"), text))
                return
            for child in n.get("content", []):
                walk(child)
        elif isinstance(n, list):
            for child in n:
                walk(child)

    walk(node)
    return found


def adf_text(node: Any) -> str:
    """Flatten an ADF document to plain text (paragraph breaks preserved)."""
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        if node.get("type") == "hardBreak":
            return "\n"
        inner = "".join(adf_text(c) for c in node.get("content", []))
        block = node.get("type") in {"paragraph", "heading", "codeBlock", "listItem"}
        return inner + ("\n" if block else "")
    if isinstance(node, list):
        return "".join(adf_text(c) for c in node)
    return ""


def adf_paragraph(text: str, *, bold: bool = False) -> dict:
    node: dict = {"type": "text", "text": text}
    if bold:
        node["marks"] = [{"type": "strong"}]
    return {"type": "paragraph", "content": [node]}


_INLINE_RE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")


def _inline(text: str) -> list[dict]:
    nodes, pos = [], 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > pos:
            nodes.append({"type": "text", "text": text[pos:match.start()]})
        if match.group(1):
            nodes.append({"type": "text", "text": match.group(1), "marks": [{"type": "strong"}]})
        else:
            nodes.append({"type": "text", "text": match.group(2), "marks": [{"type": "code"}]})
        pos = match.end()
    if pos < len(text):
        nodes.append({"type": "text", "text": text[pos:]})
    return nodes or [{"type": "text", "text": " "}]


def markdown_to_adf(markdown: str) -> dict:
    """Small markdown subset → ADF: headings, bullets, tables (as code), bold, code spans."""
    content: list[dict] = []
    bullets: list[dict] = []
    table: list[str] = []

    def flush() -> None:
        if bullets:
            content.append({"type": "bulletList", "content": list(bullets)})
            bullets.clear()
        if table:
            content.append({"type": "codeBlock", "attrs": {"language": "text"},
                            "content": [{"type": "text", "text": "\n".join(table)}]})
            table.clear()

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("|"):
            if not set(line) <= set("|-: "):
                table.append(line)
            continue
        if line.startswith(("- ", "* ")):
            if table:
                flush()
            bullets.append({"type": "listItem",
                            "content": [{"type": "paragraph", "content": _inline(line[2:])}]})
            continue
        flush()
        if not line.strip():
            continue
        if heading := re.match(r"^(#{1,6})\s+(.*)", line):
            content.append({"type": "heading", "attrs": {"level": len(heading.group(1))},
                            "content": _inline(heading.group(2))})
        else:
            text = re.sub(r"^>\s?", "", line)
            text = re.sub(r"</?sub>", "", text)
            content.append({"type": "paragraph", "content": _inline(text)})
    flush()
    return {"type": "doc", "version": 1, "content": content}
