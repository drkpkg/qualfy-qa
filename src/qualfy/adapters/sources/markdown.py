from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from qualfy.core.contract import build_spec, extract_contract
from qualfy.core.errors import SourceError
from qualfy.core.models import Ref, SpecSummary, TestSpec, Ticket


@dataclass
class MarkdownOptions:
    path: str = "specs"
    pattern: str = "*.md"
    base_dir: str = "."


class MarkdownSource:
    """Local markdown files with a fenced contract block. Useful for dev, demos and CI fixtures."""

    kind: ClassVar[str] = "markdown"
    Options: ClassVar[type] = MarkdownOptions

    def __init__(self, options: MarkdownOptions) -> None:
        root = Path(options.path)
        self.root = root if root.is_absolute() else Path(options.base_dir) / root
        self.pattern = options.pattern

    async def discover(self) -> list[SpecSummary]:
        return [SpecSummary(ref=self._ref(f), title=_heading(f) or f.stem)
                for f in sorted(self.root.glob(self.pattern))]

    async def fetch(self, key: str) -> Path:
        for candidate in (Path(key), self.root / key, self.root / f"{key}.md"):
            if candidate.is_file():
                return candidate
        raise SourceError(f"markdown spec '{key}' not found under {self.root}")

    async def ticket(self, raw: Path) -> Ticket:
        return Ticket(ref=self._ref(raw), title=_heading(raw) or raw.stem, body=raw.read_text())

    async def normalize(self, raw: Path) -> TestSpec:
        data = extract_contract(raw.read_text())
        key = str(data.get("key") or raw.stem)
        return build_spec(data, ref=Ref(system="markdown", key=key, url=raw.resolve().as_uri()),
                          title=_heading(raw), generator="human")

    def _ref(self, file: Path) -> Ref:
        return Ref(system="markdown", key=file.stem, url=file.resolve().as_uri())


def _heading(file: Path) -> str | None:
    for line in file.read_text().splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None
