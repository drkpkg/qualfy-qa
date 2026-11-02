from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from qualfy.core.models import AutomationResult, TestSpec
from qualfy.core.schema import dumps


@dataclass
class JsonFileOptions:
    path: str = ".qualfy/results"
    base_dir: str = "."


class JsonFileSink:
    """Writes each AutomationResult as a JSON file; handy for CI artifacts and dashboards."""

    kind: ClassVar[str] = "json-file"
    Options: ClassVar[type] = JsonFileOptions
    interactive: ClassVar[bool] = False

    def __init__(self, options: JsonFileOptions) -> None:
        root = Path(options.path)
        self.root = root if root.is_absolute() else Path(options.base_dir) / root

    def draft(self, spec: TestSpec, result: AutomationResult) -> str:
        return dumps(result)

    async def publish(self, spec: TestSpec, result: AutomationResult, body: str) -> str | None:
        self.root.mkdir(parents=True, exist_ok=True)
        safe_key = spec.ref.key.replace("/", "_").replace("#", "-")
        path = self.root / f"{spec.ref.system}-{safe_key}-{result.run_id}.json"
        path.write_text(body)
        return str(path)
