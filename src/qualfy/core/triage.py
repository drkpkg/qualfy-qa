"""`qualfy classify`: rank open tickets by urgency, respecting existing triage."""

from __future__ import annotations

from dataclasses import dataclass

from qualfy.core.errors import ConfigError
from qualfy.core.models import Classification, Ticket, Urgency
from qualfy.core.ports import ClassifierAdapter, TriageSource
from qualfy.core.service import AutomationService

ORDER = {u: i for i, u in enumerate(Urgency)}


@dataclass
class TriageItem:
    ticket: Ticket
    classification: Classification
    existing: bool

    @property
    def changes(self) -> bool:
        return not self.existing and self.classification.urgency != self.ticket.priority


def _source(service: AutomationService, project: str | None) -> TriageSource:
    source = service.project(project).source
    if not isinstance(source, TriageSource):
        raise ConfigError(f"source '{type(source).kind}' does not support classification")
    return source


def _classifier(service: AutomationService, project: str | None,
                name: str | None) -> ClassifierAdapter:
    if name:
        if name not in service.config.classifiers:
            known = ", ".join(service.config.classifiers)
            raise ConfigError(f"unknown classifier '{name}' ({known})")
        return service.build("classifiers", name)
    classifier = service.project(project).classifier
    if classifier is None:
        raise ConfigError("no classifier configured for this project (add `classifier:`)")
    return classifier


async def classify(service: AutomationService, project: str | None = None, *,
                   classifier: str | None = None, limit: int = 50,
                   force: bool = False) -> list[TriageItem]:
    source = _source(service, project)
    tickets = await source.triage_candidates(limit)
    items: list[TriageItem] = []
    pending: list[Ticket] = []
    for ticket in tickets:
        existing = None if force else source.existing_urgency(ticket)
        if existing is not None:
            items.append(TriageItem(ticket, existing, existing=True))
        else:
            pending.append(ticket)
    if pending:
        by_key = {t.ref.key: t for t in pending}
        results = await _classifier(service, project, classifier).classify(pending)
        for result in results:
            items.append(TriageItem(by_key[result.key], result, existing=False))
    items.sort(key=lambda i: (ORDER[i.classification.urgency], i.ticket.ref.key))
    return items


async def apply(service: AutomationService, items: list[TriageItem],
                project: str | None = None) -> dict[str, str | None]:
    """Write classifications back to the tracker. Returns key -> error."""
    source = _source(service, project)
    outcome: dict[str, str | None] = {}
    for item in items:
        if not item.changes:
            continue
        try:
            await source.apply_classification(item.ticket, item.classification)
        except Exception as exc:
            outcome[item.ticket.ref.key] = str(exc)
        else:
            outcome[item.ticket.ref.key] = None
    return outcome
