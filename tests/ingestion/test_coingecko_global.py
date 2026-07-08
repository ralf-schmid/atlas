import datetime
from decimal import Decimal
from unittest.mock import patch

import httpx

from src.ingestion.coingecko_global import (
    GlobalMarketReading,
    parse_global_response,
    run_coingecko_sync,
    sync_btc_dominance_snapshot,
)

_SAMPLE_RESPONSE = {
    "data": {
        "active_cryptocurrencies": 17000,
        "market_cap_percentage": {"btc": 54.231, "eth": 12.5},
        "total_market_cap": {"usd": 2_100_000_000_000.0, "eur": 1_900_000_000_000.0},
    }
}


def test_parse_global_response_extracts_btc_dominance_and_total_cap():
    reading = parse_global_response(_SAMPLE_RESPONSE)

    assert reading == GlobalMarketReading(
        btc_dominance_pct=54.231, total_market_cap_usd=2_100_000_000_000.0
    )


def test_sync_btc_dominance_snapshot_inserts_a_row(session):
    reading = GlobalMarketReading(btc_dominance_pct=54.231, total_market_cap_usd=2.1e12)
    snapshot_at = datetime.datetime(2026, 7, 8, 12, 0)

    sync_btc_dominance_snapshot(session, snapshot_at, reading)

    from sqlalchemy import select

    from src.db.models import BtcDominanceSnapshot

    rows = session.scalars(select(BtcDominanceSnapshot)).all()
    assert len(rows) == 1
    assert rows[0].snapshot_at == snapshot_at
    assert rows[0].btc_dominance_pct == Decimal("54.231")


def test_sync_btc_dominance_snapshot_does_not_upsert_repeated_calls(session):
    """Unlike every other ingestion source, this one has no unique constraint —
    each call is a legitimate new time-series point, not a re-delivery."""
    reading = GlobalMarketReading(btc_dominance_pct=50.0, total_market_cap_usd=2.0e12)
    snapshot_at = datetime.datetime(2026, 7, 8, 12, 0)

    sync_btc_dominance_snapshot(session, snapshot_at, reading)
    sync_btc_dominance_snapshot(session, snapshot_at, reading)

    from sqlalchemy import select

    from src.db.models import BtcDominanceSnapshot

    rows = session.scalars(select(BtcDominanceSnapshot)).all()
    assert len(rows) == 2


def test_run_coingecko_sync_reads_config_and_calls_provider(session, tmp_path):
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text('coingecko:\n  base_url: "https://api.coingecko.com/api/v3/global"\n')

    with patch("src.ingestion.coingecko_global.httpx.get") as mock_get:
        mock_get.return_value = httpx.Response(
            200,
            json=_SAMPLE_RESPONSE,
            request=httpx.Request("GET", "https://api.coingecko.com/api/v3/global"),
        )
        count = run_coingecko_sync(session, config_path=config_path)

    assert count == 1

    from sqlalchemy import select

    from src.db.models import BtcDominanceSnapshot

    rows = session.scalars(select(BtcDominanceSnapshot)).all()
    assert len(rows) == 1
    assert rows[0].btc_dominance_pct == Decimal("54.231")
