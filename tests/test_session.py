import json
from pathlib import Path

import pytest

from qualfy.core.config import AdapterConfig
from qualfy.core.errors import SessionError
from qualfy.core.models import Analysis, QuestionKind, SessionState, Step, TestCase
from qualfy.core.session import SessionRunner


class FakeHost:
    kind = "fake"
    interactive = False

    def __init__(self):
        self.calls = []

    async def open_pull_request(self, branch, title, body):
        self.calls.append((branch, title, body))
        return "https://github.com/acme/e2e/pull/7"


class FakeCommentSink:
    kind = "fake-comment"
    interactive = True

    def __init__(self):
        self.posted = []

    def draft(self, spec, result):
        return f"Run {result.run_id}: {result.status.value}"

    async def publish(self, spec, result, body):
        self.posted.append(body)
        return "https://tracker/comment/1"


def use_claude(service, fake_claude, tmp_path):
    workdir = tmp_path / "repo"
    workdir.mkdir(exist_ok=True)
    service.config.agents["claude"] = AdapterConfig(kind="claude-code", options={
        "binary": str(fake_claude), "workdir": str(workdir)})
    service.config.projects["default"].agent = "claude"


async def test_full_session(service, fake_claude, tmp_path):
    use_claude(service, fake_claude, tmp_path)
    project = service.project()
    host, sink = FakeHost(), FakeCommentSink()
    project.host = host
    project.sinks["tracker"] = sink

    runner = SessionRunner.open(service, "EXAMPLE-1")
    analysis = await runner.analyze()
    assert runner.state == SessionState.ANALYZED and "2 automatable" in analysis.summary

    questions = {q.id: q for q in runner.questions()}
    assert questions["scope"].kind == QuestionKind.MULTI
    assert questions["scope"].default == ["TC-1", "TC-2"]
    assert questions["test_password"].kind == QuestionKind.SECRET

    errors = runner.answer({"base_url": "not-a-url"})
    assert errors == {"base_url": "expected an http(s) URL"}
    assert runner.answer({"base_url": "https://staging.example.com", "scope": "TC-1,TC-2",
                          "test_user": "username=qa,role=admin", "test_password": "pw"}) == {}
    assert runner.state == SessionState.CLARIFIED
    assert runner.spec.clarifications["Test user for these cases"] == {"username": "qa",
                                                                        "role": "admin"}
    assert "test_password" not in runner.session.answers  # secrets never persisted

    resumed = SessionRunner.open(service, "EXAMPLE-1")
    assert resumed.state == SessionState.CLARIFIED

    result = await resumed.automate()
    assert result.status.value == "partial" and resumed.state == SessionState.AUTOMATED
    env = json.loads(Path(str(fake_claude) + ".env").read_text())
    assert env["QUALFY_ANSWER_TEST_PASSWORD"] == "pw"
    assert env["BASE_URL"] == "https://staging.example.com"
    assert list(resumed.session.drafts) == ["tracker"]

    assert resumed.can_open_pr()
    url = await resumed.open_pr()
    branch, title, body = host.calls[0]
    assert branch == "qa/EXAMPLE-1" and "EXAMPLE-1" in title and "| TC-1 | automated |" in body
    assert url in resumed.session.drafts["tracker"] and not resumed.can_open_pr()

    resumed.update_draft("tracker", resumed.session.drafts["tracker"] + "\nEdited by QA")
    assert await resumed.publish("tracker") == "https://tracker/comment/1"
    assert sink.posted[0].endswith("Edited by QA")
    resumed.finish()
    assert service.store.load_session("EXAMPLE-1").state == SessionState.DONE


async def test_scope_marks_cases_out(service):
    runner = SessionRunner.open(service, "EXAMPLE-1")
    await runner.analyze()
    assert runner.answer({"scope": ["TC-2"]}) == {}
    assert [c.id for c in runner.spec.automatable_cases] == ["TC-2"]
    result = await runner.automate()
    assert {c.case_id: c.notes for c in result.cases}["TC-1"] == "out of scope"


async def test_ticket_without_contract_needs_generated_cases(service, project_dir):
    (project_dir / "specs" / "FREE-1.md").write_text("# Checkout\n\nUsers pay with card.")
    runner = SessionRunner.open(service, "FREE-1")
    with pytest.raises(SessionError, match="no test contract"):
        await runner.analyze()

    class GeneratingAnalyzer:
        kind = "gen"

        async def analyze(self, ticket, spec, emit):
            case = TestCase(id="TC-1", title="Pay", steps=[Step(action="Pay")])
            return Analysis(summary="generated", cases=[case])

    gen = GeneratingAnalyzer()
    service.project().analyzer = gen
    await runner.analyze()
    assert runner.spec.cases[0].title == "Pay" and runner.spec.generator == "gen"


async def test_restart_discards_session(service):
    runner = SessionRunner.open(service, "EXAMPLE-1")
    await runner.analyze()
    assert SessionRunner.open(service, "EXAMPLE-1", restart=True).state == SessionState.NEW
