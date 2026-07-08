"""Turns new rows in the five research-bearing ingestion tables (F009-F012, F014)
into `research_item` rows for the shared research pool. See
docs/features/F017-shared-research-synthesis.md.

Technical indicators (F036) are a 6th, structurally different source: computed
fresh every cycle over the symbol universe rather than windowed by `synced_at` —
see `_research_items_from_technical_indicators` below and F036 §2.

Deliberately no LLM calls: every `summary` is a deterministic text template built from
fields the ingestion pipelines already parsed out.
"""

from __future__ import annotations

import datetime
import uuid
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import (
    AktienfinderBlogPost,
    AktienfinderSnapshot,
    BtcDominanceSnapshot,
    Cycle,
    EdgarFiling,
    MusterdepotTransaction,
    PublicationArticle,
    RedditPost,
    ResearchItem,
    ScreenerResult,
)
from src.orchestrator.indicators import (
    BollingerBands,
    IndicatorSnapshot,
    compute_indicator_snapshot,
)
from src.orchestrator.symbol_universe import resolve_symbol_universe

_BOOTSTRAP_WINDOW = datetime.timedelta(days=7)
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"


def synthesize_research_items(
    session: Session, cycle: Cycle, config_path: Path = _DEFAULT_CONFIG_PATH
) -> list[ResearchItem]:
    window_start = _resolve_window_start(session, cycle)
    window_end = cycle.started_at

    config = yaml.safe_load(config_path.read_text())
    seed_watchlist: list[str] = config["market_data"]["watchlist"]
    symbols = resolve_symbol_universe(session, seed_watchlist)

    items = [
        *_research_items_from_edgar_filings(session, cycle.id, window_start, window_end),
        *_research_items_from_screener_results(session, cycle.id, window_start, window_end),
        *_research_items_from_publication_articles(session, cycle.id, window_start, window_end),
        *_research_items_from_aktienfinder_snapshots(session, cycle.id, window_start, window_end),
        *_research_items_from_musterdepot_transactions(session, cycle.id, window_start, window_end),
        *_research_items_from_technical_indicators(session, cycle.id, symbols, cycle.started_at),
        *_research_items_from_btc_dominance_snapshots(session, cycle.id, window_start, window_end),
        *_research_items_from_reddit_posts(session, cycle.id, window_start, window_end),
        *_research_items_from_aktienfinder_blog_posts(session, cycle.id, window_start, window_end),
    ]
    session.add_all(items)
    session.flush()
    return items


def _resolve_window_start(session: Session, cycle: Cycle) -> datetime.datetime:
    stmt = (
        select(Cycle)
        .where(Cycle.market_session == cycle.market_session, Cycle.started_at < cycle.started_at)
        .order_by(Cycle.started_at.desc())
        .limit(1)
    )
    previous_cycle = session.scalar(stmt)
    if previous_cycle is not None:
        return previous_cycle.started_at
    return cycle.started_at - _BOOTSTRAP_WINDOW


def _as_datetime(value: datetime.date | datetime.datetime) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        return value
    return datetime.datetime.combine(value, datetime.time.min)


def _research_items_from_edgar_filings(
    session: Session,
    cycle_id: uuid.UUID,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> list[ResearchItem]:
    stmt = select(EdgarFiling).where(
        EdgarFiling.synced_at > window_start, EdgarFiling.synced_at <= window_end
    )
    filings = session.scalars(stmt).all()
    return [
        ResearchItem(
            cycle_id=cycle_id,
            agent="news_research",
            source_type="edgar_filing",
            source_ref=filing.accession_number,
            url=filing.link,
            published_at=filing.filed_at,
            summary=f"{filing.form_type}-Filing von {filing.company_name}: {filing.title}",
            instruments=[],
            raw={"cik": filing.cik, "company_name": filing.company_name},
        )
        for filing in filings
    ]


def _research_items_from_screener_results(
    session: Session,
    cycle_id: uuid.UUID,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> list[ResearchItem]:
    stmt = select(ScreenerResult).where(
        ScreenerResult.synced_at > window_start, ScreenerResult.synced_at <= window_end
    )
    results = session.scalars(stmt).all()
    return [
        ResearchItem(
            cycle_id=cycle_id,
            agent="market_research",
            source_type="screener_result",
            source_ref=result.symbol,
            url=None,
            published_at=_as_datetime(result.screened_at),
            summary=(
                f"VULTURE-Screener-Kandidat: {result.symbol}, "
                f"Kurs {result.price}, Volumen {result.volume}"
            ),
            instruments=[result.symbol],
            raw={"price": str(result.price), "volume": str(result.volume)},
        )
        for result in results
    ]


def _research_items_from_publication_articles(
    session: Session,
    cycle_id: uuid.UUID,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> list[ResearchItem]:
    stmt = select(PublicationArticle).where(
        PublicationArticle.synced_at > window_start, PublicationArticle.synced_at <= window_end
    )
    articles = session.scalars(stmt).all()
    return [
        ResearchItem(
            cycle_id=cycle_id,
            agent="news_research",
            source_type="publication_article",
            source_ref=f"{article.publication}/{article.issue_date}/{article.seq}",
            url=None,
            published_at=_as_datetime(article.issue_date),
            summary=(
                f"{article.publication} ({article.issue_date}), S. {article.page}: {article.title}"
            ),
            instruments=[],
            raw={"publication": article.publication, "page": article.page},
        )
        for article in articles
    ]


def _research_items_from_aktienfinder_snapshots(
    session: Session,
    cycle_id: uuid.UUID,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> list[ResearchItem]:
    stmt = select(AktienfinderSnapshot).where(
        AktienfinderSnapshot.synced_at > window_start, AktienfinderSnapshot.synced_at <= window_end
    )
    snapshots = session.scalars(stmt).all()
    return [
        ResearchItem(
            cycle_id=cycle_id,
            agent="market_research",
            source_type="aktienfinder_snapshot",
            source_ref=f"{snapshot.symbol}/{snapshot.snapshot_date}",
            url=None,
            published_at=_as_datetime(snapshot.snapshot_date),
            summary=(
                f"aktienfinder-Snapshot {snapshot.symbol}: "
                f"Kurs {snapshot.fields.get('price')}, "
                f"Dividendenrendite {snapshot.fields.get('dividend_yield')}"
            ),
            instruments=[snapshot.symbol],
            raw={**snapshot.fields, "screenshot_path": snapshot.screenshot_path},
        )
        for snapshot in snapshots
    ]


def _research_items_from_musterdepot_transactions(
    session: Session,
    cycle_id: uuid.UUID,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> list[ResearchItem]:
    stmt = select(MusterdepotTransaction).where(
        MusterdepotTransaction.synced_at > window_start,
        MusterdepotTransaction.synced_at <= window_end,
    )
    transactions = session.scalars(stmt).all()
    return [
        ResearchItem(
            cycle_id=cycle_id,
            agent="news_research",
            source_type="musterdepot_transaction",
            source_ref=f"{tx.message_id}/{tx.seq}",
            url=None,
            published_at=tx.received_at,
            summary=(
                f"DER AKTIONÄR Musterdepot: {tx.action} {tx.instrument_name} "
                f"(WKN {tx.wkn}), {tx.quantity} Stück @ {tx.price} {tx.currency}"
            ),
            instruments=[tx.wkn],
            raw={
                "action": tx.action,
                "quantity": str(tx.quantity),
                "price": str(tx.price),
                "currency": tx.currency,
            },
        )
        for tx in transactions
    ]


def _research_items_from_technical_indicators(
    session: Session,
    cycle_id: uuid.UUID,
    symbols: list[str],
    as_of: datetime.datetime,
) -> list[ResearchItem]:
    """Unlike the 5 sources above, this isn't windowed by `synced_at` — an
    indicator value isn't a new external fact arriving, it's a fresh computation
    over already-ingested `market_bar` rows, recomputed every cycle for the
    current symbol universe (see F036 §2). A symbol with too few bars for any
    indicator yet is silently skipped, not an error."""
    items = []
    for symbol in symbols:
        snapshot = compute_indicator_snapshot(session, symbol)
        if _snapshot_is_empty(snapshot):
            continue
        items.append(
            ResearchItem(
                cycle_id=cycle_id,
                agent="market_research",
                source_type="technical_indicator",
                source_ref=symbol,
                url=None,
                published_at=as_of,
                summary=_format_indicator_summary(symbol, snapshot),
                instruments=[symbol],
                raw=_indicator_raw(snapshot),
            )
        )
    return items


def _snapshot_is_empty(snapshot: IndicatorSnapshot) -> bool:
    return (
        snapshot.sma20 is None
        and snapshot.sma50 is None
        and snapshot.rsi14 is None
        and snapshot.macd is None
        and snapshot.bollinger is None
        and snapshot.crossover is None
    )


def _format_indicator_summary(symbol: str, snapshot: IndicatorSnapshot) -> str:
    parts = [f"Technische Indikatoren {symbol}:"]
    if snapshot.sma20 is not None and snapshot.sma50 is not None:
        relation = "über" if snapshot.sma20 > snapshot.sma50 else "unter"
        parts.append(f"SMA20 {relation} SMA50 ({snapshot.sma20:.2f} vs {snapshot.sma50:.2f})")
    if snapshot.crossover is not None:
        label = "Golden Cross" if snapshot.crossover == "golden_cross" else "Death Cross"
        parts.append(f"frischer {label}")
    if snapshot.rsi14 is not None:
        parts.append(f"RSI14 {snapshot.rsi14:.1f}")
    if snapshot.macd is not None:
        parts.append(
            f"MACD {snapshot.macd.macd_line:.2f} (Signal {snapshot.macd.signal_line:.2f}, "
            f"Histogramm {snapshot.macd.histogram:.2f})"
        )
    if snapshot.bollinger is not None:
        parts.append(
            f"Bollinger-Baender [{snapshot.bollinger.lower:.2f}, {snapshot.bollinger.upper:.2f}]"
        )
    return ", ".join(parts)


def _indicator_raw(snapshot: IndicatorSnapshot) -> dict[str, object]:
    bollinger: BollingerBands | None = snapshot.bollinger
    return {
        "sma20": snapshot.sma20,
        "sma50": snapshot.sma50,
        "rsi14": snapshot.rsi14,
        "macd_line": snapshot.macd.macd_line if snapshot.macd else None,
        "macd_signal": snapshot.macd.signal_line if snapshot.macd else None,
        "macd_histogram": snapshot.macd.histogram if snapshot.macd else None,
        "bollinger_upper": bollinger.upper if bollinger else None,
        "bollinger_lower": bollinger.lower if bollinger else None,
        "crossover": snapshot.crossover,
    }


def _research_items_from_btc_dominance_snapshots(
    session: Session,
    cycle_id: uuid.UUID,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> list[ResearchItem]:
    stmt = select(BtcDominanceSnapshot).where(
        BtcDominanceSnapshot.synced_at > window_start,
        BtcDominanceSnapshot.synced_at <= window_end,
    )
    snapshots = session.scalars(stmt).all()
    return [
        ResearchItem(
            cycle_id=cycle_id,
            agent="market_research",
            source_type="btc_dominance",
            source_ref=str(snapshot.id),
            url=None,
            published_at=snapshot.snapshot_at,
            summary=(
                f"BTC-Dominanz: {snapshot.btc_dominance_pct}% "
                f"(Gesamt-Marktkapitalisierung {snapshot.total_market_cap_usd} USD)"
            ),
            instruments=["BTC/USD"],
            raw={
                "btc_dominance_pct": str(snapshot.btc_dominance_pct),
                "total_market_cap_usd": str(snapshot.total_market_cap_usd),
            },
        )
        for snapshot in snapshots
    ]


def _research_items_from_reddit_posts(
    session: Session,
    cycle_id: uuid.UUID,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> list[ResearchItem]:
    """No sentiment scoring here — raw title/score/comment-count facts only, the
    persona interprets them (same pattern as every other source, Invariant #9)."""
    stmt = select(RedditPost).where(
        RedditPost.synced_at > window_start, RedditPost.synced_at <= window_end
    )
    posts = session.scalars(stmt).all()
    return [
        ResearchItem(
            cycle_id=cycle_id,
            agent="news_research",
            source_type="reddit_post",
            source_ref=post.post_id,
            url=post.permalink,
            published_at=post.created_utc,
            summary=(
                f'r/{post.subreddit}: "{post.title}" '
                f"(Score {post.score}, {post.num_comments} Kommentare)"
            ),
            instruments=[],
            raw={"score": post.score, "num_comments": post.num_comments},
        )
        for post in posts
    ]


def _research_items_from_aktienfinder_blog_posts(
    session: Session,
    cycle_id: uuid.UUID,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> list[ResearchItem]:
    """Title/date/category/tags only — never the Premium article body (F041,
    no login used for this source, see aktienfinder_blog.py)."""
    stmt = select(AktienfinderBlogPost).where(
        AktienfinderBlogPost.synced_at > window_start,
        AktienfinderBlogPost.synced_at <= window_end,
    )
    posts = session.scalars(stmt).all()
    return [
        ResearchItem(
            cycle_id=cycle_id,
            agent="news_research",
            source_type="aktienfinder_blog",
            source_ref=post.post_id,
            url=post.url,
            published_at=_as_datetime(post.published_at),
            summary=(
                f"aktienfinder-Blog ({', '.join(post.categories)}"
                f"{', Premium' if post.is_premium else ', frei'}): {post.title}"
            ),
            instruments=[],
            raw={"categories": post.categories, "tags": post.tags, "is_premium": post.is_premium},
        )
        for post in posts
    ]
