# ruff: noqa: E501 — real-shape HTML fixture below, long lines are expected.
import datetime

from src.ingestion.aktienfinder_blog import (
    BlogPost,
    parse_listing_html,
    run_aktienfinder_blog_sync,
    sync_aktienfinder_blog_posts,
)

# Minimal, real-shape fixture — trimmed from a live fetch of
# https://aktienfinder.net/blog/aktienanalyse/ (F041 §2), two article cards.
_SAMPLE_LISTING_HTML = """
<div class="elementor-posts-container">
<article class="elementor-post elementor-grid-item post-32176 post type-post status-publish format-standard has-post-thumbnail hentry category-aktienanalyse tag-aktie tag-dividende tag-general-mills" role="listitem">
    <div class="elementor-post__card">
        <a class="elementor-post__thumbnail__link" href="https://aktienfinder.net/blog/general-mills-72-dividende-wird-die-dividende-gekuerzt/" tabindex="-1"></a>
        <div class="elementor-post__text">
        <h3 class="elementor-post__title">
            <a href="https://aktienfinder.net/blog/general-mills-72-dividende-wird-die-dividende-gekuerzt/" >
                General Mills &#8211; 7,2 % Dividende! Wird die Dividende gekürzt?			</a>
        </h3>
        </div>
        <div class="elementor-post__meta-data af-elementor-post__meta-data">
          <div class="elementor-post__meta-data_inner">
                <span class="elementor-post-author">Aktionieur</span>
                <span class="elementor-post-date">11. Juni 2026</span>
          </div>
            <div class="af-cards-badges">
      <div class="af-cards-badge af-cards-badge--aktienanalyse">Aktienanalyse</div><div class="af-cards-badge af-cards-badge--premium">Premium</div>      </div>
          </div>
    </div>
</article>
<article class="elementor-post elementor-grid-item post-32293 post type-post status-publish format-standard has-post-thumbnail hentry category-artikelserie category-top-50-dividenden-aktien tag-aktie tag-top-50" role="listitem">
    <div class="elementor-post__card">
        <a class="elementor-post__thumbnail__link" href="https://aktienfinder.net/blog/top-50-dividenden-aktien-im-sommer-2026/" tabindex="-1"></a>
        <div class="elementor-post__text">
        <h3 class="elementor-post__title">
            <a href="https://aktienfinder.net/blog/top-50-dividenden-aktien-im-sommer-2026/" >
                Top 50 Dividenden-Aktien im Sommer 2026			</a>
        </h3>
        </div>
        <div class="elementor-post__meta-data af-elementor-post__meta-data">
          <div class="elementor-post__meta-data_inner">
                <span class="elementor-post-author">Aktionieur</span>
                <span class="elementor-post-date">26. Juni 2026</span>
          </div>
            <div class="af-cards-badges">
      <div class="af-cards-badge af-cards-badge--top-50-dividenden-aktien">Top 50 Dividenden-Aktien</div>      </div>
          </div>
    </div>
</article>
</div>
"""


def test_parse_listing_html_extracts_posts():
    posts = parse_listing_html(_SAMPLE_LISTING_HTML)

    assert posts == [
        BlogPost(
            post_id="32176",
            title="General Mills – 7,2 % Dividende! Wird die Dividende gekürzt?",
            url="https://aktienfinder.net/blog/general-mills-72-dividende-wird-die-dividende-gekuerzt/",
            categories=["aktienanalyse"],
            tags=["aktie", "dividende", "general-mills"],
            is_premium=True,
            published_at=datetime.date(2026, 6, 11),
        ),
        BlogPost(
            post_id="32293",
            title="Top 50 Dividenden-Aktien im Sommer 2026",
            url="https://aktienfinder.net/blog/top-50-dividenden-aktien-im-sommer-2026/",
            categories=["artikelserie", "top-50-dividenden-aktien"],
            tags=["aktie", "top-50"],
            is_premium=False,
            published_at=datetime.date(2026, 6, 26),
        ),
    ]


def test_parse_listing_html_returns_empty_for_no_articles():
    assert parse_listing_html("<div>no articles here</div>") == []


def test_sync_aktienfinder_blog_posts_returns_zero_for_empty_list(session):
    assert sync_aktienfinder_blog_posts(session, []) == 0


def test_sync_aktienfinder_blog_posts_is_idempotent_on_rerun(session):
    posts = parse_listing_html(_SAMPLE_LISTING_HTML)

    first_count = sync_aktienfinder_blog_posts(session, posts)
    second_count = sync_aktienfinder_blog_posts(session, posts)

    assert first_count == 2
    assert second_count == 0

    from sqlalchemy import select

    from src.db.models import AktienfinderBlogPost

    rows = session.scalars(select(AktienfinderBlogPost)).all()
    assert len(rows) == 2


class _FakeListingProvider:
    def __init__(self, html_by_url: dict[str, str]) -> None:
        self._html_by_url = html_by_url
        self.requested_urls: list[str] = []

    def fetch_listing(self, url: str) -> str:
        self.requested_urls.append(url)
        return self._html_by_url[url]


def test_run_aktienfinder_blog_sync_dedupes_across_overlapping_urls(session, tmp_path):
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(
        "aktienfinder_blog:\n"
        "  urls:\n"
        "    - https://aktienfinder.net/blog/\n"
        "    - https://aktienfinder.net/blog/aktienanalyse/\n"
    )
    provider = _FakeListingProvider(
        {
            "https://aktienfinder.net/blog/": _SAMPLE_LISTING_HTML,
            "https://aktienfinder.net/blog/aktienanalyse/": _SAMPLE_LISTING_HTML,
        }
    )

    count = run_aktienfinder_blog_sync(session, config_path=config_path, provider=provider)

    assert provider.requested_urls == [
        "https://aktienfinder.net/blog/",
        "https://aktienfinder.net/blog/aktienanalyse/",
    ]
    assert count == 2  # same 2 posts appear on both listing pages, no duplicates
