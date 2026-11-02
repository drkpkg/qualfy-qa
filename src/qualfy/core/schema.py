"""Stdlib-only (de)serialization, validation and JSON Schema for dataclass models.

Replaces pydantic so the package runs on distro Python packages (Ubuntu 24.04 ships pydantic 1.x).
Supported annotations: str, int, float, bool, Any, Path, datetime, StrEnum, dataclasses,
list[X], dict[str, X], X | None and Secret.
"""

from __future__ import annotations

import dataclasses
import json
import types
import typing
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar, get_args, get_origin, get_type_hints

from qualfy.core.errors import SchemaError

T = TypeVar("T")
_MISSING = dataclasses.MISSING


class Secret(str):
    """A str that never prints its value."""

    def __repr__(self) -> str:
        return "Secret('***')"

    def reveal(self) -> str:
        return str.__str__(self)


def field(*, default: Any = _MISSING, default_factory: Any = _MISSING, min_items: int | None = None,
          description: str | None = None) -> Any:
    metadata = {k: v for k, v in (("min_items", min_items), ("description", description)) if v}
    kwargs: dict[str, Any] = {"metadata": metadata}
    if default is not _MISSING:
        kwargs["default"] = default
    if default_factory is not _MISSING:
        kwargs["default_factory"] = default_factory
    return dataclasses.field(**kwargs)


def from_dict[T](cls: type[T], data: Any) -> T:
    errors: list[str] = []
    value = _convert(cls, data, "", errors)
    if errors:
        raise SchemaError(errors)
    return value


def loads[T](cls: type[T], text: str) -> T:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaError([f"invalid JSON: {exc}"]) from exc
    return from_dict(cls, data)


def to_dict(obj: Any, *, exclude: set[str] | None = None) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: to_dict(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
            if not (exclude and f.name in exclude)
        }
    if isinstance(obj, Secret):
        return obj.reveal()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [to_dict(v) for v in obj]
    return obj


def dumps(obj: Any, *, indent: int | None = 2, exclude: set[str] | None = None) -> str:
    return json.dumps(to_dict(obj, exclude=exclude), indent=indent, ensure_ascii=False)


def json_schema(cls: type) -> dict[str, Any]:
    return inline_schema(cls)


# ---- internals ------------------------------------------------------------------------------


def _hints(cls: type) -> dict[str, Any]:
    return get_type_hints(cls, include_extras=False)


def _is_optional(tp: Any) -> tuple[bool, Any]:
    if get_origin(tp) in (typing.Union, types.UnionType):
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) < len(get_args(tp)):
            return True, args[0] if len(args) == 1 else typing.Union[tuple(args)]  # noqa: UP007
    return False, tp


def _convert(tp: Any, value: Any, loc: str, errors: list[str]) -> Any:
    optional, inner = _is_optional(tp)
    if value is None:
        if optional or tp is Any:
            return None
        errors.append(f"{loc or 'value'}: field required")
        return None
    tp = inner
    origin = get_origin(tp)

    if tp is Any:
        return value
    if origin is typing.Literal:
        if value in get_args(tp):
            return value
        allowed = ", ".join(repr(a) for a in get_args(tp))
        errors.append(f"{loc or 'value'}: {value!r} is not one of {allowed}")
        return None
    if dataclasses.is_dataclass(tp):
        return _convert_dataclass(tp, value, loc, errors)
    if isinstance(tp, type) and issubclass(tp, Enum):
        try:
            return tp(value)
        except ValueError:
            allowed = ", ".join(repr(m.value) for m in tp)
            errors.append(f"{loc}: {value!r} is not one of {allowed}")
            return None
    if origin is list:
        if not isinstance(value, list | tuple):
            errors.append(f"{loc}: expected a list")
            return []
        (item,) = get_args(tp) or (Any,)
        return [_convert(item, v, f"{loc}.{i}" if loc else str(i), errors)
                for i, v in enumerate(value)]
    if origin is dict:
        if not isinstance(value, dict):
            errors.append(f"{loc}: expected a mapping")
            return {}
        _, item = get_args(tp) or (str, Any)
        return {str(k): _convert(item, v, f"{loc}.{k}" if loc else str(k), errors)
                for k, v in value.items()}
    if tp is Secret:
        return Secret(value) if isinstance(value, str) else _type_error(loc, "string", errors)
    if tp is Path:
        return Path(value) if isinstance(value, str | Path) else _type_error(loc, "path", errors)
    if tp is datetime:
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return _type_error(loc, "ISO datetime", errors)
    if tp is bool:
        return value if isinstance(value, bool) else _type_error(loc, "boolean", errors)
    if tp is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
        return value if ok else _type_error(loc, "integer", errors)
    if tp is float:
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        return float(value) if ok else _type_error(loc, "number", errors)
    if tp is str:
        if isinstance(value, str):
            return value
        if isinstance(value, int | float) and not isinstance(value, bool):
            return str(value)
        return _type_error(loc, "string", errors)
    if get_origin(tp) in (typing.Union, types.UnionType):
        for candidate in get_args(tp):
            trial: list[str] = []
            result = _convert(candidate, value, loc, trial)
            if not trial:
                return result
        errors.append(f"{loc}: does not match any allowed type")
        return None
    return value


def _type_error(loc: str, expected: str, errors: list[str]) -> None:
    errors.append(f"{loc or 'value'}: expected {expected}")
    return None


def _convert_dataclass(cls: type, value: Any, loc: str, errors: list[str]) -> Any:
    if isinstance(value, cls):
        return value
    coerce = getattr(cls, "__coerce__", None)
    if coerce is not None and isinstance(value, dict):
        value = coerce(dict(value))
    if not isinstance(value, dict):
        errors.append(f"{loc or cls.__name__}: expected an object")
        return None
    hints = _hints(cls)
    fields = {f.name: f for f in dataclasses.fields(cls) if f.init}
    extra = set(value) - set(fields)
    if extra and getattr(cls, "__extra__", "forbid") == "forbid":
        for name in sorted(extra):
            errors.append(f"{_join(loc, name)}: unexpected field")
    kwargs: dict[str, Any] = {}
    start = len(errors)
    for name, f in fields.items():
        sub = _join(loc, name)
        if name not in value:
            if f.default is _MISSING and f.default_factory is _MISSING:
                errors.append(f"{sub}: field required")
            continue
        converted = _convert(hints[name], value[name], sub, errors)
        min_items = f.metadata.get("min_items")
        if min_items and isinstance(converted, list) and len(converted) < min_items:
            errors.append(f"{sub}: must contain at least {min_items} item(s)")
        kwargs[name] = converted
    if len(errors) > start:
        return None
    try:
        return cls(**kwargs)
    except (TypeError, ValueError) as exc:
        errors.append(f"{loc or cls.__name__}: {exc}")
        return None


def _join(loc: str, name: str) -> str:
    return f"{loc}.{name}" if loc else name


def _schema(tp: Any, defs: dict[str, Any]) -> dict[str, Any]:
    optional, inner = _is_optional(tp)
    if optional:
        return {"anyOf": [_schema(inner, defs), {"type": "null"}]}
    origin = get_origin(tp)
    if tp is Any:
        return {}
    if origin is typing.Literal:
        return {"enum": list(get_args(tp))}
    if dataclasses.is_dataclass(tp):
        name = tp.__name__
        if name not in defs:
            defs[name] = {}  # recursion guard
            hints = _hints(tp)
            props, required = {}, []
            for f in dataclasses.fields(tp):
                if not f.init:
                    continue
                prop = _schema(hints[f.name], defs)
                if desc := f.metadata.get("description"):
                    prop["description"] = desc
                if min_items := f.metadata.get("min_items"):
                    prop["minItems"] = min_items
                props[f.name] = prop
                if f.default is _MISSING and f.default_factory is _MISSING:
                    required.append(f.name)
            defs[name] = {"type": "object", "title": name, "properties": props,
                          "required": required,
                          "additionalProperties": getattr(tp, "__extra__", "forbid") != "forbid"}
            if tp.__doc__ and not tp.__doc__.startswith(f"{name}("):
                defs[name]["description"] = " ".join(tp.__doc__.split())
        return {"$ref": f"#/$defs/{name}"}
    if isinstance(tp, type) and issubclass(tp, Enum):
        return {"type": "string", "enum": [m.value for m in tp]}
    if origin is list:
        (item,) = get_args(tp) or (Any,)
        return {"type": "array", "items": _schema(item, defs)}
    if origin is dict:
        _, item = get_args(tp) or (str, Any)
        return {"type": "object", "additionalProperties": _schema(item, defs)}
    if get_origin(tp) in (typing.Union, types.UnionType):
        return {"anyOf": [_schema(a, defs) for a in get_args(tp)]}
    return {
        str: {"type": "string"}, Secret: {"type": "string"}, Path: {"type": "string"},
        int: {"type": "integer"}, float: {"type": "number"}, bool: {"type": "boolean"},
        datetime: {"type": "string", "format": "date-time"},
    }.get(tp, {})


def inline_schema(cls: type) -> dict[str, Any]:
    """Schema with the root object inlined; what `claude --json-schema` and prompts expect."""
    defs: dict[str, Any] = {}
    _schema(cls, defs)
    root = dict(defs.pop(cls.__name__))
    if defs:
        root["$defs"] = defs
    return root
