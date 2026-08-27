"""Test fixtures.

The spatial tests run against a real PostGIS database — the whole point is to
prove the SQL is right, so mocking it would test nothing. They skip cleanly
when no database is reachable, and refuse to run against an unseeded one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402


def _database_ready() -> tuple[bool, str]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT PostGIS_Version()"))
            zones = conn.execute(text("SELECT COUNT(*) FROM zones")).scalar_one()
    except Exception as exc:
        return False, f"database unreachable: {type(exc).__name__}"
    if not zones:
        return False, "database has no zones — run `python scripts/seed.py --reset`"
    return True, ""


DB_READY, DB_SKIP_REASON = _database_ready()

requires_db = pytest.mark.skipif(not DB_READY, reason=DB_SKIP_REASON)


@pytest.fixture()
def db():
    """A rolled-back session: spatial tests may write, but never persist."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
