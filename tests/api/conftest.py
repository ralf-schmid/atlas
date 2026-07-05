import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.app import app
from src.api.routes import get_session


@pytest.fixture
def client(session: Session) -> TestClient:
    app.dependency_overrides[get_session] = lambda: session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
