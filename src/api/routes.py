"""Persona-facing read endpoints — portfolio snapshot (F007), profile/holdings/
transactions/decisions (F034). All read-only, no LLM, no broker access.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from collections.abc import Generator
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from src.api.schemas import (
    ChartBarOut,
    ChartFillMarkerOut,
    ChartLivePriceOut,
    DecisionExpectationOut,
    DecisionOut,
    DecisionOutcomeOut,
    DecisionReviewOut,
    HoldingChartOut,
    HoldingOut,
    ImpulseComparisonOut,
    ImpulseReactionOut,
    ImpulseSummaryOut,
    LeaderboardBenchmarkOut,
    LeaderboardOut,
    LeaderboardRowOut,
    PersonaProfileOut,
    PortfolioHistoryOut,
    PortfolioHistoryPointOut,
    PortfolioHistorySeriesOut,
    PortfolioSnapshotOut,
    PositionOut,
    ResearchRefOut,
    TransactionOut,
)
from src.broker.registry import build_market_data_provider, load_market_data_config
from src.db.base import get_session_factory
from src.db.models import (
    Cycle,
    Decision,
    DecisionAction,
    DecisionStatus,
    MarketBar,
    MarketBarTimeframe,
    OrderRecord,
    Persona,
    Portfolio,
    PortfolioMode,
    PortfolioSnapshot,
    PositionSnapshot,
    ResearchItem,
    Review,
)
from src.ingestion.market_data_sync import build_default_provider, sync_market_bars
from src.metrics.performance import (
    adjusted_return,
    daily_benchmark_values,
    daily_portfolio_values,
    daily_returns,
    max_drawdown,
    open_position_count,
    simple_return,
    slippage_malus_sum,
    sortino_ratio,
    trade_count,
)
from src.orchestrator.competition_config import load_competition_config
from src.orchestrator.persona_analysis import compute_age_days
from src.personas.charters import get_persona_profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Lazy: building the engine at import time requires DATABASE_URL to be set just to
# import this module (breaks test collection and any tooling that imports the app).
_session_factory: sessionmaker[Session] | None = None

_DEFAULT_DECISION_LIMIT = 50
_DECISION_FILTERS = frozenset({"all", "traded", "rejected", "hold"})
_DEFAULT_IMPULSE_LIMIT = 25


def _as_float(value: object) -> float | None:
    """`expected_outcome` is free-form JSONB written by the LLM path — a key can be
    missing, null, or (rarely) a string. None beats a 500 in a read-only journal."""
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def get_session() -> Generator[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = get_session_factory()
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


def _get_persona_and_portfolio(
    session: Session, name: str, mode: PortfolioMode
) -> tuple[Persona, Portfolio]:
    """`mode` selects the portfolio once paper and live run in parallel (Phase 6+);
    default is paper — the only mode that exists before then."""
    persona = session.scalar(select(Persona).where(Persona.name == name.upper()))
    if persona is None:
        raise HTTPException(status_code=404, detail=f"Unknown persona: {name!r}")

    portfolio = session.scalar(
        # F090: archived_at IS NULL — after a competition reset a persona has both an
        # archived pre-season portfolio and the active one in the same mode; the API
        # must resolve to the active one (and stay single-valued).
        select(Portfolio).where(
            Portfolio.persona_id == persona.id,
            Portfolio.mode == mode,
            Portfolio.archived_at.is_(None),
        )
    )
    if portfolio is None:
        raise HTTPException(
            status_code=404, detail=f"No {mode.value} portfolio for persona: {name!r}"
        )
    return persona, portfolio


@router.get("/personas/{name}/snapshot", response_model=PortfolioSnapshotOut)
def get_persona_snapshot(
    name: str,
    mode: PortfolioMode = PortfolioMode.PAPER,
    session: Session = Depends(get_session),
) -> PortfolioSnapshotOut:
    persona, portfolio = _get_persona_and_portfolio(session, name, mode)

    latest_snapshot = session.scalar(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.portfolio_id == portfolio.id)
        .order_by(PortfolioSnapshot.ts.desc())
        .limit(1)
    )
    if latest_snapshot is None:
        raise HTTPException(status_code=404, detail=f"No snapshot yet for persona: {name!r}")

    positions = session.scalars(
        select(PositionSnapshot).where(
            PositionSnapshot.portfolio_id == portfolio.id,
            PositionSnapshot.ts == latest_snapshot.ts,
        )
    ).all()

    return PortfolioSnapshotOut(
        persona=persona.name,
        mode=portfolio.mode.value,
        ts=latest_snapshot.ts,
        total_value=float(latest_snapshot.total_value),
        cash=float(latest_snapshot.cash),
        pnl_realized=float(latest_snapshot.pnl_realized),
        pnl_unrealized=float(latest_snapshot.pnl_unrealized),
        positions=[
            PositionOut(
                instrument=p.instrument,
                qty=float(p.qty),
                avg_price=float(p.avg_price),
                market_value=float(p.market_value),
                pnl_unrealized=float(p.pnl_unrealized),
            )
            for p in positions
        ],
    )


@router.get("/portfolios/history", response_model=PortfolioHistoryOut)
def get_portfolio_history(
    mode: PortfolioMode = PortfolioMode.PAPER,
    session: Session = Depends(get_session),
) -> PortfolioHistoryOut:
    """F100: snapshot time series of every active portfolio since the competition
    start date — the data behind the dashboard's history charts.

    `position_value` is derived here (Decimal arithmetic), not in the frontend:
    money math belongs in code (CLAUDE.md). Pre-season snapshots are excluded
    twice over — archived portfolios (F090) and the start-date cutoff (F081).
    """
    competition = load_competition_config()
    start_ts = datetime.datetime.combine(competition.start_date, datetime.time.min)

    rows = session.execute(
        select(
            Persona.name,
            PortfolioSnapshot.ts,
            PortfolioSnapshot.total_value,
            PortfolioSnapshot.cash,
        )
        .join(Portfolio, Portfolio.persona_id == Persona.id)
        .join(PortfolioSnapshot, PortfolioSnapshot.portfolio_id == Portfolio.id)
        .where(
            Portfolio.mode == mode,
            Portfolio.archived_at.is_(None),
            PortfolioSnapshot.ts >= start_ts,
        )
        .order_by(Persona.name, PortfolioSnapshot.ts)
    ).all()

    series: list[PortfolioHistorySeriesOut] = []
    for persona_name, ts, total_value, cash in rows:
        if not series or series[-1].persona != persona_name:
            series.append(
                PortfolioHistorySeriesOut(
                    persona=persona_name,
                    display_name=get_persona_profile(persona_name).display_name,
                    points=[],
                )
            )
        series[-1].points.append(
            PortfolioHistoryPointOut(
                ts=ts,
                total_value=float(total_value),
                position_value=float(total_value - cash),
                cash=float(cash),
            )
        )

    return PortfolioHistoryOut(
        start=competition.start_date,
        start_capital=float(competition.start_capital_usd),
        series=series,
    )


@router.get("/leaderboard", response_model=LeaderboardOut)
def get_leaderboard(
    mode: PortfolioMode = PortfolioMode.PAPER,
    sort: str = "raw",
    session: Session = Depends(get_session),
) -> LeaderboardOut:
    """F085: the competition standings — raw and slippage-adjusted, side by side.

    Every number comes from `src.metrics.performance` (F082/F083), never from the
    frontend and never from an LLM. `sort` is a server-side switch so the view
    stays a plain server-rendered page: the toggle is a link, not client state.
    """
    if sort not in ("raw", "adjusted"):
        raise HTTPException(status_code=422, detail="sort must be 'raw' or 'adjusted'")

    competition = load_competition_config()
    start_ts = datetime.datetime.combine(competition.start_date, datetime.time.min)
    start_capital = float(competition.start_capital_usd)

    portfolios = session.execute(
        select(Portfolio, Persona.name)
        .join(Persona, Portfolio.persona_id == Persona.id)
        .where(
            Persona.active.is_(True),
            Portfolio.mode == mode,
            Portfolio.archived_at.is_(None),
        )
        .order_by(Persona.name)
    ).all()

    rows: list[LeaderboardRowOut] = []
    trading_days = 0
    for portfolio, persona_name in portfolios:
        values = daily_portfolio_values(session, portfolio.id, start_ts)
        trading_days = max(trading_days, len(values))
        raw = simple_return([Decimal(str(start_capital)), *values])
        malus = slippage_malus_sum(session, portfolio.id, start_ts)
        rows.append(
            LeaderboardRowOut(
                rank=0,  # filled in after sorting
                persona=persona_name,
                display_name=get_persona_profile(persona_name).display_name,
                total_value=float(values[-1]) if values else start_capital,
                raw_return=raw,
                adjusted_return=adjusted_return(raw, malus, competition.start_capital_usd),
                slippage_malus_usd=float(malus) if malus is not None else None,
                sortino=sortino_ratio(daily_returns(values)),
                max_drawdown=max_drawdown(values),
                trade_count=trade_count(session, portfolio.id, start_ts),
                open_positions=open_position_count(session, portfolio.id),
                sparkline=[float(value) for value in values],
            )
        )

    key = (lambda row: row.raw_return) if sort == "raw" else (lambda row: row.adjusted_return)
    rows.sort(key=key, reverse=True)
    for index, row in enumerate(rows, start=1):
        row.rank = index

    benchmark_values = daily_benchmark_values(session, start_ts)
    benchmark = (
        LeaderboardBenchmarkOut(
            symbol=competition.benchmark_symbol,
            total_value=float(benchmark_values[-1]),
            raw_return=simple_return([Decimal(str(start_capital)), *benchmark_values]),
            sparkline=[float(value) for value in benchmark_values],
        )
        if benchmark_values
        else None
    )

    return LeaderboardOut(
        start=competition.start_date,
        start_capital=start_capital,
        sort=sort,
        has_reviews=any(row.slippage_malus_usd is not None for row in rows),
        trading_days=trading_days,
        rows=rows,
        benchmark=benchmark,
    )


def _decision_verdict(decision: Decision) -> str:
    if decision.action in (DecisionAction.BUY, DecisionAction.CLOSE):
        if decision.status in (DecisionStatus.RISK_REJECTED, DecisionStatus.HITL_REJECTED):
            return "rejected"
        return "traded"
    if decision.action == DecisionAction.REJECT_IDEA:
        return "rejected"
    return "hold"


@router.get("/research/impulses", response_model=list[ImpulseSummaryOut])
def get_impulses(
    limit: int = _DEFAULT_IMPULSE_LIMIT,
    session: Session = Depends(get_session),
) -> list[ImpulseSummaryOut]:
    """F087 entry point: research items at least one persona actually cited.

    The pool holds thousands of items per cycle; the ones nobody looked at have
    no comparison to show. Ordered by the citing cycle, newest first.
    """
    cited = (
        select(func.unnest(Decision.input_research_ids).label("item_id"), Decision.portfolio_id)
        .select_from(Decision)
        .subquery()
    )
    rows = session.execute(
        select(
            ResearchItem,
            Cycle.started_at,
            func.count(func.distinct(cited.c.portfolio_id)).label("citing_personas"),
        )
        .join(cited, cited.c.item_id == ResearchItem.id)
        .join(Cycle, Cycle.id == ResearchItem.cycle_id)
        .group_by(ResearchItem.id, Cycle.started_at)
        .order_by(Cycle.started_at.desc(), ResearchItem.id)
        .limit(limit)
    ).all()

    return [
        ImpulseSummaryOut(
            id=item.id,
            source_type=item.source_type,
            summary=item.summary,
            published_at=item.published_at,
            cycle_ts=cycle_ts,
            instruments=item.instruments,
            citing_personas=citing,
        )
        for item, cycle_ts, citing in rows
    ]


@router.get("/research/{item_id}/comparison", response_model=ImpulseComparisonOut)
def get_impulse_comparison(
    item_id: uuid.UUID,
    mode: PortfolioMode = PortfolioMode.PAPER,
    session: Session = Depends(get_session),
) -> ImpulseComparisonOut:
    """F087: one impulse, six persona views — what each made of it, and why.

    "Ignored" is a real answer and needs a real definition: the persona produced
    a decision in the cycle this item belongs to, but cited something else. A
    persona with no decision in that cycle at all (outage, paused) is reported as
    `no_run` instead — silently calling that "ignored" would blame a persona for
    an infrastructure gap (F101 U1: 13 cycles with no decisions at all).
    """
    item = session.get(ResearchItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Unknown research item: {item_id}")

    cycle = session.get_one(Cycle, item.cycle_id)

    portfolios = session.execute(
        select(Portfolio, Persona.name)
        .join(Persona, Portfolio.persona_id == Persona.id)
        .where(
            Persona.active.is_(True),
            Portfolio.mode == mode,
            Portfolio.archived_at.is_(None),
        )
        .order_by(Persona.name)
    ).all()

    # Decisions citing this item — possibly from a later cycle than the item's own
    # (the F045 search tool and F101 companions reach back).
    citing = {
        decision.portfolio_id: decision
        for decision in session.scalars(
            select(Decision).where(Decision.input_research_ids.contains([item_id]))
        ).all()
    }
    ran_that_cycle = set(
        session.scalars(
            select(Decision.portfolio_id).where(Decision.cycle_id == item.cycle_id).distinct()
        ).all()
    )

    reactions: list[ImpulseReactionOut] = []
    for portfolio, persona_name in portfolios:
        decision = citing.get(portfolio.id)
        if decision is None:
            verdict = "ignored" if portfolio.id in ran_that_cycle else "no_run"
            reactions.append(
                ImpulseReactionOut(
                    persona=persona_name,
                    display_name=get_persona_profile(persona_name).display_name,
                    verdict=verdict,
                    action=None,
                    status=None,
                    instrument=None,
                    thesis_text=None,
                    rejection_reason=None,
                    decision_id=None,
                )
            )
            continue
        reactions.append(
            ImpulseReactionOut(
                persona=persona_name,
                display_name=get_persona_profile(persona_name).display_name,
                verdict=_decision_verdict(decision),
                action=decision.action.value,
                status=decision.status.value,
                instrument=decision.instrument,
                thesis_text=decision.thesis_text,
                rejection_reason=decision.rejection_reason,
                decision_id=decision.id,
            )
        )

    return ImpulseComparisonOut(
        impulse=ImpulseSummaryOut(
            id=item.id,
            source_type=item.source_type,
            summary=item.summary,
            published_at=item.published_at,
            cycle_ts=cycle.started_at,
            instruments=item.instruments,
            citing_personas=len(citing),
        ),
        url=item.url,
        reactions=reactions,
    )


@router.get("/personas/{name}/profile", response_model=PersonaProfileOut)
def get_persona_profile_route(
    name: str, session: Session = Depends(get_session)
) -> PersonaProfileOut:
    persona = session.scalar(select(Persona).where(Persona.name == name.upper()))
    if persona is None:
        raise HTTPException(status_code=404, detail=f"Unknown persona: {name!r}")

    profile = get_persona_profile(persona.name)
    return PersonaProfileOut(
        name=profile.name,
        display_name=profile.display_name,
        philosophy=profile.philosophy,
        universe=profile.universe,
        signals=profile.signals,
        holding_period=profile.holding_period,
        failure_mode=profile.failure_mode,
    )


@router.get("/personas/{name}/holdings", response_model=list[HoldingOut])
def get_persona_holdings(
    name: str,
    mode: PortfolioMode = PortfolioMode.PAPER,
    session: Session = Depends(get_session),
) -> list[HoldingOut]:
    _persona, portfolio = _get_persona_and_portfolio(session, name, mode)

    latest_snapshot = session.scalar(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.portfolio_id == portfolio.id)
        .order_by(PortfolioSnapshot.ts.desc())
        .limit(1)
    )
    if latest_snapshot is None:
        return []

    positions = session.scalars(
        select(PositionSnapshot).where(
            PositionSnapshot.portfolio_id == portfolio.id,
            PositionSnapshot.ts == latest_snapshot.ts,
        )
    ).all()

    # Best-effort "when was this instrument last bought" — the most recent filled
    # BUY order per instrument. Positions are broker/ledger-computed averages, not
    # FIFO lots, so this is a reference date, not a per-lot purchase history.
    last_buy_rows = session.execute(
        select(Decision.instrument, func.max(OrderRecord.filled_at))
        .join(OrderRecord, OrderRecord.decision_id == Decision.id)
        .where(
            Decision.portfolio_id == portfolio.id,
            Decision.action == DecisionAction.BUY,
            OrderRecord.filled_at.isnot(None),
        )
        .group_by(Decision.instrument)
    ).all()
    last_buys: dict[str, datetime.datetime | None] = {
        instrument: filled_at for instrument, filled_at in last_buy_rows
    }

    holdings = []
    for p in positions:
        qty = float(p.qty)
        avg_price = float(p.avg_price)
        market_value = float(p.market_value)
        pnl_unrealized = float(p.pnl_unrealized)
        cost_basis = avg_price * qty
        holdings.append(
            HoldingOut(
                instrument=p.instrument,
                qty=qty,
                avg_price=avg_price,
                current_price=market_value / qty if qty else avg_price,
                market_value=market_value,
                pnl_unrealized=pnl_unrealized,
                pnl_unrealized_pct=(pnl_unrealized / cost_basis * 100) if cost_basis else 0.0,
                last_buy_at=last_buys.get(p.instrument),
            )
        )
    return holdings


@router.get("/personas/{name}/chart", response_model=HoldingChartOut)
def get_persona_holding_chart(
    name: str,
    instrument: str,
    mode: PortfolioMode = PortfolioMode.PAPER,
    session: Session = Depends(get_session),
) -> HoldingChartOut:
    """F074: price-chart data for one current holding — daily closes from 2 days
    before the first fill to today (`market_bar`), every filled buy/sell marked,
    plus a best-effort live quote. `instrument` is a query param, not a path
    segment, because crypto symbols contain "/" (e.g. "BTC/USD"), which would
    break path routing.
    """
    _persona, portfolio = _get_persona_and_portfolio(session, name, mode)

    latest_snapshot = session.scalar(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.portfolio_id == portfolio.id)
        .order_by(PortfolioSnapshot.ts.desc())
        .limit(1)
    )
    is_current_holding = latest_snapshot is not None and (
        session.scalar(
            select(PositionSnapshot.id).where(
                PositionSnapshot.portfolio_id == portfolio.id,
                PositionSnapshot.ts == latest_snapshot.ts,
                PositionSnapshot.instrument == instrument,
            )
        )
        is not None
    )
    if not is_current_holding:
        raise HTTPException(
            status_code=404,
            detail=f"{instrument!r} is not a current holding of {name!r}",
        )

    fill_rows = session.execute(
        select(OrderRecord.filled_at, OrderRecord.fill_price, Decision.quantity, Decision.action)
        .join(Decision, OrderRecord.decision_id == Decision.id)
        .where(
            Decision.portfolio_id == portfolio.id,
            Decision.instrument == instrument,
            OrderRecord.filled_at.isnot(None),
            OrderRecord.fill_price.isnot(None),
            Decision.quantity.isnot(None),
        )
        .order_by(OrderRecord.filled_at.asc())
    ).all()

    if fill_rows:
        first_fill_at = min(filled_at for filled_at, _, _, _ in fill_rows)
        chart_start = first_fill_at.date() - datetime.timedelta(days=2)
    else:
        # F074: demo/seed positions (scripts/seed_demo_snapshot.py) have no backing
        # OrderRecord — fall back to a fixed recent window instead of erroring.
        chart_start = datetime.date.today() - datetime.timedelta(days=30)

    fills = [
        ChartFillMarkerOut(
            ts=filled_at,
            price=float(fill_price),
            qty=float(qty),
            action="buy" if action == DecisionAction.BUY else "sell",
        )
        for filled_at, fill_price, qty, action in fill_rows
    ]

    bars = _read_market_bars(session, instrument, chart_start)
    if not bars or bars[0].ts.date() > chart_start:
        _try_backfill(session, instrument, chart_start)
        bars = _read_market_bars(session, instrument, chart_start)

    return HoldingChartOut(
        instrument=instrument,
        start=chart_start,
        bars=[ChartBarOut(ts=bar.ts.date(), close=float(bar.close)) for bar in bars],
        fills=fills,
        live_price=_try_live_price(instrument),
    )


def _read_market_bars(
    session: Session, instrument: str, chart_start: datetime.date
) -> list[MarketBar]:
    return list(
        session.scalars(
            select(MarketBar)
            .where(
                MarketBar.symbol == instrument,
                MarketBar.timeframe == MarketBarTimeframe.DAY,
                MarketBar.ts >= datetime.datetime.combine(chart_start, datetime.time.min),
            )
            .order_by(MarketBar.ts.asc())
        ).all()
    )


def _try_backfill(session: Session, instrument: str, chart_start: datetime.date) -> None:
    """Best-effort: a symbol only just added to the watchlist on its purchase day
    won't have bars for the 2 days before yet. Stock-only — crypto symbols contain
    "/" and need a different Alpaca data client; F064's crypto watchlist already
    includes open positions, so this gap is not expected to matter in practice.
    Swallows failures: an Alpaca outage must degrade to an incomplete chart, not a
    500 on the whole holdings page (this endpoint is otherwise a pure DB read, like
    the rest of this module)."""
    if "/" in instrument:
        return
    try:
        provider = build_default_provider()
        sync_market_bars(session, provider, [instrument], chart_start, datetime.date.today())
    except Exception:
        logger.exception("F074: on-demand market_bar backfill failed for %s", instrument)


def _try_live_price(instrument: str) -> ChartLivePriceOut | None:
    try:
        market = "crypto" if "/" in instrument else "stock"
        provider = build_market_data_provider(market, load_market_data_config())
        price = provider.get_last_price(instrument)
    except Exception:
        logger.exception("F074: live price fetch failed for %s", instrument)
        return None
    return ChartLivePriceOut(
        ts=datetime.datetime.now(datetime.UTC).replace(tzinfo=None), price=price
    )


@router.get("/personas/{name}/transactions", response_model=list[TransactionOut])
def get_persona_transactions(
    name: str,
    mode: PortfolioMode = PortfolioMode.PAPER,
    session: Session = Depends(get_session),
) -> list[TransactionOut]:
    _persona, portfolio = _get_persona_and_portfolio(session, name, mode)

    rows = session.execute(
        select(OrderRecord, Decision)
        .join(Decision, OrderRecord.decision_id == Decision.id)
        .where(Decision.portfolio_id == portfolio.id)
        .order_by(OrderRecord.submitted_at.desc())
    ).all()

    return [
        TransactionOut(
            decision_id=decision.id,
            instrument=decision.instrument,
            action=decision.action.value,
            quantity=float(decision.quantity) if decision.quantity is not None else None,
            submitted_at=order.submitted_at,
            filled_at=order.filled_at,
            fill_price=float(order.fill_price) if order.fill_price is not None else None,
            status=order.status.value,
            thesis_text=decision.thesis_text,
        )
        for order, decision in rows
    ]


@router.get("/personas/{name}/decisions", response_model=list[DecisionOut])
def get_persona_decisions(
    name: str,
    mode: PortfolioMode = PortfolioMode.PAPER,
    limit: int = _DEFAULT_DECISION_LIMIT,
    filter: str = "all",
    session: Session = Depends(get_session),
) -> list[DecisionOut]:
    """The decision journal (F086): every decision (buy/hold/reject_idea, any
    status) with the research items it actually cited — each tagged with the same
    age-at-decision-time signal the persona itself saw (F033) — plus what the
    persona expected, what the broker actually did, and the review's verdict.

    `filter` narrows by outcome: `traded` (an order was attempted), `rejected`
    (the idea died — `reject_idea` or a gate/HITL refusal), `hold` (no action at
    all). Filtering server-side keeps the journal a plain server component and
    keeps `limit` meaningful — a client-side filter over the newest 50 rows would
    show 3 trades out of 50 holds and call it a journal.
    """
    if filter not in _DECISION_FILTERS:
        raise HTTPException(
            status_code=422, detail=f"filter must be one of {sorted(_DECISION_FILTERS)}"
        )
    _persona, portfolio = _get_persona_and_portfolio(session, name, mode)

    stmt = (
        select(Decision, Cycle)
        .join(Cycle, Decision.cycle_id == Cycle.id)
        .where(Decision.portfolio_id == portfolio.id)
    )
    if filter == "traded":
        stmt = stmt.where(Decision.action.in_((DecisionAction.BUY, DecisionAction.CLOSE)))
    elif filter == "rejected":
        stmt = stmt.where(
            or_(
                Decision.action == DecisionAction.REJECT_IDEA,
                Decision.status.in_((DecisionStatus.RISK_REJECTED, DecisionStatus.HITL_REJECTED)),
            )
        )
    elif filter == "hold":
        stmt = stmt.where(Decision.action == DecisionAction.HOLD)

    rows = session.execute(stmt.order_by(Cycle.started_at.desc()).limit(limit)).all()

    out = []
    for decision, cycle in rows:
        research_items = session.scalars(
            select(ResearchItem)
            .where(ResearchItem.id.in_(decision.input_research_ids))
            .order_by(ResearchItem.published_at.desc())
        ).all()
        order = session.scalar(
            select(OrderRecord)
            .where(OrderRecord.decision_id == decision.id)
            .order_by(OrderRecord.submitted_at.desc())
            .limit(1)
        )
        review = session.scalar(select(Review).where(Review.decision_id == decision.id))
        expected = decision.expected_outcome
        out.append(
            DecisionOut(
                id=decision.id,
                ts=cycle.started_at,
                instrument=decision.instrument,
                action=decision.action.value,
                status=decision.status.value,
                conviction=expected.get("conviction"),
                thesis_text=decision.thesis_text,
                rejection_reason=decision.rejection_reason,
                expected=DecisionExpectationOut(
                    entry_price=_as_float(expected.get("entry_price")),
                    stop_loss_price=_as_float(expected.get("stop_loss_price")),
                    target_price=_as_float(expected.get("target_price")),
                    horizon_days=_as_float(expected.get("horizon_days")),
                ),
                outcome=None
                if order is None
                else DecisionOutcomeOut(
                    order_status=order.status.value,
                    quantity=float(decision.quantity) if decision.quantity is not None else None,
                    fill_price=float(order.fill_price) if order.fill_price is not None else None,
                    filled_at=order.filled_at,
                ),
                review=None
                if review is None
                else DecisionReviewOut(
                    verdict=review.verdict.value,
                    reviewed_at=review.reviewed_at,
                    deviation=float(review.deviation) if review.deviation is not None else None,
                    slippage_malus=float(review.slippage_malus)
                    if review.slippage_malus is not None
                    else None,
                    lessons_text=review.lessons_text,
                ),
                research_items=[
                    ResearchRefOut(
                        id=item.id,
                        source_type=item.source_type,
                        summary=item.summary,
                        published_at=item.published_at,
                        age_days=compute_age_days(item.published_at, cycle.started_at),
                        url=item.url,
                    )
                    for item in research_items
                ],
            )
        )
    return out
