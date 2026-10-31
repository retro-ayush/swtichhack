"""In-process pub/sub feeding the dashboard's SSE stream.

publish() is safe to call from any thread (API handlers run in FastAPI's
threadpool; the Switch connector runs on the event loop)."""
from __future__ import annotations

import asyncio
import json
from typing import Any

_loop: asyncio.AbstractEventLoop | None = None
_subscribers: set[asyncio.Queue] = set()


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def publish(event: dict[str, Any]) -> None:
    if _loop is None:
        return

    def _put() -> None:
        for q in list(_subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    try:
        _loop.call_soon_threadsafe(_put)
    except RuntimeError:
        pass  # loop shut down


def sse_format(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"
