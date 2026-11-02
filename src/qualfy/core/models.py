from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from qualfy.core.schema import field, to_dict

SCHEMA_VERSION = "1"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Ref:
    system: str
    key: str
    url: str | None = None

    def __str__(self) -> str:
        return f"{self.system}:{self.key}"


@dataclass
class Step:
    action: str
    expected: list[str] = field(default_factory=list)


def _as_list(value: Any) -> Any:
    return [value] if isinstance(value, str) else value


@dataclass
class TestCase:
    __test__ = False

    id: str
    title: str
    steps: list[Step] = field(min_items=1)
    priority: Priority = Priority.MEDIUM
    automatable: bool = True
    tags: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    expected: list[str] = field(default_factory=list)

    @staticmethod
    def __coerce__(data: dict[str, Any]) -> dict[str, Any]:
        if isinstance(data.get("steps"), list):
            data["steps"] = [{"action": s} if isinstance(s, str) else s for s in data["steps"]]
        for key in ("preconditions", "expected", "tags"):
            if key in data:
                data[key] = _as_list(data[key])
        if isinstance(data.get("id"), int):
            data["id"] = str(data["id"])
        return data


@dataclass
class TestSpec:
    __test__ = False

    ref: Ref
    title: str
    cases: list[TestCase] = field(min_items=1)
    schema_version: str = SCHEMA_VERSION
    spec_ref: Ref | None = None
    generator: str = "unknown"
    framework: str | None = None
    clarifications: dict[str, Any] = field(default_factory=dict)
    revision: str = ""

    def __post_init__(self) -> None:
        if not self.revision:
            self.revision = self.compute_revision()

    def compute_revision(self) -> str:
        payload = json.dumps(to_dict(self.cases), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]

    @property
    def automatable_cases(self) -> list[TestCase]:
        return [c for c in self.cases if c.automatable]


@dataclass
class Ticket:
    """Raw tracker item, before (or without) a test contract."""

    ref: Ref
    title: str
    body: str = ""
    labels: list[str] = field(default_factory=list)
    status: str | None = None
    priority: str | None = None
    created_at: datetime | None = None


@dataclass
class SpecSummary:
    ref: Ref
    title: str
    status: str | None = None


# ---- analysis & clarification -----------------------------------------------------------------


class QuestionKind(StrEnum):
    CONFIRM = "confirm"
    CHOICE = "choice"
    MULTI = "multi"
    TEXT = "text"
    URL = "url"
    SECRET = "secret"
    DATA = "data"


@dataclass
class Question:
    """A typed question the UI renders as a matching input widget."""

    id: str
    kind: QuestionKind
    label: str
    help: str = ""
    options: list[str] = field(default_factory=list, description="choice/multi options")
    fields: list[str] = field(default_factory=list, description="data: field names to fill")
    default: Any = None
    required: bool = True
    case_id: str | None = None


@dataclass
class Analysis:
    """Analyzer output: refined or generated cases plus open questions."""

    __extra__ = "ignore"

    summary: str
    questions: list[Question] = field(default_factory=list)
    cases: list[TestCase] = field(
        default_factory=list, description="Generated cases when the ticket had no test contract"
    )
    risks: list[str] = field(default_factory=list)


# ---- classification ---------------------------------------------------------------------------


class Urgency(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


@dataclass
class Classification:
    __extra__ = "ignore"

    key: str
    urgency: Urgency
    reason: str
    impact: Priority = Priority.MEDIUM
    automatable: bool = True
    source: str = "classifier"


@dataclass
class ClassificationSet:
    __extra__ = "ignore"

    items: list[Classification]


# ---- results ----------------------------------------------------------------------------------


class CaseStatus(StrEnum):
    AUTOMATED = "automated"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class FailureKind(StrEnum):
    TEST = "test"
    APP = "app"
    ENV = "env"


@dataclass
class BugReport:
    title: str
    description: str
    case_id: str


@dataclass
class CaseResult:
    case_id: str
    status: CaseStatus
    test_file: str | None = None
    test_name: str | None = None
    failure_kind: FailureKind | None = None
    notes: str = ""


class RunStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class AgentReport:
    """What the agent must write as its final output."""

    __extra__ = "ignore"

    summary: str
    cases: list[CaseResult]
    files: list[str] = field(default_factory=list)
    branch: str | None = None
    pr_url: str | None = None
    bugs: list[BugReport] = field(default_factory=list)


@dataclass
class AutomationResult:
    run_id: str
    spec_ref: Ref
    spec_revision: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime
    summary: str = ""
    cases: list[CaseResult] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    branch: str | None = None
    pr_url: str | None = None
    bugs: list[BugReport] = field(default_factory=list)
    cost_usd: float | None = None
    turns: int | None = None
    error: str | None = None

    @classmethod
    def from_report(cls, *, run_id: str, spec: TestSpec, report: AgentReport,
                    started_at: datetime, **extra: Any) -> AutomationResult:
        return cls(
            run_id=run_id, spec_ref=spec.ref, spec_revision=spec.revision,
            status=derive_status(report.cases), started_at=started_at,
            finished_at=extra.pop("finished_at", None) or utcnow(),
            summary=report.summary, cases=report.cases, files=report.files,
            branch=report.branch, pr_url=report.pr_url, bugs=report.bugs, **extra,
        )

    @classmethod
    def failure(cls, *, run_id: str, spec: TestSpec, error: str, started_at: datetime,
                **extra: Any) -> AutomationResult:
        return cls(run_id=run_id, spec_ref=spec.ref, spec_revision=spec.revision,
                   status=RunStatus.ERROR, error=error, started_at=started_at,
                   finished_at=utcnow(), **extra)


def derive_status(cases: list[CaseResult]) -> RunStatus:
    relevant = [c for c in cases if c.status != CaseStatus.SKIPPED]
    if not relevant:
        return RunStatus.SKIPPED if cases else RunStatus.FAILED
    automated = sum(c.status == CaseStatus.AUTOMATED for c in relevant)
    if automated == len(relevant):
        return RunStatus.SUCCESS
    return RunStatus.PARTIAL if automated else RunStatus.FAILED


# ---- sessions ---------------------------------------------------------------------------------


class SessionState(StrEnum):
    NEW = "new"
    ANALYZED = "analyzed"
    CLARIFIED = "clarified"
    AUTOMATED = "automated"
    DONE = "done"


@dataclass
class Session:
    """Persisted progress of `qualfy start KEY`, so a session can resume where it stopped."""

    key: str
    project: str
    state: SessionState = SessionState.NEW
    spec: TestSpec | None = None
    analysis: Analysis | None = None
    answers: dict[str, Any] = field(default_factory=dict)
    result: AutomationResult | None = None
    drafts: dict[str, str] = field(default_factory=dict)
    published: dict[str, str] = field(default_factory=dict)
    pr_url: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
