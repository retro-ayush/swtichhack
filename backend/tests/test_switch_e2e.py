"""End-to-end over real HTTP against a fake Switch agent bridge.

The fake implements the documented agent protocol surface the adapter uses
(docs.switchagents.ai/switch-rooms/internals/agent-protocol): SSE stream with
a connection_state first frame, heartbeat endpoint, and ops endpoint. It
proves: stream open with the right params, heartbeat, connect_to_room, a
human @mention becoming tasks, and the coordinator's replies going back
through post_message / send_targeted_message (recorded delivered_via=switch).
It does not prove behaviour of the real Switch server; TODO_NOV4.txt A6 does."""
from __future__ import annotations

import asyncio
import json
import queue
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

AGENT_ID = "agent-coord-1"
TOKEN = "test-token"
ROOM = "room-42"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def build_fake():
    app = FastAPI()
    state = {"ops": [], "beats": 0, "opens": [], "auth_failures": 0}
    outbox: queue.Queue = queue.Queue()

    def authed(req: Request) -> bool:
        ok = req.headers.get("authorization") == f"Bearer {TOKEN}"
        if not ok:
            state["auth_failures"] += 1
        return ok

    @app.get("/agents/{agent_id}/events")
    async def events(agent_id: str, request: Request):
        assert authed(request) and agent_id == AGENT_ID
        state["opens"].append(dict(request.query_params))

        async def gen():
            yield "event: connection_state\ndata: " + json.dumps({
                "connection_id": request.query_params["connection_id"], "agent_id": AGENT_ID,
                "rooms": [ROOM], "cursor": 0, "heartbeat_interval_seconds": 0.2,
            }) + "\n\n"
            seq = 0
            while True:
                try:
                    evt = outbox.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.05)
                    yield ": keepalive\n\n"
                    continue
                seq += 1
                evt["sequence"] = seq
                yield f"id: {seq}\nevent: {evt['type']}\ndata: {json.dumps(evt)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/agents/{agent_id}/connection/beat")
    async def beat(agent_id: str, request: Request):
        assert authed(request)
        state["beats"] += 1
        return {"ok": True, "rooms": [ROOM], "cursor": 0}

    @app.post("/agents/{agent_id}/ops/{name}")
    async def op(agent_id: str, name: str, request: Request):
        assert authed(request)
        assert request.headers.get("x-switch-connection-id")
        state["ops"].append((name, await request.json()))
        return {"result": {"ok": True, "room_id": ROOM}}

    return app, state, outbox


def _wait(pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_adapter_and_connector_over_real_http(client):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Message, Task
    from app.switchbridge import adapter as switch
    from app.switchbridge.connector import on_domain_event

    fake, state, outbox = build_fake()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(fake, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    assert _wait(lambda: server.started)

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    a = switch.SwitchAdapter(f"http://127.0.0.1:{port}", TOKEN, AGENT_ID, ROOM)
    a.on_event = on_domain_event
    asyncio.run_coroutine_threadsafe(a.start(), loop).result(5)
    switch._adapter = a
    try:
        # Stream opened with the protocol's params, room declared on the URL.
        assert _wait(lambda: a.state == "connected")
        params = state["opens"][0]
        assert params["rooms"] == ROOM and params["filter"] == "all" and params["connection_id"]
        assert _wait(lambda: any(n == "connect_to_room" for n, _ in state["ops"]))
        assert _wait(lambda: state["beats"] >= 2), "heartbeat not running"

        with SessionLocal() as db:
            before = db.execute(select(Task.id)).scalars().all()

        # A human addresses the coordinator in the room.
        outbox.put({"type": "message", "room_id": ROOM, "payload": {
            "addressed": True, "sender": "@switch-user-1:local", "sender_name": "lead",
            "body": "@teampilot-coordinator Fix the password reset email bug",
            "message_id": "m1", "thread_id": None,
        }})

        # Coordinator plans and dispatches back THROUGH Switch.
        assert _wait(lambda: any(n == "send_targeted_message" for n, _ in state["ops"])), state["ops"]
        targeted = [args for n, args in state["ops"] if n == "send_targeted_message"]
        assert targeted[0]["target_names"] and targeted[0]["target_names"][0].startswith("teampilot-")
        assert "```json" in targeted[0]["body"] and "TASK_ASSIGNED" in targeted[0]["body"]
        assert any(n == "post_message" for n, _ in state["ops"])  # plan summary

        with SessionLocal() as db:
            new_tasks = db.execute(select(Task).where(Task.id.notin_(before))).scalars().all()
            assert len(new_tasks) >= 3
            assigned = db.execute(select(Message).where(
                Message.message_type == "TASK_ASSIGNED", Message.task_id.in_([t.id for t in new_tasks])
            )).scalars().all()
            assert assigned and all(m.delivered_via == "switch" for m in assigned)
            first_key = new_tasks[0].key
            mirrored = db.execute(select(Message).where(Message.switch_message_id == "m1")).scalars().first()
            assert mirrored is not None and mirrored.sender_type == "human"

        # The assigned agent answers with a card in the room -> state changes.
        agent_name = targeted[0]["target_names"][0]
        outbox.put({"type": "message", "room_id": ROOM, "payload": {
            "addressed": True, "sender_name": agent_name, "message_id": "m2",
            "body": "On it\n```json\n" + json.dumps(
                {"type": "TASK_STARTED", "from": agent_name, "task_id": first_key}) + "\n```",
        }})

        def started():
            with SessionLocal() as db:
                return db.get(Task, new_tasks[0].id).status == "in_progress"
        assert _wait(started)

        # A human command from the room is executed, and answered in the room.
        n_posts = sum(n == "post_message" for n, _ in state["ops"])
        outbox.put({"type": "message", "room_id": ROOM, "payload": {
            "addressed": True, "sender_name": "lead", "message_id": "m3",
            "body": "@teampilot-coordinator status",
        }})
        assert _wait(lambda: sum(n == "post_message" for n, _ in state["ops"]) > n_posts)
        last = [args for n, args in state["ops"] if n == "post_message"][-1]
        assert "done." in last["body"]

        assert state["auth_failures"] == 0
    finally:
        switch._adapter = None
        asyncio.run_coroutine_threadsafe(a.stop(), loop).result(5)
        loop.call_soon_threadsafe(loop.stop)
        server.should_exit = True


def test_reconnects_with_same_connection_id_and_cursor():
    from app.switchbridge import adapter as switch

    app = FastAPI()
    opens: list[dict] = []

    @app.get("/agents/{agent_id}/events")
    async def events(agent_id: str, request: Request):
        opens.append({**request.query_params, "last": request.headers.get("last-event-id")})

        async def gen():
            yield "event: connection_state\ndata: " + json.dumps({"cursor": 7}) + "\n\n"
            if len(opens) == 1:
                yield "id: 8\nevent: message\ndata: " + json.dumps(
                    {"type": "message", "sequence": 8, "payload": {}}) + "\n\n"
                return  # drop the socket
            while True:
                await asyncio.sleep(0.1)
                yield ": keepalive\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/agents/{agent_id}/connection/beat")
    async def beat(agent_id: str):
        return {"ok": True}

    @app.post("/agents/{agent_id}/ops/{name}")
    async def op(agent_id: str, name: str):
        return {"result": {}}

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    assert _wait(lambda: server.started)
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    a = switch.SwitchAdapter(f"http://127.0.0.1:{port}", TOKEN, AGENT_ID, ROOM)
    asyncio.run_coroutine_threadsafe(a.start(), loop).result(5)
    try:
        assert _wait(lambda: len(opens) >= 2, timeout=8), "no reconnect"
        assert opens[0]["connection_id"] == opens[1]["connection_id"]  # protocol: reuse id
        assert opens[1]["last"] == "8"  # resume after the last event seen
        assert _wait(lambda: a.state == "connected")
    finally:
        asyncio.run_coroutine_threadsafe(a.stop(), loop).result(5)
        loop.call_soon_threadsafe(loop.stop)
        server.should_exit = True


def test_deliver_is_local_when_disconnected():
    from app.switchbridge import adapter as switch
    switch._adapter = None
    assert switch.deliver("hello") == "local"
