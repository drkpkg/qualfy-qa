"""Terminal renderers for typed questions. Each kind registers itself via `__init_subclass__`."""

from __future__ import annotations

from typing import Any, ClassVar

from rich.console import Console
from rich.prompt import Confirm, Prompt

from qualfy.core import questions as q
from qualfy.core.models import Question, QuestionKind


class PromptField:
    registry: ClassVar[dict[QuestionKind, type[PromptField]]] = {}
    kind: ClassVar[QuestionKind]

    def __init_subclass__(cls, kind: QuestionKind | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if kind is not None:
            cls.kind = kind
            PromptField.registry[kind] = cls

    def __init__(self, question: Question, console: Console) -> None:
        self.question = question
        self.console = console

    @classmethod
    def for_question(cls, question: Question, console: Console) -> PromptField:
        return cls.registry.get(question.kind, TextField)(question, console)

    def label(self) -> str:
        tag = f"[dim]{self.question.case_id}[/] " if self.question.case_id else ""
        optional = "" if self.question.required else " [dim](optional)[/]"
        return f"{tag}{self.question.label}{optional}"

    def ask(self) -> Any:
        default = self.question.default
        answer = Prompt.ask(self.label(), console=self.console,
                            default=None if default is None else str(default))
        return answer or None

    def run(self) -> Any:
        if self.question.help:
            self.console.print(f"  [dim]{self.question.help}[/]")
        while True:
            value = q.coerce(self.question, self.ask())
            error = q.validate(self.question, value)
            if error is None:
                return value
            self.console.print(f"  [red]{error}[/]")


class TextField(PromptField, kind=QuestionKind.TEXT):
    pass


class UrlField(PromptField, kind=QuestionKind.URL):
    pass


class SecretField(PromptField, kind=QuestionKind.SECRET):
    def ask(self) -> Any:
        return Prompt.ask(self.label(), password=True, console=self.console, default="") or None


class ConfirmField(PromptField, kind=QuestionKind.CONFIRM):
    def ask(self) -> Any:
        return Confirm.ask(self.label(), default=bool(self.question.default), console=self.console)


class ChoiceField(PromptField, kind=QuestionKind.CHOICE):
    def ask(self) -> Any:
        options = self.question.options
        for i, option in enumerate(options, 1):
            self.console.print(f"  [cyan]{i}[/] {option}")
        default = self.question.default if self.question.default in options else None
        raw = Prompt.ask(self.label(), console=self.console,
                         default=None if default is None else str(options.index(default) + 1))
        if raw and raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        return raw or None


class MultiField(PromptField, kind=QuestionKind.MULTI):
    def ask(self) -> Any:
        options = self.question.options
        chosen = set(self.question.default or [])
        for i, option in enumerate(options, 1):
            mark = "[green]●[/]" if option in chosen else "○"
            self.console.print(f"  [cyan]{i}[/] {mark} {option}")
        default = ",".join(str(options.index(o) + 1) for o in options if o in chosen)
        raw = Prompt.ask(f"{self.label()} [dim](numbers, comma separated)[/]",
                         console=self.console, default=default or None)
        picks = [p.strip() for p in (raw or "").split(",") if p.strip()]
        return [options[int(p) - 1] if p.isdigit() and 1 <= int(p) <= len(options) else p
                for p in picks]


class DataField(PromptField, kind=QuestionKind.DATA):
    def ask(self) -> Any:
        self.console.print(self.label())
        defaults = self.question.default if isinstance(self.question.default, dict) else {}
        return {name: Prompt.ask(f"  {name}", console=self.console,
                                 default=str(defaults.get(name, "")) or None) or ""
                for name in self.question.fields}


def ask_all(questions: list[Question], console: Console) -> dict[str, Any]:
    return {question.id: PromptField.for_question(question, console).run()
            for question in questions}
