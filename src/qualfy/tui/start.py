"""Textual wizard for `qualfy start`: analyze → clarify → confirm → run → review & publish."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    ContentSwitcher,
    Footer,
    Header,
    Label,
    LoadingIndicator,
    Markdown,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from qualfy import render
from qualfy.core import questions as q
from qualfy.core.errors import QualfyError
from qualfy.core.events import Event
from qualfy.core.models import SessionState
from qualfy.core.session import SessionRunner
from qualfy.tui import theme
from qualfy.tui.forms import QuestionField


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "dismiss(False)", "Cancel")]

    def __init__(self, title: str, body: str, ok: str = "Confirm") -> None:
        super().__init__()
        self.title_text, self.body, self.ok = title, body, ok

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.title_text, id="dialog-title")
            with VerticalScroll(id="dialog-body"):
                yield Markdown(self.body)
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(self.ok, id="ok", variant="primary")

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(False)


class StartApp(App[int]):
    TITLE = "qualfy"
    CSS_PATH = "start.tcss"
    BINDINGS = [Binding("ctrl+q", "quit", "Quit"), Binding("ctrl+l", "clear_log", "Clear log")]

    def __init__(self, runner: SessionRunner) -> None:
        super().__init__()
        self.runner = runner
        self.sub_title = f"start {runner.session.key}"
        self._unsubscribe = runner.service.bus.subscribe(self._on_event)

    def compose(self) -> ComposeResult:
        yield Header()
        with ContentSwitcher(initial="analyze", id="steps"):
            with Vertical(id="analyze"):
                yield LoadingIndicator()
                yield Static("Analyzing the ticket…", id="analyze-msg")
            with VerticalScroll(id="clarify"):
                yield Static(id="spec-summary")
                yield Static(id="analysis")
                yield Label("Questions", classes="section")
                yield Vertical(id="questions")
                with Horizontal(classes="actions"):
                    yield Button("Review answers", id="to-confirm", variant="primary")
            with VerticalScroll(id="confirm"):
                yield Static(id="answers")
                with Horizontal(classes="actions"):
                    yield Button("Back", id="back")
                    yield Button("Start automation", id="start", variant="success")
            with Vertical(id="run"):
                yield RichLog(id="log", wrap=True, markup=False, highlight=False, min_width=20)
                yield Static("running…", id="run-status")
            with Vertical(id="review"):
                yield Static(id="results")
                yield Label("Draft comments (editable)", classes="section")
                yield TabbedContent(id="drafts")
                with Horizontal(classes="actions"):
                    yield Button("Create pull request", id="pr", variant="primary")
                    yield Button("Post comment", id="post", variant="warning")
                    yield Button("Finish", id="finish", variant="success")
        yield Footer()

    def on_mount(self) -> None:
        theme.install(self)
        state = self.runner.state
        if state == SessionState.NEW:
            self.analyze()
        elif state == SessionState.ANALYZED:
            self.show_clarify()
        elif state == SessionState.CLARIFIED:
            self.show_confirm()
        else:
            self.show_review()

    def on_unmount(self) -> None:
        self._unsubscribe()

    def _step(self, name: str) -> None:
        self.query_one("#steps", ContentSwitcher).current = name

    # ---- analyze & clarify -------------------------------------------------------------------

    @work(exclusive=True)
    async def analyze(self) -> None:
        try:
            await self.runner.analyze()
        except QualfyError as exc:
            self.query_one(LoadingIndicator).display = False
            self.query_one("#analyze-msg", Static).update(Text(f"✗ {exc}", style="red"))
            self.notify(str(exc), title="Analysis failed", severity="error", timeout=10)
            return
        self.show_clarify()

    def show_clarify(self) -> None:
        r = self.runner
        self.query_one("#spec-summary", Static).update(render.spec_table(r.spec))
        analysis = r.session.analysis
        if analysis:
            text = Text()
            text.append(analysis.summary or "", style="italic")
            for risk in analysis.risks:
                text.append(f"\n! {risk}", style="#F7A043")
            self.query_one("#analysis", Static).update(text)
        container = self.query_one("#questions", Vertical)
        container.remove_children()
        fields = [QuestionField.build(question, i) for i, question in enumerate(r.questions())]
        container.mount(*fields)
        self._step("clarify")

    @on(Button.Pressed, "#to-confirm")
    def _submit_answers(self) -> None:
        fields = list(self.query(QuestionField))
        errors = self.runner.answer({f.question.id: f.value for f in fields})
        for f in fields:
            f.show_error(errors.get(f.question.id))
        if errors:
            self.notify(f"{len(errors)} answer(s) need attention", severity="warning")
            return
        self.show_confirm()

    def show_confirm(self) -> None:
        r = self.runner
        table = Table(title=f"{r.spec.ref} · {len(r.spec.automatable_cases)} case(s) to automate",
                      show_header=False, expand=True)
        for question, value in r.summary():
            table.add_row(question.label, q.display(question, value))
        self.query_one("#answers", Static).update(table)
        self._step("confirm")

    @on(Button.Pressed, "#back")
    def _back(self) -> None:
        self.show_clarify()

    # ---- run ---------------------------------------------------------------------------------

    @on(Button.Pressed, "#start")
    def _start(self) -> None:
        self._step("run")
        self.automate()

    @work(exclusive=True)
    async def automate(self) -> None:
        try:
            await self.runner.automate()
        except QualfyError as exc:
            self.query_one("#run-status", Static).update(Text(f"✗ {exc}", style="red"))
            self.notify(str(exc), title="Automation failed", severity="error", timeout=10)
            return
        self.show_review()

    def _on_event(self, event: Event) -> None:
        if self.query("#log"):
            self.query_one("#log", RichLog).write(render.event_text(event))

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    # ---- review & publish --------------------------------------------------------------------

    def show_review(self) -> None:
        r = self.runner
        self.query_one("#results", Static).update(render.result_table(r.result))
        drafts = self.query_one("#drafts", TabbedContent)
        drafts.clear_panes()
        for i, (sink, body) in enumerate(r.session.drafts.items()):
            drafts.add_pane(TabPane(sink, TextArea(body, id=f"draft-{i}"), id=f"pane-{i}"))
        self._refresh_buttons()
        self._step("review")

    def _refresh_buttons(self) -> None:
        r = self.runner
        self.query_one("#pr", Button).disabled = not r.can_open_pr()
        unpublished = [s for s in r.session.drafts if s not in r.session.published]
        self.query_one("#post", Button).disabled = not unpublished

    def _active_sink(self) -> tuple[str, TextArea] | None:
        drafts = self.query_one("#drafts", TabbedContent)
        if not drafts.active:
            return None
        index = int(drafts.active.removeprefix("pane-"))
        sink = list(self.runner.session.drafts)[index]
        return sink, self.query_one(f"#draft-{index}", TextArea)

    def _save_drafts(self) -> None:
        for i, sink in enumerate(list(self.runner.session.drafts)):
            area = self.query(f"#draft-{i}")
            if area:
                self.runner.update_draft(sink, area.first(TextArea).text)

    @on(Button.Pressed, "#pr")
    def _pr(self) -> None:
        branch, title, body = self.runner.pr_defaults()
        self.push_screen(ConfirmScreen(f"Open PR from {branch}: {title}", body, ok="Create PR"),
                         self._pr_confirmed)

    def _pr_confirmed(self, ok: bool | None) -> None:
        if ok:
            self._save_drafts()
            self.open_pr()

    @work(exclusive=True, group="publish")
    async def open_pr(self) -> None:
        try:
            url = await self.runner.open_pr()
        except QualfyError as exc:
            self.notify(str(exc), title="Pull request failed", severity="error", timeout=10)
            return
        for i, sink in enumerate(self.runner.session.drafts):
            self.query_one(f"#draft-{i}", TextArea).text = self.runner.session.drafts[sink]
        self.notify(url, title="Pull request created")
        self._refresh_buttons()

    @on(Button.Pressed, "#post")
    def _post(self) -> None:
        active = self._active_sink()
        if active is None:
            return
        sink, area = active
        if sink in self.runner.session.published:
            self.notify(f"Already posted to {sink}", severity="warning")
            return
        self.runner.update_draft(sink, area.text)
        self.push_screen(ConfirmScreen(f"Post this comment to {sink}?", area.text, ok="Post"),
                         lambda ok: self.publish(sink) if ok else None)

    @work(group="publish")
    async def publish(self, sink: str) -> None:
        try:
            location = await self.runner.publish(sink)
        except QualfyError as exc:
            self.notify(str(exc), title=f"Posting to {sink} failed", severity="error", timeout=10)
            return
        self.notify(location or sink, title="Comment posted")
        self._refresh_buttons()

    @on(Button.Pressed, "#finish")
    def _finish(self) -> None:
        if self.runner.session.drafts:
            self._save_drafts()
        self.runner.finish()
        self.exit(0)
