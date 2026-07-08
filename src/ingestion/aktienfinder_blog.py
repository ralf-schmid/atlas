"""aktienfinder.net blog/analysis/recommendation listing ingestion into
`aktienfinder_blog_post` — see docs/features/F041-aktienfinder-blog-ingestion.md.

Public listing pages only (no login, no Playwright) — title/date/category/tags
from the article cards, never the Premium article body itself: CLAUDE.md
forbids storing aktienfinder full text in the repo/UI, and the listing pages
don't expose Premium body text without a login this path doesn't use (unlike
`aktienfinder_grabbing.py`'s logged-in stock-profile scraping, F012).

Idempotent: upsert on the WordPress `post_id` (never reused), so re-fetching
the same, overlapping listing pages (the general /blog/ archive contains
articles that also appear in the category-specific archives) never creates
duplicates.
"""

from __future__ import annotations

import datetime
import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
import yaml
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import AktienfinderBlogPost

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"

_ARTICLE_RE = re.compile(r'<article class="([^"]*)"[^>]*>(.*?)</article>', re.DOTALL)
_POST_ID_RE = re.compile(r"\bpost-(\d+)\b")
_CATEGORY_RE = re.compile(r"\bcategory-([\w-]+)\b")
_TAG_RE = re.compile(r"\btag-([\w-]+)\b")
_URL_RE = re.compile(r'href="([^"]+)"')
_TITLE_RE = re.compile(r'elementor-post__title">\s*<a[^>]*>\s*(.*?)\s*</a>', re.DOTALL)
_DATE_RE = re.compile(r'elementor-post-date">\s*([^<]+?)\s*</span>')
_GERMAN_DATE_RE = re.compile(r"(\d{1,2})\.\s*(\w+)\s*(\d{4})")

_GERMAN_MONTHS = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}


@dataclass(frozen=True, slots=True)
class BlogPost:
    post_id: str
    title: str
    url: str
    categories: list[str]
    tags: list[str]
    is_premium: bool
    published_at: datetime.date


class BlogListingProvider(Protocol):
    def fetch_listing(self, url: str) -> str: ...


class HttpBlogListingProvider:
    def fetch_listing(self, url: str) -> str:
        response = httpx.get(url, timeout=15.0, follow_redirects=True)
        response.raise_for_status()
        return response.text


def parse_listing_html(html_text: str) -> list[BlogPost]:
    """Parses aktienfinder.net's Elementor-generated blog archive markup — a
    regular, regex-friendly structure (see F041 §2 for why this doesn't use a
    full HTML-parsing dependency)."""
    posts = []
    for class_attr, body in _ARTICLE_RE.findall(html_text):
        post_id_match = _POST_ID_RE.search(class_attr)
        url_match = _URL_RE.search(body)
        title_match = _TITLE_RE.search(body)
        date_match = _DATE_RE.search(body)
        if not (post_id_match and url_match and title_match and date_match):
            continue

        published_at = _parse_german_date(date_match.group(1))
        if published_at is None:
            continue

        posts.append(
            BlogPost(
                post_id=post_id_match.group(1),
                title=html.unescape(title_match.group(1)),
                url=url_match.group(1),
                categories=_CATEGORY_RE.findall(class_attr),
                tags=_TAG_RE.findall(class_attr),
                is_premium="af-cards-badge--premium" in body,
                published_at=published_at,
            )
        )
    return posts


def _parse_german_date(text: str) -> datetime.date | None:
    match = _GERMAN_DATE_RE.match(text.strip())
    if not match:
        return None
    day, month_name, year = match.groups()
    month = _GERMAN_MONTHS.get(month_name.lower())
    if month is None:
        return None
    return datetime.date(int(year), month, int(day))


def sync_aktienfinder_blog_posts(session: Session, posts: list[BlogPost]) -> int:
    """Upserts `posts`. Returns the number of newly inserted rows (a post
    already known by `post_id` is not re-counted)."""
    if not posts:
        return 0

    rows = [
        {
            "post_id": p.post_id,
            "title": p.title,
            "url": p.url,
            "categories": p.categories,
            "tags": p.tags,
            "is_premium": p.is_premium,
            "published_at": p.published_at,
        }
        for p in posts
    ]

    insert_stmt = insert(AktienfinderBlogPost).values(rows)
    upsert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=["post_id"]).returning(
        AktienfinderBlogPost.id
    )
    result = session.execute(upsert_stmt)
    inserted = len(result.fetchall())
    session.flush()
    return inserted


def run_aktienfinder_blog_sync(
    session: Session,
    config_path: Path = _DEFAULT_CONFIG_PATH,
    provider: BlogListingProvider | None = None,
) -> int:
    """Config-driven entry point, mirrors the other F008-F040 `run_*` functions.
    Wired into the ingestion scheduler (F041, `src/ingestion/scheduler.py`).
    Fetches page 1 of each configured listing URL only — sufficient for a daily
    incremental sync (new articles land on page 1 first), not a full backfill."""
    config = yaml.safe_load(config_path.read_text())
    urls: list[str] = config["aktienfinder_blog"]["urls"]
    active_provider = provider or HttpBlogListingProvider()

    all_posts: dict[str, BlogPost] = {}
    for url in urls:
        html_text = active_provider.fetch_listing(url)
        for post in parse_listing_html(html_text):
            all_posts[post.post_id] = post  # de-dup across overlapping listings

    return sync_aktienfinder_blog_posts(session, list(all_posts.values()))
