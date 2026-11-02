from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from qualfy.core.events import Event
from qualfy.core.models import AutomationResult, Session, TestSpec, utcnow
from qualfy.core.schema import dumps, loads


@dataclass
class RunRecord:
    run_id: str
    project: str
    spec_ref: str
    status: str | None = None
    started_at: datetime | None = None


class RunStore:
    """Filesystem history: <workspace>/runs/<run_id>/… and <workspace>/sessions/<key>.json.

    Swap for a DB-backed implementation when the API service lands; the service only uses this API.
    """

    def __init__(self, root: Path) -> None:
        self.root = root / "runs"
        self.sessions_dir = root / "sessions"

    # ---- runs --------------------------------------------------------------------------------

    def new_run(self, project: str, spec: TestSpec) -> RunRecord:
        run_id = f"{utcnow():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
        record = RunRecord(run_id=run_id, project=project, spec_ref=str(spec.ref),
                           started_at=utcnow())
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        self._write(run_dir / "meta.json", record)
        self._write(run_dir / "spec.json", spec)
        return record

    def run_dir(self, run_id: str) -> Path:
        return self.root / run_id

    def append_event(self, event: Event) -> None:
        if event.run_id is None:
            return
        path = self.run_dir(event.run_id) / "events.jsonl"
        if path.parent.exists():
            with path.open("a") as fh:
                fh.write(dumps(event, indent=None) + "\n")

    def save_result(self, result: AutomationResult) -> None:
        self._write(self.run_dir(result.run_id) / "result.json", result)
        meta = self.load_meta(result.run_id)
        meta.status = result.status.value
        self._write(self.run_dir(result.run_id) / "meta.json", meta)

    def load_meta(self, run_id: str) -> RunRecord:
        return loads(RunRecord, (self.run_dir(run_id) / "meta.json").read_text())

    def load_spec(self, run_id: str) -> TestSpec:
        return loads(TestSpec, (self.run_dir(run_id) / "spec.json").read_text())

    def load_result(self, run_id: str) -> AutomationResult | None:
        path = self.run_dir(run_id) / "result.json"
        return loads(AutomationResult, path.read_text()) if path.exists() else None

    def load_events(self, run_id: str) -> list[Event]:
        path = self.run_dir(run_id) / "events.jsonl"
        if not path.exists():
            return []
        return [loads(Event, line) for line in path.read_text().splitlines() if line]

    def list_runs(self, limit: int = 50) -> list[RunRecord]:
        if not self.root.exists():
            return []
        metas = sorted(self.root.glob("*/meta.json"), reverse=True)[:limit]
        return [loads(RunRecord, p.read_text()) for p in metas]

    # ---- sessions ----------------------------------------------------------------------------

    def session_path(self, key: str) -> Path:
        return self.sessions_dir / f"{re.sub(r'[^A-Za-z0-9._-]', '_', key)}.json"

    def load_session(self, key: str) -> Session | None:
        path = self.session_path(key)
        return loads(Session, path.read_text()) if path.exists() else None

    def save_session(self, session: Session) -> None:
        session.updated_at = utcnow()
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._write(self.session_path(session.key), session)

    def list_sessions(self) -> list[Session]:
        if not self.sessions_dir.exists():
            return []
        return sorted((loads(Session, p.read_text()) for p in self.sessions_dir.glob("*.json")),
                      key=lambda s: s.updated_at, reverse=True)

    @staticmethod
    def _write(path: Path, obj: Any) -> None:
        path.write_text(dumps(obj))
