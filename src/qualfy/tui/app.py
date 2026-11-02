from __future__ import annotations

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Label,
    Markdown,
    OptionList,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from qualfy import render
from qualfy.core.errors import QualfyError
from qualfy.core.events import Event
from qualfy.core.models import AutomationResult, TestCase, TestSpec
from qualfy.core.service import AutomationService
from qualfy.tui import theme


class DashboardApp(App):
    TITLE = "qualfy"
    SUB_TITLE = "dashboard"
    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding("a", "automate", "Automate"),
        Binding("x", "cancel", "Cancel run"),
        Binding("r", "refresh", "Refresh"),
        Binding("c", "clear_log", "Clear log"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, service: AutomationService, project: str | None = None) -> None:
        super().__init__()
        self.service = service
        self.projects = list(service.config.projects)
        self.project_name = project or (self.projects[0] if self.projects else None)
        self.spec: TestSpec | None = None
        self.running = False
        service.bus.subscribe(self._on_bus_event)

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="automate"):
            with TabPane("Automate", id="automate"), Horizontal(id="main"):
                with Vertical(id="sidebar"):
                    yield Label("Project", classes="section")
                    yield Select(
                        [(p, p) for p in self.projects], value=self.project_name or Select.BLANK,
                        allow_blank=not self.projects, id="project",
                    )
                    yield Label("Tickets", classes="section")
                    yield OptionList(id="specs")
                with Vertical(id="detail"):
                    yield Static("Select a ticket", id="spec-title")
                    yield DataTable(id="cases", cursor_type="row", zebra_stripes=True)
                    yield Markdown("", id="case-detail")
                with Vertical(id="activity"):
                    yield Label("Activity", classes="section")
                    yield RichLog(id="log", wrap=True, markup=False, highlight=False, min_width=20)
                    yield Static("idle", id="status")
            with TabPane("History", id="history"), Horizontal(id="history-main"):
                yield DataTable(id="runs", cursor_type="row", zebra_stripes=True)
                yield RichLog(id="run-detail", wrap=True, markup=False, highlight=False,
                              min_width=20)
        yield Footer()

    def on_mount(self) -> None:
        theme.install(self)
        self.query_one("#cases", DataTable).add_columns("ID", "Title", "Priority", "Auto")
        self.query_one("#runs", DataTable).add_columns("Run", "Project", "Spec", "Status")
        self.action_refresh()

    # ---- data loading -------------------------------------------------------------------

    def action_refresh(self) -> None:
        self.load_specs()
        self.load_runs()

    @work(exclusive=True, group="discover")
    async def load_specs(self) -> None:
        specs = self.query_one("#specs", OptionList)
        specs.clear_options()
        if not self.project_name:
            return
        specs.loading = True
        try:
            items = await self.service.discover(self.project_name)
        except QualfyError as exc:
            self.notify(str(exc), title="Discover failed", severity="error")
            return
        finally:
            specs.loading = False
        specs.add_options(
            Option(Text.assemble((s.ref.key, "bold"), "  ", s.title), id=s.ref.key) for s in items
        )
        if not items:
            self.notify("No tickets ready for automation", severity="warning")

    def load_runs(self) -> None:
        table = self.query_one("#runs", DataTable)
        table.clear()
        for r in self.service.store.list_runs():
            status = r.status or "running"
            table.add_row(r.run_id, r.project, r.spec_ref,
                          Text(status, style=render.STATUS_STYLE.get(status, "")), key=r.run_id)

    @work(exclusive=True, group="ingest")
    async def load_spec(self, key: str) -> None:
        detail = self.query_one("#detail")
        detail.loading = True
        try:
            self.spec = await self.service.ingest(key, self.project_name)
        except QualfyError as exc:
            self.spec = None
            self.query_one("#spec-title", Static).update(Text(f"✗ {key}: {exc}", style="red"))
            self.query_one("#cases", DataTable).clear()
            return
        finally:
            detail.loading = False
        self._show_spec(self.spec)

    def _show_spec(self, spec: TestSpec) -> None:
        self.query_one("#spec-title", Static).update(Text.assemble(
            (str(spec.ref), "bold"), "  ", spec.title, "\n",
            (f"generator {spec.generator} · rev {spec.revision} · "
             f"{len(spec.automatable_cases)}/{len(spec.cases)} automatable", "dim"),
        ))
        table = self.query_one("#cases", DataTable)
        table.clear()
        for case in spec.cases:
            table.add_row(case.id, case.title, case.priority.value,
                          "✓" if case.automatable else "—", key=case.id)
        if spec.cases:
            self._show_case(spec.cases[0])

    def _show_case(self, case: TestCase) -> None:
        steps = []
        for i, step in enumerate(case.steps, 1):
            steps.append(f"{i}. {step.action}")
            steps += [f"   - ⇒ {e}" for e in step.expected]
        sections = [
            (f"### {case.id} · {case.title}", []),
            ("**Preconditions**", [f"- {p}" for p in case.preconditions]),
            ("**Steps**", steps),
            ("**Expected**", [f"- {e}" for e in case.expected]),
            ("**Data**", [f"- `{k}`: {v}" for k, v in case.data.items()]),
        ]
        body = "\n\n".join(
            "\n".join([head, *items]) if items else head
            for head, items in sections if items or head.startswith("#")
        )
        self.query_one("#case-detail", Markdown).update(body)

    # ---- events ---------------------------------------------------------------------------

    @on(Select.Changed, "#project")
    def _project_changed(self, event: Select.Changed) -> None:
        if event.value is not Select.BLANK and event.value != self.project_name:
            self.project_name = str(event.value)
            self.load_specs()

    @on(OptionList.OptionHighlighted, "#specs")
    def _spec_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id:
            self.load_spec(event.option.id)

    @on(OptionList.OptionSelected, "#specs")
    def _spec_selected(self, event: OptionList.OptionSelected) -> None:
        self.query_one("#cases", DataTable).focus()

    @on(DataTable.RowHighlighted, "#cases")
    def _case_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self.spec and event.row_key.value:
            case = next((c for c in self.spec.cases if c.id == event.row_key.value), None)
            if case:
                self._show_case(case)

    @on(DataTable.RowHighlighted, "#runs")
    def _run_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if not event.row_key.value:
            return
        log = self.query_one("#run-detail", RichLog)
        log.clear()
        for e in self.service.store.load_events(event.row_key.value):
            log.write(render.event_text(e))
        result = self.service.store.load_result(event.row_key.value)
        if result:
            log.write(render.result_table(result))

    def _on_bus_event(self, event: Event) -> None:
        self.query_one("#log", RichLog).write(render.event_text(event))
        if event.kind in ("run.started", "stage.started"):
            self._set_status(event.message, "running")

    def _set_status(self, message: str, state: str) -> None:
        status = self.query_one("#status", Static)
        status.update(message)
        status.set_classes(state)

    # ---- actions ----------------------------------------------------------------------------

    def action_automate(self) -> None:
        if self.running:
            self.notify("A run is already in progress", severity="warning")
        elif self.spec is None:
            self.notify("Select a ticket first", severity="warning")
        else:
            self.automate(self.spec)

    @work(exclusive=True, group="run")
    async def automate(self, spec: TestSpec) -> None:
        self.running = True
        try:
            result = await self.service.run(spec, self.project_name)
        except QualfyError as exc:
            self._set_status(f"✗ {exc}", "error")
            self.notify(str(exc), title="Run failed", severity="error")
            return
        finally:
            self.running = False
        self._finish(result)

    def _finish(self, result: AutomationResult) -> None:
        log = self.query_one("#log", RichLog)
        log.write(render.result_table(result))
        state = result.status.value
        self._set_status(f"{result.spec_ref} → {state}", state)
        self.notify(f"{result.spec_ref}: {state}", title="Run finished",
                    severity="error" if state in ("error", "failed") else "information")
        self.load_runs()

    def action_cancel(self) -> None:
        if self.running:
            self.workers.cancel_group(self, "run")
            self.running = False
            self._set_status("cancelled", "error")
            self.load_runs()

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()
