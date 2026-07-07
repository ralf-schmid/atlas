"""Turns new rows in the five research-bearing ingestion tables (F009-F012, F014)
into `research_item` rows for the shared research pool. See
docs/features/F017-shared-research-synthesis.md.

`market_bar` is deliberately excluded — raw OHLCV bars are base market data for later
technical-indicator computation, not a research finding (see F017 §1 Non-Scope).

Deliberately no LLM calls: every `summary` is a deterministic text template built from
fields the ingestion pipelines already parsed out.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import (
    AktienfinderSnapshot,
    Cycle,
    EdgarFiling,
    MusterdepotTransaction,
    PublicationArticle,
    ResearchItem,
    ScreenerResult,
)

_BOOTSTRAP_WINDOW = datetime.timedelta(days=7)


def synthesize_research_items(session: Session, cycle: Cycle) -> list[ResearchItem]:
    window_start = _resolve_window_start(session, cycle)
    window_end = cycle.started_at

    items = [
        *_research_items_from_edgar_filings(session, cycle.id, window_start, window_end),
        *_research_items_from_screener_results(session, cycle.id, window_start, window_end),
        *_research_items_from_publication_articles(session, cycle.id, window_start, window_end),
        *_research_items_from_aktienfinder_snapshots(session, cycle.id, window_start, window_end),
        *_research_items_from_musterdepot_transactions(session, cycle.id, window_start, window_end),
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
