import json

import httpx
import pytest

from qualfy.adapters.sinks.github_comment import GitHubCommentOptions, GitHubCommentSink
from qualfy.adapters.sources.github_issues import GitHubIssuesOptions, GitHubIssuesSource
from qualfy.core.errors import ContractError, SinkError, SourceError
from qualfy.core.models import (
    AutomationResult,
    CaseResult,
    CaseStatus,
    FailureKind,
    Ref,
    RunStatus,
    Step,
    TestCase,
    TestSpec,
    utcnow,
)

BODY = """Tests for checkout.

```yaml
spec: shop-40
cases:
  - id: TC-1
    title: Pay with card
    steps: [Add item, Pay]
  - id: TC-2
    title: Pipe | in title
    steps: [Open cart]
```
"""

ISSUE = {"number": 42, "title": "Checkout tests", "body": BODY,
         "html_url": "https://github.com/acme/shop/issues/42",
         "labels": [{"name": "qa:ready"}]}
PULL = {"number": 43, "title": "A PR", "body": "", "pull_request": {}, "labels": []}

OPTS = dict(owner="acme", repo="shop", token="ghp_x")


def transport(requests: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path, method = request.url.path, request.method
        if path == "/repos/acme/shop/issues" and method == "GET":
            return httpx.Response(200, json=[ISSUE, PULL])
        if path == "/repos/acme/shop/issues/42" and method == "GET":
            return httpx.Response(200, json=ISSUE)
        if path == "/repos/acme/shop/issues/42/comments":
            return httpx.Response(201, json={"id": 1})
        if path == "/repos/acme/shop/issues/42/labels":
            return httpx.Response(200, json=[])
        if path.startswith("/repos/acme/shop/issues/42/labels/"):
            return httpx.Response(404 if "missing" in path else 200, json={})
        return httpx.Response(404, text="Not Found")

    return httpx.MockTransport(handler)


async def test_discover_filters_labels_and_pull_requests():
    requests: list[httpx.Request] = []
    source = GitHubIssuesSource(GitHubIssuesOptions(**OPTS), transport=transport(requests))
    items = await source.discover()
    assert [(i.ref.key, i.status) for i in items] == [("shop-42", "qa:ready")]
    assert requests[0].url.params["labels"] == "qa:ready"
    assert requests[0].headers["authorization"] == "Bearer ghp_x"
    assert requests[0].headers["x-github-api-version"] == "2022-11-28"


@pytest.mark.parametrize("key", ["42", "#42", "shop-42", "acme/shop#42"])
async def test_fetch_accepts_key_formats(key):
    source = GitHubIssuesSource(GitHubIssuesOptions(**OPTS), transport=transport([]))
    spec = await source.normalize(await source.fetch(key))
    assert spec.ref == Ref(system="github", key="shop-42",
                           url="https://github.com/acme/shop/issues/42")
    assert spec.title == "Checkout tests"
    assert spec.spec_ref and spec.spec_ref.key == "shop-40"
    assert len(spec.cases) == 2


@pytest.mark.parametrize("key", ["other/repo#42", "abc", "42a"])
async def test_rejects_bad_keys(key):
    source = GitHubIssuesSource(GitHubIssuesOptions(**OPTS), transport=transport([]))
    with pytest.raises(SourceError):
        await source.fetch(key)


async def test_key_prefix_and_empty_body():
    source = GitHubIssuesSource(GitHubIssuesOptions(**OPTS, key_prefix="SHOP"),
                                transport=transport([]))
    assert (await source.normalize(ISSUE)).ref.key == "SHOP-42"
    with pytest.raises(ContractError):
        await source.normalize({**ISSUE, "body": None})


def _result(spec: TestSpec, status: RunStatus) -> AutomationResult:
    return AutomationResult(
        run_id="r1", spec_ref=spec.ref, spec_revision=spec.revision, status=status,
        summary="Done", pr_url="https://github.com/acme/e2e/pull/7", cost_usd=1.5, turns=9,
        started_at=utcnow(), finished_at=utcnow(),
        cases=[CaseResult(case_id="TC-1", status=CaseStatus.AUTOMATED,
                          test_file="tests/pay.spec.ts"),
               CaseResult(case_id="TC-2", status=CaseStatus.FAILED,
                          failure_kind=FailureKind.APP, notes="cart empty")],
    )


async def test_comment_sink_posts_markdown_and_moves_labels():
    requests: list[httpx.Request] = []
    source = GitHubIssuesSource(GitHubIssuesOptions(**OPTS), transport=transport(requests))
    spec = await source.normalize(ISSUE)
    sink = GitHubCommentSink(
        GitHubCommentOptions(**OPTS, labels={"partial": ["qa:needs-review"]},
                             remove_labels=["qa:ready", "missing label"]),
        transport=transport(requests),
    )
    result = _result(spec, RunStatus.PARTIAL)
    await sink.publish(spec, result, sink.draft(spec, result))

    comment, add, remove, remove_missing = requests
    body = json.loads(comment.content)["body"]
    assert "**PARTIAL**" in body
    assert "| ✅ | TC-1 | Pay with card | tests/pay.spec.ts |" in body
    assert "Pipe \\| in title" in body and "**app issue** cart empty" in body
    assert "https://github.com/acme/e2e/pull/7" in body and "$1.50 · 9 turns" in body
    assert json.loads(add.content) == {"labels": ["qa:needs-review"]}
    assert remove.method == "DELETE" and remove.url.path.endswith("/labels/qa:ready")
    assert remove_missing.url.raw_path.endswith(b"/labels/missing%20label")


async def test_comment_sink_skips_labels_for_unmapped_status():
    requests: list[httpx.Request] = []
    source = GitHubIssuesSource(GitHubIssuesOptions(**OPTS), transport=transport([]))
    spec = await source.normalize(ISSUE)
    sink = GitHubCommentSink(GitHubCommentOptions(**OPTS), transport=transport(requests))
    result = _result(spec, RunStatus.SUCCESS)
    await sink.publish(spec, result, sink.draft(spec, result))
    assert [r.method for r in requests] == ["POST"]


async def test_comment_sink_rejects_foreign_tickets():
    sink = GitHubCommentSink(GitHubCommentOptions(**OPTS), transport=transport([]))
    spec = TestSpec(ref=Ref(system="jira", key="PROJ-1"), title="t",
                    cases=[TestCase(id="TC-1", title="x", steps=[Step(action="a")])])
    with pytest.raises(SinkError):
        await sink.publish(spec, _result(spec, RunStatus.SUCCESS), "body")
