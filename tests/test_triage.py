import json

import httpx
import pytest

from qualfy.adapters.classifiers.rules import RulesClassifier, RulesClassifierOptions
from qualfy.adapters.sources.github_issues import GitHubIssuesOptions, GitHubIssuesSource
from qualfy.adapters.sources.jira_rovo import JiraRovoOptions, JiraRovoSource
from qualfy.core import triage
from qualfy.core.config import AdapterConfig
from qualfy.core.errors import ConfigError
from qualfy.core.models import Ref, Ticket, Urgency


def ticket(key, title, body="", labels=(), priority=None):
    return Ticket(ref=Ref(system="github", key=key), title=title, body=body,
                  labels=list(labels), priority=priority)


async def test_rules_classifier():
    rules = RulesClassifier(RulesClassifierOptions())
    results = await rules.classify([
        ticket("a-1", "Checkout crashes on submit"),
        ticket("a-2", "Login error for SSO users"),
        ticket("a-3", "Typo in footer"),
        ticket("a-4", "Add dark mode"),
        ticket("a-5", "Anything", labels=["security"]),
        ticket("a-6", "Review brand look and feel"),
    ])
    assert [r.urgency for r in results] == [Urgency.P0, Urgency.P1, Urgency.P3, Urgency.P2,
                                            Urgency.P0, Urgency.P2]
    assert results[0].reason == "mentions 'crashes'" and results[4].reason == "label 'security'"
    assert results[5].automatable is False


ISSUES = [
    {"number": 1, "title": "Payment fails for Visa", "body": "", "labels": [],
     "html_url": "u1", "state": "open", "created_at": "2026-10-01T10:00:00Z"},
    {"number": 2, "title": "Fix typo", "body": "", "labels": [{"name": "priority:P1"}],
     "html_url": "u2", "state": "open", "created_at": "2026-10-02T10:00:00Z"},
    {"number": 3, "title": "Improve docs", "body": "", "labels": [{"name": "priority:P0"}],
     "html_url": "u3", "state": "open", "created_at": "2026-10-03T10:00:00Z"},
]


def gh_transport(requests):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path.endswith("/issues"):
            return httpx.Response(200, json=ISSUES)
        if request.url.path.endswith("/labels") and request.method == "GET":
            return httpx.Response(200, json=[{"name": "qa:ready"}])
        return httpx.Response(200, json=[])
    return httpx.MockTransport(handler)


async def test_github_triage_respects_existing_labels(service):
    requests = []
    source = GitHubIssuesSource(GitHubIssuesOptions(owner="acme", repo="shop", token="t"),
                                transport=gh_transport(requests))
    project = service.project()
    project.source = source

    items = await triage.classify(service)
    by_key = {i.ticket.ref.key: i for i in items}
    assert [i.ticket.ref.key for i in items] == ["shop-1", "shop-3", "shop-2"]  # by urgency
    assert by_key["shop-1"].classification.urgency == Urgency.P0 and by_key["shop-1"].changes
    assert by_key["shop-2"].existing and not by_key["shop-2"].changes

    forced = await triage.classify(service, force=True)
    assert {i.ticket.ref.key: i.classification.urgency for i in forced}["shop-3"] == Urgency.P3

    requests.clear()
    outcome = await triage.apply(service, items)
    assert outcome == {"shop-1": None}
    add = [r for r in requests if r.method == "POST"]
    assert json.loads(add[0].content) == {"labels": ["priority:P0"]}

    requests.clear()
    shop3 = {i.ticket.ref.key: i for i in forced}["shop-3"]
    await triage.apply(service, [shop3])
    assert [r.method for r in requests] == ["DELETE", "POST"]
    assert requests[0].url.path.endswith("/labels/priority:P0")


async def test_github_ensure_labels():
    requests = []
    source = GitHubIssuesSource(GitHubIssuesOptions(owner="acme", repo="shop", token="t"),
                                transport=gh_transport(requests))
    created = await source.ensure_labels()
    assert created == ["priority:P0", "priority:P1", "priority:P2", "priority:P3"]


async def test_jira_triage_maps_priorities(service):
    issues = [
        {"key": "P-1", "fields": {"summary": "Outage in prod", "priority": {"name": "Medium"},
                                  "description": None, "labels": [], "status": {"name": "To Do"},
                                  "created": "2026-10-01T10:00:00.000+0000"}},
        {"key": "P-2", "fields": {"summary": "Set by Rovo", "priority": {"name": "High"},
                                  "description": None, "labels": [], "status": {"name": "To Do"}}},
    ]
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/search/jql"):
            return httpx.Response(200, json={"issues": issues})
        return httpx.Response(204)

    source = JiraRovoSource(JiraRovoOptions(base_url="https://x.atlassian.net", email="a@b.c",
                                            token="t"), transport=httpx.MockTransport(handler))
    service.project().source = source
    items = await triage.classify(service)
    by_key = {i.ticket.ref.key: i for i in items}
    assert by_key["P-2"].existing and by_key["P-2"].classification.urgency == Urgency.P1
    assert by_key["P-1"].classification.urgency == Urgency.P0
    assert by_key["P-1"].ticket.created_at is not None

    await triage.apply(service, items)
    put = [r for r in requests if r.method == "PUT"]
    assert len(put) == 1 and put[0].url.path.endswith("/issue/P-1")
    assert json.loads(put[0].content) == {"fields": {"priority": {"name": "Highest"}}}


async def test_classifier_override_and_errors(service):
    with pytest.raises(ConfigError, match="does not support classification"):
        await triage.classify(service)

    service.project().source = GitHubIssuesSource(
        GitHubIssuesOptions(owner="acme", repo="shop", token="t"), transport=gh_transport([]))
    service.config.classifiers["lazy"] = AdapterConfig(kind="rules", options={
        "rules": {"P0": [], "P1": [], "P3": []}, "default": "P3"})
    items = await triage.classify(service, classifier="lazy", force=True)
    assert {i.classification.urgency for i in items} == {Urgency.P3}
    with pytest.raises(ConfigError, match="unknown classifier"):
        await triage.classify(service, classifier="missing")
