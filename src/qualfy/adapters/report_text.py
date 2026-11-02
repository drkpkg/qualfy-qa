"""Markdown rendering of a run, shared by the comment sinks."""

from __future__ import annotations

from qualfy.core.models import AutomationResult, TestSpec

ICONS = {"automated": "✅", "failed": "❌", "blocked": "⛔", "skipped": "⏭"}


def result_markdown(spec: TestSpec, result: AutomationResult) -> str:
    titles = {c.id: c.title for c in spec.cases}
    lines = [f"### QA automation run `{result.run_id}`: **{result.status.value.upper()}**", ""]
    if result.summary:
        lines += [result.summary, ""]
    if result.error:
        lines += [f"> **Error:** {result.error}", ""]
    if result.cases:
        lines += ["| | Case | Title | File | Notes |", "|---|---|---|---|---|"]
        for case in result.cases:
            notes = case.notes
            if case.failure_kind:
                notes = f"**{case.failure_kind.value} issue** {notes}".strip()
            lines.append(
                f"| {ICONS.get(case.status.value, '•')} | {case.case_id} "
                f"| {_cell(titles.get(case.case_id, ''))} | {_cell(case.test_file or '')} "
                f"| {_cell(notes)} |"
            )
        lines.append("")
    if result.pr_url:
        lines.append(f"- PR: {result.pr_url}")
    if result.branch:
        lines.append(f"- Branch: `{result.branch}`")
    lines += [f"- Suspected bug ({b.case_id}): {b.title}" for b in result.bugs]
    meta = [f"rev `{result.spec_revision}`"]
    if result.cost_usd is not None:
        meta.append(f"${result.cost_usd:.2f}")
    if result.turns is not None:
        meta.append(f"{result.turns} turns")
    lines += ["", f"<sub>{' · '.join(meta)}</sub>"]
    return "\n".join(lines)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
