from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from qualfy.core.events import Event
from qualfy.core.models import AutomationResult, SpecSummary, TestSpec

BRAND_PURPLE = "#5B2C6F"
BRAND_ORANGE = "#F7A043"

STATUS_STYLE = {
    "success": "green", "automated": "green",
    "partial": "yellow", "skipped": "dim",
    "failed": "red", "error": "bold red", "blocked": "magenta",
}

EVENT_STYLE = {
    "run.started": ("▶", "bold cyan"),
    "run.finished": ("■", "bold cyan"),
    "stage.started": ("…", "blue"),
    "stage.finished": ("✓", "green"),
    "stage.failed": ("✗", "red"),
    "agent.message": ("💬", "default"),
    "agent.tool": ("⚙", "dim"),
    "agent.result": ("◆", "magenta"),
    "log": ("·", "dim"),
}


def event_text(event: Event) -> Text:
    icon, style = EVENT_STYLE.get(event.kind, ("·", "default"))
    text = Text(f"{event.at:%H:%M:%S} ", style="dim")
    text.append(f"{icon} ", style=style)
    text.append(event.message, style=style)
    return text


def spec_table(spec: TestSpec) -> Table:
    table = Table(title=f"{spec.ref}  {spec.title}", caption=f"rev {spec.revision} · "
                  f"generator {spec.generator}", expand=True)
    table.add_column("ID", no_wrap=True)
    table.add_column("Title")
    table.add_column("Priority")
    table.add_column("Auto", justify="center")
    table.add_column("Steps", justify="right")
    for case in spec.cases:
        table.add_row(case.id, case.title, case.priority.value,
                      "✓" if case.automatable else "—", str(len(case.steps)))
    return table


def summaries_table(items: list[SpecSummary]) -> Table:
    table = Table(expand=True)
    table.add_column("Key", no_wrap=True)
    table.add_column("Title")
    table.add_column("Status")
    for item in items:
        table.add_row(item.ref.key, item.title, item.status or "")
    return table


def result_table(result: AutomationResult) -> Table:
    style = STATUS_STYLE.get(result.status.value, "default")
    meta = [f"run {result.run_id}"]
    if result.cost_usd is not None:
        meta.append(f"${result.cost_usd:.2f}")
    if result.turns is not None:
        meta.append(f"{result.turns} turns")
    table = Table(title=Text(f"{result.spec_ref} → {result.status.value.upper()}", style=style),
                  caption=" · ".join(meta), expand=True)
    table.add_column("Case", no_wrap=True)
    table.add_column("Status")
    table.add_column("File")
    table.add_column("Notes")
    for case in result.cases:
        kind = f" ({case.failure_kind.value})" if case.failure_kind else ""
        table.add_row(case.case_id,
                      Text(case.status.value + kind, style=STATUS_STYLE.get(case.status.value, "")),
                      case.test_file or "", case.notes)
    return table


def print_result(console: Console, result: AutomationResult) -> None:
    console.print(result_table(result))
    if result.summary:
        console.print(result.summary)
    if result.error:
        console.print(f"[red]error:[/] {result.error}")
    if result.pr_url:
        console.print(f"PR: {result.pr_url}")


URGENCY_STYLE = {"P0": "bold white on #b60205", "P1": "bold #d93f0b", "P2": "#c08a00",
                 "P3": "green"}


def triage_table(items) -> Table:
    table = Table(expand=True, title="Classification",
                  caption="✎ = will be written to the tracker")
    for col in ("", "Urgency", "Key", "Title", "Impact", "Auto", "Reason", "Source"):
        table.add_column(col, no_wrap=col in ("Key", "Urgency"))
    for item in items:
        c = item.classification
        badge = Text(f" {c.urgency} ", style=URGENCY_STYLE[c.urgency])
        table.add_row("✎" if item.changes else "", badge,
                      item.ticket.ref.key, item.ticket.title, c.impact.value,
                      "✓" if c.automatable else "—", c.reason, c.source)
    return table
