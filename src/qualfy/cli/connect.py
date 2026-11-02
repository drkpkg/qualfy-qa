"""`qualfy connect`: link the project to its tracker and code host, and check Claude Code."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from qualfy.adapters.github import GitHubClient, GitHubOptions, parse_remote
from qualfy.adapters.jira import JiraClient, JiraOptions
from qualfy.core.config import AdapterConfig, Config, save_config
from qualfy.core.errors import QualfyError
from qualfy.core.schema import Secret
from qualfy.core.secrets import Secrets


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


# ---- probes (kept free of prompts so they are testable) ----------------------------------------


def git_remote(root: Path, remote: str = "origin") -> str | None:
    if not shutil.which("git"):
        return None
    out = subprocess.run(["git", "remote", "get-url", remote], cwd=root, capture_output=True,
                         text=True, check=False)
    return out.stdout.strip() or None if out.returncode == 0 else None


def gh_token() -> str | None:
    if not shutil.which("gh"):
        return None
    out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=False)
    return out.stdout.strip() or None if out.returncode == 0 else None


async def verify_github(owner: str, repo: str, token: str,
                        transport: httpx.AsyncBaseTransport | None = None) -> Check:
    client = GitHubClient(GitHubOptions(owner=owner, repo=repo, token=Secret(token)),
                          transport=transport)
    try:
        data = await client.get_repo()
    except QualfyError as exc:
        return Check(f"GitHub {owner}/{repo}", False, str(exc))
    finally:
        await client.aclose()
    perms = data.get("permissions") or {}
    access = "write" if perms.get("push") else "read-only"
    return Check(f"GitHub {owner}/{repo}", True,
                 f"{'private' if data.get('private') else 'public'}, {access} access")


async def verify_jira(base_url: str, email: str, token: str,
                      transport: httpx.AsyncBaseTransport | None = None) -> Check:
    client = JiraClient(JiraOptions(base_url=base_url, email=email, token=Secret(token)),
                        transport=transport)
    try:
        me = await client.myself()
    except QualfyError as exc:
        return Check(f"Jira {base_url}", False, str(exc))
    finally:
        await client.aclose()
    return Check(f"Jira {base_url}", True, f"signed in as {me.get('displayName', email)}")


def claude_status(binary: str = "claude") -> Check:
    if not shutil.which(binary):
        return Check("Claude Code", False,
                     "not installed: npm install -g @anthropic-ai/claude-code")
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False)
    status = subprocess.run([binary, "auth", "status", "--json"], capture_output=True, text=True,
                            check=False)
    try:
        info = json.loads(status.stdout)
    except json.JSONDecodeError:
        info = {}
    label = version.stdout.strip().split(" ")[0] or "installed"
    if not info.get("loggedIn"):
        return Check("Claude Code", False, f"{label}, not signed in: run `claude auth login`")
    who = info.get("email") or info.get("authMethod", "")
    plan = f" ({info['subscriptionType']})" if info.get("subscriptionType") else ""
    return Check("Claude Code", True, f"{label}, signed in as {who}{plan}")


# ---- config mutation --------------------------------------------------------------------------


def apply_github(config: Config, owner: str, repo: str, *, labels: list[str],
                 host: tuple[str, str] | None, project: str = "default") -> None:
    common = {"owner": owner, "repo": repo, "token": "${secret:github_token}"}
    config.sources["github"] = AdapterConfig(kind="github-issues",
                                             options={**common, "labels": labels})
    config.sinks["github"] = AdapterConfig(kind="github-comment", options={
        **common,
        "labels": {"success": ["qa:automated"], "partial": ["qa:needs-review"],
                   "failed": ["qa:needs-review"]},
        "remove_labels": labels,
    })
    _apply_host(config, host)
    _link(config, project, source="github", sink="github")


def apply_jira(config: Config, base_url: str, email: str, *, jql: str,
               host: tuple[str, str] | None, project: str = "default") -> None:
    common = {"base_url": base_url, "email": email, "token": "${secret:jira_token}"}
    config.sources["jira"] = AdapterConfig(kind="jira-rovo", options={**common, "jql": jql})
    config.sinks["jira"] = AdapterConfig(kind="jira-comment", options=common)
    _apply_host(config, host)
    _link(config, project, source="jira", sink="jira")


def _apply_host(config: Config, host: tuple[str, str] | None) -> None:
    if host:
        owner, repo = host
        config.hosts["origin"] = AdapterConfig(kind="github", options={
            "owner": owner, "repo": repo, "token": "${secret:github_token}", "base": "main"})


def _link(config: Config, project: str, *, source: str, sink: str) -> None:
    from qualfy.core.config import ProjectConfig

    proj = config.projects.get(project) or ProjectConfig(source=source)
    proj.source = source
    proj.sinks = [s for s in proj.sinks if s != sink] + [sink]
    if "origin" in config.hosts:
        proj.host = "origin"
    config.projects[project] = proj


# ---- interactive flow -------------------------------------------------------------------------


async def run(config: Config, args: argparse.Namespace, console: Console) -> int:
    interactive = not args.yes
    secrets = Secrets(config.name)
    checks: list[Check] = []
    root = config.base_dir

    def ask(prompt: str, default: str | None = None, *, password: bool = False) -> str:
        if not interactive:
            if default is None:
                raise QualfyError(f"missing value for: {prompt} (pass it as a flag)")
            return default
        return Prompt.ask(prompt, default=default, password=password, console=console)

    console.rule("[bold]qualfy connect")
    tracker = args.tracker or (ask("Tracker", "github") if interactive else "local")
    if tracker not in {"github", "jira", "local"}:
        raise QualfyError("tracker must be github, jira or local")

    remote = parse_remote(git_remote(root) or "")
    host: tuple[str, str] | None = None

    if tracker in {"github", "jira"}:
        token = os.environ.get(args.token_env) if args.token_env else None
        token = token or secrets.get("github_token")
        if token is None and (gh := gh_token()):
            use_gh = not interactive or Confirm.ask("Use your GitHub CLI (gh) login token?",
                                                    default=True, console=console)
            token = gh if use_gh else None
        if token is None and (tracker == "github" or remote):
            token = ask("GitHub token (fine-grained PAT: Issues + Pull requests read/write)",
                        password=True)
        if token:
            secrets.set("github_token", token)

    if tracker == "github":
        owner = args.owner or ask("Issues repository owner", remote[0] if remote else None)
        repo = args.repo or ask("Issues repository name", remote[1] if remote else None)
        checks.append(await verify_github(owner, repo, secrets.get("github_token") or ""))
        labels = [label.strip() for label in args.labels.split(",") if label.strip()]
        host = _pick_host(remote, interactive, console)
        if host and host != (owner, repo):
            checks.append(await verify_github(*host, secrets.get("github_token") or ""))
        apply_github(config, owner, repo, labels=labels, host=host)
        if checks[0].ok and not args.no_labels and (
                not interactive or Confirm.ask(f"Create missing labels ({', '.join(labels)}, "
                                               "priority:P0–P3) on GitHub?", default=True,
                                               console=console)):
            checks.append(await _ensure_labels(config, secrets))
    elif tracker == "jira":
        base_url = args.jira_url or ask("Jira site URL (https://yourco.atlassian.net)")
        email = args.jira_email or ask("Atlassian account email")
        token = (os.environ.get(args.jira_token_env) if args.jira_token_env else None) or (
            secrets.get("jira_token") or ask("Atlassian API token", password=True))
        secrets.set("jira_token", token)
        checks.append(await verify_jira(base_url, email, token))
        host = _pick_host(remote, interactive, console)
        apply_jira(config, base_url, email, jql=args.jql, host=host)

    if not args.skip_claude:
        checks.append(claude_status())

    path = save_config(config)
    _report(console, checks, path, secrets, host)
    return 0 if all(c.ok for c in checks) else 1


def _pick_host(remote: tuple[str, str] | None, interactive: bool,
               console: Console) -> tuple[str, str] | None:
    if remote is None:
        console.print("[yellow]No GitHub `origin` remote: pull requests are disabled until you "
                      "add one (gh repo create --source . --push) and rerun `qualfy connect`.")
        return None
    if not interactive or Confirm.ask(f"Open pull requests on {remote[0]}/{remote[1]}?",
                                      default=True, console=console):
        return remote
    return None


async def _ensure_labels(config: Config, secrets: Secrets) -> Check:
    from qualfy.adapters.sources.github_issues import GitHubIssuesOptions, GitHubIssuesSource
    from qualfy.core.config import interpolate
    from qualfy.core.schema import from_dict

    options = from_dict(GitHubIssuesOptions,
                        interpolate(config.sources["github"].options, secrets.get))
    source = GitHubIssuesSource(options)
    try:
        created = await source.ensure_labels()
    except QualfyError as exc:
        return Check("GitHub labels", False, str(exc))
    return Check("GitHub labels", True, f"created {', '.join(created)}" if created else "present")


def _report(console: Console, checks: list[Check], path: Path, secrets: Secrets,
            host: tuple[str, str] | None) -> None:
    table = Table(show_header=False, box=None, padding=(0, 1))
    for check in checks:
        table.add_row("[green]✓[/]" if check.ok else "[red]✗[/]", check.name,
                      f"[dim]{check.detail}[/]")
    console.print(table)
    console.print(f"Saved [bold]{path}[/] · secrets in {secrets.store.name} store")
    console.print(
        "\n[bold]Claude in CI[/] (optional): run [cyan]claude[/] in this repo and type "
        "[cyan]/install-github-app[/] to install the Claude GitHub App and store the secret, or "
        "create a token with [cyan]claude setup-token[/] and save it as "
        "CLAUDE_CODE_OAUTH_TOKEN. For a shared org secret prefer an API key."
    )
    if host is None:
        console.print("[dim]Pull requests: not configured.[/]")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tracker", choices=["github", "jira", "local"])
    parser.add_argument("--owner", help="GitHub owner of the issues repository")
    parser.add_argument("--repo", help="GitHub issues repository")
    parser.add_argument("--labels", default="qa:ready", help="comma-separated ready labels")
    parser.add_argument("--token-env", help="read the GitHub token from this env variable")
    parser.add_argument("--jira-url")
    parser.add_argument("--jira-email")
    parser.add_argument("--jira-token-env", help="read the Jira token from this env variable")
    parser.add_argument("--jql", default='status = "Ready for Automation" ORDER BY updated DESC')
    parser.add_argument("--no-labels", action="store_true", help="do not create GitHub labels")
    parser.add_argument("--skip-claude", action="store_true")
    parser.add_argument("-y", "--yes", action="store_true", help="no prompts; use flags/defaults")
