"""Optional Textual front end. Ubuntu 24.04 ships textual 0.1.x, so everything degrades to Rich."""

from __future__ import annotations

MIN_TEXTUAL = (2, 1)


def _version() -> tuple[int, ...] | None:
    try:
        from importlib.metadata import version

        return tuple(int(p) for p in version("textual").split(".")[:2])
    except Exception:
        return None


def available() -> bool:
    found = _version()
    return found is not None and found >= MIN_TEXTUAL


def unavailable_reason() -> str:
    found = _version()
    if found is None:
        return "Textual is not installed (install python3-textual / python-textual for the TUI)"
    return (f"Textual {'.'.join(map(str, found))} is too old; the TUI needs "
            f"{'.'.join(map(str, MIN_TEXTUAL))}+")
