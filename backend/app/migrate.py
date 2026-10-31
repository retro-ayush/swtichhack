"""Run Alembic migrations to head programmatically (called on startup).

A database created by an earlier build (create_all, no alembic_version
table) is stamped at the baseline revision first, so upgrading never trips
over tables that already exist."""
from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from .db import engine

log = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[1]
BASELINE_REVISION = "bb2438221581"  # the initial-schema migration


def _config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def upgrade_to_head() -> None:
    cfg = _config()
    tables = set(inspect(engine).get_table_names())
    if "tasks" in tables and "alembic_version" not in tables:
        log.warning("legacy database without alembic_version found; stamping baseline %s", BASELINE_REVISION)
        command.stamp(cfg, BASELINE_REVISION)
    command.upgrade(cfg, "head")
