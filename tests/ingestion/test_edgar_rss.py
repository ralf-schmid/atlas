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


def test_http_edgar_feed_provider_appends_form_type_to_url():
    with patch("src.ingestion.edgar_rss.httpx.get") as mock_get:
        mock_get.return_value = httpx.Response(
            200,
            text=_MALFORMED_ENTRY_FEED,
            request=httpx.Request("GET", "https://www.sec.gov/feed"),
        )

        provider = HttpEdgarFeedProvider(
            feed_url="https://www.sec.gov/feed", user_agent="ATLAS/1.0"
        )
        provider.fetch_current_filings(form_type="SC 13D")

        mock_get.assert_called_once_with(
            "https://www.sec.gov/feed&type=SC+13D",
            headers={"User-Agent": "ATLAS/1.0"},
            timeout=10.0,
        )


def test_run_current_filings_sync_fetches_one_request_per_configured_form_type(
    session, tmp_path, monkeypatch
):
    """F044: the unfiltered SEC firehose (424B/FWP/N-CSRS from large banks/funds)
    drowned out the 8-K/insider-filing signal VULTURE's charter names — see
    docs/features/F044-research-pool-signal-quality.md."""
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "edgar:\n"
        "  feed_url: https://www.sec.gov/feed\n"
        "  user_agent_env: TEST_EDGAR_USER_AGENT\n"
        "  form_types: ['8-K', '4']\n"
    )
    monkeypatch.setenv("TEST_EDGAR_USER_AGENT", "ATLAS/1.0 (test@example.com)")

    requested_urls: list[str] = []

    def _fake_get(url: str, headers: dict, timeout: float) -> httpx.Response:
        requested_urls.append(url)
        return httpx.Response(200, text=_SAMPLE_FEED, request=httpx.Request("GET", url))

    with patch("src.ingestion.edgar_rss.httpx.get", side_effect=_fake_get):
        count = run_current_filings_sync(session, config_path=config_path)

    assert requested_urls == [
        "https://www.sec.gov/feed&type=8-K",
        "https://www.sec.gov/feed&type=4",
    ]
    # _SAMPLE_FEED has a 10-K and a Form-4 entry. The type=8-K response keeps
    # neither (exact post-filter), the type=4 response keeps only the Form 4.
    assert count == 1


def test_fetch_filtered_filings_drops_prefix_matched_form_types(session, tmp_path, monkeypatch):
    """SEC's `type=` param matches by *prefix* (live-observed 09.07.2026: type=4
    returned 59 424B2 plus 485BXT/497K/424B4 rows within two hours) — the exact
    form_type post-filter is what actually enforces the configured whitelist."""
    prefix_polluted_feed = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>4 - Doe John (0000000001) (Reporting)</title>
    <link rel="alternate" type="text/html" href="https://www.sec.gov/a"/>
    <summary type="html">Statement of changes</summary>
    <updated>2026-07-09T15:00:00-04:00</updated>
    <id>urn:tag:sec.gov,2008:accession-number=0000000001-26-000010</id>
  </entry>
  <entry>
    <title>424B2 - BIG BANK INC (0000000002) (Filer)</title>
    <link rel="alternate" type="text/html" href="https://www.sec.gov/b"/>
    <summary type="html">Structured note prospectus</summary>
    <updated>2026-07-09T15:01:00-04:00</updated>
    <id>urn:tag:sec.gov,2008:accession-number=0000000002-26-000011</id>
  </entry>
  <entry>
    <title>497K - SOME FUND (0000000003) (Filer)</title>
    <link rel="alternate" type="text/html" href="https://www.sec.gov/c"/>
    <summary type="html">Fund summary prospectus</summary>
    <updated>2026-07-09T15:02:00-04:00</updated>
    <id>urn:tag:sec.gov,2008:accession-number=0000000003-26-000012</id>
  </entry>
</feed>
"""
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "edgar:\n"
        "  feed_url: https://www.sec.gov/feed\n"
        "  user_agent_env: TEST_EDGAR_USER_AGENT\n"
        "  form_types: ['4']\n"
    )
    monkeypatch.setenv("TEST_EDGAR_USER_AGENT", "ATLAS/1.0 (test@example.com)")

    with patch("src.ingestion.edgar_rss.httpx.get") as mock_get:
        mock_get.return_value = httpx.Response(
            200, text=prefix_polluted_feed, request=httpx.Request("GET", "https://www.sec.gov/feed")
        )
        count = run_current_filings_sync(session, config_path=config_path)

    assert count == 1

    from sqlalchemy import select

    from src.db.models import EdgarFiling

    rows = session.scalars(select(EdgarFiling)).all()
    assert [row.form_type for row in rows] == ["4"]


def test_run_current_filings_sync_without_form_types_makes_a_single_unfiltered_request(
    session, tmp_path, monkeypatch
):
    """Backward-compat: omitting `form_types` keeps the old single-fetch behaviour."""
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "edgar:\n  feed_url: https://www.sec.gov/feed\n  user_agent_env: TEST_EDGAR_USER_AGENT\n"
    )
    monkeypatch.setenv("TEST_EDGAR_USER_AGENT", "ATLAS/1.0 (test@example.com)")

    with patch("src.ingestion.edgar_rss.httpx.get") as mock_get:
        mock_get.return_value = httpx.Response(
            200, text=_SAMPLE_FEED, request=httpx.Request("GET", "https://www.sec.gov/feed")
        )
        run_current_filings_sync(session, config_path=config_path)

        mock_get.assert_called_once_with(
            "https://www.sec.gov/feed",
            headers={"User-Agent": "ATLAS/1.0 (test@example.com)"},
            timeout=10.0,
        )
