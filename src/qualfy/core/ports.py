"""Adapter contracts. Each adapter class declares `kind` and an `Options` dataclass."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable

from qualfy.core.events import RunEmitter
from qualfy.core.models import (
    AgentReport,
    Analysis,
    AutomationResult,
    Classification,
    SpecSummary,
    TestSpec,
    Ticket,
)
from qualfy.core.schema import field


class Adapter(Protocol):
    kind: ClassVar[str]
    Options: ClassVar[type]

    def __init__(self, options: Any) -> None: ...


@runtime_checkable
class SourceAdapter(Adapter, Protocol):
    """Fetches tickets from a tracker and normalizes them into a TestSpec."""

    async def discover(self) -> list[SpecSummary]: ...

    async def fetch(self, key: str) -> Any: ...

    async def ticket(self, raw: Any) -> Ticket: ...

    async def normalize(self, raw: Any) -> TestSpec: ...


@runtime_checkable
class TriageSource(Protocol):
    """Optional source capability used by `qualfy classify`."""

    async def triage_candidates(self, limit: int = 50) -> list[Ticket]: ...

    def existing_urgency(self, ticket: Ticket) -> Classification | None: ...

    async def apply_classification(self, ticket: Ticket, item: Classification) -> None: ...


@runtime_checkable
class SinkAdapter(Adapter, Protocol):
    """Publishes a result. `interactive` sinks get a draft the user reviews before posting."""

    interactive: ClassVar[bool]

    def draft(self, spec: TestSpec, result: AutomationResult) -> str: ...

    async def publish(self, spec: TestSpec, result: AutomationResult, body: str) -> str | None: ...


@dataclass
class AgentContext:
    run_id: str
    run_dir: Path
    report_path: Path
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class AgentRun:
    report: AgentReport | None
    cost_usd: float | None = None
    turns: int | None = None
    error: str | None = None


@runtime_checkable
class AgentAdapter(Adapter, Protocol):
    """Turns a TestSpec into automated tests and returns the agent's report."""

    async def automate(self, spec: TestSpec, ctx: AgentContext, emit: RunEmitter) -> AgentRun: ...


@runtime_checkable
class AnalyzerAdapter(Adapter, Protocol):
    """Reviews a ticket (and its spec when present) and returns cases plus open questions."""

    async def analyze(self, ticket: Ticket, spec: TestSpec | None,
                      emit: RunEmitter) -> Analysis: ...


@runtime_checkable
class ClassifierAdapter(Adapter, Protocol):
    async def classify(self, tickets: list[Ticket]) -> list[Classification]: ...


@runtime_checkable
class HostAdapter(Adapter, Protocol):
    """Code host where the test repository lives; opens pull requests."""

    async def open_pull_request(self, branch: str, title: str, body: str) -> str: ...
