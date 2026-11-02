from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

import pytest

from qualfy.core.errors import SchemaError
from qualfy.core.models import AutomationResult, RunStatus, TestSpec, utcnow
from qualfy.core.schema import Secret, dumps, field, from_dict, json_schema, loads, to_dict


class Color(StrEnum):
    RED = "red"
    BLUE = "blue"


@dataclass
class Inner:
    name: str
    tags: list[str] = field(default_factory=list)


@dataclass
class Outer:
    id: int
    inner: Inner
    items: list[Inner] = field(min_items=1)
    color: Color = Color.RED
    mode: Literal["a", "b"] = "a"
    extra: dict[str, Any] = field(default_factory=dict)
    when: datetime | None = None
    token: Secret | None = None
    ratio: float = 1.0


def test_round_trip():
    data = {"id": 1, "inner": {"name": "x"}, "items": [{"name": "y", "tags": ["t"]}],
            "color": "blue", "mode": "b", "when": "2026-11-02T10:00:00+00:00", "token": "s3cr3t",
            "ratio": 2}
    obj = from_dict(Outer, data)
    assert obj.color is Color.BLUE and obj.items[0].tags == ["t"] and obj.ratio == 2.0
    assert isinstance(obj.when, datetime)
    assert repr(obj.token) == "Secret('***')" and to_dict(obj)["token"] == "s3cr3t"
    assert loads(Outer, dumps(obj)) == obj


def test_errors_are_collected_with_paths():
    with pytest.raises(SchemaError) as exc:
        from_dict(Outer, {"id": "nope", "inner": {}, "items": [], "color": "green",
                          "mode": "z", "bogus": 1})
    text = str(exc.value)
    for fragment in ("id: expected integer", "inner.name: field required",
                     "items: must contain at least 1", "color: 'green' is not one of",
                     "mode: 'z' is not one of", "bogus: unexpected field"):
        assert fragment in text


def test_bool_is_not_int_and_numbers_become_strings():
    with pytest.raises(SchemaError):
        from_dict(Outer, {"id": True, "inner": {"name": "x"}, "items": [{"name": "y"}]})
    assert from_dict(Inner, {"name": 5}).name == "5"


def test_json_schema_shape():
    schema = json_schema(Outer)
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert set(schema["required"]) == {"id", "inner", "items"}
    assert schema["properties"]["items"]["minItems"] == 1
    assert schema["properties"]["color"] == {"type": "string", "enum": ["red", "blue"]}
    assert schema["properties"]["mode"] == {"enum": ["a", "b"]}
    assert schema["properties"]["inner"] == {"$ref": "#/$defs/Inner"}
    assert "Inner" in schema["$defs"]


def test_models_round_trip():
    spec = from_dict(TestSpec, {"ref": {"system": "x", "key": "K-1"}, "title": "t",
                                "cases": [{"id": 1, "title": "c", "steps": ["a"]}]})
    assert spec.cases[0].id == "1" and spec.revision
    result = AutomationResult(run_id="r", spec_ref=spec.ref, spec_revision=spec.revision,
                              status=RunStatus.SUCCESS, started_at=utcnow(), finished_at=utcnow())
    assert loads(AutomationResult, dumps(result)) == result
