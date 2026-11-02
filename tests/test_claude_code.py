import json
from pathlib import Path

from qualfy.core.config import AdapterConfig
from qualfy.core.events import Event
from qualfy.core.models import CaseStatus, RunStatus
from qualfy.core.service import AutomationService


def use_fake(service: AutomationService, fake: Path, workdir: Path, **options) -> None:
    service.config.agents["claude"] = AdapterConfig(kind="claude-code", options={
        "binary": str(fake), "workdir": str(workdir), "max_budget_usd": 2,
        "allowed_tools": ["Read", "Bash(npx playwright:*)"], **options})
    service.config.projects["default"].agent = "claude"


async def test_claude_code_agent_end_to_end(service, fake_claude, tmp_path):
    workdir = tmp_path / "e2e"
    workdir.mkdir()
    use_fake(service, fake_claude, workdir, model="some-model")
    events: list[Event] = []
    service.bus.subscribe(events.append)

    spec = await service.ingest("EXAMPLE-1")
    spec.clarifications = {"Which environment?": "staging"}
    result = await service.automate(spec, env={"BASE_URL": "https://staging.example.com"})

    assert result.status == RunStatus.PARTIAL
    assert [c.status for c in result.cases] == [CaseStatus.AUTOMATED, CaseStatus.FAILED]
    assert result.cases[1].failure_kind == "app"
    assert result.cost_usd == 0.42 and result.turns == 7 and result.branch == "qa/EXAMPLE-1"
    assert [e.message for e in events if e.kind == "agent.tool"] == ["Bash npx playwright test"]

    args = json.loads(Path(str(fake_claude) + ".args").read_text())
    assert args[:4] == ["-p", "--output-format", "stream-json", "--verbose"]
    assert args[args.index("--model") + 1] == "some-model"
    assert args[args.index("--max-budget-usd") + 1] == "2.0"
    assert args[-3:] == ["--allowedTools", "Read", "Bash(npx playwright:*)"]
    env = json.loads(Path(str(fake_claude) + ".env").read_text())
    assert env["BASE_URL"] == "https://staging.example.com"

    prompt = (service.store.run_dir(result.run_id) / "prompt.md").read_text()
    assert "Never weaken" in prompt and "qa/EXAMPLE-1" in prompt
    assert "**Which environment?**: staging" in prompt and "`BASE_URL`" in prompt


async def test_missing_report_is_error(service, tmp_path):
    fake = tmp_path / "silent-claude"
    fake.write_text("#!/bin/sh\ncat >/dev/null\necho '{\"type\":\"result\",\"is_error\":false}'\n")
    fake.chmod(0o755)
    use_fake(service, fake, tmp_path)
    result = await service.run("EXAMPLE-1")
    assert result.status == RunStatus.ERROR and "did not write its report" in (result.error or "")


async def test_nonzero_exit_surfaces_stderr(service, tmp_path):
    fake = tmp_path / "broken-claude"
    fake.write_text("#!/bin/sh\ncat >/dev/null\necho 'auth required' >&2\nexit 3\n")
    fake.chmod(0o755)
    use_fake(service, fake, tmp_path)
    result = await service.run("EXAMPLE-1")
    assert result.status == RunStatus.ERROR and "auth required" in (result.error or "")
