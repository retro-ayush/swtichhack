from app.engine.coordinator import card_error, extract_card


def test_card_error_explains_rejection():
    assert card_error("no card here") is None
    ok = '```json\n{"type": "TASK_STARTED", "from": "a", "task_id": "T-1"}\n```'
    assert card_error(ok) is None
    bad_json = '```json\n{"type": "TASK_STARTED", "from": "a",}\n```'
    assert "not valid JSON" in card_error(bad_json)
    extra = '```json\n{"type": "TASK_STARTED", "from": "a", "eta": "5m"}\n```'
    err = card_error(extra)
    assert "eta" in err and "card rejected" in err
    missing = '```json\n{"type": "TEST_RESULT", "from": "a", "task_id": "T-1"}\n```'
    assert "passed" in card_error(missing)


def test_invalid_card_gets_a_reply(client):
    pid = client.get("/api/projects").json()[0]["id"]
    r = client.post(f"/api/projects/{pid}/agent-message", json={
        "sender_name": "teampilot-testing",
        "content": '```json\n{"type": "TEST_RESULT", "from": "teampilot-testing", "task_id": "T-1"}\n```'})
    assert r.status_code == 200
    assert r.json()["card_recognized"] is False and "passed" in r.json()["card_error"]
    msgs = client.get(f"/api/projects/{pid}/messages").json()
    assert msgs[-1]["message_type"] == "CARD_REJECTED"


def test_fenced_card_parsed():
    body = 'Working on it.\n```json\n{"type": "BLOCKER", "from": "teampilot-frontend", "task_id": "T-3", "message": "waiting on API contract"}\n```'
    card = extract_card(body)
    assert card is not None and card.type == "BLOCKER"
    assert card.from_agent == "teampilot-frontend"
    assert card.task_key == "T-3"


def test_bare_json_card_parsed():
    card = extract_card('{"type": "TEST_RESULT", "from": "teampilot-testing", "task_id": "T-9", "passed": false, "message": "2 failures"}')
    assert card is not None and card.type == "TEST_RESULT" and card.passed is False


def test_invalid_cards_ignored():
    assert extract_card("just chatting about the task") is None
    assert extract_card('{"type": "NOT_A_TYPE", "from": "x"}') is None
    assert extract_card('```json\n{"type": "BLOCKER"}\n```') is None  # missing required "from"
    # unknown extra fields are rejected, not silently accepted
    assert extract_card('{"type": "BLOCKER", "from": "a", "rm": "-rf"}') is None
