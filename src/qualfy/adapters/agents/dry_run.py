from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from qualfy.core.events import RunEmitter
from qualfy.core.models import AgentReport, CaseResult, CaseStatus, TestSpec
from qualfy.core.ports import AgentContext, AgentRun
from qualfy.core.schema import dumps


@dataclass
class DryRunOptions:
    pass


class DryRunAgent:
    """Walks the pipeline without calling any model. Every case is reported skipped."""

    kind: ClassVar[str] = "dry-run"
    Options: ClassVar[type] = DryRunOptions

    def __init__(self, options: DryRunOptions) -> None:
        self.options = options

    async def automate(self, spec: TestSpec, ctx: AgentContext, emit: RunEmitter) -> AgentRun:
        cases = []
        for case in spec.cases:
            await emit("agent.message", f"[dry-run] would automate {case.id}: {case.title}",
                       case_id=case.id)
            cases.append(CaseResult(case_id=case.id, status=CaseStatus.SKIPPED,
                                    notes="dry run" if case.automatable else "out of scope"))
        report = AgentReport(summary=f"Dry run over {len(spec.cases)} cases", cases=cases)
        ctx.report_path.write_text(dumps(report))
        return AgentRun(report=report, cost_usd=0.0, turns=0)
