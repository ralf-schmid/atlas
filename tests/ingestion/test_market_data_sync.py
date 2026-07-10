import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from alpaca.data.enums import DataFeed
from alpaca.data.models.bars import Bar as AlpacaBar
from alpaca.data.models.bars import BarSet

from src.ingestion.market_data_sync import (
    AlpacaBarsProvider,
    Bar,
    run_daily_sync,
    sync_market_bars,
)


def _alpaca_bar(symbol: str, ts: datetime.datetime, close: float) -> AlpacaBar:
    return AlpacaBar.model_construct(
        symbol=symbol,
        timestamp=ts,
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=1000.0,
        trade_count=None,
        vwap=None,
    )


def test_alpaca_bars_provider_maps_bar_set_to_bar_dataclass():
    ts = datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC)
    bar_set = BarSet.model_construct(
        data={"AAPL": [_alpaca_bar("AAPL", ts, 150.0)]},
    )
    with patch("src.ingestion.market_data_sync.StockHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_stock_bars.return_value = bar_set

        provider = AlpacaBarsProvider(api_key="key", secret_key="secret")
        day = datetime.date(2026, 7, 1)
        bars = provider.get_daily_bars(["AAPL"], day, day)

        mock_cls.assert_called_once_with("key", "secret")
        assert bars == [
            Bar(
                symbol="AAPL",
                ts=ts.replace(tzinfo=None),
                open=Decimal("149.0"),
                high=Decimal("151.0"),
                low=Decimal("148.0"),
                close=Decimal("150.0"),
                volume=Decimal("1000.0"),
            )
        ]


def test_alpaca_bars_provider_uses_inclusive_end_of_day_for_same_day_range():
    """Regression test: found via live verification against the real Alpaca API
    while deploying F035 — a same-day request (start == end, the common "sync
    today's bar" case) with `end` at midnight was a zero-width window that never
    returned that day's bar."""
    bar_set = BarSet.model_construct(data={})
    with patch("src.ingestion.market_data_sync.StockHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_stock_bars.return_value = bar_set

        provider = AlpacaBarsProvider(api_key="key", secret_key="secret")
        day = datetime.date(2026, 7, 1)
        provider.get_daily_bars(["AAPL"], day, day)

        request = mock_cls.return_value.get_stock_bars.call_args[0][0]
        assert request.start == datetime.datetime(2026, 7, 1, 0, 0, 0)
        assert request.end == datetime.datetime(2026, 7, 1, 23, 59, 59, 999999)


def test_alpaca_bars_provider_uses_iex_feed():
    """Regression test: found via live verification against the real Alpaca API
    while deploying F035 — the default (SIP) feed 403s for the Paper-Key-based
    market-data account ("subscription does not permit querying recent SIP
    data"); IEX is what this account tier is actually entitled to."""
    bar_set = BarSet.model_construct(data={})
    with patch("src.ingestion.market_data_sync.StockHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_stock_bars.return_value = bar_set

        provider = AlpacaBarsProvider(api_key="key", secret_key="secret")
        day = datetime.date(2026, 7, 1)
        provider.get_daily_bars(["AAPL"], day, day)

        request = mock_cls.return_value.get_stock_bars.call_args[0][0]
        assert request.feed == DataFeed.IEX


def test_alpaca_bars_provider_skips_symbols_with_no_bars():
    bar_set = BarSet.model_construct(data={})
    with patch("src.ingestion.market_data_sync.StockHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_stock_bars.return_value = bar_set

        provider = AlpacaBarsProvider(api_key="key", secret_key="secret")
        day = datetime.date(2026, 7, 1)
        bars = provider.get_daily_bars(["ZZZZ"], day, day)

        assert bars == []


class _FakeProvider:
    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    def get_daily_bars(
        self, symbols: list[str], start: datetime.date, end: datetime.date
    ) -> list[Bar]:
        return self._bars


def test_sync_market_bars_returns_zero_for_empty_symbol_list(session):
    count = sync_market_bars(
        session, _FakeProvider([]), [], datetime.date(2026, 7, 1), datetime.date(2026, 7, 1)
    )
    assert count == 0


def test_sync_market_bars_inserts_bars(session):
    bar = Bar(
        symbol="AAPL",
        ts=datetime.datetime(2026, 7, 1),
        open=Decimal("149"),
        high=Decimal("151"),
        low=Decimal("148"),
        close=Decimal("150"),
        volume=Decimal("1000"),
    )
    count = sync_market_bars(
        session,
        _FakeProvider([bar]),
        ["AAPL"],
        datetime.date(2026, 7, 1),
        datetime.date(2026, 7, 1),
    )
    assert count == 1

    from sqlalchemy import select

    from src.db.models import MarketBar

    row = session.scalars(select(MarketBar).where(MarketBar.symbol == "AAPL")).one()
    assert row.close == Decimal("150.000000")


def test_sync_market_bars_upserts_on_rerun_without_duplicates(session):
    bar_v1 = Bar(
        symbol="AAPL",
        ts=datetime.datetime(2026, 7, 1),
        open=Decimal("149"),
        high=Decimal("151"),
        low=Decimal("148"),
        close=Decimal("150"),
        volume=Decimal("1000"),
    )
    bar_v2 = Bar(
        symbol="AAPL",
        ts=datetime.datetime(2026, 7, 1),
        open=Decimal("149"),
        high=Decimal("152"),
        low=Decimal("148"),
        close=Decimal("151"),
        volume=Decimal("1200"),
    )

    sync_market_bars(
        session,
        _FakeProvider([bar_v1]),
        ["AAPL"],
        datetime.date(2026, 7, 1),
        datetime.date(2026, 7, 1),
    )
    sync_market_bars(
        session,
        _FakeProvider([bar_v2]),
        ["AAPL"],
        datetime.date(2026, 7, 1),
        datetime.date(2026, 7, 1),
    )

    from sqlalchemy import select

    from src.db.models import MarketBar

    rows = session.scalars(select(MarketBar).where(MarketBar.symbol == "AAPL")).all()
    assert len(rows) == 1
    assert rows[0].close == Decimal("151.000000")
    assert rows[0].volume == Decimal("1200.000000")


def test_sync_market_bars_chunks_large_batches(session):
    """F048: a 90-day backfill over the full symbol universe (188 symbols × ~62
    trading days, live-hit 2026-07-10) produces enough rows to blow past
    PostgreSQL's 65535-bind-parameter-per-statement limit in a single bulk
    upsert (10 params/row -> ~6553 rows max). Must transparently chunk instead
    of raising."""
    many_bars = [
        Bar(
            symbol=f"SYM{i}",
            ts=datetime.datetime(2026, 7, 1),
            open=Decimal("10"),
            high=Decimal("11"),
            low=Decimal("9"),
            close=Decimal("10.5"),
            volume=Decimal("1000"),
        )
        for i in range(8000)
    ]

    count = sync_market_bars(
        session,
        _FakeProvider(many_bars),
        [f"SYM{i}" for i in range(8000)],
        datetime.date(2026, 7, 1),
        datetime.date(2026, 7, 1),
    )

    assert count == 8000

    from sqlalchemy import func, select

    from src.db.models import MarketBar

    total = session.scalar(select(func.count()).select_from(MarketBar))
    assert total == 8000


def test_run_daily_sync_reads_config_and_env(session, tmp_path, monkeypatch):
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "market_data:\n"
        "  key_id_env: TEST_MD_KEY_ID\n"
        "  secret_key_env: TEST_MD_SECRET_KEY\n"
        "  watchlist:\n"
        "    - AAPL\n"
    )
    monkeypatch.setenv("TEST_MD_KEY_ID", "key")
    monkeypatch.setenv("TEST_MD_SECRET_KEY", "secret")

    ts = datetime.datetime(2026, 7, 1)
    bar_set = BarSet.model_construct(
        data={"AAPL": [_alpaca_bar("AAPL", ts, 150.0)]},
    )
    with patch("src.ingestion.market_data_sync.StockHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_stock_bars.return_value = bar_set

        count = run_daily_sync(session, datetime.date(2026, 7, 1), config_path=config_path)

    assert count == 1


def test_run_daily_sync_defaults_to_a_single_day_window(session, tmp_path, monkeypatch):
    """F048: default lookback_days=1 preserves the exact prior single-day
    behaviour (existing callers/tests)."""
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "market_data:\n"
        "  key_id_env: TEST_MD_KEY_ID\n"
        "  secret_key_env: TEST_MD_SECRET_KEY\n"
        "  watchlist:\n"
        "    - AAPL\n"
    )
    monkeypatch.setenv("TEST_MD_KEY_ID", "key")
    monkeypatch.setenv("TEST_MD_SECRET_KEY", "secret")

    ts = datetime.datetime(2026, 7, 1)
    bar_set = BarSet.model_construct(data={"AAPL": [_alpaca_bar("AAPL", ts, 150.0)]})
    with patch("src.ingestion.market_data_sync.StockHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_stock_bars.return_value = bar_set

        run_daily_sync(session, datetime.date(2026, 7, 1), config_path=config_path)

        request = mock_cls.return_value.get_stock_bars.call_args[0][0]

    assert request.start == datetime.datetime(2026, 7, 1)
    assert request.end == datetime.datetime.combine(datetime.date(2026, 7, 1), datetime.time.max)


def test_run_daily_sync_with_lookback_days_backfills_a_rolling_window(
    session, tmp_path, monkeypatch
):
    """F048: technical indicators (SMA20/RSI14/MACD/Bollinger,
    src/orchestrator/indicators.py) need 15-90 daily bars of history — a
    symbol only ever synced one day at a time never accumulates enough
    (live-confirmed 2026-07-10: 92 symbols, exactly 1 bar each, zero
    technical_indicator research items ever produced). The daily job now
    requests a rolling lookback window instead of a single day — idempotent
    upsert (see sync_market_bars) makes this safe to re-run daily, and it's
    self-healing for any day the job didn't fire at all (container restart,
    outage, ...)."""
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "market_data:\n"
        "  key_id_env: TEST_MD_KEY_ID\n"
        "  secret_key_env: TEST_MD_SECRET_KEY\n"
        "  watchlist:\n"
        "    - AAPL\n"
    )
    monkeypatch.setenv("TEST_MD_KEY_ID", "key")
    monkeypatch.setenv("TEST_MD_SECRET_KEY", "secret")

    ts = datetime.datetime(2026, 7, 1)
    bar_set = BarSet.model_construct(data={"AAPL": [_alpaca_bar("AAPL", ts, 150.0)]})
    trading_day = datetime.date(2026, 7, 10)
    with patch("src.ingestion.market_data_sync.StockHistoricalDataClient") as mock_cls:
        mock_cls.return_value.get_stock_bars.return_value = bar_set

        run_daily_sync(session, trading_day, config_path=config_path, lookback_days=90)

        request = mock_cls.return_value.get_stock_bars.call_args[0][0]

    expected_start = trading_day - datetime.timedelta(days=89)
    assert request.start == datetime.datetime.combine(expected_start, datetime.time.min)
    assert request.end == datetime.datetime.combine(trading_day, datetime.time.max)


def test_run_daily_sync_raises_when_env_var_missing(session, tmp_path, monkeypatch):
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "market_data:\n"
        "  key_id_env: TEST_MD_KEY_ID_MISSING\n"
        "  secret_key_env: TEST_MD_SECRET_KEY_MISSING\n"
        "  watchlist:\n"
        "    - AAPL\n"
    )
    monkeypatch.delenv("TEST_MD_KEY_ID_MISSING", raising=False)
    monkeypatch.delenv("TEST_MD_SECRET_KEY_MISSING", raising=False)

    with pytest.raises(ValueError, match="TEST_MD_KEY_ID_MISSING"):
        run_daily_sync(session, datetime.date(2026, 7, 1), config_path=config_path)
