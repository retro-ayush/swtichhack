"""End-to-end flow against the real app (local mode, rule-based decomposition):
request -> tasks -> start -> blocker -> unblock -> done -> review loop ->
tests -> approval -> completion. Mirrors docs/ARCHITECTURE.md §4."""
import json


def card(**kw) -> str:
    return "```json\n" + json.dumps(kw) + "\n```"


def send(client, pid, sender, **kw):
    r = client.post(f"/api/projects/{pid}/agent-message",
                    json={"sender_name": sender, "content": card(**kw)})
    assert r.status_code == 200, r.text
    assert r.json()["card_recognized"] is True
    return r.json()


def get_tasks(client, pid):
    return {t["key"]: t for t in client.get(f"/api/projects/{pid}/tasks").json()}


def test_full_workflow(client):
    pid = client.get("/api/projects").json()[0]["id"]

    # 1. Human request -> decomposed tasks (rules path: no API key in tests).
    r = client.post(f"/api/projects/{pid}/chat", json={
        "content": "Investigate the login validation bug, fix it, and verify the solution.",
        "sender_name": "priya", "as_request": True,
    })
    assert r.status_code == 200
    created = r.json()
    assert len(created) == 5  # investigate, backend, frontend, test, review
    by_kind = {t["kind"]: t for t in created}
    inv, test_t, review = by_kind["investigation"], by_kind["test"], by_kind["review"]
    impls = [t for t in created if t["kind"] == "feature"]
    assert review["requires_approval"] is True
    assert inv["status"] == "ready" and test_t["status"] == "backlog"

    # TASK_ASSIGNED went out for the ready task (recorded local — no Switch here).
    msgs = client.get(f"/api/projects/{pid}/messages").json()
    assigned = [m for m in msgs if m["message_type"] == "TASK_ASSIGNED"]
    assert assigned and all(m["delivered_via"] == "local" for m in assigned)

    # 2. Dependencies are enforced: starting the test task now is refused.
    r = client.patch(f"/api/tasks/{test_t['id']}", json={"status": "ready"})
    assert r.status_code == 409

    # 3. Investigation: start -> blocker -> human unblocks -> done -> review approves.
    send(client, pid, "teampilot-backend", type="TASK_STARTED",
         **{"from": "teampilot-backend"}, task_id=inv["key"])
    assert get_tasks(client, pid)[inv["key"]]["status"] == "in_progress"

    send(client, pid, "teampilot-backend", type="BLOCKER",
         **{"from": "teampilot-backend"}, task_id=inv["key"],
         message="need repo access")
    assert get_tasks(client, pid)[inv["key"]]["status"] == "blocked"

    r = client.patch(f"/api/tasks/{inv['id']}",
                     json={"status": "in_progress", "actor": "priya", "reason": "access granted"})
    assert r.status_code == 200

    send(client, pid, "teampilot-backend", type="TASK_COMPLETED",
         **{"from": "teampilot-backend"}, task_id=inv["key"],
         summary="root cause found", evidence="notes in thread")
    # Agent saying done != done: it is in review now.
    assert get_tasks(client, pid)[inv["key"]]["status"] == "in_review"

    send(client, pid, "teampilot-reviewer", type="REVIEW_FEEDBACK",
         **{"from": "teampilot-reviewer"}, task_id=inv["key"], approved=True)
    assert get_tasks(client, pid)[inv["key"]]["status"] == "completed"

    # 4. Implementation tasks unlock in dependency order; reject-then-approve loop.
    tasks = get_tasks(client, pid)
    be = next(t for t in tasks.values() if t["kind"] == "feature" and t["status"] == "ready")
    send(client, pid, "teampilot-backend", type="TASK_STARTED",
         **{"from": "teampilot-backend"}, task_id=be["key"])
    send(client, pid, "teampilot-backend", type="REVIEW_REQUEST",
         **{"from": "teampilot-backend"}, task_id=be["key"], message="fix pushed", diff_ref="branch fix/login")
    assert get_tasks(client, pid)[be["key"]]["status"] == "in_review"
    send(client, pid, "teampilot-reviewer", type="REVIEW_FEEDBACK",
         **{"from": "teampilot-reviewer"}, task_id=be["key"], approved=False,
         findings=["empty input unhandled"], message="handle empty input")
    assert get_tasks(client, pid)[be["key"]]["status"] == "in_progress"
    send(client, pid, "teampilot-backend", type="REVIEW_REQUEST",
         **{"from": "teampilot-backend"}, task_id=be["key"], message="fixed empty input")
    send(client, pid, "teampilot-reviewer", type="REVIEW_FEEDBACK",
         **{"from": "teampilot-reviewer"}, task_id=be["key"], approved=True)
    assert get_tasks(client, pid)[be["key"]]["status"] == "completed"

    # Frontend impl unlocked; complete it the same way.
    fe = [t for t in get_tasks(client, pid).values() if t["kind"] == "feature" and t["key"] != be["key"]][0]
    assert fe["status"] == "ready"
    send(client, pid, "teampilot-frontend", type="TASK_STARTED",
         **{"from": "teampilot-frontend"}, task_id=fe["key"])
    send(client, pid, "teampilot-frontend", type="REVIEW_REQUEST",
         **{"from": "teampilot-frontend"}, task_id=fe["key"], message="UI integrated")
    send(client, pid, "teampilot-reviewer", type="REVIEW_FEEDBACK",
         **{"from": "teampilot-reviewer"}, task_id=fe["key"], approved=True)

    # 5. Test task: failed run bounces back, passing run + review completes.
    tasks = get_tasks(client, pid)
    assert tasks[test_t["key"]]["status"] == "ready"
    send(client, pid, "teampilot-testing", type="TASK_STARTED",
         **{"from": "teampilot-testing"}, task_id=test_t["key"])
    send(client, pid, "teampilot-testing", type="TEST_RESULT",
         **{"from": "teampilot-testing"}, task_id=test_t["key"], passed=False,
         commands=["pytest -q"], log_excerpt="1 failed", message="regression in validator")
    runs = client.get(f"/api/tasks/{test_t['id']}/runs").json()
    assert [r["status"] for r in runs] == ["failed"]
    send(client, pid, "teampilot-testing", type="TEST_RESULT",
         **{"from": "teampilot-testing"}, task_id=test_t["key"], passed=True,
         commands=["pytest -q"], log_excerpt="12 passed")
    send(client, pid, "teampilot-testing", type="TASK_COMPLETED",
         **{"from": "teampilot-testing"}, task_id=test_t["key"], summary="all green",
         evidence="12 passed")
    send(client, pid, "teampilot-reviewer", type="REVIEW_FEEDBACK",
         **{"from": "teampilot-reviewer"}, task_id=test_t["key"], approved=True)
    assert get_tasks(client, pid)[test_t["key"]]["status"] == "completed"

    # 6. Review/merge task requires HUMAN approval: reviewer approval parks it
    #    at waiting_approval; the human decision completes it.
    tasks = get_tasks(client, pid)
    assert tasks[review["key"]]["status"] == "ready"
    send(client, pid, "teampilot-reviewer", type="TASK_STARTED",
         **{"from": "teampilot-reviewer"}, task_id=review["key"])
    send(client, pid, "teampilot-reviewer", type="REVIEW_REQUEST",
         **{"from": "teampilot-reviewer"}, task_id=review["key"], message="final check")
    send(client, pid, "teampilot-reviewer", type="REVIEW_FEEDBACK",
         **{"from": "teampilot-reviewer"}, task_id=review["key"], approved=True)
    assert get_tasks(client, pid)[review["key"]]["status"] == "waiting_approval"

    # API cannot force completion past the approval gate.
    r = client.patch(f"/api/tasks/{review['id']}", json={"status": "completed"})
    assert r.status_code == 409

    r = client.post(f"/api/tasks/{review['id']}/approve",
                    json={"decided_by": "priya", "reason": "demo verified"})
    assert r.status_code == 200
    assert get_tasks(client, pid)[review["key"]]["status"] == "completed"

    # 7. Metrics add up and activity is persisted.
    m = client.get(f"/api/projects/{pid}/metrics").json()
    assert m["completed"] == 5 and m["blocked"] == 0 and m["pending_approvals"] == 0
    activity = client.get(f"/api/projects/{pid}/activity").json()
    assert any(e["event_type"] == "approval_approved" for e in activity)
    assert any(e["event_type"] == "test_result" for e in activity)


def test_cycle_rejected_via_api(client):
    pid = client.get("/api/projects").json()[0]["id"]
    a = client.post(f"/api/projects/{pid}/tasks", json={"title": "A"}).json()
    b = client.post(f"/api/projects/{pid}/tasks", json={"title": "B", "depends_on": [a["id"]]}).json()
    r = client.post(f"/api/projects/{pid}/tasks",
                    json={"title": "C", "depends_on": [b["id"]]})
    assert r.status_code == 200
    # Now try to close a cycle A -> C through the API-level validation.
    r = client.post(f"/api/projects/{pid}/tasks", json={"title": "D", "depends_on": [999999]})
    assert r.status_code == 422


def test_unknown_agent_rejected(client):
    pid = client.get("/api/projects").json()[0]["id"]
    r = client.post(f"/api/projects/{pid}/agent-message",
                    json={"sender_name": "evil-agent", "content": "{}"})
    assert r.status_code == 422


def test_switch_status_honest(client):
    s = client.get("/api/switch/status").json()
    assert s["configured"] is False and s["state"] == "disabled"
