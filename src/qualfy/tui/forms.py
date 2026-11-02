"""Textual widgets for typed questions. A kind maps to a widget through `__init_subclass__`."""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Select, SelectionList, Static, Switch

from qualfy.core.models import Question, QuestionKind


class QuestionField(Vertical):
    registry: ClassVar[dict[QuestionKind, type[QuestionField]]] = {}

    DEFAULT_CSS = """
    QuestionField { height: auto; margin: 0 0 1 0; padding: 0 1; border-left: tall $panel; }
    QuestionField:focus-within { border-left: tall $accent; }
    QuestionField .q-label { text-style: bold; }
    QuestionField .q-help { color: $text-muted; }
    QuestionField .q-error { color: $error; height: auto; }
    QuestionField SelectionList { height: auto; max-height: 12; }
    """

    def __init_subclass__(cls, kind: QuestionKind | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if kind is not None:
            QuestionField.registry[kind] = cls

    def __init__(self, question: Question, index: int) -> None:
        super().__init__(classes="question")
        self.question = question
        self.index = index

    @classmethod
    def build(cls, question: Question, index: int) -> QuestionField:
        return cls.registry.get(question.kind, TextQuestion)(question, index)

    def compose(self) -> ComposeResult:
        q = self.question
        prefix = f"[{q.case_id}] " if q.case_id else ""
        suffix = "" if q.required else "  (optional)"
        yield Label(f"{prefix}{q.label}{suffix}", classes="q-label")
        if q.help:
            yield Static(q.help, classes="q-help")
        yield from self.inputs()
        yield Static("", classes="q-error")

    def inputs(self) -> ComposeResult:
        yield Input(value="" if self.question.default is None else str(self.question.default),
                    id=f"q{self.index}", password=self.question.kind == QuestionKind.SECRET)

    @property
    def value(self) -> Any:
        return self.query_one(Input).value or None

    def show_error(self, message: str | None) -> None:
        self.query_one(".q-error", Static).update(message or "")


class TextQuestion(QuestionField, kind=QuestionKind.TEXT):
    pass


class UrlQuestion(QuestionField, kind=QuestionKind.URL):
    def inputs(self) -> ComposeResult:
        yield Input(value=self.question.default or "", placeholder="https://…", id=f"q{self.index}")


class SecretQuestion(QuestionField, kind=QuestionKind.SECRET):
    pass


class ConfirmQuestion(QuestionField, kind=QuestionKind.CONFIRM):
    def inputs(self) -> ComposeResult:
        yield Switch(value=bool(self.question.default), id=f"q{self.index}")

    @property
    def value(self) -> Any:
        return self.query_one(Switch).value


class ChoiceQuestion(QuestionField, kind=QuestionKind.CHOICE):
    def inputs(self) -> ComposeResult:
        options = [(o, o) for o in self.question.options]
        default = self.question.default if self.question.default in self.question.options else None
        yield Select(options, value=default if default is not None else Select.BLANK,
                     allow_blank=True, id=f"q{self.index}")

    @property
    def value(self) -> Any:
        value = self.query_one(Select).value
        return None if value is Select.BLANK else value


class MultiQuestion(QuestionField, kind=QuestionKind.MULTI):
    def inputs(self) -> ComposeResult:
        chosen = set(self.question.default or [])
        yield SelectionList[str](*[(o, o, o in chosen) for o in self.question.options],
                                 id=f"q{self.index}")

    @property
    def value(self) -> Any:
        return list(self.query_one(SelectionList).selected)


class DataQuestion(QuestionField, kind=QuestionKind.DATA):
    def inputs(self) -> ComposeResult:
        defaults = self.question.default if isinstance(self.question.default, dict) else {}
        for i, name in enumerate(self.question.fields):
            yield Input(value=str(defaults.get(name, "")), placeholder=name,
                        id=f"q{self.index}-{i}", classes="data-field")

    @property
    def value(self) -> Any:
        inputs = list(self.query(Input))
        return {name: inputs[i].value for i, name in enumerate(self.question.fields)}
