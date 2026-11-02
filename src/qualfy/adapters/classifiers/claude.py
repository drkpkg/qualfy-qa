from __future__ import annotations

import json
from dataclasses import dataclass
from typing import ClassVar

from qualfy.adapters.claude_cli import ClaudeOptions, ask_json
from qualfy.core.models import Classification, ClassificationSet, Ticket

GUIDE = """\
- P0: production broken, security, data loss, payments or login unusable for many users.
- P1: important flow broken or regressed with a workaround, or a release blocker.
- P2: normal priority work, minor bugs, features.
- P3: cosmetic, copy, docs, nice to have."""


@dataclass
class ClaudeClassifierOptions(ClaudeOptions):
    body_chars: int = 1500


class ClaudeClassifier:
    """Claude ranks tickets by urgency with a reason, in a single structured call."""

    kind: ClassVar[str] = "claude"
    Options: ClassVar[type] = ClaudeClassifierOptions

    def __init__(self, options: ClaudeClassifierOptions) -> None:
        self.options = options

    def prompt(self, tickets: list[Ticket]) -> str:
        items = [{"key": t.ref.key, "title": t.title, "labels": t.labels,
                  "current_priority": t.priority, "body": t.body[: self.options.body_chars]}
                 for t in tickets]
        return (
            "Classify each ticket by urgency for a QA team. Use this scale:\n"
            f"{GUIDE}\n\nFor each ticket return its `key`, `urgency`, `impact` "
            "(low|medium|high|critical), whether its checks are `automatable` with browser "
            "tests (false for visual/manual-only work), and a short `reason` (max 15 words). "
            "Return one item per ticket, same keys.\n\n"
            f"```json\n{json.dumps(items, ensure_ascii=False, indent=1)}\n```"
        )

    async def classify(self, tickets: list[Ticket]) -> list[Classification]:
        if not tickets:
            return []
        result, _ = await ask_json(self.options, self.prompt(tickets), ClassificationSet,
                                   tools=[])
        known = {t.ref.key for t in tickets}
        items = [c for c in result.items if c.key in known]
        for item in items:
            item.source = "claude"
        return items
