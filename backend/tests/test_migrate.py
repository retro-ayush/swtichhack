"""A database created by the pre-migration build (create_all, no
alembic_version) must be adopted, not crashed on."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

SCRIPT = r"""
import sys
from sqlalchemy import inspect
from app.db import Base, engine
from app import models
Base.metadata.create_all(engine)                      # legacy shape: no alembic_version
assert "alembic_version" not in inspect(engine).get_table_names()
from app.migrate import upgrade_to_head
upgrade_to_head()                                     # must stamp, then upgrade without error
names = set(inspect(engine).get_table_names())
assert "alembic_version" in names and "tasks" in names, names
upgrade_to_head()                                     # idempotent
print("ok")
"""


def test_legacy_database_is_stamped_then_upgraded():
    dbfile = os.path.join(tempfile.mkdtemp(prefix="teampilot-legacy-"), "legacy.db")
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{dbfile}"}
    # Separate interpreter: app.config/app.db bind the URL at import time.
    out = subprocess.run([sys.executable, "-c", SCRIPT], cwd=BACKEND, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().endswith("ok")
