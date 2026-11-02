import argparse

import httpx

from qualfy.adapters.github import parse_remote
from qualfy.cli import connect
from qualfy.cli.scaffold import create_project
from qualfy.core.config import load_config


def mock(status, payload):
    return httpx.MockTransport(lambda request: httpx.Response(status, json=payload))


def test_parse_remote():
    assert parse_remote("git@github.com:acme/e2e.git") == ("acme", "e2e")
    assert parse_remote("https://github.com/acme/e2e") == ("acme", "e2e")
    assert parse_remote("https://gitlab.com/acme/e2e.git") is None


async def test_verify_github_and_jira():
    ok = await connect.verify_github("acme", "e2e", "t", mock(200, {
        "private": True, "permissions": {"push": True}}))
    assert ok.ok and ok.detail == "private, write access"
    bad = await connect.verify_github("acme", "e2e", "t", mock(404, {"message": "Not Found"}))
    assert not bad.ok and "404" in bad.detail
    jira = await connect.verify_jira("https://x.atlassian.net", "a@b.c", "t",
                                     mock(200, {"displayName": "Ana"}))
    assert jira.ok and jira.detail == "signed in as Ana"


def args(**overrides):
    defaults = dict(tracker="github", owner="acme", repo="shop", labels="qa:ready",
                    token_env="GH_TEST_TOKEN", jira_url=None, jira_email=None,
                    jira_token_env=None, jql="status = Ready", no_labels=True,
                    skip_claude=True, yes=True)
    return argparse.Namespace(**{**defaults, **overrides})


async def test_connect_github_non_interactive(tmp_path, monkeypatch):
    create_project(tmp_path / "p", git=False)
    config = load_config(tmp_path / "p" / "qualfy.yaml")
    monkeypatch.setenv("GH_TEST_TOKEN", "ghp_test")
    monkeypatch.setattr(connect, "git_remote", lambda root: "git@github.com:acme/e2e.git")
    seen = []

    async def fake_verify(owner, repo, token, transport=None):
        seen.append((owner, repo, token))
        return connect.Check(f"GitHub {owner}/{repo}", True, "ok")

    monkeypatch.setattr(connect, "verify_github", fake_verify)
    from rich.console import Console

    code = await connect.run(config, args(), Console(record=True, width=120))
    assert code == 0
    assert seen == [("acme", "shop", "ghp_test"), ("acme", "e2e", "ghp_test")]

    saved = load_config(tmp_path / "p" / "qualfy.yaml")
    project = saved.projects["default"]
    assert project.source == "github" and project.host == "origin"
    assert project.sinks == ["results", "github"]
    assert saved.sources["github"].options["token"] == "${secret:github_token}"
    assert saved.hosts["origin"].options["repo"] == "e2e"
    assert "ghp_test" not in (tmp_path / "p" / "qualfy.yaml").read_text()

    from qualfy.core.secrets import Secrets
    assert Secrets(saved.name).get("github_token") == "ghp_test"


async def test_connect_jira(tmp_path, monkeypatch):
    create_project(tmp_path / "p", git=False)
    config = load_config(tmp_path / "p" / "qualfy.yaml")
    monkeypatch.setenv("JIRA_TEST_TOKEN", "atl")
    monkeypatch.setattr(connect, "git_remote", lambda root: None)

    async def fake_verify(base_url, email, token, transport=None):
        return connect.Check("Jira", token == "atl", "")

    monkeypatch.setattr(connect, "verify_jira", fake_verify)
    from rich.console import Console

    code = await connect.run(config, args(tracker="jira", jira_url="https://x.atlassian.net",
                                          jira_email="a@b.c", jira_token_env="JIRA_TEST_TOKEN",
                                          token_env=None),
                             Console(record=True))
    assert code == 0
    saved = load_config(tmp_path / "p" / "qualfy.yaml")
    assert saved.projects["default"].source == "jira" and saved.projects["default"].host is None
    assert saved.sources["jira"].options["jql"] == "status = Ready"
