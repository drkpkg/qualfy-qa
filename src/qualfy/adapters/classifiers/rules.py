from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from qualfy.core.models import Classification, Priority, Ticket, Urgency
from qualfy.core.schema import field

DEFAULT_RULES = {
    "P0": [r"\b(outage|down|data loss|security|vulnerab\w*|payment fail\w*|cannot log ?in|"
           r"crash(es|ing)?|blocker|sev ?1)\b"],
    "P1": [r"\b(regression|broken|error|fail(s|ing|ure)?|critical|checkout|login|sign ?in|"
           r"urgent)\b"],
    "P3": [r"\b(typo|cosmetic|copy|wording|nice to have|polish|docs?|documentation)\b"],
}
LABEL_HINTS = {"bug": "P1", "critical": "P0", "security": "P0", "regression": "P1",
               "enhancement": "P2", "documentation": "P3", "good first issue": "P3"}
MANUAL_RE = re.compile(r"\b(visual|look and feel|brand|exploratory|usability|ux review)\b", re.I)


@dataclass
class RulesClassifierOptions:
    rules: dict[str, list[str]] = field(default_factory=lambda: dict(DEFAULT_RULES),
                                        description="urgency -> regexes matched on title+body")
    default: Urgency = Urgency.P2


class RulesClassifier:
    """Keyword and label heuristics. Free, offline and predictable; good enough to pre-sort."""

    kind: ClassVar[str] = "rules"
    Options: ClassVar[type] = RulesClassifierOptions

    def __init__(self, options: RulesClassifierOptions) -> None:
        self.options = options
        self.patterns = {Urgency(u): [re.compile(p, re.I) for p in pats]
                         for u, pats in options.rules.items()}

    async def classify(self, tickets: list[Ticket]) -> list[Classification]:
        return [self._one(t) for t in tickets]

    def _one(self, ticket: Ticket) -> Classification:
        text = f"{ticket.title}\n{ticket.body}"
        for label in ticket.labels:
            if hint := LABEL_HINTS.get(label.lower()):
                return self._make(ticket, Urgency(hint), f"label '{label}'", text)
        for urgency in (Urgency.P0, Urgency.P1, Urgency.P3):
            for pattern in self.patterns.get(urgency, []):
                if match := pattern.search(text):
                    return self._make(ticket, urgency, f"mentions '{match.group(0)}'", text)
        return self._make(ticket, self.options.default, "no urgency signals", text)

    @staticmethod
    def _make(ticket: Ticket, urgency: Urgency, reason: str, text: str) -> Classification:
        impact = {Urgency.P0: Priority.CRITICAL, Urgency.P1: Priority.HIGH,
                  Urgency.P2: Priority.MEDIUM, Urgency.P3: Priority.LOW}[urgency]
        return Classification(key=ticket.ref.key, urgency=urgency, reason=reason, impact=impact,
                              automatable=not MANUAL_RE.search(text), source="rules")
