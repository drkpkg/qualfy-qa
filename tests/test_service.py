import asyncio
from pathlib import Path

import pytest

from qualfy.core.config import AdapterConfig, load_config, save_config
from qualfy.core.errors import AdapterNotFound, ConfigError
from qualfy.core.events import Event
from qualfy.core.models import RunStatus
from qualfy.core.service import AutomationService


async def test_discover_and_ingest(service: AutomationService):
    items = await service.discover()
    assert [i.ref.key for i in items] == ["EXAMPLE-1"]
    spec = await service.ingest("EXAMPLE-1")
    assert spec.ref.key == "EXAMPLE-1" and spec.framework == "playwright"
    assert len(spec.automatable_cases) == 2


async def test_ingest_ticket_without_contract(service: AutomationService, project_dir: Path):
    (project_dir / "specs" / "FREE-1.md").write_text("# Free text\n\nNo contract here.")
    ingested = await service.ingest_ticket("FREE-1")
    assert ingested.spec is None and "no fenced YAML" in (ingested.contract_error or "")
    assert ingested.ticket.title == "Free text"


async def test_dry_run_pipeline_persists_everything(service: AutomationService, project_dir: Path):
    events: list[Event] = []
    service.bus.subscribe(events.append)
    result = await service.run("EXAMPLE-1")

    assert result.status == RunStatus.SKIPPED
    kinds = [e.kind for e in events]
    assert kinds[0] == "run.started" and "run.finished" in kinds
    run_dir = project_dir / ".qualfy" / "runs" / result.run_id
    assert {p.name for p in run_dir.iterdir()} >= {"meta.json", "spec.json", "result.json",
                                                   "events.jsonl", "report.json"}
    assert service.store.list_runs()[0].status == "skipped"
    assert service.store.load_events(result.run_id)[0].kind == "run.started"
    assert list((project_dir / ".qualfy" / "results").glob("markdown-EXAMPLE-1-*.json"))


async def test_failing_sink_does_not_block_others(service: AutomationService):
    class Boom:
        interactive = False

        def draft(self, spec, result):
            return ""

        async def publish(self, spec, result, body):
            raise RuntimeError("down")

    project = service.project()
    project.sinks = {"boom": Boom(), **project.sinks}
    spec = await service.ingest("EXAMPLE-1")
    result = await service.automate(spec)
    assert await service.report(spec, result) == {"boom": "down", "results": None}


async def test_rereport(service: AutomationService):
    result = await service.run("EXAMPLE-1", report=False)
    assert await service.rereport(result.run_id) == {"results": None}


async def test_missing_agent_workdir_becomes_error_result(service: AutomationService):
    service.config.agents["claude"].options["workdir"] = "does-not-exist"
    service.config.projects["default"].agent = "claude"
    result = await service.run("EXAMPLE-1")
    assert result.status == RunStatus.ERROR and "workdir" in (result.error or "")


async def test_bus_stream(service: AutomationService):
    spec = await service.ingest("EXAMPLE-1")
    received: list[str] = []

    async def consume():
        async for event in service.bus.stream():
            received.append(event.kind)
            if event.kind == "run.finished":
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await service.run(spec)
    await asyncio.wait_for(task, 1)
    assert received[0] == "run.started"


def test_secret_and_env_interpolation(service: AutomationService, monkeypatch):
    service.config.sources["jira"] = AdapterConfig(kind="jira-rovo", options={
        "base_url": "${JIRA_URL}", "email": "a@b.c", "token": "${secret:jira_token}"})
    monkeypatch.setenv("JIRA_URL", "https://x.atlassian.net")
    with pytest.raises(ConfigError, match="secret 'jira_token'"):
        service.build("sources", "jira")
    service.secrets.set("jira_token", "t0k")
    source = service.build("sources", "jira")
    assert source.client.base_url == "https://x.atlassian.net"
    monkeypatch.setenv("QUALFY_SECRET_JIRA_TOKEN", "from-env")
    assert service.secrets.get("jira_token") == "from-env"


def test_unknown_kind_and_bad_options(service: AutomationService):
    with pytest.raises(AdapterNotFound, match="nope"):
        service.registry.build("sinks", "x", AdapterConfig(kind="nope"))
    with pytest.raises(ConfigError, match="unexpected"):
        service.registry.build("sinks", "x", AdapterConfig(kind="json-file",
                                                            options={"unexpected": 1}))


def test_config_reference_validation(project_dir: Path):
    path = project_dir / "qualfy.yaml"
    path.write_text(path.read_text().replace("sinks: [results]", "sinks: [missing]"))
    with pytest.raises(ConfigError, match="unknown sink 'missing'"):
        load_config(path)


def test_config_save_round_trip(project_dir: Path):
    config = load_config(project_dir / "qualfy.yaml")
    save_config(config)
    again = load_config(project_dir / "qualfy.yaml")
    assert again.projects == config.projects and again.sources == config.sources
    assert again.name == "test-project"
