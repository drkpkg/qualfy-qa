"""The YAML test-ticket contract (v1) that generators like Rovo or humans fill in.

    key: PROJ-123          # optional, falls back to the ticket key
    title: Checkout        # optional, falls back to the ticket summary
    spec: PROJ-120         # upstream requirement
    framework: playwright  # optional hint for the agent
    cases:
      - id: TC-1
        title: ...
        steps: [ "do X", {action: "do Y", expected: ["Z"]} ]
        expected: [ ... ]
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from qualfy.core.errors import ContractError, SchemaError
from qualfy.core.models import Ref, TestSpec
from qualfy.core.schema import from_dict, to_dict

FENCE_RE = re.compile(r"```(?:ya?ml|qualfy)?[ \t]*\n(.*?)```", re.DOTALL)


def load_contract(text: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ContractError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict) or "cases" not in data:
        raise ContractError("contract must be a mapping with a 'cases' list")
    return data


def extract_contract(text: str) -> dict[str, Any]:
    """Find the first fenced YAML block in free text that looks like a contract."""
    for block in FENCE_RE.findall(text):
        try:
            return load_contract(block)
        except ContractError:
            continue
    raise ContractError("no fenced YAML block with a 'cases' list found")


def build_spec(
    data: dict[str, Any],
    *,
    ref: Ref,
    title: str | None = None,
    generator: str,
    spec_system: str | None = None,
) -> TestSpec:
    upstream = data.get("spec")
    try:
        return from_dict(TestSpec, {
            "ref": to_dict(ref),
            "title": data.get("title") or title or ref.key,
            "spec_ref": {"system": spec_system or ref.system, "key": str(upstream)}
            if upstream else None,
            "generator": data.get("generator", generator),
            "framework": data.get("framework"),
            "cases": data["cases"],
        })
    except SchemaError as exc:
        raise ContractError(f"contract validation failed:\n{exc}") from exc
