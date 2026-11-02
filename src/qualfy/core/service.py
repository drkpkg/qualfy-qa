from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qualfy.core.config import Config, ProjectConfig, find_config, load_config
from qualfy.core.errors import ConfigError, ContractError, QualfyError
from qualfy.core.events import EventBus, RunEmitter
from qualfy.core.models import AutomationResult, SpecSummary, TestSpec, Ticket, utcnow
from qualfy.core.ports import (
    AgentAdapter,
    AgentContext,
    AnalyzerAdapter,
    ClassifierAdapter,
    HostAdapter,
    SinkAdapter,
    SourceAdapter,
)
from qualfy.core.registry import Registry, Slot, default_registry
from qualfy.core.secrets import Secrets
from qualfy.core.store import RunStore


@dataclass
class Project:
    name: str
    config: ProjectConfig
    source: SourceAdapter
    agent: AgentAdapter
    sinks: dict[str, SinkAdapter]
    analyzer: AnalyzerAdapter | None = None
    classifier: ClassifierAdapter | None = None
    host: HostAdapter | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Ingested:
    ticket: Ticket
    spec: TestSpec | None
    contract_error: str | None = None


class AutomationService:
    """Application facade. CLI, TUI and the future HTTP API all drive the pipeline through this."""

    def __init__(self, config: Config, registry: Registry | None = None,
                 bus: EventBus | None = None, store: RunStore | None = None,
                 secrets: Secrets | None = None) -> None:
        self.config = config
        self.registry = registry or default_registry()
        self.bus = bus or EventBus()
        self.store = store or RunStore(config.workspace_dir)
        self.secrets = secrets or Secrets(config.name)
        self.bus.subscribe(self.store.append_event)
        self._projects: dict[str, Project] = {}

    @classmethod
    def from_file(cls, path: Path | None = None, **kwargs: Any) -> AutomationService:
        return cls(load_config(path or find_config()), **kwargs)

    @property
    def root(self) -> Path:
        return self.config.base_dir

    def build(self, slot: Slot, name: str) -> Any:
        return self.registry.build(slot, name, getattr(self.config, slot)[name],
                                   base_dir=self.config.base_dir, secrets=self.secrets.get)

    def project(self, name: str | None = None) -> Project:
        name, cfg = self.config.project(name)
        if name not in self._projects:
            self._projects[name] = Project(
                name=name,
                config=cfg,
                source=self.build("sources", cfg.source),
                agent=self.build("agents", cfg.agent),
                sinks={s: self.build("sinks", s) for s in cfg.sinks},
                analyzer=self.build("analyzers", cfg.analyzer) if cfg.analyzer else None,
                classifier=self.build("classifiers", cfg.classifier) if cfg.classifier else None,
                host=self.build("hosts", cfg.host) if cfg.host else None,
            )
        return self._projects[name]

    # ---- pipeline steps ----------------------------------------------------------------------

    async def discover(self, project: str | None = None) -> list[SpecSummary]:
        return await self.project(project).source.discover()

    async def ingest_ticket(self, key: str, project: str | None = None) -> Ingested:
        """Fetch a ticket; the spec is None when the ticket has no (valid) test contract."""
        proj = self.project(project)
        raw = await proj.source.fetch(key)
        ticket = await proj.source.ticket(raw)
        try:
            spec = await proj.source.normalize(raw)
        except ContractError as exc:
            return Ingested(ticket=ticket, spec=None, contract_error=str(exc))
        if spec.framework is None and proj.config.framework:
            spec.framework = proj.config.framework
        return Ingested(ticket=ticket, spec=spec)

    async def ingest(self, key: str, project: str | None = None) -> TestSpec:
        ingested = await self.ingest_ticket(key, project)
        if ingested.spec is None:
            raise ContractError(ingested.contract_error or f"{key} has no test contract")
        return ingested.spec

    async def automate(self, spec: TestSpec, project: str | None = None, *,
                       env: dict[str, str] | None = None) -> AutomationResult:
        proj = self.project(project)
        record = self.store.new_run(proj.name, spec)
        run_id = record.run_id
        emit = RunEmitter(self.bus, run_id)
        started = record.started_at or utcnow()
        run_dir = self.store.run_dir(run_id)

        await emit("run.started", f"Automating {spec.ref} ({len(spec.automatable_cases)} cases)",
                   project=proj.name, spec_ref=str(spec.ref))
        await emit("stage.started", "agent", stage="agent", agent=type(proj.agent).kind)
        try:
            ctx = AgentContext(run_id=run_id, run_dir=run_dir, report_path=run_dir / "report.json",
                               env=env or {})
            outcome = await proj.agent.automate(spec, ctx, emit)
        except asyncio.CancelledError:
            self.store.save_result(AutomationResult.failure(
                run_id=run_id, spec=spec, error="cancelled", started_at=started))
            raise
        except QualfyError as exc:
            await emit("stage.failed", str(exc), stage="agent")
            result = AutomationResult.failure(run_id=run_id, spec=spec, error=str(exc),
                                              started_at=started)
        else:
            extra = {"cost_usd": outcome.cost_usd, "turns": outcome.turns}
            if outcome.report is None:
                error = outcome.error or "agent produced no report"
                await emit("stage.failed", error, stage="agent")
                result = AutomationResult.failure(run_id=run_id, spec=spec, error=error,
                                                  started_at=started, **extra)
            else:
                await emit("stage.finished", "agent", stage="agent")
                result = AutomationResult.from_report(
                    run_id=run_id, spec=spec, report=outcome.report, started_at=started,
                    error=outcome.error, **extra)

        self.store.save_result(result)
        await self.bus.emit("run.finished", result.status.value, run_id=run_id,
                            status=result.status.value)
        return result

    def drafts(self, spec: TestSpec, result: AutomationResult,
               project: str | None = None) -> dict[str, str]:
        return {name: sink.draft(spec, result)
                for name, sink in self.project(project).sinks.items() if sink.interactive}

    async def publish(self, sink_name: str, spec: TestSpec, result: AutomationResult, body: str,
                      project: str | None = None) -> str | None:
        sink = self.project(project).sinks[sink_name]
        emit = RunEmitter(self.bus, result.run_id)
        await emit("stage.started", f"sink:{sink_name}", stage="sink", sink=sink_name)
        try:
            location = await sink.publish(spec, result, body)
        except Exception as exc:
            await emit("stage.failed", f"sink:{sink_name}: {exc}", stage="sink", sink=sink_name)
            raise
        await emit("stage.finished", f"sink:{sink_name}", stage="sink", sink=sink_name)
        return location

    async def publish_automatic(self, spec: TestSpec, result: AutomationResult,
                                project: str | None = None) -> dict[str, str | None]:
        """Publish non-interactive sinks (files, dashboards). Returns sink -> error."""
        return await self._fan_out(spec, result, project, interactive=False)

    async def report(self, spec: TestSpec, result: AutomationResult,
                     project: str | None = None) -> dict[str, str | None]:
        """Publish every sink with its default draft. A failing sink never blocks the others."""
        return await self._fan_out(spec, result, project, interactive=None)

    async def _fan_out(self, spec: TestSpec, result: AutomationResult, project: str | None,
                       interactive: bool | None) -> dict[str, str | None]:
        outcomes: dict[str, str | None] = {}
        for name, sink in self.project(project).sinks.items():
            if interactive is not None and sink.interactive != interactive:
                continue
            try:
                await self.publish(name, spec, result, sink.draft(spec, result), project)
            except Exception as exc:
                outcomes[name] = str(exc)
            else:
                outcomes[name] = None
        return outcomes

    async def open_pull_request(self, branch: str, title: str, body: str,
                                project: str | None = None) -> str:
        host = self.project(project).host
        if host is None:
            raise ConfigError("no code host configured for pull requests (run `qualfy connect`)")
        return await host.open_pull_request(branch, title, body)

    async def run(self, target: str | TestSpec, project: str | None = None, *,
                  report: bool = True) -> AutomationResult:
        spec = target if isinstance(target, TestSpec) else await self.ingest(target, project)
        result = await self.automate(spec, project)
        if report:
            await self.report(spec, result, project)
        return result

    async def rereport(self, run_id: str, project: str | None = None) -> dict[str, str | None]:
        result = self.store.load_result(run_id)
        if result is None:
            raise QualfyError(f"run {run_id} has no result")
        project = project or self.store.load_meta(run_id).project
        return await self.report(self.store.load_spec(run_id), result, project)
