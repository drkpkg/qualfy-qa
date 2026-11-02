"""Inline terminal version of `qualfy start` (used when Textual is unavailable or with --no-tui)."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from qualfy import render
from qualfy.cli.prompts import ask_all
from qualfy.core import questions as q
from qualfy.core.errors import QualfyError
from qualfy.core.models import SessionState
from qualfy.core.session import SessionRunner


class Wizard:
    def __init__(self, runner: SessionRunner, console: Console, *, assume_yes: bool = False,
                 answers: dict[str, Any] | None = None, publish: bool = True) -> None:
        self.runner = runner
        self.console = console
        self.yes = assume_yes
        self.preset = answers or {}
        self.allow_publish = publish

    def confirm(self, prompt: str, default: bool = True) -> bool:
        if self.yes:
            return default
        return Confirm.ask(prompt, default=default, console=self.console)

    async def run(self) -> int:
        r, c = self.runner, self.console
        c.rule(f"[bold]qualfy start {r.session.key}")
        if r.state != SessionState.NEW:
            c.print(f"[dim]Resuming session at step '{r.state}'. Use --restart to start over.[/]")

        if r.state == SessionState.NEW:
            with c.status("Analyzing the ticket…"):
                await r.analyze()
        self.show_analysis()

        if r.state == SessionState.ANALYZED and not self.clarify():
            return 1
        self.show_answers()

        if r.state == SessionState.CLARIFIED:
            if not self.confirm("Start automation?"):
                c.print("Stopped. Run the same command later to resume.")
                return 0
            unsubscribe = r.service.bus.subscribe(lambda e: c.print(render.event_text(e)))
            try:
                await r.automate()
            finally:
                unsubscribe()

        render.print_result(c, r.result)
        await self.review()
        r.finish()
        return 0 if r.result.status.value in ("success", "partial", "skipped") else 2

    def show_analysis(self) -> None:
        r, c = self.runner, self.console
        analysis = r.session.analysis
        c.print(render.spec_table(r.spec))
        if analysis:
            c.print(Panel(analysis.summary or "—", title="Analysis", border_style="magenta"))
            for risk in analysis.risks:
                c.print(f"  [yellow]![/] {risk}")

    def clarify(self) -> bool:
        questions = self.runner.questions()
        if self.yes:
            answers = dict(self.preset)
        else:
            self.console.print(f"\n[bold]{len(questions)} question(s) before automating[/]")
            pending = [x for x in questions if x.id not in self.preset]
            answers = {**self.preset, **ask_all(pending, self.console)}
        errors = self.runner.answer(answers)
        for qid, error in errors.items():
            self.console.print(f"[red]✗ {qid}: {error}[/]")
        if errors and self.yes:
            self.console.print("[red]Provide the missing answers with --answer id=value.[/]")
        return not errors

    def show_answers(self) -> None:
        table = Table(title="Answers", show_header=False, expand=True)
        for question, value in self.runner.summary():
            table.add_row(question.label, q.display(question, value))
        self.console.print(table)

    async def review(self) -> None:
        r, c = self.runner, self.console
        for sink, body in list(r.session.drafts.items()):
            if sink in r.session.published:
                continue
            c.print(Panel(Markdown(body), title=f"Draft comment · {sink}", border_style="cyan"))
            edit = not self.yes and Confirm.ask("Edit this draft?", default=False, console=c)
            if edit:
                r.update_draft(sink, edit_text(body))

        if r.can_open_pr():
            branch, title, body = r.pr_defaults()
            c.print(Panel(Markdown(body), title=f"Pull request · {branch} → {title}",
                          border_style="magenta"))
            if self.allow_publish and self.confirm("Create the pull request?"):
                try:
                    c.print(f"[green]PR:[/] {await r.open_pr(title, body)}")
                except QualfyError as exc:
                    c.print(f"[red]Pull request failed:[/] {exc}")
        elif r.session.pr_url:
            c.print(f"PR: {r.session.pr_url}")

        for sink in r.session.drafts:
            if sink in r.session.published or not self.allow_publish:
                continue
            if self.confirm(f"Post the draft comment to {sink}?"):
                try:
                    location = await r.publish(sink)
                    c.print(f"[green]Posted[/] {location or ''}")
                except QualfyError as exc:
                    c.print(f"[red]Posting to {sink} failed:[/] {exc}")


def edit_text(text: str) -> str:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as fh:
        fh.write(text)
        path = Path(fh.name)
    try:
        subprocess.run([*shlex.split(editor), str(path)], check=False)
        return path.read_text()
    finally:
        path.unlink(missing_ok=True)
