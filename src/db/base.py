"""SQLAlchemy engine/session setup — reads DATABASE_URL from environment.

See docs/features/F003-db-schema-decision-order-record.md.
"""

from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def get_engine(database_url: str | None = None) -> Engine:
    return create_engine(database_url or _require_database_url())


def get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url))


def _require_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("Environment variable 'DATABASE_URL' is not set")
    return url
