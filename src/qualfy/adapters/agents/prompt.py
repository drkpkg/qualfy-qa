from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from qualfy.core.models import AgentReport, TestSpec
from qualfy.core.schema import dumps, inline_schema

GitMode = Literal["none", "branch", "pr"]

GIT_INSTRUCTIONS: dict[str, str] = {
    "none": "Do not run any git command that changes history (no branch, commit or push).",
    "branch": (
        "Create a branch named `qa/{key}` from the current HEAD, commit the new and changed test "
        "files with message `test({key}): automate {key}`, and do not push. Report the branch name."
    ),
    "pr": (
        "Create a branch named `qa/{key}` from the current HEAD, commit with message "
        "`test({key}): automate {key}`, push it and open a pull request whose body lists every "
        "case and its status. Report the branch name and the PR URL."
    ),
}


def build_prompt(spec: TestSpec, report_path: Path, *, git: GitMode = "branch", extra: str = "",
                 env_names: list[str] | None = None) -> str:
    key = spec.ref.key
    framework = spec.framework or "the framework already used in this repository"
    schema = json.dumps(inline_schema(AgentReport), indent=2)
    spec_json = dumps(spec, exclude={"schema_version", "revision", "clarifications"})
    sections = [
        f"You are automating the test ticket {spec.ref} (\"{spec.title}\") with {framework}.",
        "## Test specification\n"
        "This is the source of truth. Steps and expected results come from a reviewed ticket.\n"
        f"```json\n{spec_json}\n```",
    ]
    if spec.clarifications:
        answers = "\n".join(f"- **{label}**: {_fmt(value)}"
                            for label, value in spec.clarifications.items())
        sections.append("## Clarifications from the QA engineer\n"
                        "They override any ambiguity in the specification.\n" + answers)
    if env_names:
        sections.append("## Environment\nThese variables are set for you; read them instead of "
                        "hardcoding values: " + ", ".join(f"`{n}`" for n in env_names))
    sections += [
        "## How to work\n"
        "1. Read the repository conventions first (CLAUDE.md, README, existing tests, page "
        "objects, fixtures, helpers). Follow them exactly and reuse existing building blocks "
        "before creating new ones.\n"
        "2. Skip cases with `automatable: false` and report them as `skipped`.\n"
        "3. When a browser tool is available, explore the running application to find real "
        "selectors and flows instead of guessing them.\n"
        f"4. Tag or name every test so it carries both `{key}` and its case id "
        f"(e.g. `@{key} @TC-1` in the title).\n"
        "5. Run the tests you wrote and iterate until they pass or you can classify the failure.",
        "## Rules\n"
        "- Never weaken, drop or rewrite an expected result to make a test pass.\n"
        "- Classify each failure: `test` (your test is wrong: fix it), `app` (the application "
        "does not behave as specified: keep the assertion, mark the test as an expected failure "
        "using the framework's idiom referencing the case id, and add an entry to `bugs`), or "
        "`env` (environment, data or flakiness: retry once, then report it).\n"
        "- Never hardcode secrets; read credentials from the environment or existing fixtures.\n"
        "- Prefer API or fixture-based setup for preconditions over driving the UI.\n"
        f"- {GIT_INSTRUCTIONS[git].format(key=key)}",
    ]
    if extra.strip():
        sections.append(f"## Project-specific instructions\n{extra.strip()}")
    sections.append(
        "## Final report (required)\n"
        f"Before finishing, write a JSON file to `{report_path}` that validates against this "
        "schema. Include one entry in `cases` per case in the specification, with paths relative "
        "to the repository root.\n"
        f"```json\n{schema}\n```"
    )
    return "\n\n".join(sections)


def _fmt(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(map(str, value))
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items())
    return str(value)
