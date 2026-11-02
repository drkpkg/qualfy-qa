from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

import httpx

from qualfy.adapters.github import GitHubClient, GitHubOptions
from qualfy.core.contract import build_spec, extract_contract
from qualfy.core.errors import ContractError
from qualfy.core.models import Classification, Ref, SpecSummary, TestSpec, Ticket, Urgency
from qualfy.core.schema import field

# GitHub issues have no native priority; teams use labels (or a Projects field).
PRIORITY_COLORS = {"P0": "b60205", "P1": "d93f0b", "P2": "fbca04", "P3": "0e8a16"}


@dataclass
class GitHubIssuesOptions(GitHubOptions):
    labels: list[str] = field(default_factory=lambda: ["qa:ready"])
    state: str = "open"
    generator: str = "human"
    priority_prefix: str = "priority:"
    automatable_label: str | None = None


class GitHubIssuesSource:
    """GitHub issues whose body holds the YAML contract; discovery filters by label."""

    kind: ClassVar[str] = "github-issues"
    Options: ClassVar[type] = GitHubIssuesOptions

    def __init__(self, options: GitHubIssuesOptions,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.options = options
        self.client = GitHubClient(options, transport=transport)

    async def discover(self) -> list[SpecSummary]:
        issues = await self.client.list_issues(self.options.labels, self.options.state)
        return [
            SpecSummary(ref=self._ref(i), title=i.get("title", ""),
                        status=", ".join(label["name"] for label in i.get("labels", [])) or None)
            for i in issues
        ]

    async def fetch(self, key: str) -> dict:
        return await self.client.get_issue(self.client.parse_number(key))

    async def ticket(self, raw: dict) -> Ticket:
        labels = [label["name"] for label in raw.get("labels", [])]
        prefix = self.options.priority_prefix
        priority = next((label[len(prefix):] for label in labels if label.startswith(prefix)), None)
        created = raw.get("created_at")
        return Ticket(
            ref=self._ref(raw), title=raw.get("title", ""), body=raw.get("body") or "",
            labels=labels, status=raw.get("state"), priority=priority,
            created_at=datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None,
        )

    async def normalize(self, raw: dict) -> TestSpec:
        if not raw.get("body"):
            raise ContractError(f"issue #{raw.get('number')} has no body")
        return build_spec(extract_contract(raw["body"]), ref=self._ref(raw),
                          title=raw.get("title"), generator=self.options.generator)

    # ---- triage -----------------------------------------------------------------------------

    async def triage_candidates(self, limit: int = 50) -> list[Ticket]:
        return [await self.ticket(i) for i in await self.client.list_issues(limit=limit)]

    def existing_urgency(self, ticket: Ticket) -> Classification | None:
        if ticket.priority in {u.value for u in Urgency}:
            return Classification(key=ticket.ref.key, urgency=Urgency(ticket.priority),
                                  source="label", reason="priority label already set")
        return None

    async def apply_classification(self, ticket: Ticket, item: Classification) -> None:
        number = self.client.parse_number(ticket.ref.key)
        prefix = self.options.priority_prefix
        target = f"{prefix}{item.urgency}"
        for label in ticket.labels:
            if label.startswith(prefix) and label != target:
                await self.client.remove_label(number, label)
        add = [target]
        if item.automatable and self.options.automatable_label:
            add.append(self.options.automatable_label)
        await self.client.add_labels(number, add)

    async def ensure_labels(self) -> list[str]:
        """Create the priority and workflow labels this source relies on. Returns created ones."""
        existing = set(await self.client.list_labels())
        wanted = {f"{self.options.priority_prefix}{u}": (PRIORITY_COLORS[u], f"Urgency {u}")
                  for u in PRIORITY_COLORS}
        for label in self.options.labels:
            wanted.setdefault(label, ("1d76db", "Ready for QA automation"))
        created = []
        for name, (color, description) in wanted.items():
            if name not in existing:
                await self.client.create_label(name, color, description)
                created.append(name)
        return created

    def _ref(self, issue: dict) -> Ref:
        return Ref(system="github", key=self.client.key(issue["number"]), url=issue.get("html_url"))
