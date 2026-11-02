from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from qualfy.core.models import utcnow
from qualfy.core.schema import field

log = logging.getLogger(__name__)

EventKind = Literal[
    "run.started",
    "run.finished",
    "stage.started",
    "stage.finished",
    "stage.failed",
    "agent.message",
    "agent.tool",
    "agent.result",
    "log",
]


@dataclass
class Event:
    """UI-agnostic progress event. Serializable so an API can stream it as SSE/WebSocket."""

    kind: str
    run_id: str | None = None
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    at: datetime = field(default_factory=utcnow)


Handler = Callable[[Event], Awaitable[None] | None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[Handler] = []

    def subscribe(self, handler: Handler) -> Callable[[], None]:
        self._handlers.append(handler)
        return lambda: self._handlers.remove(handler)

    async def publish(self, event: Event) -> None:
        for handler in list(self._handlers):
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                log.exception("event handler failed for %s", event.kind)

    async def emit(self, kind: EventKind, message: str = "", *, run_id: str | None = None,
                   **data: Any) -> None:
        await self.publish(Event(kind=kind, run_id=run_id, message=message, data=data))

    async def stream(self, run_id: str | None = None) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()

        def _enqueue(event: Event) -> None:
            if run_id is None or event.run_id == run_id:
                queue.put_nowait(event)

        unsubscribe = self.subscribe(_enqueue)
        try:
            while True:
                event = await queue.get()
                yield event
                if event.kind == "run.finished" and run_id is not None:
                    return
        finally:
            unsubscribe()


class RunEmitter:
    """EventBus bound to a run id, handed to adapters so they never deal with run bookkeeping."""

    def __init__(self, bus: EventBus, run_id: str | None) -> None:
        self.bus = bus
        self.run_id = run_id

    async def __call__(self, kind: EventKind, message: str = "", **data: Any) -> None:
        await self.bus.emit(kind, message, run_id=self.run_id, **data)
