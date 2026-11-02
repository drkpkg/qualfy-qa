from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from qualfy.adapters.claude_cli import ClaudeOptions, ask_json
from qualfy.core.events import RunEmitter
from qualfy.core.models import Analysis, QuestionKind, TestSpec, Ticket
from qualfy.core.schema import dumps

KINDS = ", ".join(k.value for k in QuestionKind)


@dataclass
class ClaudeAnalyzerOptions(ClaudeOptions):
    max_questions: int = 8


class ClaudeAnalyzer:
    """Claude reads the ticket and the test repo (read-only) and returns cases + questions."""

    kind: ClassVar[str] = "claude"
    Options: ClassVar[type] = ClaudeAnalyzerOptions

    def __init__(self, options: ClaudeAnalyzerOptions) -> None:
        self.options = options

    def prompt(self, ticket: Ticket, spec: TestSpec | None) -> str:
        parts = [
            "You are a senior QA engineer preparing a ticket for test automation in this "
            "repository. Read the repository conventions (CLAUDE.md, existing tests, page "
            "objects, fixtures) with your read-only tools before answering.",
            f"## Ticket {ticket.ref}\nTitle: {ticket.title}\n\n{ticket.body.strip() or '(empty)'}",
        ]
        if spec is not None:
            parts.append("## Reviewed test specification\n"
                         f"```json\n{dumps(spec, exclude={'revision', 'clarifications'})}\n```\n"
                         "Do not rewrite these cases; return `cases` as an empty list.")
        else:
            parts.append("## No test specification\nThe ticket has no test contract. Derive "
                         "concrete test cases from it in `cases` (ids TC-1, TC-2, …; each with "
                         "steps and expected results; mark visual or manual-only checks "
                         "`automatable: false`).")
        parts.append(
            "## Questions\n"
            f"Ask at most {self.options.max_questions} questions, only about things that block "
            "writing reliable tests and that you cannot find in the repo: ambiguous expected "
            "results, missing test data, roles, environments, feature flags, external services. "
            f"Use the `kind` that fits the answer ({KINDS}): `choice`/`multi` need `options`, "
            "`data` needs `fields`, use `secret` for passwords or tokens, `confirm` for yes/no. "
            "Set `case_id` when a question concerns one case and a sensible `default` when you "
            "can. Do not ask which cases to automate or for the base URL; those are asked "
            "already.\n\nAlso return a one-paragraph `summary` and notable `risks`.")
        return "\n\n".join(parts)

    async def analyze(self, ticket: Ticket, spec: TestSpec | None, emit: RunEmitter) -> Analysis:
        await emit("log", f"Analyzing {ticket.ref} with Claude…")
        analysis, cost = await ask_json(self.options, self.prompt(ticket, spec), Analysis)
        if cost is not None:
            await emit("log", f"analysis cost ${cost:.2f}", cost_usd=cost)
        analysis.questions = analysis.questions[: self.options.max_questions]
        return analysis
