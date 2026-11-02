from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import httpx

from qualfy.adapters.github import GitHubClient, GitHubOptions
from qualfy.adapters.report_text import result_markdown
from qualfy.core.errors import SinkError
from qualfy.core.models import AutomationResult, TestSpec
from qualfy.core.schema import field


@dataclass
class GitHubCommentOptions(GitHubOptions):
    labels: dict[str, list[str]] = field(
        default_factory=dict, description="run status -> labels to add, e.g. success: [qa:done]")
    remove_labels: list[str] = field(
        default_factory=list, description="labels removed after publishing, e.g. qa:ready")


class GitHubCommentSink:
    """Comments the run summary on the originating GitHub issue and moves its labels."""

    kind: ClassVar[str] = "github-comment"
    Options: ClassVar[type] = GitHubCommentOptions
    interactive: ClassVar[bool] = True

    def __init__(self, options: GitHubCommentOptions,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.options = options
        self.client = GitHubClient(options, transport=transport)

    def draft(self, spec: TestSpec, result: AutomationResult) -> str:
        return result_markdown(spec, result)

    async def publish(self, spec: TestSpec, result: AutomationResult, body: str) -> str | None:
        if spec.ref.system != "github":
            raise SinkError(f"cannot comment on non-GitHub ticket {spec.ref}")
        number = self.client.parse_number(spec.ref.key)
        comment = await self.client.add_comment(number, body)
        if add := self.options.labels.get(result.status.value):
            await self.client.add_labels(number, add)
        for label in self.options.remove_labels:
            await self.client.remove_label(number, label)
        return comment.get("html_url")
