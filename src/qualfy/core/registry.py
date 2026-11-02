from __future__ import annotations

from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Literal

from qualfy.core.config import AdapterConfig, SecretResolver, interpolate
from qualfy.core.errors import AdapterNotFound, ConfigError, SchemaError
from qualfy.core.schema import from_dict

Slot = Literal["sources", "sinks", "agents", "analyzers", "classifiers", "hosts"]
SLOTS: tuple[Slot, ...] = ("sources", "sinks", "agents", "analyzers", "classifiers", "hosts")


class Registry:
    """Maps adapter kinds to classes; plugins register through `qualfy.<slot>` entry points."""

    def __init__(self) -> None:
        self._kinds: dict[Slot, dict[str, type]] = {slot: {} for slot in SLOTS}

    def register(self, slot: Slot, cls: type) -> type:
        self._kinds[slot][cls.kind] = cls
        return cls

    def kinds(self, slot: Slot) -> dict[str, type]:
        return dict(self._kinds[slot])

    def build(self, slot: Slot, name: str, config: AdapterConfig, *,
              base_dir: Path | None = None, secrets: SecretResolver | None = None) -> Any:
        cls = self._kinds[slot].get(config.kind)
        if cls is None:
            available = ", ".join(sorted(self._kinds[slot])) or "none"
            raise AdapterNotFound(f"{slot} '{name}': unknown kind '{config.kind}' ({available})")
        options = interpolate(config.options, secrets)
        if base_dir is not None and "base_dir" in cls.Options.__dataclass_fields__:
            options.setdefault("base_dir", str(base_dir))
        try:
            return cls(from_dict(cls.Options, options))
        except SchemaError as exc:
            raise ConfigError(f"{slot} '{name}' ({config.kind}) options invalid:\n{exc}") from exc

    def load_entry_points(self) -> Registry:
        for slot in SLOTS:
            for ep in entry_points(group=f"qualfy.{slot}"):
                if ep.name not in self._kinds[slot]:
                    self.register(slot, ep.load())
        return self


def default_registry() -> Registry:
    from qualfy.adapters import register_builtins

    registry = Registry()
    register_builtins(registry)
    return registry.load_entry_points()
