import datetime
from unittest.mock import patch

import httpx
import pytest

from src.ingestion.reddit_sentiment import (
    HttpRedditProvider,
    Post,
    parse_listing_response,
    run_reddit_sync,
    sync_reddit_posts,
)

_SAMPLE_LISTING = {
    "data": {
        "children": [
            {
                "data": {
                    "id": "abc123",
                    "title": "BTC breaks above 60k",
                    "score": 4200,
                    "num_comments": 731,
                    "created_utc": 1751000000.0,
                    "permalink": "/r/Bitcoin/comments/abc123/btc_breaks_above_60k/",
                }
            },
            {
                "data": {
                    "id": "def456",
                    "title": "Daily discussion",
                    "score": 12,
                    "num_comments": 3,
                    "created_utc": 1751003600.0,
                    "permalink": "/r/Bitcoin/comments/def456/daily_discussion/",
                }
            },
        ]
    }
}


def test_parse_listing_response_extracts_posts():
    posts = parse_listing_response("Bitcoin", _SAMPLE_LISTING)

    assert posts == [
        Post(
            post_id="abc123",
            subreddit="Bitcoin",
            title="BTC breaks above 60k",
            score=4200,
            num_comments=731,
            created_utc=datetime.datetime.fromtimestamp(1751000000.0, tz=datetime.UTC).replace(
                tzinfo=None
            ),
            permalink="https://reddit.com/r/Bitcoin/comments/abc123/btc_breaks_above_60k/",
        ),
        Post(
            post_id="def456",
            subreddit="Bitcoin",
            title="Daily discussion",
            score=12,
            num_comments=3,
            created_utc=datetime.datetime.fromtimestamp(1751003600.0, tz=datetime.UTC).replace(
                tzinfo=None
            ),
            permalink="https://reddit.com/r/Bitcoin/comments/def456/daily_discussion/",
        ),
    ]


def test_sync_reddit_posts_returns_zero_for_empty_list(session):
    assert sync_reddit_posts(session, []) == 0


def test_sync_reddit_posts_is_idempotent_on_rerun(session):
    posts = parse_listing_response("Bitcoin", _SAMPLE_LISTING)

    first_count = sync_reddit_posts(session, posts)
    second_count = sync_reddit_posts(session, posts)

    assert first_count == 2
    assert second_count == 0

    from sqlalchemy import select

    from src.db.models import RedditPost

    rows = session.scalars(select(RedditPost)).all()
    assert len(rows) == 2


def test_fetch_new_posts_reuses_cached_token_within_ttl():
    token_calls = []
    listing_calls = []

    def _fake_post(url, **kwargs):
        token_calls.append(kwargs)
        return httpx.Response(
            200,
            json={"access_token": "tok-1", "expires_in": 3600},
            request=httpx.Request("POST", url),
        )

    def _fake_get(url, **kwargs):
        listing_calls.append(kwargs)
        return httpx.Response(200, json=_SAMPLE_LISTING, request=httpx.Request("GET", url))

    provider = HttpRedditProvider(
        client_id="cid", client_secret="csecret", user_agent="atlas-test/1.0"
    )

    with (
        patch("src.ingestion.reddit_sentiment.httpx.post", side_effect=_fake_post),
        patch("src.ingestion.reddit_sentiment.httpx.get", side_effect=_fake_get),
    ):
        provider.fetch_new_posts("Bitcoin", limit=25)
        provider.fetch_new_posts("ethereum", limit=25)

    assert len(token_calls) == 1  # token reused for the second call
    assert len(listing_calls) == 2
    assert token_calls[0]["auth"] == ("cid", "csecret")
    assert token_calls[0]["headers"]["User-Agent"] == "atlas-test/1.0"
    assert listing_calls[0]["headers"]["Authorization"] == "Bearer tok-1"


def test_fetch_new_posts_refetches_token_after_expiry():
    token_calls = []

    def _fake_post(url, **kwargs):
        token_calls.append(kwargs)
        return httpx.Response(
            200,
            # expires_in <= the safety margin -> treated as already expired
            json={"access_token": f"tok-{len(token_calls)}", "expires_in": 0},
            request=httpx.Request("POST", url),
        )

    def _fake_get(url, **kwargs):
        return httpx.Response(200, json=_SAMPLE_LISTING, request=httpx.Request("GET", url))

    provider = HttpRedditProvider(
        client_id="cid", client_secret="csecret", user_agent="atlas-test/1.0"
    )

    with (
        patch("src.ingestion.reddit_sentiment.httpx.post", side_effect=_fake_post),
        patch("src.ingestion.reddit_sentiment.httpx.get", side_effect=_fake_get),
    ):
        provider.fetch_new_posts("Bitcoin", limit=25)
        provider.fetch_new_posts("ethereum", limit=25)

    assert len(token_calls) == 2


def test_run_reddit_sync_reads_config_and_env(session, tmp_path, monkeypatch):
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "reddit:\n"
        "  client_id_env: TEST_REDDIT_CLIENT_ID\n"
        "  client_secret_env: TEST_REDDIT_CLIENT_SECRET\n"
        "  user_agent_env: TEST_REDDIT_USER_AGENT\n"
        "  subreddits: [Bitcoin]\n"
        "  limit_per_subreddit: 25\n"
    )
    monkeypatch.setenv("TEST_REDDIT_CLIENT_ID", "cid")
    monkeypatch.setenv("TEST_REDDIT_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("TEST_REDDIT_USER_AGENT", "atlas-test/1.0")

    def _fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={"access_token": "tok-1", "expires_in": 3600},
            request=httpx.Request("POST", url),
        )

    def _fake_get(url, **kwargs):
        return httpx.Response(200, json=_SAMPLE_LISTING, request=httpx.Request("GET", url))

    with (
        patch("src.ingestion.reddit_sentiment.httpx.post", side_effect=_fake_post),
        patch("src.ingestion.reddit_sentiment.httpx.get", side_effect=_fake_get),
    ):
        count = run_reddit_sync(session, config_path=config_path)

    assert count == 2


def test_run_reddit_sync_raises_when_env_var_missing(session, tmp_path, monkeypatch):
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "reddit:\n"
        "  client_id_env: TEST_REDDIT_CLIENT_ID_MISSING\n"
        "  client_secret_env: TEST_REDDIT_CLIENT_SECRET\n"
        "  user_agent_env: TEST_REDDIT_USER_AGENT\n"
        "  subreddits: [Bitcoin]\n"
        "  limit_per_subreddit: 25\n"
    )
    monkeypatch.delenv("TEST_REDDIT_CLIENT_ID_MISSING", raising=False)

    with pytest.raises(ValueError, match="TEST_REDDIT_CLIENT_ID_MISSING"):
        run_reddit_sync(session, config_path=config_path)
