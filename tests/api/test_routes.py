import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.db.models import DecisionAction, DecisionStatus, Persona, PortfolioMode
from src.orchestrator.competition_config import load_competition_config
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
    make_review,
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


def _competition_start() -> datetime.datetime:
    """Anchor the F100 history tests to the configured start date instead of a
    hardcoded one — the endpoint cuts off there, and the date is Ralf's config."""
    return datetime.datetime.combine(load_competition_config().start_date, datetime.time.min)


def test_get_portfolio_history_returns_series_per_persona(client: TestClient, session):
    start = _competition_start()
    for name in ("VULTURE", "HYPE"):
        portfolio = make_portfolio(session, make_persona(session, name=name))
        make_portfolio_snapshot(session, portfolio, ts=start + datetime.timedelta(hours=16))
        make_portfolio_snapshot(session, portfolio, ts=start + datetime.timedelta(days=1))
    session.flush()

    response = client.get("/api/portfolios/history")

    assert response.status_code == 200
    body = response.json()
    assert body["start"] == load_competition_config().start_date.isoformat()
    assert body["start_capital"] == float(load_competition_config().start_capital_usd)
    assert [s["persona"] for s in body["series"]] == ["HYPE", "VULTURE"]
    hype = body["series"][0]
    assert hype["display_name"].startswith("HYPE")
    assert [p["ts"] for p in hype["points"]] == sorted(p["ts"] for p in hype["points"])
    assert len(hype["points"]) == 2


def test_get_portfolio_history_computes_position_value(client: TestClient, session):
    portfolio = make_portfolio(session, make_persona(session, name="GUARDIAN"))
    make_portfolio_snapshot(
        session,
        portfolio,
        ts=_competition_start() + datetime.timedelta(hours=16),
        total_value=Decimal("5200.00"),
        cash=Decimal("1200.00"),
    )
    session.flush()

    response = client.get("/api/portfolios/history")

    point = response.json()["series"][0]["points"][0]
    assert point["total_value"] == 5200.0
    assert point["cash"] == 1200.0
    assert point["position_value"] == 4000.0


def test_get_portfolio_history_excludes_archived_portfolios(client: TestClient, session):
    persona = make_persona(session, name="CONTRA")
    archived = make_portfolio(session, persona)
    archived.archived_at = _competition_start()
    make_portfolio_snapshot(
        session, archived, ts=_competition_start() + datetime.timedelta(hours=16)
    )
    session.flush()

    response = client.get("/api/portfolios/history")

    assert response.json()["series"] == []


def test_get_portfolio_history_starts_at_competition_start_date(client: TestClient, session):
    portfolio = make_portfolio(session, make_persona(session, name="CHARTIST"))
    make_portfolio_snapshot(
        session, portfolio, ts=_competition_start() - datetime.timedelta(days=1)
    )
    make_portfolio_snapshot(
        session, portfolio, ts=_competition_start() + datetime.timedelta(days=1)
    )
    session.flush()

    response = client.get("/api/portfolios/history")

    points = response.json()["series"][0]["points"]
    assert len(points) == 1
    assert points[0]["ts"].startswith(
        (_competition_start() + datetime.timedelta(days=1)).date().isoformat()
    )


def test_get_portfolio_history_defaults_to_paper_mode(client: TestClient, session):
    persona = make_persona(session, name="CRYPTOR")
    live = make_portfolio(session, persona, mode=PortfolioMode.LIVE)
    make_portfolio_snapshot(session, live, ts=_competition_start() + datetime.timedelta(hours=16))
    session.flush()

    response = client.get("/api/portfolios/history")

    assert response.json()["series"] == []


def test_get_portfolio_history_without_snapshots_returns_empty_series(client: TestClient, session):
    make_portfolio(session, make_persona(session, name="VULTURE"))
    session.flush()

    response = client.get("/api/portfolios/history")

    assert response.status_code == 200
    assert response.json()["series"] == []


def test_health_endpoint(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- F085: leaderboard ------------------------------------------------------------


def _seed_leaderboard_persona(
    session, name: str, values: list[str], *, day_offset: int = 0
) -> object:
    """One persona with one portfolio and one snapshot per day since the start."""
    portfolio = make_portfolio(session, make_persona(session, name=name))
    for index, value in enumerate(values):
        make_portfolio_snapshot(
            session,
            portfolio,
            ts=_competition_start() + datetime.timedelta(days=index + day_offset, hours=16),
            total_value=Decimal(value),
            cash=Decimal(value),
        )
    return portfolio


def test_get_leaderboard_ranks_by_raw_return(client: TestClient, session):
    _seed_leaderboard_persona(session, "VULTURE", ["5000.00", "5100.00"])
    _seed_leaderboard_persona(session, "HYPE", ["5000.00", "4800.00"])
    _seed_leaderboard_persona(session, "GUARDIAN", ["5000.00", "5300.00"])
    session.flush()

    response = client.get("/api/leaderboard")

    assert response.status_code == 200
    body = response.json()
    assert [row["persona"] for row in body["rows"]] == ["GUARDIAN", "VULTURE", "HYPE"]
    assert [row["rank"] for row in body["rows"]] == [1, 2, 3]
    assert body["rows"][0]["raw_return"] == pytest.approx(0.06)
    assert body["rows"][0]["total_value"] == 5300.0
    assert body["sort"] == "raw"


def test_get_leaderboard_uses_the_days_last_snapshot(client: TestClient, session):
    portfolio = make_portfolio(session, make_persona(session, name="CHARTIST"))
    for hour, value in ((9, "5100.00"), (16, "4900.00")):
        make_portfolio_snapshot(
            session,
            portfolio,
            ts=_competition_start() + datetime.timedelta(hours=hour),
            total_value=Decimal(value),
            cash=Decimal(value),
        )
    session.flush()

    response = client.get("/api/leaderboard")

    row = response.json()["rows"][0]
    assert row["sparkline"] == [4900.0]
    assert row["raw_return"] == pytest.approx(-0.02)


def test_get_leaderboard_without_reviews_reports_adjusted_equals_raw(client: TestClient, session):
    _seed_leaderboard_persona(session, "VULTURE", ["5000.00", "5100.00"])
    session.flush()

    body = client.get("/api/leaderboard").json()

    row = body["rows"][0]
    assert body["has_reviews"] is False
    assert row["slippage_malus_usd"] is None
    assert row["adjusted_return"] == row["raw_return"]


def test_get_leaderboard_subtracts_the_slippage_malus_from_the_adjusted_return(
    client: TestClient, session
):
    persona = make_persona(session, name="CONTRA")
    portfolio = make_portfolio(session, persona)
    make_portfolio_snapshot(
        session,
        portfolio,
        ts=_competition_start() + datetime.timedelta(hours=16),
        total_value=Decimal("5100.00"),
        cash=Decimal("5100.00"),
    )
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)
    decision = make_decision(session, cycle, portfolio, research_item)
    make_review(
        session,
        decision,
        slippage_malus=Decimal("50.00"),
        reviewed_at=_competition_start() + datetime.timedelta(days=1),
    )
    session.flush()

    body = client.get("/api/leaderboard").json()

    row = body["rows"][0]
    assert body["has_reviews"] is True
    assert row["slippage_malus_usd"] == 50.0
    # raw 2 % minus 50 USD on 5000 start capital = 1 %
    assert row["raw_return"] == pytest.approx(0.02)
    assert row["adjusted_return"] == pytest.approx(0.01)


def test_get_leaderboard_sort_adjusted_changes_the_ranking(client: TestClient, session):
    good_raw = make_portfolio(session, make_persona(session, name="VULTURE"))
    make_portfolio_snapshot(
        session,
        good_raw,
        ts=_competition_start() + datetime.timedelta(hours=16),
        total_value=Decimal("5100.00"),
        cash=Decimal("5100.00"),
    )
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)
    make_review(
        session,
        make_decision(session, cycle, good_raw, research_item),
        slippage_malus=Decimal("150.00"),
        reviewed_at=_competition_start() + datetime.timedelta(days=1),
    )
    steady = make_portfolio(session, make_persona(session, name="GUARDIAN"))
    make_portfolio_snapshot(
        session,
        steady,
        ts=_competition_start() + datetime.timedelta(hours=16),
        total_value=Decimal("5050.00"),
        cash=Decimal("5050.00"),
    )
    session.flush()

    raw_order = [r["persona"] for r in client.get("/api/leaderboard?sort=raw").json()["rows"]]
    adjusted = client.get("/api/leaderboard?sort=adjusted").json()

    assert raw_order == ["VULTURE", "GUARDIAN"]
    assert [r["persona"] for r in adjusted["rows"]] == ["GUARDIAN", "VULTURE"]
    assert adjusted["sort"] == "adjusted"


def test_get_leaderboard_reports_the_spy_benchmark_row(client: TestClient, session):
    portfolio = make_portfolio(session, make_persona(session, name="VULTURE"))
    make_portfolio_snapshot(
        session,
        portfolio,
        ts=_competition_start() + datetime.timedelta(hours=16),
        total_value=Decimal("5000.00"),
        cash=Decimal("5000.00"),
        benchmark_value=Decimal("5150.00"),
    )
    session.flush()

    body = client.get("/api/leaderboard").json()

    assert body["benchmark"]["symbol"] == "SPY"
    assert body["benchmark"]["total_value"] == 5150.0
    assert body["benchmark"]["raw_return"] == pytest.approx(0.03)


def test_get_leaderboard_without_benchmark_snapshots_omits_the_row(client: TestClient, session):
    _seed_leaderboard_persona(session, "VULTURE", ["5000.00"])
    session.flush()

    assert client.get("/api/leaderboard").json()["benchmark"] is None


def test_get_leaderboard_excludes_archived_portfolios(client: TestClient, session):
    persona = make_persona(session, name="HYPE")
    archived = make_portfolio(session, persona)
    archived.archived_at = _competition_start()
    make_portfolio_snapshot(
        session, archived, ts=_competition_start() + datetime.timedelta(hours=16)
    )
    session.flush()

    assert client.get("/api/leaderboard").json()["rows"] == []


def test_get_leaderboard_rejects_an_unknown_sort_key(client: TestClient, session):
    assert client.get("/api/leaderboard?sort=sortino").status_code == 422


# --- F086: decision journal -------------------------------------------------------


def test_get_persona_decisions_reports_expectation_outcome_and_review(client: TestClient, session):
    persona = make_persona(session, name="VULTURE")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)
    decision = make_decision(
        session,
        cycle,
        portfolio,
        research_item,
        action=DecisionAction.BUY,
        quantity=Decimal("4"),
        expected_outcome={
            "entry_price": 100.0,
            "stop_loss_price": 92.0,
            "target_price": 130.0,
            "horizon_days": 21,
            "conviction": 0.6,
        },
    )
    make_order_record(
        session,
        decision,
        filled_at=datetime.datetime(2026, 7, 4, 10, 0),
        fill_price=Decimal("101.25"),
    )
    make_review(
        session,
        decision,
        slippage_malus=Decimal("1.50"),
        lessons_text="Einstieg zu spät nach dem Volumen-Spike.",
    )
    session.flush()

    body = client.get("/api/personas/VULTURE/decisions").json()

    entry = body[0]
    assert entry["expected"] == {
        "entry_price": 100.0,
        "stop_loss_price": 92.0,
        "target_price": 130.0,
        "horizon_days": 21.0,
    }
    assert entry["outcome"]["order_status"] == "filled"
    assert entry["outcome"]["fill_price"] == 101.25
    assert entry["outcome"]["quantity"] == 4.0
    assert entry["review"]["verdict"] == "thesis_confirmed"
    assert entry["review"]["slippage_malus"] == 1.5
    assert entry["review"]["lessons_text"].startswith("Einstieg")


def test_get_persona_decisions_without_order_or_review_reports_none(client: TestClient, session):
    persona = make_persona(session, name="GUARDIAN")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    research_item = make_research_item(session, cycle)
    make_decision(
        session, cycle, portfolio, research_item, action=DecisionAction.HOLD, expected_outcome={}
    )
    session.flush()

    entry = client.get("/api/personas/GUARDIAN/decisions").json()[0]

    assert entry["outcome"] is None
    assert entry["review"] is None
    assert entry["expected"]["entry_price"] is None


def test_get_persona_decisions_filter_rejected_covers_reject_idea_and_gate_refusals(
    client: TestClient, session
):
    """F086's Rejected-Filter: an idea can die as `reject_idea` (the persona
    dropped it) or at the risk gate — the journal must show both as verworfen."""
    persona = make_persona(session, name="CHARTIST")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    item = make_research_item(session, cycle)
    make_decision(
        session,
        cycle,
        portfolio,
        item,
        instrument="AAA",
        action=DecisionAction.REJECT_IDEA,
        rejection_reason="position_too_small_for_whole_share",
    )
    make_decision(
        session,
        cycle,
        portfolio,
        item,
        instrument="BBB",
        action=DecisionAction.BUY,
        status=DecisionStatus.RISK_REJECTED,
    )
    make_decision(session, cycle, portfolio, item, instrument="CCC", action=DecisionAction.HOLD)
    make_decision(session, cycle, portfolio, item, instrument="DDD", action=DecisionAction.BUY)
    session.flush()

    rejected = client.get("/api/personas/CHARTIST/decisions?filter=rejected").json()

    assert {entry["instrument"] for entry in rejected} == {"AAA", "BBB"}


def test_get_persona_decisions_filter_traded_and_hold(client: TestClient, session):
    persona = make_persona(session, name="CONTRA")
    portfolio = make_portfolio(session, persona)
    cycle = make_cycle(session)
    item = make_research_item(session, cycle)
    make_decision(session, cycle, portfolio, item, instrument="AAA", action=DecisionAction.BUY)
    make_decision(session, cycle, portfolio, item, instrument="BBB", action=DecisionAction.CLOSE)
    make_decision(session, cycle, portfolio, item, instrument="CCC", action=DecisionAction.HOLD)
    session.flush()

    traded = client.get("/api/personas/CONTRA/decisions?filter=traded").json()
    held = client.get("/api/personas/CONTRA/decisions?filter=hold").json()

    assert {entry["instrument"] for entry in traded} == {"AAA", "BBB"}
    assert [entry["instrument"] for entry in held] == ["CCC"]


def test_get_persona_decisions_rejects_an_unknown_filter(client: TestClient, session):
    make_persona(session, name="HYPE")
    make_portfolio(session, session.scalars(select(Persona)).first())
    session.flush()

    assert client.get("/api/personas/HYPE/decisions?filter=broken").status_code == 422


# --- F087: impulse comparison -----------------------------------------------------


def test_get_impulses_lists_only_cited_items_with_persona_counts(client: TestClient, session):
    """The pool holds thousands of items per cycle — one nobody cited has no
    comparison to show."""
    cycle = make_cycle(session)
    cited = make_research_item(session, cycle, source_ref="CITED")
    make_research_item(session, cycle, source_ref="UNCITED")
    for name in ("VULTURE", "HYPE"):
        portfolio = make_portfolio(session, make_persona(session, name=name))
        make_decision(session, cycle, portfolio, cited)
    session.flush()

    body = client.get("/api/research/impulses").json()

    assert [entry["id"] for entry in body] == [str(cited.id)]
    assert body[0]["citing_personas"] == 2


def test_get_impulse_comparison_reports_one_reaction_per_persona(client: TestClient, session):
    cycle = make_cycle(session)
    item = make_research_item(session, cycle)
    other = make_research_item(session, cycle, source_ref="OTHER")

    bought = make_portfolio(session, make_persona(session, name="VULTURE"))
    make_decision(session, cycle, bought, item, action=DecisionAction.BUY, instrument="AAPL")

    dropped = make_portfolio(session, make_persona(session, name="CONTRA"))
    make_decision(
        session,
        cycle,
        dropped,
        item,
        action=DecisionAction.REJECT_IDEA,
        rejection_reason="kein fundamentaler Cross-Check",
    )

    held = make_portfolio(session, make_persona(session, name="GUARDIAN"))
    make_decision(session, cycle, held, item, action=DecisionAction.HOLD)

    # ran that cycle, but cited a different item -> ignored
    ignoring = make_portfolio(session, make_persona(session, name="HYPE"))
    make_decision(session, cycle, ignoring, other, action=DecisionAction.HOLD)

    # no decision in that cycle at all -> no_run, not "ignored"
    make_portfolio(session, make_persona(session, name="CHARTIST"))
    session.flush()

    body = client.get(f"/api/research/{item.id}/comparison").json()

    verdicts = {r["persona"]: r["verdict"] for r in body["reactions"]}
    assert verdicts == {
        "VULTURE": "traded",
        "CONTRA": "rejected",
        "GUARDIAN": "hold",
        "HYPE": "ignored",
        "CHARTIST": "no_run",
    }
    assert body["impulse"]["citing_personas"] == 3
    contra = next(r for r in body["reactions"] if r["persona"] == "CONTRA")
    assert contra["rejection_reason"] == "kein fundamentaler Cross-Check"
    assert contra["thesis_text"] == "Test thesis"


def test_get_impulse_comparison_counts_a_gate_refusal_as_rejected(client: TestClient, session):
    """A buy the risk gate refused is not a trade — the comparison must not claim
    the persona acted on the impulse."""
    cycle = make_cycle(session)
    item = make_research_item(session, cycle)
    portfolio = make_portfolio(session, make_persona(session, name="VULTURE"))
    make_decision(
        session,
        cycle,
        portfolio,
        item,
        action=DecisionAction.BUY,
        status=DecisionStatus.RISK_REJECTED,
    )
    session.flush()

    body = client.get(f"/api/research/{item.id}/comparison").json()

    assert body["reactions"][0]["verdict"] == "rejected"


def test_get_impulse_comparison_unknown_item_returns_404(client: TestClient, session):
    import uuid as _uuid

    assert client.get(f"/api/research/{_uuid.uuid4()}/comparison").status_code == 404
