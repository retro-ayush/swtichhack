import os
import tempfile

# Must be set before any app import: config reads env at import time.
_dbfile = os.path.join(tempfile.mkdtemp(prefix="teampilot-test-"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_dbfile}"
os.environ["ANTHROPIC_API_KEY"] = ""  # force rule-based decomposition
os.environ["TEAMPILOT_API_TOKEN"] = ""  # no auth in tests
os.environ.pop("SWITCH_API_ENDPOINT", None)
os.environ.pop("SWITCH_API_TOKEN", None)
os.environ.pop("SWITCH_AGENT_ID", None)

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as c:  # runs lifespan: create_all + seed
        yield c


@pytest.fixture()
def db(client):
    from app.db import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
