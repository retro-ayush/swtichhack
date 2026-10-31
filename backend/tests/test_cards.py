from app.engine.coordinator import extract_card


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
