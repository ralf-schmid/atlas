"""Shared Postgres fixtures for tests/db, tests/api (any suite needing a real DB).

Session-scoped: the real Alembic migration is applied once per pytest session
and downgraded once at the very end — see F003 §3 test 1. Per-test isolation
is a connection + transaction that gets rolled back after each test.
"""

import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from alembic import command
from src.db.base import get_engine

_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — this suite needs a real Postgres, see F003 §3")
    return url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Engine:
    return get_engine(database_url)


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema(database_url: str):
    """Applies the real Alembic migration once per test session, downgrades after.

    Exercises the same upgrade()/downgrade() this feature ships — see F003 §3 test 1.
    The full upgrade -> downgrade -> upgrade idempotency cycle was additionally
    verified manually via the Alembic CLI (see F003 §5).
    """
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")
    yield
    command.downgrade(cfg, "base")


@pytest.fixture
def session(engine: Engine):
    connection = engine.connect()
    transaction = connection.begin()
    db_session = Session(bind=connection)
    try:
        yield db_session
    finally:
        db_session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()
