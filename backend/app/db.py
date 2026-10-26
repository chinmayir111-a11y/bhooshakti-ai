"""SQLAlchemy engine / session wiring."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Standalone scripts / background tasks."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Columns added after a database was first seeded. create_all() makes new
# tables but never alters existing ones, so each addition is listed here and
# applied idempotently at API start-up (and by the test fixtures).
SCHEMA_ADDITIONS = [
    "ALTER TABLE citizen_reports ADD COLUMN IF NOT EXISTS signs JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE zones ADD COLUMN IF NOT EXISTS terrain_source VARCHAR(80) NOT NULL DEFAULT 'SIMULATED'",
]


def ensure_schema_additions() -> None:
    from sqlalchemy import text

    from . import models  # noqa: F401  (registers every table on Base)
    Base.metadata.create_all(bind=engine)          # new tables only; never alters
    with engine.begin() as conn:
        for stmt in SCHEMA_ADDITIONS:
            conn.execute(text(stmt))
