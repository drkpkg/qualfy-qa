import pytest

from qualfy.core.contract import build_spec, extract_contract, load_contract
from qualfy.core.errors import ContractError
from qualfy.core.models import CaseResult, CaseStatus, Ref, RunStatus, derive_status

REF = Ref(system="jira", key="PROJ-1")

CONTRACT = """
spec: PROJ-0
cases:
  - id: TC-1
    title: Happy path
    priority: high
    preconditions: single string
    steps:
      - Open page
      - action: Submit
        expected: [Saved]
"""


def test_build_spec_coerces_steps_and_lists():
    spec = build_spec(load_contract(CONTRACT), ref=REF, title="Title", generator="rovo")
    case = spec.cases[0]
    assert [s.action for s in case.steps] == ["Open page", "Submit"]
    assert case.steps[1].expected == ["Saved"]
    assert case.preconditions == ["single string"]
    assert spec.spec_ref == Ref(system="jira", key="PROJ-0")
    assert spec.title == "Title"
    assert spec.generator == "rovo"


def test_revision_is_stable_and_content_sensitive():
    a = build_spec(load_contract(CONTRACT), ref=REF, generator="x")
    b = build_spec(load_contract(CONTRACT), ref=REF, generator="y")
    c = build_spec(load_contract(CONTRACT.replace("Submit", "Send")), ref=REF, generator="x")
    assert a.revision == b.revision != c.revision


def test_extract_skips_non_contract_blocks():
    text = f"intro\n```yaml\nfoo: bar\n```\nthen\n```yaml\n{CONTRACT}\n```"
    assert extract_contract(text)["spec"] == "PROJ-0"


@pytest.mark.parametrize("bad, message", [
    ("cases: []", "cases"),
    ("cases:\n  - id: TC-1\n    title: x\n    steps: []", "steps"),
    ("cases:\n  - id: TC-1\n    steps: [a]", "title"),
    ("cases:\n  - id: TC-1\n    title: x\n    priority: urgent\n    steps: [a]", "priority"),
])
def test_contract_errors_are_readable(bad, message):
    with pytest.raises(ContractError, match=message):
        build_spec(load_contract(bad), ref=REF, generator="x")


def test_missing_block():
    with pytest.raises(ContractError):
        extract_contract("no yaml here")


@pytest.mark.parametrize("statuses, expected", [
    (["automated", "automated"], RunStatus.SUCCESS),
    (["automated", "failed"], RunStatus.PARTIAL),
    (["failed", "skipped"], RunStatus.FAILED),
    (["skipped"], RunStatus.SKIPPED),
    ([], RunStatus.FAILED),
])
def test_derive_status(statuses, expected):
    cases = [CaseResult(case_id=str(i), status=CaseStatus(s)) for i, s in enumerate(statuses)]
    assert derive_status(cases) == expected
