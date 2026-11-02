from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from qualfy.core.events import RunEmitter
from qualfy.core.models import Analysis, Question, QuestionKind, TestSpec, Ticket

CREDENTIAL_RE = re.compile(r"\b(log ?in|sign ?in|password|credential|user(name)?)\b", re.I)


@dataclass
class StaticAnalyzerOptions:
    ask_credentials: bool = True


class StaticAnalyzer:
    """Rule-based review, no model calls: flags cases without expected results and missing data."""

    kind: ClassVar[str] = "static"
    Options: ClassVar[type] = StaticAnalyzerOptions

    def __init__(self, options: StaticAnalyzerOptions) -> None:
        self.options = options

    async def analyze(self, ticket: Ticket, spec: TestSpec | None, emit: RunEmitter) -> Analysis:
        if spec is None:
            return Analysis(summary=f"{ticket.title}: no test contract; the static analyzer "
                                    "cannot generate cases (configure the claude analyzer).")
        questions: list[Question] = []
        for case in spec.automatable_cases:
            if not case.expected and not any(step.expected for step in case.steps):
                questions.append(Question(
                    id=f"{case.id.lower()}_expected", kind=QuestionKind.TEXT, case_id=case.id,
                    label=f"What is the expected result of {case.id} ({case.title})?"))
        text = " ".join(f"{c.title} {' '.join(s.action for s in c.steps)}" for c in spec.cases)
        if self.options.ask_credentials and CREDENTIAL_RE.search(text):
            questions.append(Question(
                id="test_user", kind=QuestionKind.DATA, fields=["username", "role"],
                label="Test user for these cases", required=False,
                help="The password goes in the next question and is never stored in the spec."))
            questions.append(Question(id="test_password", kind=QuestionKind.SECRET,
                                      label="Password for the test user", required=False))
        summary = (f"{len(spec.cases)} cases, {len(spec.automatable_cases)} automatable, "
                   f"{len(questions)} open question(s).")
        return Analysis(summary=summary, questions=questions)
