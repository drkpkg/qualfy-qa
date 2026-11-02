from __future__ import annotations

from typing import ClassVar

import httpx

from qualfy.adapters.jira import JiraClient, JiraOptions, markdown_to_adf
from qualfy.adapters.report_text import result_markdown
from qualfy.core.errors import SinkError
from qualfy.core.models import AutomationResult, TestSpec


class JiraCommentSink:
    """Posts the run summary as a comment on the originating Jira ticket."""

    kind: ClassVar[str] = "jira-comment"
    Options: ClassVar[type] = JiraOptions
    interactive: ClassVar[bool] = True

    def __init__(self, options: JiraOptions,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.client = JiraClient(options, transport=transport)

    def draft(self, spec: TestSpec, result: AutomationResult) -> str:
        return result_markdown(spec, result)

    async def publish(self, spec: TestSpec, result: AutomationResult, body: str) -> str | None:
        if spec.ref.system != "jira":
            raise SinkError(f"cannot comment on non-Jira ticket {spec.ref}")
        comment = await self.client.add_comment(spec.ref.key, markdown_to_adf(body))
        return f"{self.client.browse_url(spec.ref.key)}?focusedCommentId={comment.get('id', '')}"
