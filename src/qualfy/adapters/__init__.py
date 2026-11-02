from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qualfy.core.registry import Registry


def register_builtins(registry: Registry) -> None:
    from qualfy.adapters.agents.claude_code import ClaudeCodeAgent
    from qualfy.adapters.agents.dry_run import DryRunAgent
    from qualfy.adapters.analyzers.claude import ClaudeAnalyzer
    from qualfy.adapters.analyzers.static import StaticAnalyzer
    from qualfy.adapters.classifiers.claude import ClaudeClassifier
    from qualfy.adapters.classifiers.rules import RulesClassifier
    from qualfy.adapters.hosts.github import GitHubHost
    from qualfy.adapters.sinks.github_comment import GitHubCommentSink
    from qualfy.adapters.sinks.jira_comment import JiraCommentSink
    from qualfy.adapters.sinks.json_file import JsonFileSink
    from qualfy.adapters.sources.github_issues import GitHubIssuesSource
    from qualfy.adapters.sources.jira_rovo import JiraRovoSource
    from qualfy.adapters.sources.markdown import MarkdownSource

    builtins = {
        "sources": (MarkdownSource, JiraRovoSource, GitHubIssuesSource),
        "sinks": (JsonFileSink, JiraCommentSink, GitHubCommentSink),
        "agents": (ClaudeCodeAgent, DryRunAgent),
        "analyzers": (StaticAnalyzer, ClaudeAnalyzer),
        "classifiers": (RulesClassifier, ClaudeClassifier),
        "hosts": (GitHubHost,),
    }
    for slot, classes in builtins.items():
        for cls in classes:
            registry.register(slot, cls)
