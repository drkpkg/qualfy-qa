from __future__ import annotations

import textwrap
from importlib import resources
from pathlib import Path

import pytest

from qualfy.core.secrets import FileStore, Secrets
from qualfy.core.service import AutomationService

CONFIG = """\
name: test-project
workspace: .qualfy
sources:
  local:
    kind: markdown
    options: {path: specs}
sinks:
  results:
    kind: json-file
    options: {path: .qualfy/results}
agents:
  dry:
    kind: dry-run
  claude:
    kind: claude-code
    options: {workdir: .}
analyzers:
  static:
    kind: static
classifiers:
  rules:
    kind: rules
projects:
  default:
    source: local
    agent: dry
    analyzer: static
    classifier: rules
    sinks: [results]
    framework: playwright
"""


def example_spec() -> str:
    path = resources.files("qualfy.templates") / "playwright" / "specs" / "EXAMPLE-1.md"
    return path.read_text()


@pytest.fixture(autouse=True)
def isolated_env(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg")))
    monkeypatch.setenv("QUALFY_SECRET_STORE", "file")
    monkeypatch.delenv("BASE_URL", raising=False)


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    (tmp_path / "specs").mkdir()
    (tmp_path / "qualfy.yaml").write_text(CONFIG)
    (tmp_path / "specs" / "EXAMPLE-1.md").write_text(example_spec())
    return tmp_path


@pytest.fixture
def secrets(tmp_path: Path) -> Secrets:
    return Secrets("test-project", FileStore(tmp_path / "creds.json"))


@pytest.fixture
def service(project_dir: Path, secrets: Secrets) -> AutomationService:
    return AutomationService.from_file(project_dir / "qualfy.yaml", secrets=secrets)


@pytest.fixture
def fake_claude(tmp_path: Path) -> Path:
    """Fake `claude` binary: emits stream-json and writes the report the prompt asks for."""
    script = tmp_path / "fake-claude"
    script.write_text(textwrap.dedent('''\
        #!/usr/bin/env python3
        import json, os, re, sys
        prompt = sys.stdin.read()
        open(sys.argv[0] + ".args", "w").write(json.dumps(sys.argv[1:]))
        open(sys.argv[0] + ".env", "w").write(json.dumps(
            {k: v for k, v in os.environ.items() if k.startswith(("QUALFY_", "BASE_URL"))}))
        report = re.search(r"write a JSON file to `([^`]+)`", prompt).group(1)
        ids = re.findall(r'"id": "(TC-\\d+)"', prompt)
        def out(msg): print(json.dumps(msg), flush=True)
        out({"type": "system", "subtype": "init", "session_id": "s1", "model": "fake"})
        out({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Reading conventions"},
            {"type": "tool_use", "name": "Bash", "input": {"command": "npx playwright test"}},
        ]}})
        cases = [{"case_id": i, "status": "automated", "test_file": "tests/login.spec.ts"}
                 for i in ids[:2]]
        cases[-1].update(status="failed", failure_kind="app", notes="wrong message")
        json.dump({"summary": "done", "cases": cases, "files": ["tests/login.spec.ts"],
                   "branch": "qa/EXAMPLE-1",
                   "bugs": [{"title": "Bad error", "description": "x", "case_id": ids[1]}]},
                  open(report, "w"))
        out({"type": "result", "subtype": "success", "is_error": False,
             "total_cost_usd": 0.42, "num_turns": 7, "result": "ok"})
    '''))
    script.chmod(0o755)
    return script
