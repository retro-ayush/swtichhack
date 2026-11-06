import os
import tempfile

# Must be set before any app import: config reads env at import time.
_dbfile = os.path.join(tempfile.mkdtemp(prefix="teampilot-test-"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_dbfile}"
os.environ["ANTHROPIC_API_KEY"] = ""  # force rule-based decomposition
os.environ["TEAMPILOT_API_TOKEN"] = ""  # no auth in tests
# Set to empty, not popped: app.config calls load_dotenv(), which fills any
# *missing* variable from backend/.env. Real Switch credentials in .env must
# never reach a test run (it would join the real room as the coordinator).
for _var in ("SWITCH_API_ENDPOINT", "SWITCH_API_TOKEN", "SWITCH_AGENT_ID", "SWITCH_ROOM_ID",
             "SWITCH_PROJECT_ID", "ANTHROPIC_API_KEY", "TEAMPILOT_API_TOKEN"):
    os.environ[_var] = ""

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
