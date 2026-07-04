import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from src.db.base import get_engine, get_session_factory


def test_get_engine_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="DATABASE_URL"):
        get_engine()


def test_get_engine_falls_back_to_database_url_env_var(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://atlas:atlas@localhost:5432/atlas")

    assert isinstance(get_engine(), Engine)


def test_get_session_factory_returns_sessionmaker():
    factory = get_session_factory("postgresql+psycopg://atlas:atlas@localhost:5432/atlas")

    assert isinstance(factory, sessionmaker)
