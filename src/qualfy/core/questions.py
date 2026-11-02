"""Validation and coercion of answers to typed questions, shared by every front end."""

from __future__ import annotations

import os
from typing import Any

from qualfy.core.models import Question, QuestionKind, TestSpec

SCOPE_ID = "scope"
BASE_URL_ID = "base_url"
TRUE = {"y", "yes", "true", "1", "si", "sí"}
FALSE = {"n", "no", "false", "0"}


def standard_questions(spec: TestSpec) -> list[Question]:
    """Questions every session asks, whatever the analyzer returns."""
    automatable = [c.id for c in spec.automatable_cases]
    questions = [
        Question(
            id=SCOPE_ID, kind=QuestionKind.MULTI, label="Cases to automate",
            options=[c.id for c in spec.cases], default=automatable,
            help="Unchecked cases are reported as skipped.",
        ),
        Question(
            id=BASE_URL_ID, kind=QuestionKind.URL, label="Base URL of the application under test",
            default=os.environ.get("BASE_URL") or None, required=False,
            help="Passed to the agent; leave empty to use the repo's playwright.config.",
        ),
    ]
    return questions


def merge_questions(first: list[Question], extra: list[Question]) -> list[Question]:
    seen = {q.id for q in first}
    return first + [q for q in extra if q.id not in seen]


def coerce(question: Question, value: Any) -> Any:
    """Turn raw input (e.g. `--answer id=value` strings) into the typed value."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    match question.kind:
        case QuestionKind.CONFIRM:
            if text.lower() in TRUE:
                return True
            if text.lower() in FALSE:
                return False
            return text
        case QuestionKind.MULTI:
            return [v.strip() for v in text.split(",") if v.strip()]
        case QuestionKind.DATA:
            pairs = [p.split("=", 1) for p in text.split(",") if "=" in p]
            return {k.strip(): v.strip() for k, v in pairs}
    return text


def validate(question: Question, value: Any) -> str | None:
    """Return an error message, or None when the value is acceptable."""
    if value in (None, "", [], {}):
        return "required" if question.required else None
    match question.kind:
        case QuestionKind.CONFIRM:
            return None if isinstance(value, bool) else "answer yes or no"
        case QuestionKind.CHOICE:
            if question.options and value not in question.options:
                return f"choose one of: {', '.join(question.options)}"
        case QuestionKind.MULTI:
            if not isinstance(value, list):
                return "expected a list"
            unknown = [v for v in value if question.options and v not in question.options]
            if unknown:
                return f"unknown option(s): {', '.join(map(str, unknown))}"
        case QuestionKind.URL:
            if not (isinstance(value, str) and value.startswith(("http://", "https://"))):
                return "expected an http(s) URL"
        case QuestionKind.DATA:
            if not isinstance(value, dict):
                return "expected field=value pairs"
            missing = [f for f in question.fields if not value.get(f)]
            if missing and question.required:
                return f"missing: {', '.join(missing)}"
        case QuestionKind.TEXT | QuestionKind.SECRET:
            if not isinstance(value, str):
                return "expected text"
    return None


def resolve(questions: list[Question],
            answers: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Apply defaults and coercion. Returns (values, errors by question id)."""
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for q in questions:
        value = coerce(q, answers[q.id]) if q.id in answers else q.default
        if (error := validate(q, value)) is not None:
            errors[q.id] = error
        values[q.id] = value
    return values, errors


def display(question: Question, value: Any) -> str:
    if question.kind == QuestionKind.SECRET and value:
        return "••••••"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(map(str, value)) or "—"
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items()) or "—"
    return "—" if value in (None, "") else str(value)
