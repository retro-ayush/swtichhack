"""Login validation for the demo app.

Contains ONE deliberately introduced, safe-to-test bug for the TeamPilot
demo scenario (docs/ARCHITECTURE.md §13): empty/whitespace emails pass
validation because the emptiness check runs after .strip() is discarded.
The testing agent should surface it; the backend agent should fix it.
"""
from __future__ import annotations

import re

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email(email: str) -> bool:
    if email is None:
        return False
    email.strip()  # BUG: result discarded, so "   " is validated below as-is
    if not _EMAIL.match(email or "x@x.x"):  # BUG: falsy email falls back to a valid dummy
        return False
    return True


def validate_login(email: str, password: str) -> dict:
    errors = []
    if not validate_email(email):
        errors.append("invalid email")
    if not password or len(password) < 8:
        errors.append("password must be at least 8 characters")
    return {"ok": not errors, "errors": errors}
