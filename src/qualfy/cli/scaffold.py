"""`qualfy new`: create a test repository from a bundled template."""

from __future__ import annotations

import re
import shutil
import subprocess
from importlib import resources
from pathlib import Path

TEMPLATES = ("playwright",)
RENAMES = {"gitignore": ".gitignore"}
TEXT_SUFFIXES = {".md", ".json", ".ts", ".yaml", ".yml", ".example", ""}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "qualfy-project"


def create_project(target: Path, *, name: str | None = None, template: str = "playwright",
                   git: bool = True, force: bool = False) -> list[Path]:
    if template not in TEMPLATES:
        raise ValueError(f"unknown template '{template}' ({', '.join(TEMPLATES)})")
    target = target.resolve()
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(f"{target} is not empty (use --force to scaffold into it)")
    display = name or target.name
    replacements = {"__PROJECT_NAME__": display, "__PROJECT_SLUG__": slugify(display)}

    written: list[Path] = []
    root = resources.files("qualfy.templates") / template
    for source, relative in _walk(root):
        parts = [RENAMES.get(p, p) for p in relative]
        dest = target.joinpath(*parts)
        if dest.exists() and not force:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        if dest.suffix in TEXT_SUFFIXES:
            text = data.decode()
            for key, value in replacements.items():
                text = text.replace(key, value)
            dest.write_text(text)
        else:
            dest.write_bytes(data)
        written.append(dest)

    if git and shutil.which("git") and not (target / ".git").exists():
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=False)
    return written


def _walk(node, prefix: tuple[str, ...] = ()):
    for child in sorted(node.iterdir(), key=lambda c: c.name):
        if child.name in {"__pycache__", "__init__.py"}:
            continue
        if child.is_dir():
            yield from _walk(child, (*prefix, child.name))
        else:
            yield child, (*prefix, child.name)
