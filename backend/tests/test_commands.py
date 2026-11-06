"""Human chat commands go through the same guarded engine as the API."""
import json

from app.engine.commands import parse


def test_parse():
    assert parse("approve T-5 looks good") == ("approve", "T-5", "looks good")
    assert parse("  Unblock t-3") == ("unblock", "T-3", "")
    assert parse("status") == ("status", None, "")
    assert parse("approve the plan please") is None  # prose, not a command
    assert parse("Build a login page") is None


def _card(client, pid, sender, **kw):
    body = "```json\n" + json.dumps({"from": sender, **kw}) + "\n```"
    r = client.post(f"/api/projects/{pid}/agent-message", json={"sender_name": sender, "content": body})
    assert r.status_code == 200 and r.json()["card_recognized"], r.text


def _say(client, pid, text):
    r = client.post(f"/api/projects/{pid}/chat", json={"content": text, "sender_name": "lead", "as_request": True})
    assert r.status_code == 200, r.text
    return r.json()


def _last_reply(client, pid):
    msgs = client.get(f"/api/projects/{pid}/messages").json()
    return [m for m in msgs if m["sender_type"] == "coordinator" and m["message_type"] == "CHAT"][-1]["content"]


def test_chat_commands_drive_the_engine(client):
    pid = client.post("/api/projects", json={"name": "cmd-test"}).json()["id"]
    # project needs agents: reuse seeded names by creating them via the seed helper
    from app.db import SessionLocal
    from app.models import Agent
    with SessionLocal() as db:
        for role in ("backend", "frontend", "testing", "reviewer"):
            db.add(Agent(project_id=pid, name=f"cmd-{role}", role=role))
        db.commit()

    tasks = _say(client, pid, "Fix the signup API bug")
    first = tasks[0]["key"]
    tid = tasks[0]["id"]

    # Commands are not turned into new tasks.
    assert _say(client, pid, "status") == []
    assert "done." in _last_reply(client, pid)

    _card(client, pid, "cmd-backend", type="TASK_STARTED", task_id=first)
    _card(client, pid, "cmd-backend", type="BLOCKER", task_id=first, message="no creds")
    assert _say(client, pid, f"unblock {first} creds shared") == []
    assert client.get(f"/api/tasks/{tid}").json()["status"] == "in_progress"

    # Illegal moves are refused with the engine's message, not executed.
    _say(client, pid, f"approve {first}")
    assert "no pending approval" in _last_reply(client, pid)

    _say(client, pid, f"reassign {first} cmd-frontend")
    assert "reassigned to cmd-frontend" in _last_reply(client, pid)

    _say(client, pid, f"cancel {first} duplicate")
    assert client.get(f"/api/tasks/{tid}").json()["status"] == "cancelled"
    _say(client, pid, f"unblock {first}")
    assert "illegal transition" in _last_reply(client, pid)


def test_reject_requires_reason(client):
    pid = client.get("/api/projects").json()[0]["id"]
    _say(client, pid, "reject T-1")
    assert "Give a reason" in _last_reply(client, pid)
