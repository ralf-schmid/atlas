"""Reddit ingestion into `reddit_post` — see docs/features/F039-reddit-ingestion.md.

OAuth2 **client_credentials** (app-only, read-only) via `httpx` directly — no
`praw` dependency, no personal Reddit login. Reddit requires a descriptive
`User-Agent` on every request (unauthenticated or not), see
https://github.com/reddit-archive/reddit/wiki/API#rules.

No sentiment scoring here or anywhere in ingestion code — only raw structured
facts (title/score/comment count) are persisted; interpretation is left
entirely to the persona at decision time, same as every other research source
(Invariant #9).

Idempotent: upsert on the `post_id` unique constraint (Reddit's own post id never
changes), so re-polling overlapping listing windows never creates duplicates.
"""

from __future__ import annotations

import datetime
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import RedditPost

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"
_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS = 60  # refresh a bit before the token actually expires


@dataclass(frozen=True, slots=True)
class Post:
    post_id: str
    subreddit: str
    title: str
    score: int
    num_comments: int
    created_utc: datetime.datetime
    permalink: str


class RedditPostProvider(Protocol):
    def fetch_new_posts(self, subreddit: str, limit: int) -> list[Post]: ...


@dataclass
class _CachedToken:
    value: str
    expires_at: float


class HttpRedditProvider:
    """Fetches recent posts from a subreddit via Reddit's OAuth2 app-only flow.

    The access token is cached in-process for its TTL — cheap given the sync
    cadence (hourly-ish), no need for anything more elaborate.
    """

    def __init__(self, client_id: str, client_secret: str, user_agent: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._cached_token: _CachedToken | None = None

    def fetch_new_posts(self, subreddit: str, limit: int) -> list[Post]:
        token = self._get_token()
        response = httpx.get(
            f"https://oauth.reddit.com/r/{subreddit}/new",
            params={"limit": limit},
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": self._user_agent,
            },
            timeout=10.0,
        )
        response.raise_for_status()
        return parse_listing_response(subreddit, response.json())

    def _get_token(self) -> str:
        if self._cached_token is not None and self._cached_token.expires_at > time.monotonic():
            return self._cached_token.value

        response = httpx.post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
            headers={"User-Agent": self._user_agent},
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        expires_at = time.monotonic() + payload["expires_in"] - _TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS
        self._cached_token = _CachedToken(value=payload["access_token"], expires_at=expires_at)
        return self._cached_token.value


def parse_listing_response(subreddit: str, payload: dict[str, Any]) -> list[Post]:
    children = payload["data"]["children"]
    return [
        Post(
            post_id=child["data"]["id"],
            subreddit=subreddit,
            title=child["data"]["title"],
            score=int(child["data"]["score"]),
            num_comments=int(child["data"]["num_comments"]),
            created_utc=datetime.datetime.fromtimestamp(
                child["data"]["created_utc"], tz=datetime.UTC
            ).replace(tzinfo=None),
            permalink=f"https://reddit.com{child['data']['permalink']}",
        )
        for child in children
    ]


def sync_reddit_posts(session: Session, posts: list[Post]) -> int:
    """Upserts `posts`. Returns the number of newly inserted rows (a post already
    known by `post_id` is not re-counted — posts are immutable enough for our
    purposes; score/comment-count drift isn't worth tracking as an update)."""
    if not posts:
        return 0

    rows = [
        {
            "post_id": p.post_id,
            "subreddit": p.subreddit,
            "title": p.title,
            "score": p.score,
            "num_comments": p.num_comments,
            "created_utc": p.created_utc,
            "permalink": p.permalink,
        }
        for p in posts
    ]

    insert_stmt = insert(RedditPost).values(rows)
    upsert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=["post_id"]).returning(
        RedditPost.id
    )
    result = session.execute(upsert_stmt)
    inserted = len(result.fetchall())
    session.flush()
    return inserted


def run_reddit_sync(session: Session, config_path: Path = _DEFAULT_CONFIG_PATH) -> int:
    """Config-driven entry point, mirrors the other F008-F014 `run_*` functions.
    Wired into the ingestion scheduler (F035/F039, `src/ingestion/scheduler.py`)."""
    config = yaml.safe_load(config_path.read_text())
    reddit_config = config["reddit"]

    client_id = _require_env(reddit_config["client_id_env"])
    client_secret = _require_env(reddit_config["client_secret_env"])
    user_agent = _require_env(reddit_config["user_agent_env"])
    subreddits: list[str] = reddit_config["subreddits"]
    limit_per_subreddit: int = reddit_config["limit_per_subreddit"]

    provider = HttpRedditProvider(
        client_id=client_id, client_secret=client_secret, user_agent=user_agent
    )
    posts = [
        post
        for subreddit in subreddits
        for post in provider.fetch_new_posts(subreddit, limit_per_subreddit)
    ]
    return sync_reddit_posts(session, posts)


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ValueError(f"Environment variable {var_name!r} is not set")
    return value
