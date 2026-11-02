import pytest
from rich.console import Console

from qualfy.cli import main as cli
from qualfy.cli.prompts import PromptField
from qualfy.cli.wizard import Wizard
from qualfy.core.models import Question, QuestionKind
from qualfy.core.session import SessionRunner


@pytest.fixture
def run(project_dir, monkeypatch):
    console = Console(record=True, width=160)
    monkeypatch.setattr(cli, "console", console)
    monkeypatch.setattr(cli, "err", console)

    def invoke(*argv: str) -> tuple[int, str]:
        console.export_text(clear=True)
        code = cli.main([*argv, "-c", str(project_dir / "qualfy.yaml")] if argv[0] not in (
            "new",) else list(argv))
        return code, console.export_text(clear=True)

    return invoke


def test_version(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert "qualfy 0.1.0" in capsys.readouterr().out


def test_list_ingest_run_runs(run):
    code, out = run("list")
    assert code == 0 and "EXAMPLE-1" in out
    code, out = run("ingest", "EXAMPLE-1", "--json")
    assert code == 0 and '"TC-1"' in out
    code, out = run("run", "EXAMPLE-1")
    assert code == 0 and "SKIPPED" in out
    assert "EXAMPLE-1" in run("runs")[1]


def test_validate_and_errors(run, project_dir, tmp_path):
    code, out = run("validate", str(project_dir / "specs" / "EXAMPLE-1.md"))
    assert code == 0 and "2/3 automatable" in out
    bad = tmp_path / "bad.yaml"
    bad.write_text("cases:\n  - id: TC-1\n    steps: [x]\n")
    assert run("validate", str(bad))[0] == 1
    code, out = run("ingest", "NOPE")
    assert code == 1 and "not found" in out


def test_new_command(run, tmp_path):
    code, out = run("new", str(tmp_path / "proj"), "--no-git")
    assert code == 0 and "qualfy connect" in out
    assert (tmp_path / "proj" / "qualfy.yaml").exists()
    assert run("new", str(tmp_path / "proj"))[0] == 1


def test_start_non_interactive(run):
    code, out = run("start", "EXAMPLE-1", "--yes", "--answer", "scope=TC-1")
    assert code == 0, out
    assert "SKIPPED" in out and "Cases to automate" in out
    code, out = run("sessions")
    assert "EXAMPLE-1" in out and "done" in out


def test_start_reports_missing_answers(run, project_dir):
    (project_dir / "specs" / "Q-1.md").write_text(
        "# Q\n```yaml\ncases:\n  - id: TC-1\n    title: No expectations\n    steps: [Do]\n```\n")
    code, out = run("start", "Q-1", "--yes")
    assert code == 1 and "tc-1_expected: required" in out


def test_classify_unsupported_source(run):
    code, out = run("classify", "--dry-run")
    assert code == 1 and "does not support classification" in out


def test_adapters_and_schema(run):
    out = run("adapters")[1]
    assert all(k in out for k in ("github-issues", "claude-code", "static", "rules", "github"))
    assert '"questions"' in run("schema", "analysis")[1]


def test_prompt_fields_registry():
    assert {k for k in PromptField.registry} == set(QuestionKind)


@pytest.mark.parametrize("kind, extra, replies, expected", [
    (QuestionKind.CHOICE, {"options": ["staging", "qa"]}, ["2"], "qa"),
    (QuestionKind.MULTI, {"options": ["TC-1", "TC-2"], "default": ["TC-1"]}, ["1,2"],
     ["TC-1", "TC-2"]),
    (QuestionKind.URL, {}, ["nope", "https://x.io"], "https://x.io"),
    (QuestionKind.DATA, {"fields": ["user", "role"]}, ["qa", "admin"],
     {"user": "qa", "role": "admin"}),
    (QuestionKind.CONFIRM, {}, ["y"], True),
])
def test_prompt_fields(kind, extra, replies, expected, monkeypatch):
    console = Console(record=True)
    answers = iter(replies)
    monkeypatch.setattr(console, "input", lambda *a, **k: next(answers))
    question = Question(id="x", kind=kind, label="X", **extra)
    assert PromptField.for_question(question, console).run() == expected


async def test_wizard_inline_flow(service, monkeypatch):
    console = Console(record=True, width=140)
    runner = SessionRunner.open(service, "EXAMPLE-1")
    wizard = Wizard(runner, console, assume_yes=True, publish=False)
    assert await wizard.run() == 0
    text = console.export_text()
    assert "Analysis" in text and "Answers" in text and "SKIPPED" in text
