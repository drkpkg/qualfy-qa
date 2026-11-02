from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

import httpx

from qualfy.adapters.jira import JiraClient, JiraOptions, adf_code_blocks, adf_text
from qualfy.core.contract import build_spec, extract_contract, load_contract
from qualfy.core.errors import ContractError
from qualfy.core.models import Classification, Ref, SpecSummary, TestSpec, Ticket, Urgency
from qualfy.core.schema import field

DEFAULT_PRIORITIES = {"P0": "Highest", "P1": "High", "P2": "Medium", "P3": "Low"}


@dataclass
class JiraRovoOptions(JiraOptions):
    jql: str = 'status = "Ready for Automation" ORDER BY updated DESC'
    triage_jql: str = "statusCategory != Done ORDER BY created DESC"
    generator: str = "rovo"
    priority_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PRIORITIES))
    untriaged_priority: str = field(
        default="Medium",
        description="Priority Jira assigns by default; anything else counts as already triaged "
                    "(by a person or a Rovo triage agent) and is kept unless forced.")


class JiraRovoSource:
    """Jira test tickets whose description holds the YAML contract written by a Rovo agent."""

    kind: ClassVar[str] = "jira-rovo"
    Options: ClassVar[type] = JiraRovoOptions

    def __init__(self, options: JiraRovoOptions,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.options = options
        self.client = JiraClient(options, transport=transport)

    async def discover(self) -> list[SpecSummary]:
        issues = await self.client.search(self.options.jql)
        return [
            SpecSummary(ref=self._ref(i["key"]), title=i["fields"].get("summary", ""),
                        status=(i["fields"].get("status") or {}).get("name"))
            for i in issues
        ]

    async def fetch(self, key: str) -> dict:
        return await self.client.get_issue(key)

    async def ticket(self, raw: dict) -> Ticket:
        fields = raw.get("fields", {})
        description = fields.get("description")
        body = adf_text(description) if isinstance(description, dict) else (description or "")
        created = fields.get("created")
        return Ticket(
            ref=self._ref(raw["key"]),
            title=fields.get("summary", ""),
            body=body,
            labels=list(fields.get("labels") or []),
            status=(fields.get("status") or {}).get("name"),
            priority=(fields.get("priority") or {}).get("name"),
            created_at=_parse_jira_date(created),
        )

    async def normalize(self, raw: dict) -> TestSpec:
        fields = raw.get("fields", {})
        return build_spec(_contract_from_description(fields.get("description")),
                          ref=self._ref(raw["key"]), title=fields.get("summary"),
                          generator=self.options.generator)

    # ---- triage -----------------------------------------------------------------------------

    async def triage_candidates(self, limit: int = 50) -> list[Ticket]:
        issues = await self.client.search(
            self.options.triage_jql, fields="summary,description,status,priority,labels,created",
            limit=limit)
        return [await self.ticket(i) for i in issues]

    def existing_urgency(self, ticket: Ticket) -> Classification | None:
        if not ticket.priority or ticket.priority == self.options.untriaged_priority:
            return None
        reverse = {v.lower(): k for k, v in self.options.priority_map.items()}
        urgency = reverse.get(ticket.priority.lower())
        if urgency is None:
            return None
        return Classification(key=ticket.ref.key, urgency=Urgency(urgency), source="jira",
                              reason=f"priority already set to {ticket.priority}")

    async def apply_classification(self, ticket: Ticket, item: Classification) -> None:
        await self.client.set_priority(ticket.ref.key, self.options.priority_map[item.urgency])

    def _ref(self, key: str) -> Ref:
        return Ref(system="jira", key=key, url=self.client.browse_url(key))


def _contract_from_description(description: Any) -> dict:
    if not description:
        raise ContractError("ticket has no description")
    if isinstance(description, str):
        return extract_contract(description)
    for language, text in adf_code_blocks(description):
        if language in (None, "", "yaml", "yml"):
            try:
                return load_contract(text)
            except ContractError:
                continue
    return extract_contract(adf_text(description))


def _parse_jira_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError:
        return None
