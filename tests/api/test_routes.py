from decimal import Decimal

from fastapi.testclient import TestClient

from src.db.models import PortfolioMode
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


def test_get_persona_snapshot_defaults_to_paper_mode(client: TestClient, session):
    persona = make_persona(session, name="HYPE")
    paper = make_portfolio(session, persona, mode=PortfolioMode.PAPER)
    live = make_portfolio(session, persona, mode=PortfolioMode.LIVE)
    make_portfolio_snapshot(session, paper)
    live_snapshot = make_portfolio_snapshot(session, live)
    live_snapshot.total_value = Decimal("2000.00")
    session.flush()

    response = client.get("/api/personas/HYPE/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "paper"
    assert body["total_value"] == 5050.0


def test_get_persona_snapshot_mode_live_selects_live_portfolio(client: TestClient, session):
    persona = make_persona(session, name="HYPE")
    make_portfolio(session, persona, mode=PortfolioMode.PAPER)
    live = make_portfolio(session, persona, mode=PortfolioMode.LIVE)
    make_portfolio_snapshot(session, live)
    session.flush()

    response = client.get("/api/personas/HYPE/snapshot?mode=live")

    assert response.status_code == 200
    assert response.json()["mode"] == "live"


def test_get_persona_snapshot_missing_mode_portfolio_returns_404(client: TestClient, session):
    persona = make_persona(session, name="HYPE")
    make_portfolio(session, persona, mode=PortfolioMode.PAPER)
    session.flush()

    response = client.get("/api/personas/HYPE/snapshot?mode=live")

    assert response.status_code == 404
    assert "live" in response.json()["detail"]


def test_get_persona_snapshot_invalid_mode_returns_422(client: TestClient, session):
    make_persona(session, name="HYPE")
    session.flush()

    response = client.get("/api/personas/HYPE/snapshot?mode=demo")

    assert response.status_code == 422


def test_health_endpoint(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
