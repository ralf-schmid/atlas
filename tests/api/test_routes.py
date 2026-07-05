from fastapi.testclient import TestClient

from tests.db.factories import (
    make_persona,
    make_portfolio,
    make_portfolio_snapshot,
    make_position_snapshot,
)


def test_get_persona_snapshot_returns_totals_and_positions(client: TestClient, session):
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    snapshot = make_portfolio_snapshot(session, portfolio)
    make_position_snapshot(session, portfolio)
    session.flush()

    response = client.get("/api/personas/VULTURE/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["persona"] == "VULTURE"
    assert body["total_value"] == float(snapshot.total_value)
    assert body["cash"] == float(snapshot.cash)
    assert len(body["positions"]) == 1
    assert body["positions"][0]["instrument"] == "AAPL"


def test_get_persona_snapshot_is_case_insensitive(client: TestClient, session):
    persona = make_persona(session, name="GUARDIAN")
    portfolio = make_portfolio(session, persona)
    make_portfolio_snapshot(session, portfolio)
    session.flush()

    response = client.get("/api/personas/guardian/snapshot")

    assert response.status_code == 200
    assert response.json()["persona"] == "GUARDIAN"


def test_get_persona_snapshot_unknown_persona_returns_404(client: TestClient):
    response = client.get("/api/personas/NONEXISTENT/snapshot")

    assert response.status_code == 404


def test_get_persona_snapshot_without_portfolio_returns_404(client: TestClient, session):
    make_persona(session, name="CHARTIST")
    session.flush()

    response = client.get("/api/personas/CHARTIST/snapshot")

    assert response.status_code == 404


def test_get_persona_snapshot_without_snapshot_returns_404(client: TestClient, session):
    persona = make_persona(session, name="CONTRA")
    make_portfolio(session, persona)
    session.flush()

    response = client.get("/api/personas/CONTRA/snapshot")

    assert response.status_code == 404


def test_health_endpoint(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
