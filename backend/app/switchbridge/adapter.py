"""Switch agent-protocol client.

Implements only what the published protocol documents
(docs.switchagents.ai/switch-rooms/internals/agent-protocol):
- one SSE stream down: GET /agents/{id}/events?connection_id=...&scope=...&filter=all
- heartbeat every 2 s: POST /agents/{id}/connection/beat {connection_id, cursor}
  (404/409 => reopen the stream, not back off)
- operations up:      POST /agents/{id}/ops/{name} + X-Switch-Connection-Id header
- auth: Authorization: Bearer <agent API key> on every call

With no credentials configured the module stays in "disabled" state and
deliver() reports "local", so the rest of the app never pretends a Switch
delivery happened.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Awaitable, Callable

import httpx

from ..config import settings

log = logging.getLogger(__name__)

EventHandler = Callable[[dict], Awaitable[None]]


class SwitchAdapter:
    def __init__(self, endpoint: str, token: str, agent_id: str, room_id: str = "") -> None:
        self.base = endpoint.rstrip("/")
        self.agent_id = agent_id
        self.room_id = room_id
        self.connection_id = str(uuid.uuid4())  # reused across reconnects (protocol rule)
        self.cursor: int | None = None
        self.state = "connecting"
        self.last_error = ""
        self.on_event: EventHandler | None = None
        self._auth = {"Authorization": f"Bearer {token}"}
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=None))
        self._main_task: asyncio.Task | None = None
        self._beat_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._main_task = asyncio.create_task(self._run(), name="switch-stream")

    async def stop(self) -> None:
        for t in (self._beat_task, self._main_task):
            if t:
                t.cancel()
        await self._client.aclose()
        self.state = "stopped"

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                await self._stream_once()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.state = "error"
                self.last_error = f"{type(e).__name__}: {e}"
                log.warning("Switch stream dropped (%s); reconnecting in %.0fs", self.last_error, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def _stream_once(self) -> None:
        params = {
            "connection_id": self.connection_id,
            "scope": "single",
            "filter": "all",
        }
        if self.room_id:
            params["rooms"] = self.room_id  # declare rooms on the open URL (protocol rule)
        headers = {**self._auth, "Accept": "text/event-stream"}
        if self.cursor is not None:
            headers["Last-Event-ID"] = str(self.cursor)

        url = f"{self.base}/agents/{self.agent_id}/events"
        async with self._client.stream("GET", url, params=params, headers=headers) as resp:
            resp.raise_for_status()
            self.state = "connected"
            try:
                async for frame in self._iter_sse(resp):
                    await self._dispatch(frame)
            finally:
                if self._beat_task:
                    self._beat_task.cancel()
                    self._beat_task = None

    @staticmethod
    async def _iter_sse(resp: httpx.Response):
        event: dict[str, Any] = {"event": "message", "data": []}
        async for line in resp.aiter_lines():
            if line == "":
                if event["data"]:
                    yield event
                event = {"event": "message", "data": []}
            elif line.startswith(":"):
                continue  # keepalive comment
            elif line.startswith("event:"):
                event["event"] = line[len("event:"):].strip()
            elif line.startswith("data:"):
                event["data"].append(line[len("data:"):].lstrip())
            elif line.startswith("id:"):
                event["id"] = line[len("id:"):].strip()

    async def _dispatch(self, frame: dict) -> None:
        try:
            data = json.loads("\n".join(frame["data"]))
        except json.JSONDecodeError:
            log.warning("unparseable SSE frame: %r", frame)
            return
        name = frame["event"]

        if name == "connection_state":
            self.cursor = data.get("cursor", self.cursor)
            self.state = "connected"
            if self._beat_task is None:
                interval = float(data.get("heartbeat_interval_seconds") or 2.0)
                self._beat_task = asyncio.create_task(self._beat_loop(interval), name="switch-beat")
            if self.room_id:
                try:
                    await self.op("connect_to_room", room_id=self.room_id)
                except Exception as e:
                    log.warning("connect_to_room failed: %s", e)
            return
        if name == "evicted":
            raise ConnectionError(f"evicted: {data.get('reason')}")
        if name in ("gap", "subscription_changed", "room_released"):
            log.info("control frame %s: %s", name, data)
            return

        # Domain event: cursor rides on the data object as `sequence`.
        if isinstance(data.get("sequence"), int):
            self.cursor = data["sequence"]
        if self.on_event:
            await self.on_event(data)

    async def _beat_loop(self, interval: float) -> None:
        url = f"{self.base}/agents/{self.agent_id}/connection/beat"
        while True:
            await asyncio.sleep(interval)
            try:
                r = await self._client.post(
                    url, headers=self._auth,
                    json={"connection_id": self.connection_id, "cursor": self.cursor or 0},
                )
                if r.status_code in (404, 409):
                    # Protocol: both mean reopen the stream, not back off.
                    log.warning("heartbeat %s -> reopening stream", r.status_code)
                    if self._main_task:
                        self._main_task.cancel()
                        self._main_task = asyncio.create_task(self._run(), name="switch-stream")
                    return
            except httpx.HTTPError as e:
                log.warning("heartbeat error: %s", e)

    # ------------------------------------------------------------ operations
    async def op(self, name: str, **args: Any) -> Any:
        r = await self._client.post(
            f"{self.base}/agents/{self.agent_id}/ops/{name}",
            headers={**self._auth, "X-Switch-Connection-Id": self.connection_id},
            json={k: v for k, v in args.items() if v is not None},
        )
        r.raise_for_status()
        return r.json().get("result")

    async def post_message(self, body: str, thread_id: str | None = None) -> Any:
        return await self.op("post_message", body=body, thread_id=thread_id)

    async def send_targeted(self, targets: list[str], body: str, thread_id: str | None = None) -> Any:
        return await self.op("send_targeted_message", target_names=targets, body=body, thread_id=thread_id)

    async def read_context(self) -> Any:
        return await self.op("read_context")

    def status(self) -> dict:
        return {
            "configured": True, "state": self.state, "agent_id": self.agent_id,
            "room_id": self.room_id, "last_error": self.last_error,
        }


# ------------------------------------------------- module-level singleton API
_adapter: SwitchAdapter | None = None


def build_from_settings() -> SwitchAdapter | None:
    global _adapter
    if settings.switch_configured:
        _adapter = SwitchAdapter(
            settings.switch_endpoint, settings.switch_token,
            settings.switch_agent_id, settings.switch_room_id,
        )
    return _adapter


def get_adapter() -> SwitchAdapter | None:
    return _adapter


def status() -> dict:
    if _adapter is None:
        return {"configured": False, "state": "disabled",
                "hint": "set SWITCH_API_ENDPOINT / SWITCH_API_TOKEN / SWITCH_AGENT_ID / SWITCH_ROOM_ID"}
    return _adapter.status()


def deliver(body: str, target: str | None = None, thread_id: str | None = None) -> str:
    """Synchronous bridge used by the engine (which runs in worker threads).
    Returns the channel the message actually went through: "switch" or "local".
    Never claims Switch delivery that didn't confirm."""
    a = _adapter
    if a is None or a.state != "connected" or a._loop is None:
        return "local"
    coro = a.send_targeted([target], body, thread_id) if target else a.post_message(body, thread_id)
    try:
        fut = asyncio.run_coroutine_threadsafe(coro, a._loop)
        fut.result(timeout=15)
        return "switch"
    except Exception as e:
        log.warning("Switch delivery failed (%s); recorded as local", e)
        return "local"
