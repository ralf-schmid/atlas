import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.app import app
from src.api.routes import get_session


@pytest.fixture(autouse=True)
def _apply_migration(_migrated_schema: None) -> None:
    """Opts this suite into the real-Postgres schema — see tests/conftest.py."""


@pytest.fixture
def client(session: Session) -> TestClient:
    app.dependency_overrides[get_session] = lambda: session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
