from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from qualfy import __version__, render
from qualfy.core.config import CONFIG_NAME, Config, find_config, load_config
from qualfy.core.contract import build_spec, extract_contract, load_contract
from qualfy.core.errors import ContractError, QualfyError, SchemaError
from qualfy.core.models import (
    AgentReport,
    Analysis,
    AutomationResult,
    Ref,
    RunStatus,
    TestSpec,
    Urgency,
)
from qualfy.core.registry import SLOTS, default_registry
from qualfy.core.schema import dumps, json_schema, loads
from qualfy.core.service import AutomationService

console = Console()
err = Console(stderr=True)
T = TypeVar("T")


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _config_path(args: argparse.Namespace) -> Path:
    return Path(args.config) if args.config else find_config()


def _service(args: argparse.Namespace) -> AutomationService:
    return AutomationService.from_file(_config_path(args))


# ---- commands ---------------------------------------------------------------------------------


def cmd_new(args: argparse.Namespace) -> int:
    from qualfy.cli.scaffold import create_project

    target = Path(args.name)
    written = create_project(target, name=args.title, template=args.template,
                             git=not args.no_git, force=args.force)
    console.print(f"[green]Created[/] {target.resolve()} ({len(written)} files)\n")
    console.print("Next steps:")
    if str(target) != ".":
        console.print(f"  [cyan]cd {target}[/]")
    console.print("  [cyan]npm install && npx playwright install chromium[/]")
    console.print("  [cyan]qualfy connect[/]      link GitHub or Jira, check Claude Code")
    console.print("  [cyan]qualfy classify[/]     sort open issues by urgency")
    console.print("  [cyan]qualfy start <ID>[/]   automate a ticket")
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    from qualfy.cli import connect

    path = _config_path(args)
    config = load_config(path) if path.exists() else Config(base_dir=path.parent.resolve(),
                                                             path=path)
    return _run(connect.run(config, args, console))


def cmd_classify(args: argparse.Namespace) -> int:
    return _run(_classify(_service(args), args))


async def _classify(service: AutomationService, args: argparse.Namespace) -> int:
    # One event loop for fetch and write-back: the source's httpx pool is bound to the loop
    # that opened it, so a second asyncio.run() fails its first request on a reused connection.
    from qualfy.core import triage

    with console.status("Fetching and classifying tickets…"):
        items = await triage.classify(service, args.project, classifier=args.classifier,
                                      limit=args.limit, force=args.force)
    if not items:
        console.print("[dim]No open tickets.[/]")
        return 0
    console.print(render.triage_table(items))
    changes = [i for i in items if i.changes]
    if not changes:
        console.print("[green]Everything is already classified.[/]")
        return 0
    if args.dry_run:
        return 0
    if not args.yes:
        choice = Prompt.ask(f"Write {len(changes)} classification(s) to the tracker?",
                            choices=["y", "n", "e"], default="y", console=console)
        if choice == "n":
            return 0
        if choice == "e":
            for item in changes:
                picked = Prompt.ask(f"{item.ticket.ref.key} {item.ticket.title[:60]}",
                                    choices=[u.value for u in Urgency],
                                    default=item.classification.urgency.value, console=console)
                item.classification.urgency = Urgency(picked)
    outcome = await triage.apply(service, changes, args.project)
    for key, error in outcome.items():
        console.print(f"[red]✗ {key}: {error}[/]" if error else f"[green]✓[/] {key}")
    return 1 if any(outcome.values()) else 0


def cmd_start(args: argparse.Namespace) -> int:
    from qualfy.core.session import SessionRunner

    service = _service(args)
    runner = SessionRunner.open(service, args.key, args.project, restart=args.restart)
    answers = dict(a.split("=", 1) for a in args.answer or [] if "=" in a)
    use_tui = not args.no_tui and not args.yes and sys.stdout.isatty()
    if use_tui:
        from qualfy import tui

        if tui.available():
            from qualfy.tui.start import StartApp

            return StartApp(runner).run() or 0
        console.print(f"[dim]{tui.unavailable_reason()}; using the inline wizard.[/]")
    from qualfy.cli.wizard import Wizard

    wizard = Wizard(runner, console, assume_yes=args.yes, answers=answers,
                    publish=not args.no_publish)
    return _run(wizard.run())


def cmd_sessions(args: argparse.Namespace) -> int:
    table = Table(expand=True)
    for col in ("Key", "Project", "Step", "Result", "PR", "Updated"):
        table.add_column(col)
    for s in _service(args).store.list_sessions():
        table.add_row(s.key, s.project, s.state.value,
                      s.result.status.value if s.result else "", s.pr_url or "",
                      f"{s.updated_at:%Y-%m-%d %H:%M}")
    console.print(table)
    return 0


def cmd_adapters(args: argparse.Namespace) -> int:
    registry = default_registry()
    for slot in SLOTS:
        console.print(f"[bold]{slot}[/]")
        for kind, cls in sorted(registry.kinds(slot).items()):
            doc = (cls.__doc__ or "").strip().splitlines()
            console.print(f"  {kind:<15} [dim]{doc[0] if doc else ''}[/]")
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    models = {"spec": TestSpec, "report": AgentReport, "result": AutomationResult,
              "analysis": Analysis}
    console.print_json(json.dumps(json_schema(models[args.name])))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    items = _run(_service(args).discover(args.project))
    console.print(render.summaries_table(items) if items else "[dim]nothing to automate[/]")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    spec = _run(_service(args).ingest(args.key, args.project))
    if args.output:
        Path(args.output).write_text(dumps(spec))
        console.print(f"[green]wrote[/] {args.output}")
    elif args.json:
        console.print_json(dumps(spec))
    else:
        console.print(render.spec_table(spec))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        spec = load_spec_file(Path(args.path))
    except QualfyError as exc:
        err.print(f"[red]invalid:[/] {exc}")
        return 1
    console.print(render.spec_table(spec))
    console.print(f"[green]valid[/] · {len(spec.automatable_cases)}/{len(spec.cases)} automatable")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    service = _service(args)
    if not args.quiet:
        service.bus.subscribe(lambda e: console.print(render.event_text(e)))
    path = Path(args.target)
    target: str | TestSpec = load_spec_file(path) if path.suffix and path.is_file() else args.target
    result = _run(service.run(target, args.project, report=not args.no_report))
    render.print_result(console, result)
    return 2 if result.status in (RunStatus.ERROR, RunStatus.FAILED) else 0


def cmd_runs(args: argparse.Namespace) -> int:
    table = Table(expand=True)
    for col in ("Run", "Project", "Spec", "Status", "Started"):
        table.add_column(col)
    for r in _service(args).store.list_runs(args.limit):
        table.add_row(r.run_id, r.project, r.spec_ref, r.status or "running",
                      f"{r.started_at:%Y-%m-%d %H:%M}" if r.started_at else "")
    console.print(table)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    store = _service(args).store
    if args.events:
        for event in store.load_events(args.run_id):
            console.print(render.event_text(event))
    result = store.load_result(args.run_id)
    if result is None:
        err.print(f"[red]error:[/] run {args.run_id} has no result")
        return 1
    render.print_result(console, result)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    if not args.yes and not Confirm.ask("Publish this run to every sink again?", console=console):
        return 0
    outcomes = _run(_service(args).rereport(args.run_id, args.project))
    for sink, error in outcomes.items():
        console.print(f"[red]✗ {sink}: {error}[/]" if error else f"[green]✓ {sink}[/]")
    return 1 if any(outcomes.values()) else 0


def cmd_tui(args: argparse.Namespace) -> int:
    from qualfy import tui

    if not tui.available():
        err.print(f"[red]{tui.unavailable_reason()}[/]")
        return 1
    from qualfy.tui.app import DashboardApp

    DashboardApp(_service(args), project=args.project).run()
    return 0


def load_spec_file(path: Path) -> TestSpec:
    if not path.is_file():
        raise QualfyError(f"file not found: {path}")
    text = path.read_text()
    if path.suffix == ".json":
        try:
            return loads(TestSpec, text)
        except SchemaError as exc:
            raise ContractError(str(exc)) from exc
    data = load_contract(text) if path.suffix in (".yaml", ".yml") else extract_contract(text)
    key = str(data.get("key") or path.stem)
    return build_spec(data, ref=Ref(system="file", key=key, url=path.resolve().as_uri()),
                      generator="human")


# ---- parser -----------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", help=f"path to {CONFIG_NAME} (default: search upwards)")
    common.add_argument("-p", "--project", help="project from the config")

    parser = argparse.ArgumentParser(
        prog="qualfy", description="Turn reviewed test tickets into automated tests with Claude.")
    parser.add_argument("-V", "--version", action="version", version=f"qualfy {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def add(name: str, func, help_text: str, **kwargs: Any) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text, description=help_text, parents=[common], **kwargs)
        p.set_defaults(func=func)
        return p

    p = add("new", cmd_new, "create a new test project")
    p.add_argument("name", help="directory to create ('.' for the current one)")
    p.add_argument("--title", help="display name (defaults to the directory name)")
    p.add_argument("--template", default="playwright", choices=["playwright"])
    p.add_argument("--no-git", action="store_true")
    p.add_argument("--force", action="store_true", help="scaffold into a non-empty directory")

    from qualfy.cli.connect import add_arguments
    add_arguments(add("connect", cmd_connect, "link GitHub/Jira and check Claude Code"))

    p = add("classify", cmd_classify, "rank open tickets by urgency and write it back")
    p.add_argument("--classifier", help="classifier from the config (default: project's)")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--force", action="store_true", help="reclassify already triaged tickets")
    p.add_argument("--dry-run", action="store_true", help="show, do not write")
    p.add_argument("-y", "--yes", action="store_true")

    p = add("start", cmd_start, "analyze, clarify, automate and publish one ticket")
    p.add_argument("key", help="ticket key or number")
    p.add_argument("--restart", action="store_true", help="discard the saved session")
    p.add_argument("--no-tui", action="store_true", help="use the inline wizard")
    p.add_argument("-y", "--yes", action="store_true",
                   help="non-interactive: defaults + --answer values, then PR and post")
    p.add_argument("--answer", action="append", metavar="ID=VALUE", help="preset an answer")
    p.add_argument("--no-publish", action="store_true", help="never open PRs or post comments")

    add("sessions", cmd_sessions, "list saved `start` sessions")
    add("adapters", cmd_adapters, "list available adapter kinds")
    p = add("schema", cmd_schema, "print a JSON Schema of the contract models")
    p.add_argument("name", nargs="?", default="spec", choices=["spec", "report", "result",
                                                               "analysis"])
    add("list", cmd_list, "list tickets ready for automation")
    p = add("ingest", cmd_ingest, "fetch a ticket and print its normalized TestSpec")
    p.add_argument("key")
    p.add_argument("-o", "--output")
    p.add_argument("--json", action="store_true")
    p = add("validate", cmd_validate, "validate a spec file (json, yaml or markdown)")
    p.add_argument("path")
    p = add("run", cmd_run, "non-interactive ingest → automate → report")
    p.add_argument("target", help="ticket key or local spec file")
    p.add_argument("--no-report", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true")
    p = add("runs", cmd_runs, "show run history")
    p.add_argument("-n", "--limit", type=int, default=20)
    p = add("show", cmd_show, "show a past run")
    p.add_argument("run_id")
    p.add_argument("-e", "--events", action="store_true")
    p = add("report", cmd_report, "publish a past run to the sinks again")
    p.add_argument("run_id")
    p.add_argument("-y", "--yes", action="store_true")
    add("tui", cmd_tui, "open the dashboard (requires textual >= 2.1)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args) or 0
    except QualfyError as exc:
        err.print(f"[red]error:[/] {exc}")
        return 1
    except FileExistsError as exc:
        err.print(f"[red]error:[/] {exc}")
        return 1
    except KeyboardInterrupt:
        err.print("\n[dim]interrupted[/]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
