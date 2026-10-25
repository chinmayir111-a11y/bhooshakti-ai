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
from app.config import settings as _settings  # noqa: E402

# No background weather pulls or rescoring while tests run.
_settings.weather_refresh_minutes = 0
_settings.quake_feed_enabled = False

try:                                    # columns added since the database was seeded
    from app.db import ensure_schema_additions  # noqa: E402
    ensure_schema_additions()
except Exception:                       # no database: the DB tests skip anyway
    pass


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


@pytest.fixture()
def tx_db():
    """A session whose commits are only savepoints inside one outer
    transaction that is always rolled back. The escalation and alerting code
    commits as it goes — exactly what it does in production — and the test
    still leaves the database as it found it."""
    from sqlalchemy.orm import Session

    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


@pytest.fixture()
def client(tx_db):
    """FastAPI TestClient bound to the rolled-back session. The app lifespan
    (MQTT, schedulers) is deliberately not started."""
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    def _override():
        yield tx_db

    app.dependency_overrides[get_db] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def no_siren(monkeypatch):
    """Record siren publishes instead of sending them to a real broker."""
    sent: list[tuple[str, dict]] = []
    from app.mqtt_client import ingest
    monkeypatch.setattr(ingest, "publish", lambda topic, payload, retain=False: sent.append((topic, payload)) or True)
    return sent


@pytest.fixture(autouse=True, scope="session")
def trained_model():
    """Load the trained model once, as the API does at startup. Without this
    every risk computed in a test comes from the heuristic fallback and
    silently disagrees with the running system."""
    from app.services import risk_service
    risk_service.registry.load()
    yield


@pytest.fixture(autouse=True)
def _no_real_email(monkeypatch):
    """Tests never send real email, even when .env has SMTP set up."""
    from app.config import settings
    monkeypatch.setattr(settings, "smtp_host", "")
