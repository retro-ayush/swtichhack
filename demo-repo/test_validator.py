"""Run with: python3 -m pytest demo-repo -q
Two tests fail until the bug in validator.py is fixed — that failure is the
demo's starting point, not a mistake."""
from validator import validate_email, validate_login


def test_valid_email():
    assert validate_email("jane@example.com") is True


def test_rejects_malformed():
    assert validate_email("jane@") is False
    assert validate_email("@example.com") is False
    assert validate_email("jane@example") is False


def test_rejects_empty_email():
    assert validate_email("") is False          # fails: falsy fallback bug
    assert validate_email("   ") is False       # fails: discarded strip() bug


def test_login_flow():
    assert validate_login("jane@example.com", "s3cretpass")["ok"] is True
    res = validate_login("", "short")
    assert res["ok"] is False and len(res["errors"]) == 2
