"""`qualfy start` as a resumable state machine. Front ends only call these methods."""

from __future__ import annotations

from typing import Any

from qualfy.core import questions as q
from qualfy.core.errors import SessionError
from qualfy.core.events import RunEmitter
from qualfy.core.models import (
    Analysis,
    AutomationResult,
    CaseStatus,
    Question,
    QuestionKind,
    Session,
    SessionState,
    TestSpec,
)
from qualfy.core.service import AutomationService


class SessionRunner:
    def __init__(self, service: AutomationService, session: Session) -> None:
        self.service = service
        self.session = session

    @classmethod
    def open(cls, service: AutomationService, key: str, project: str | None = None, *,
             restart: bool = False) -> SessionRunner:
        name, _ = service.config.project(project)
        existing = None if restart else service.store.load_session(key)
        session = existing or Session(key=key, project=name)
        return cls(service, session)

    @property
    def state(self) -> SessionState:
        return self.session.state

    @property
    def spec(self) -> TestSpec:
        if self.session.spec is None:
            raise SessionError("session has not been analyzed yet")
        return self.session.spec

    @property
    def result(self) -> AutomationResult:
        if self.session.result is None:
            raise SessionError("session has not been automated yet")
        return self.session.result

    def save(self) -> None:
        self.service.store.save_session(self.session)

    # ---- 1. analyze ----------------------------------------------------------------------------

    async def analyze(self) -> Analysis:
        project = self.service.project(self.session.project)
        ingested = await self.service.ingest_ticket(self.session.key, self.session.project)
        emit = RunEmitter(self.service.bus, None)
        if project.analyzer is not None:
            analysis = await project.analyzer.analyze(ingested.ticket, ingested.spec, emit)
        else:
            analysis = Analysis(summary=f"{ingested.ticket.title}: no analyzer configured")

        spec = ingested.spec
        if spec is None:
            if not analysis.cases:
                raise SessionError(
                    f"{self.session.key} has no test contract "
                    f"({ingested.contract_error}) and the analyzer generated no cases"
                )
            spec = TestSpec(
                ref=ingested.ticket.ref, title=ingested.ticket.title, cases=analysis.cases,
                generator=type(project.analyzer).kind if project.analyzer else "unknown",
                framework=project.config.framework,
            )
        self.session.spec = spec
        self.session.analysis = analysis
        self.session.state = SessionState.ANALYZED
        self.save()
        return analysis

    # ---- 2. clarify ----------------------------------------------------------------------------

    def questions(self) -> list[Question]:
        analysis = self.session.analysis
        return q.merge_questions(q.standard_questions(self.spec),
                                 analysis.questions if analysis else [])

    def answer(self, answers: dict[str, Any]) -> dict[str, str]:
        """Validate and store answers. Returns errors by question id (empty on success)."""
        questions = self.questions()
        values, errors = q.resolve(questions, answers)
        if errors:
            return errors

        spec = self.spec
        scope = set(values.get(q.SCOPE_ID) or [])
        for case in spec.cases:
            case.automatable = case.automatable and case.id in scope
        spec.clarifications = {}
        for question in questions:
            value = values[question.id]
            if question.id == q.SCOPE_ID or value in (None, "", [], {}):
                continue
            if question.kind == QuestionKind.SECRET:
                self.service.secrets.set(self._secret_name(question.id), value)
                value = f"<provided in environment variable {self.env_name(question.id)}>"
            label = f"{question.case_id}: {question.label}" if question.case_id else question.label
            spec.clarifications[label] = value
        spec.revision = spec.compute_revision()
        self.session.answers = {k: v for k, v in values.items()
                                if not self._is_secret(questions, k)}
        self.session.state = SessionState.CLARIFIED
        self.save()
        return {}

    def summary(self) -> list[tuple[Question, Any]]:
        return [(question, self.session.answers.get(question.id)) for question in self.questions()]

    # ---- 3. automate ---------------------------------------------------------------------------

    async def automate(self) -> AutomationResult:
        if self.state not in (SessionState.CLARIFIED, SessionState.AUTOMATED):
            raise SessionError(f"cannot automate from state '{self.state}'")
        env = {self.env_name(question.id): value
               for question in self.questions() if question.kind == QuestionKind.SECRET
               if (value := self.service.secrets.get(self._secret_name(question.id)))}
        if base_url := self.session.answers.get(q.BASE_URL_ID):
            env["BASE_URL"] = base_url
        result = await self.service.automate(self.spec, self.session.project, env=env)
        await self.service.publish_automatic(self.spec, result, self.session.project)
        self.session.result = result
        self.session.drafts = self.service.drafts(self.spec, result, self.session.project)
        self.session.state = SessionState.AUTOMATED
        self.save()
        return result

    # ---- 4. review & publish -------------------------------------------------------------------

    def update_draft(self, sink: str, body: str) -> None:
        self.session.drafts[sink] = body
        self.save()

    def pr_defaults(self) -> tuple[str, str, str]:
        result, spec = self.result, self.spec
        if not result.branch:
            raise SessionError("the agent did not report a branch to open a pull request from")
        title = f"test({spec.ref.key}): automate {spec.title}"[:120]
        lines = [f"Automated tests for {spec.ref.url or spec.ref}.", "", result.summary, "",
                 "| Case | Status | File |", "|---|---|---|"]
        lines += [f"| {c.case_id} | {c.status.value} | {c.test_file or ''} |" for c in result.cases]
        if result.bugs:
            lines += ["", "Suspected application bugs:"]
            lines += [f"- {b.case_id}: {b.title}" for b in result.bugs]
        return result.branch, title, "\n".join(lines)

    def can_open_pr(self) -> bool:
        return (self.service.project(self.session.project).host is not None
                and self.session.result is not None and bool(self.session.result.branch)
                and not self.session.pr_url
                and any(c.status == CaseStatus.AUTOMATED for c in self.session.result.cases))

    async def open_pr(self, title: str | None = None, body: str | None = None) -> str:
        branch, default_title, default_body = self.pr_defaults()
        url = await self.service.open_pull_request(branch, title or default_title,
                                                   body or default_body, self.session.project)
        self.session.pr_url = url
        self.result.pr_url = url
        for sink, draft in self.session.drafts.items():
            if url not in draft:
                self.session.drafts[sink] = f"{draft.rstrip()}\n\nPull request: {url}\n"
        self.save()
        return url

    async def publish(self, sink: str) -> str | None:
        body = self.session.drafts.get(sink)
        if body is None:
            raise SessionError(f"no draft for sink '{sink}'")
        location = await self.service.publish(sink, self.spec, self.result, body,
                                              self.session.project)
        self.session.published[sink] = location or "published"
        self.save()
        return location

    def finish(self) -> None:
        self.session.state = SessionState.DONE
        self.save()

    # ---- helpers -------------------------------------------------------------------------------

    def env_name(self, question_id: str) -> str:
        return f"QUALFY_ANSWER_{question_id.upper()}"

    def _secret_name(self, question_id: str) -> str:
        return f"answer:{self.session.key}:{question_id}"

    @staticmethod
    def _is_secret(questions: list[Question], question_id: str) -> bool:
        return any(x.id == question_id and x.kind == QuestionKind.SECRET for x in questions)
