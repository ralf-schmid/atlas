import datetime
from unittest.mock import patch

import httpx
import pytest

from src.ingestion.edgar_rss import (
    Filing,
    HttpEdgarFeedProvider,
    parse_atom_feed,
    run_current_filings_sync,
    sync_edgar_filings,
)

_SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>10-K - APPLE INC (0000320193) (Filer)</title>
    <link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/index.htm"/>
    <summary type="html">Annual report</summary>
    <updated>2026-07-01T18:04:23-04:00</updated>
    <category scheme="https://www.sec.gov/" label="form type" term="10-K"/>
    <id>urn:tag:sec.gov,2008:accession-number=0000320193-26-000106</id>
  </entry>
  <entry>
    <title>4 - Doe John (0000000001) (Reporting)</title>
    <link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/1/000000000126000001/index.htm"/>
    <summary type="html">Statement of changes</summary>
    <updated>2026-07-01T18:05:00-04:00</updated>
    <category scheme="https://www.sec.gov/" label="form type" term="4"/>
    <id>urn:tag:sec.gov,2008:accession-number=0000000001-26-000001</id>
  </entry>
</feed>
"""

_MALFORMED_ENTRY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>No id or updated here</title>
  </entry>
</feed>
"""


def test_parse_atom_feed_extracts_filings():
    filings = parse_atom_feed(_SAMPLE_FEED)

    assert filings == [
        Filing(
            accession_number="0000320193-26-000106",
            cik="0000320193",
            company_name="APPLE INC",
            form_type="10-K",
            filed_at=datetime.datetime(2026, 7, 1, 18, 4, 23),
            title="10-K - APPLE INC (0000320193) (Filer)",
            link="https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/index.htm",
            summary="Annual report",
        ),
        Filing(
            accession_number="0000000001-26-000001",
            cik="0000000001",
            company_name="Doe John",
            form_type="4",
            filed_at=datetime.datetime(2026, 7, 1, 18, 5, 0),
            title="4 - Doe John (0000000001) (Reporting)",
            link="https://www.sec.gov/Archives/edgar/data/1/000000000126000001/index.htm",
            summary="Statement of changes",
        ),
    ]


def test_parse_atom_feed_skips_entries_without_id_or_updated():
    filings = parse_atom_feed(_MALFORMED_ENTRY_FEED)
    assert filings == []


def test_http_edgar_feed_provider_sends_user_agent():
    with patch("src.ingestion.edgar_rss.httpx.get") as mock_get:
        mock_get.return_value = httpx.Response(
            200, text=_SAMPLE_FEED, request=httpx.Request("GET", "https://www.sec.gov/feed")
        )

        provider = HttpEdgarFeedProvider(
            feed_url="https://www.sec.gov/feed", user_agent="ATLAS/1.0 (ralf@example.com)"
        )
        filings = provider.fetch_current_filings()

        mock_get.assert_called_once_with(
            "https://www.sec.gov/feed",
            headers={"User-Agent": "ATLAS/1.0 (ralf@example.com)"},
            timeout=10.0,
        )
        assert len(filings) == 2


def test_http_edgar_feed_provider_raises_on_http_error():
    with patch("src.ingestion.edgar_rss.httpx.get") as mock_get:
        mock_get.return_value = httpx.Response(
            503, request=httpx.Request("GET", "https://www.sec.gov/feed")
        )

        provider = HttpEdgarFeedProvider(
            feed_url="https://www.sec.gov/feed", user_agent="ATLAS/1.0"
        )
        with pytest.raises(httpx.HTTPStatusError):
            provider.fetch_current_filings()


def test_sync_edgar_filings_returns_zero_for_empty_list(session):
    assert sync_edgar_filings(session, []) == 0


def test_sync_edgar_filings_inserts_new_filings(session):
    filings = parse_atom_feed(_SAMPLE_FEED)
    count = sync_edgar_filings(session, filings)
    assert count == 2

    from sqlalchemy import select

    from src.db.models import EdgarFiling

    rows = session.scalars(select(EdgarFiling)).all()
    assert {row.accession_number for row in rows} == {
        "0000320193-26-000106",
        "0000000001-26-000001",
    }


def test_sync_edgar_filings_is_idempotent_on_rerun(session):
    filings = parse_atom_feed(_SAMPLE_FEED)
    first_count = sync_edgar_filings(session, filings)
    second_count = sync_edgar_filings(session, filings)

    assert first_count == 2
    assert second_count == 0

    from sqlalchemy import select

    from src.db.models import EdgarFiling

    rows = session.scalars(select(EdgarFiling)).all()
    assert len(rows) == 2


def test_run_current_filings_sync_reads_config_and_env(session, tmp_path, monkeypatch):
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "edgar:\n  feed_url: https://www.sec.gov/feed\n  user_agent_env: TEST_EDGAR_USER_AGENT\n"
    )
    monkeypatch.setenv("TEST_EDGAR_USER_AGENT", "ATLAS/1.0 (test@example.com)")

    with patch("src.ingestion.edgar_rss.httpx.get") as mock_get:
        mock_get.return_value = httpx.Response(
            200, text=_SAMPLE_FEED, request=httpx.Request("GET", "https://www.sec.gov/feed")
        )
        count = run_current_filings_sync(session, config_path=config_path)

    assert count == 2


def test_run_current_filings_sync_raises_when_env_var_missing(session, tmp_path, monkeypatch):
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "edgar:\n"
        "  feed_url: https://www.sec.gov/feed\n"
        "  user_agent_env: TEST_EDGAR_USER_AGENT_MISSING\n"
    )
    monkeypatch.delenv("TEST_EDGAR_USER_AGENT_MISSING", raising=False)

    with pytest.raises(ValueError, match="TEST_EDGAR_USER_AGENT_MISSING"):
        run_current_filings_sync(session, config_path=config_path)
