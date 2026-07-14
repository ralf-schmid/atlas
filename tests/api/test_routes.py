import datetime
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.db.models import DecisionAction, PortfolioMode
from tests.db.factories import (
    make_cycle,
    make_decision,
    make_market_bar,
    make_order_record,
    make_persona,
    make_portfolio,
    make_portfolio_snapshot,
    make_position_snapshot,
    make_research_item,
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


def test_get_persona_profile_returns_static_content(client: TestClient, session):
    make_persona(session, name="VULTURE")
    session.flush()

    response = client.get("/api/personas/VULTURE/profile")

    assert response.status_code == 200
    body = response.json()
    assert body["display_name"].startswith("VULTURE")
    assert "Lottery-Ticket" in body["philosophy"]


def test_get_persona_profile_unknown_persona_returns_404(client: TestClient):
    response = client.get("/api/personas/NONEXISTENT/profile")

    assert response.status_code == 404


def test_get_persona_holdings_computes_current_price_and_pct_from_snapshot(
    client: TestClient, session
):
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    make_portfolio_snapshot(session, portfolio)
    make_position_snapshot(session, portfolio)  # AAPL: qty 10, avg 150, mv 1550, pnl 50
    session.flush()

    response = client.get("/api/personas/VULTURE/holdings")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    holding = body[0]
    assert holding["instrument"] == "AAPL"
    assert holding["current_price"] == 155.0
    assert round(holding["pnl_unrealized_pct"], 2) == 3.33
    assert holding["last_buy_at"] is None


def test_get_persona_holdings_includes_last_buy_at_from_filled_buy_order(
    client: TestClient, session
):
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    make_portfolio_snapshot(session, portfolio)
    make_position_snapshot(session, portfolio)
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)
    decision = make_decision(
        session, cycle, portfolio, research_item, instrument="AAPL", action=DecisionAction.BUY
    )
    filled_at = datetime.datetime(2026, 7, 3, 10, 0)
    make_order_record(session, decision, filled_at=filled_at, fill_price=Decimal("149.50"))
    session.flush()

    response = client.get("/api/personas/VULTURE/holdings")

    assert response.status_code == 200
    assert response.json()[0]["last_buy_at"] == filled_at.isoformat()


def test_get_persona_holdings_without_snapshot_returns_empty_list(client: TestClient, session):
    persona = make_persona(session, name="GUARDIAN")
    make_portfolio(session, persona)
    session.flush()

    response = client.get("/api/personas/GUARDIAN/holdings")

    assert response.status_code == 200
    assert response.json() == []


def test_get_persona_holding_chart_returns_bars_and_fill_markers(client: TestClient, session):
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    make_portfolio_snapshot(session, portfolio)
    make_position_snapshot(session, portfolio)  # AAPL
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)
    buy = make_decision(
        session, cycle, portfolio, research_item, instrument="AAPL", action=DecisionAction.BUY
    )
    make_order_record(
        session,
        buy,
        filled_at=datetime.datetime(2026, 7, 4, 10, 0),
        fill_price=Decimal("149.50"),
    )
    sell = make_decision(
        session,
        cycle,
        portfolio,
        research_item,
        instrument="AAPL",
        action=DecisionAction.SELL,
        quantity=Decimal("4"),
    )
    make_order_record(
        session,
        sell,
        filled_at=datetime.datetime(2026, 7, 5, 10, 0),
        fill_price=Decimal("152.00"),
    )
    # Bars already cover [chart_start, today] — the fast DB-only path applies.
    make_market_bar(session, symbol="AAPL", ts=datetime.datetime(2026, 7, 2, 0, 0))
    make_market_bar(session, symbol="AAPL", ts=datetime.datetime(2026, 7, 4, 0, 0))
    session.flush()

    with (
        patch("src.api.routes.build_default_provider") as mock_backfill_provider,
        patch("src.api.routes.build_market_data_provider") as mock_live_provider,
    ):
        mock_live_provider.return_value.get_last_price.return_value = 153.25
        response = client.get("/api/personas/VULTURE/chart?instrument=AAPL")

    assert response.status_code == 200
    mock_backfill_provider.assert_not_called()  # bars already covered the range
    body = response.json()
    assert body["instrument"] == "AAPL"
    assert body["start"] == "2026-07-02"  # first fill (07-04) minus 2 days
    assert [bar["ts"] for bar in body["bars"]] == ["2026-07-02", "2026-07-04"]
    assert len(body["fills"]) == 2
    assert body["fills"][0]["action"] == "buy"
    assert body["fills"][0]["price"] == 149.50
    assert body["fills"][1]["action"] == "sell"
    assert body["fills"][1]["price"] == 152.00
    assert body["live_price"] == {"ts": body["live_price"]["ts"], "price": 153.25}


def test_get_persona_holding_chart_without_fills_falls_back_to_30_day_window(
    client: TestClient, session
):
    persona = make_persona(session, name="GUARDIAN")
    portfolio = make_portfolio(session, persona)
    make_portfolio_snapshot(session, portfolio)
    make_position_snapshot(session, portfolio)  # demo-style position, no OrderRecord
    session.flush()

    with (
        patch("src.api.routes.build_default_provider", side_effect=RuntimeError("no bars")),
        patch("src.api.routes.build_market_data_provider") as mock_live_provider,
    ):
        mock_live_provider.return_value.get_last_price.side_effect = RuntimeError("no quote")
        response = client.get("/api/personas/GUARDIAN/chart?instrument=AAPL")

    assert response.status_code == 200
    body = response.json()
    assert body["start"] == str(datetime.date.today() - datetime.timedelta(days=30))
    assert body["bars"] == []
    assert body["fills"] == []
    assert body["live_price"] is None  # live fetch failure degrades gracefully


def test_get_persona_holding_chart_triggers_backfill_when_bars_incomplete(
    client: TestClient, session
):
    from src.ingestion.market_data_sync import Bar

    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    make_portfolio_snapshot(session, portfolio)
    make_position_snapshot(session, portfolio)  # AAPL
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)
    buy = make_decision(
        session, cycle, portfolio, research_item, instrument="AAPL", action=DecisionAction.BUY
    )
    make_order_record(
        session,
        buy,
        filled_at=datetime.datetime(2026, 7, 4, 10, 0),
        fill_price=Decimal("149.50"),
    )
    # No pre-existing market_bar rows at all — forces the backfill path.
    session.flush()

    fake_bar = Bar(
        symbol="AAPL",
        ts=datetime.datetime(2026, 7, 2, 0, 0),
        open=Decimal("148"),
        high=Decimal("150"),
        low=Decimal("147"),
        close=Decimal("149"),
        volume=Decimal("1000"),
    )
    with (
        patch("src.api.routes.build_default_provider") as mock_backfill_provider,
        patch("src.api.routes.build_market_data_provider") as mock_live_provider,
    ):
        mock_backfill_provider.return_value.get_daily_bars.return_value = [fake_bar]
        mock_live_provider.return_value.get_last_price.return_value = 150.0
        response = client.get("/api/personas/VULTURE/chart?instrument=AAPL")

    assert response.status_code == 200
    mock_backfill_provider.return_value.get_daily_bars.assert_called_once()
    body = response.json()
    assert [bar["ts"] for bar in body["bars"]] == ["2026-07-02"]


def test_get_persona_holding_chart_backfill_failure_degrades_gracefully(
    client: TestClient, session
):
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    make_portfolio_snapshot(session, portfolio)
    make_position_snapshot(session, portfolio)  # AAPL
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)
    buy = make_decision(
        session, cycle, portfolio, research_item, instrument="AAPL", action=DecisionAction.BUY
    )
    make_order_record(
        session,
        buy,
        filled_at=datetime.datetime(2026, 7, 4, 10, 0),
        fill_price=Decimal("149.50"),
    )
    session.flush()

    with (
        patch("src.api.routes.build_default_provider", side_effect=RuntimeError("Alpaca down")),
        patch("src.api.routes.build_market_data_provider", side_effect=RuntimeError("down")),
    ):
        response = client.get("/api/personas/VULTURE/chart?instrument=AAPL")

    assert response.status_code == 200  # no 500 despite both external calls failing
    body = response.json()
    assert body["bars"] == []
    assert body["live_price"] is None


def test_get_persona_holding_chart_unknown_instrument_returns_404(client: TestClient, session):
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    make_portfolio_snapshot(session, portfolio)
    make_position_snapshot(session, portfolio)  # AAPL only
    session.flush()

    response = client.get("/api/personas/VULTURE/chart?instrument=MSFT")

    assert response.status_code == 404


def test_get_persona_holding_chart_crypto_symbol_query_param_works(client: TestClient, session):
    persona = make_persona(session, name="CRYPTOR")
    portfolio = make_portfolio(session, persona)
    make_portfolio_snapshot(session, portfolio)
    make_position_snapshot(session, portfolio, instrument="BTC/USD")
    make_market_bar(session, symbol="BTC/USD", ts=datetime.datetime(2026, 7, 4, 0, 0))
    session.flush()

    with patch("src.api.routes.build_market_data_provider") as mock_live_provider:
        mock_live_provider.return_value.get_last_price.return_value = 65000.0
        response = client.get("/api/personas/CRYPTOR/chart?instrument=BTC/USD")

    assert response.status_code == 200
    body = response.json()
    assert body["instrument"] == "BTC/USD"
    # crypto -> the "market" arg passed to build_market_data_provider must be "crypto"
    assert mock_live_provider.call_args[0][0] == "crypto"


def test_get_persona_transactions_orders_newest_first(client: TestClient, session):
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)
    older_decision = make_decision(session, cycle, portfolio, research_item, instrument="AAPL")
    make_order_record(
        session,
        older_decision,
        submitted_at=datetime.datetime(2026, 7, 1, 9, 0),
        filled_at=datetime.datetime(2026, 7, 1, 9, 1),
        fill_price=Decimal("140.00"),
    )
    newer_decision = make_decision(session, cycle, portfolio, research_item, instrument="MSFT")
    make_order_record(
        session,
        newer_decision,
        submitted_at=datetime.datetime(2026, 7, 3, 9, 0),
        filled_at=datetime.datetime(2026, 7, 3, 9, 1),
        fill_price=Decimal("300.00"),
    )
    session.flush()

    response = client.get("/api/personas/VULTURE/transactions")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["instrument"] == "MSFT"
    assert body[1]["instrument"] == "AAPL"
    assert body[0]["fill_price"] == 300.0


def test_get_persona_decisions_includes_research_items_with_age_days(client: TestClient, session):
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)  # started_at = 2026-07-04 09:00
    research_item = make_research_item(session, cycle)
    research_item.published_at = datetime.datetime(2026, 7, 2, 9, 0)  # 2 days earlier
    session.flush()
    make_decision(session, cycle, portfolio, research_item, instrument="AAPL")
    session.flush()

    response = client.get("/api/personas/VULTURE/decisions")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    decision = body[0]
    assert decision["instrument"] == "AAPL"
    assert len(decision["research_items"]) == 1
    assert decision["research_items"][0]["age_days"] == 2.0


def test_get_persona_decisions_conviction_present_for_buy_absent_for_hold(
    client: TestClient, session
):
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)
    make_decision(
        session,
        cycle,
        portfolio,
        research_item,
        instrument="AAPL",
        action=DecisionAction.BUY,
        expected_outcome={"entry_price": 150.0, "stop_loss_price": 140.0, "conviction": 0.7},
    )
    make_decision(
        session, cycle, portfolio, research_item, instrument="MSFT", action=DecisionAction.HOLD
    )
    session.flush()

    response = client.get("/api/personas/VULTURE/decisions")

    assert response.status_code == 200
    body = {d["instrument"]: d for d in response.json()}
    assert body["AAPL"]["conviction"] == 0.7
    assert body["MSFT"]["conviction"] is None


def test_health_endpoint(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
