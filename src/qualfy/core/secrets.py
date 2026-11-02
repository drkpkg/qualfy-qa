"""Credential storage: env override → OS keyring (if installed and usable) → 0600 file."""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Protocol

SERVICE = "qualfy"


class SecretStore(Protocol):
    name: str

    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...

    def delete(self, key: str) -> None: ...


class FileStore:
    name = "file"

    def __init__(self, path: Path | None = None) -> None:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.path = path or base / "qualfy" / "credentials.json"

    def _load(self) -> dict[str, str]:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
        tmp.replace(self.path)

    def get(self, key: str) -> str | None:
        return self._load().get(key)

    def set(self, key: str, value: str) -> None:
        data = self._load()
        data[key] = value
        self._save(data)

    def delete(self, key: str) -> None:
        data = self._load()
        if data.pop(key, None) is not None:
            self._save(data)


class KeyringStore:
    name = "keyring"

    def __init__(self) -> None:
        import keyring

        self._keyring = keyring

    def get(self, key: str) -> str | None:
        return self._keyring.get_password(SERVICE, key)

    def set(self, key: str, value: str) -> None:
        self._keyring.set_password(SERVICE, key, value)

    def delete(self, key: str) -> None:
        with contextlib.suppress(self._keyring.errors.PasswordDeleteError):
            self._keyring.delete_password(SERVICE, key)


class Secrets:
    """Namespaced per project so two projects can hold different tokens."""

    def __init__(self, namespace: str, store: SecretStore | None = None) -> None:
        self.namespace = namespace
        self.store = store or default_store()

    def _key(self, name: str) -> str:
        return f"{self.namespace}:{name}"

    def get(self, name: str) -> str | None:
        env = os.environ.get(f"QUALFY_SECRET_{name.upper()}")
        return env if env is not None else self.store.get(self._key(name))

    def set(self, name: str, value: str) -> None:
        self.store.set(self._key(name), value)

    def delete(self, name: str) -> None:
        self.store.delete(self._key(name))


def default_store() -> SecretStore:
    if os.environ.get("QUALFY_SECRET_STORE") != "file":
        try:
            import keyring
            from keyring.backends import fail

            if not isinstance(keyring.get_keyring(), fail.Keyring):
                return KeyringStore()
        except Exception:
            pass
    return FileStore()
