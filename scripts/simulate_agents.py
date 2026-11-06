#!/usr/bin/env python3
"""Play the four specialist agents locally, so the full workflow can be seen
without Switch. Every message it sends is recorded as delivered_via=local.

    python3 scripts/simulate_agents.py            # step by step (press Enter)
    python3 scripts/simulate_agents.py --auto     # run straight through

It stops at the human-approval gate: approve the last task yourself in the
dashboard (Approvals) or by typing  approve T-n looks good  in Team Chat.
Env: TEAMPILOT_URL (default http://localhost:8000), TEAMPILOT_API_TOKEN."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("TEAMPILOT_URL", "http://localhost:8000").rstrip("/") + "/api"
TOKEN = os.environ.get("TEAMPILOT_API_TOKEN", "")
AUTO = "--auto" in sys.argv


def call(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> {e.code}: {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        sys.exit(f"Backend not reachable at {BASE} ({e.reason}). Start it first (see README).")


def step(title: str):
    print(f"\n▶ {title}")
    if AUTO:
        time.sleep(1.2)
    else:
        input("  (Enter to run, then watch the dashboard) ")


def card(pid: int, agent: str, line: str, **fields):
    body = f"{line}\n```json\n" + json.dumps({"from": agent, **fields}) + "\n```"
    r = call("POST", f"/projects/{pid}/agent-message", {"sender_name": agent, "content": body})
    print(f"  {agent}: {fields['type']} {fields.get('task_id', '')}  {'' if r['card_recognized'] else '(rejected: ' + str(r.get('card_error')) + ')'}")


def main():
    pid = call("GET", "/projects")[0]["id"]
    step("You post a request in Team Chat")
    tasks = call("POST", f"/projects/{pid}/chat", {
        "content": "Investigate the login validation bug, fix it, and verify the solution.",
        "sender_name": "you", "as_request": True})
    k = {t["kind"] if t["kind"] != "feature" else f"feature{i}": t["key"] for i, t in enumerate(tasks)}
    feats = [t["key"] for t in tasks if t["kind"] == "feature"]
    inv, test, review = k["investigation"], k["test"], k["review"]
    for t in tasks:
        print(f"  {t['key']} {t['status']:8} {t['title']}")

    step(f"Backend agent investigates {inv}, hits a blocker")
    card(pid, "teampilot-backend", "On it, reproducing.", type="TASK_STARTED", task_id=inv)
    card(pid, "teampilot-backend", "Blocked.", type="BLOCKER", task_id=inv,
         message="Need read access to the demo repo")
    print("  -> Overview shows 'Attention needed'; the task is Blocked")

    step(f"You unblock {inv} from chat")
    call("POST", f"/projects/{pid}/chat", {"content": f"unblock {inv} access granted", "sender_name": "you"})
    card(pid, "teampilot-backend", "Root cause found.", type="TASK_COMPLETED", task_id=inv,
         summary="validate_email discards strip() and falls back to a dummy for empty input",
         evidence="pytest demo-repo: 2 failed, 2 passed")
    card(pid, "teampilot-reviewer", "Confirmed.", type="REVIEW_FEEDBACK", task_id=inv, approved=True,
         message="root cause verified")

    step(f"Backend fix {feats[0]}: reviewer rejects once, then approves")
    card(pid, "teampilot-backend", "Fixing.", type="TASK_STARTED", task_id=feats[0])
    card(pid, "teampilot-backend", "Fix pushed.", type="REVIEW_REQUEST", task_id=feats[0],
         message="use stripped value; remove dummy fallback", diff_ref="teampilot/backend/fix @ 3f2a91c")
    card(pid, "teampilot-reviewer", "Changes requested.", type="REVIEW_FEEDBACK", task_id=feats[0],
         approved=False, findings=["None email still raises AttributeError"], message="guard None")
    card(pid, "teampilot-backend", "None handled.", type="REVIEW_REQUEST", task_id=feats[0],
         message="None guarded", diff_ref="teampilot/backend/fix @ 9b04c1d")
    card(pid, "teampilot-reviewer", "LGTM.", type="REVIEW_FEEDBACK", task_id=feats[0], approved=True)

    for f in feats[1:]:
        step(f"Frontend {f}: wired and approved")
        card(pid, "teampilot-frontend", "Wiring the form.", type="TASK_STARTED", task_id=f)
        card(pid, "teampilot-frontend", "UI done.", type="REVIEW_REQUEST", task_id=f, message="error text shown")
        card(pid, "teampilot-reviewer", "LGTM.", type="REVIEW_FEEDBACK", task_id=f, approved=True)

    step(f"Testing {test}: first run FAILS, second run passes")
    card(pid, "teampilot-testing", "Running tests.", type="TASK_STARTED", task_id=test)
    card(pid, "teampilot-testing", "1 failure.", type="TEST_RESULT", task_id=test, passed=False,
         commands=["python3 -m pytest -q"], log_excerpt="FAILED test_validator.py::test_rejects_empty_email",
         message="whitespace email still accepted")
    card(pid, "teampilot-testing", "All green.", type="TEST_RESULT", task_id=test, passed=True,
         commands=["python3 -m pytest -q"], log_excerpt="4 passed in 0.02s")
    card(pid, "teampilot-testing", "Done.", type="TASK_COMPLETED", task_id=test,
         summary="all tests pass", evidence="4 passed in 0.02s")
    card(pid, "teampilot-reviewer", "Evidence checks out.", type="REVIEW_FEEDBACK", task_id=test, approved=True)

    step(f"Final review {review}: reviewer approves, then it waits for YOU")
    card(pid, "teampilot-reviewer", "Final check.", type="TASK_STARTED", task_id=review)
    card(pid, "teampilot-reviewer", "Reviewing combined change.", type="REVIEW_REQUEST", task_id=review,
         message="combined branch")
    card(pid, "teampilot-reviewer", "Ready for merge.", type="REVIEW_FEEDBACK", task_id=review, approved=True)

    status = {t["key"]: t["status"] for t in call("GET", f"/projects/{pid}/tasks")}
    print(f"\n✅ {review} is '{status[review]}'. Your turn:")
    print(f"   Approvals page -> Approve, or type in Team Chat:  approve {review} looks good")


if __name__ == "__main__":
    main()
