from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from qualfy.core.errors import ConfigError, SchemaError
from qualfy.core.schema import field, from_dict, to_dict

CONFIG_NAME = "qualfy.yaml"
REF_RE = re.compile(r"\$\{(?:(secret):)?([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

SecretResolver = Callable[[str], str | None]


@dataclass
class AdapterConfig:
    kind: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectConfig:
    source: str
    agent: str = "default"
    analyzer: str | None = None
    classifier: str | None = None
    host: str | None = None
    sinks: list[str] = field(default_factory=list)
    framework: str | None = None


@dataclass
class Config:
    name: str = "qualfy"
    workspace: Path = Path(".qualfy")
    sources: dict[str, AdapterConfig] = field(default_factory=dict)
    sinks: dict[str, AdapterConfig] = field(default_factory=dict)
    agents: dict[str, AdapterConfig] = field(
        default_factory=lambda: {"default": AdapterConfig(kind="dry-run")}
    )
    analyzers: dict[str, AdapterConfig] = field(default_factory=dict)
    classifiers: dict[str, AdapterConfig] = field(default_factory=dict)
    hosts: dict[str, AdapterConfig] = field(default_factory=dict)
    projects: dict[str, ProjectConfig] = field(default_factory=dict)
    base_dir: Path = Path(".")
    path: Path | None = None

    def __post_init__(self) -> None:
        for name, project in self.projects.items():
            refs = [("sources", project.source), ("agents", project.agent)]
            refs += [("sinks", s) for s in project.sinks]
            refs += [(slot, ref) for slot, ref in (("analyzers", project.analyzer),
                                                   ("classifiers", project.classifier),
                                                   ("hosts", project.host)) if ref]
            for slot, ref in refs:
                if ref not in getattr(self, slot):
                    raise ValueError(f"project '{name}': unknown {slot[:-1]} '{ref}'")

    @property
    def workspace_dir(self) -> Path:
        return self.workspace if self.workspace.is_absolute() else self.base_dir / self.workspace

    def project(self, name: str | None) -> tuple[str, ProjectConfig]:
        if not self.projects:
            raise ConfigError("no projects defined in config")
        if name is None:
            if "default" in self.projects:
                name = "default"
            elif len(self.projects) == 1:
                name = next(iter(self.projects))
            else:
                raise ConfigError(f"several projects defined, pick one: {', '.join(self.projects)}")
        try:
            return name, self.projects[name]
        except KeyError:
            raise ConfigError(f"unknown project '{name}'") from None

    def to_yaml(self) -> str:
        data = to_dict(self, exclude={"base_dir", "path"})
        for project in data["projects"].values():
            for key in [k for k, v in project.items() if v in (None, [])]:
                del project[key]
        for slot in ("analyzers", "classifiers", "hosts"):
            if not data[slot]:
                del data[slot]
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def find_config(start: Path | None = None) -> Path:
    """Walk up from `start` to find qualfy.yaml, like git does for .git."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate
    return here / CONFIG_NAME


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigError(f"config file not found: {path} (run `qualfy new` or `qualfy connect`)")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    try:
        return from_dict(Config, {**raw, "base_dir": str(path.parent.resolve()),
                                  "path": str(path.resolve())})
    except SchemaError as exc:
        raise ConfigError(f"invalid config {path}:\n{exc}") from exc
    except ValueError as exc:
        raise ConfigError(f"invalid config {path}: {exc}") from exc


def save_config(config: Config, path: Path | None = None) -> Path:
    target = path or config.path or config.base_dir / CONFIG_NAME
    header = "# qualfy configuration. ${VAR} reads the environment, ${secret:name} the keyring.\n"
    target.write_text(header + config.to_yaml())
    return target


def interpolate(value: Any, secrets: SecretResolver | None = None) -> Any:
    """Resolve ${VAR}, ${VAR:-default} and ${secret:name}. Applied lazily per adapter."""
    if isinstance(value, str):
        def _sub(match: re.Match[str]) -> str:
            is_secret, name, default = match.group(1), match.group(2), match.group(3)
            if is_secret:
                resolved = secrets(name) if secrets else None
                if resolved is None:
                    raise ConfigError(f"secret '{name}' not found (run `qualfy connect`)")
                return resolved
            resolved = os.environ.get(name, default)
            if resolved is None:
                raise ConfigError(f"environment variable {name} is not set")
            return resolved

        return REF_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: interpolate(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, secrets) for v in value]
    return value
