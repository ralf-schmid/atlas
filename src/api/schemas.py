"""Pydantic response models for the FastAPI layer. See F007, F034."""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel


class PositionOut(BaseModel):
    instrument: str
    qty: float
    avg_price: float
    market_value: float
    pnl_unrealized: float


class PortfolioSnapshotOut(BaseModel):
    persona: str
    mode: str  # "paper" | "live"
    ts: datetime.datetime
    total_value: float
    cash: float
    pnl_realized: float
    pnl_unrealized: float
    positions: list[PositionOut]


class PortfolioHistoryPointOut(BaseModel):
    ts: datetime.datetime
    total_value: float  # cash + positions (broker equity)
    position_value: float  # total_value - cash, computed server-side (F100)
    cash: float


class PortfolioHistorySeriesOut(BaseModel):
    persona: str
    display_name: str
    points: list[PortfolioHistoryPointOut]


class PortfolioHistoryOut(BaseModel):
    start: datetime.date
    start_capital: float
    series: list[PortfolioHistorySeriesOut]


class LeaderboardRowOut(BaseModel):
    rank: int
    persona: str
    display_name: str
    total_value: float
    raw_return: float
    adjusted_return: float
    slippage_malus_usd: float | None  # None = no review with a malus yet (F083/F084)
    # F112: how many trades the malus above actually covers. Less than `trade_count`
    # means the adjusted return is optimistic — only reviewed trades carry friction.
    malus_trade_count: int
    sortino: float | None  # None until 20 daily returns exist (F082)
    max_drawdown: float
    trade_count: int
    open_positions: int
    sparkline: list[float]


class LeaderboardBenchmarkOut(BaseModel):
    symbol: str
    total_value: float
    raw_return: float
    sparkline: list[float]


class LeaderboardOut(BaseModel):
    start: datetime.date
    start_capital: float
    sort: str  # "raw" | "adjusted"
    has_reviews: bool
    trading_days: int
    rows: list[LeaderboardRowOut]
    benchmark: LeaderboardBenchmarkOut | None


class PersonaProfileOut(BaseModel):
    name: str
    display_name: str
    philosophy: str
    universe: str
    signals: str
    holding_period: str
    failure_mode: str


class HoldingOut(BaseModel):
    instrument: str
    qty: float
    avg_price: float
    current_price: float
    market_value: float
    pnl_unrealized: float
    pnl_unrealized_pct: float
    last_buy_at: datetime.datetime | None


class ChartBarOut(BaseModel):
    ts: datetime.date
    close: float


class ChartFillMarkerOut(BaseModel):
    ts: datetime.datetime
    price: float
    qty: float
    action: str  # "buy" | "sell"


class ChartLivePriceOut(BaseModel):
    ts: datetime.datetime
    price: float


class HoldingChartOut(BaseModel):
    instrument: str
    start: datetime.date
    bars: list[ChartBarOut]
    fills: list[ChartFillMarkerOut]
    live_price: ChartLivePriceOut | None


class TransactionOut(BaseModel):
    decision_id: uuid.UUID
    instrument: str
    action: str
    quantity: float | None
    submitted_at: datetime.datetime
    filled_at: datetime.datetime | None
    fill_price: float | None
    status: str
    thesis_text: str


class ResearchRefOut(BaseModel):
    id: uuid.UUID
    source_type: str
    summary: str
    published_at: datetime.datetime | None
    age_days: float | None
    url: str | None


class CycleSummaryOut(BaseModel):
    """One line per orchestrator run for the trace list (F088)."""

    id: uuid.UUID
    trading_day: datetime.date
    seq: int
    market_session: str
    started_at: datetime.datetime
    research_items: int
    decisions: int
    agent_runs: int
    failed_runs: int
    tokens_in: int
    tokens_out: int
    cost_usd: float


class AgentRunOut(BaseModel):
    agent: str
    persona: str | None
    status: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    error: str | None


class HitlEventOut(BaseModel):
    decision_id: uuid.UUID
    persona: str
    instrument: str
    status: str
    amount_usd: float | None
    requested_at: datetime.datetime | None
    decided_at: datetime.datetime | None
    decided_by: str | None


class CycleTraceOut(BaseModel):
    cycle: CycleSummaryOut
    runs: list[AgentRunOut]
    hitl_events: list[HitlEventOut]
    decisions_by_status: dict[str, int]


class ImpulseSummaryOut(BaseModel):
    """One entry in the impulse picker (F087) — a research item at least one
    persona actually cited."""

    id: uuid.UUID
    source_type: str
    summary: str
    published_at: datetime.datetime | None
    cycle_ts: datetime.datetime
    instruments: list[str]
    citing_personas: int


class ImpulseReactionOut(BaseModel):
    """What one persona made of the impulse.

    `verdict` is derived, not stored: `traded` | `rejected` | `hold` (the persona
    cited it) | `ignored` (it ran that cycle and cited something else) |
    `no_run` (it produced no decision in that cycle at all).
    """

    persona: str
    display_name: str
    verdict: str
    action: str | None
    status: str | None
    instrument: str | None
    thesis_text: str | None
    rejection_reason: str | None
    decision_id: uuid.UUID | None


class ImpulseComparisonOut(BaseModel):
    impulse: ImpulseSummaryOut
    url: str | None
    reactions: list[ImpulseReactionOut]


class DecisionExpectationOut(BaseModel):
    """What the persona said would happen — straight from `expected_outcome`."""

    entry_price: float | None
    stop_loss_price: float | None
    target_price: float | None
    horizon_days: float | None


class DecisionOutcomeOut(BaseModel):
    """What actually happened at the broker."""

    order_status: str
    quantity: float | None
    fill_price: float | None
    filled_at: datetime.datetime | None


class DecisionReviewOut(BaseModel):
    """F084's verdict on the decision, once the review agent has looked at it."""

    verdict: str
    reviewed_at: datetime.datetime
    deviation: float | None
    slippage_malus: float | None
    lessons_text: str | None


class DecisionOut(BaseModel):
    id: uuid.UUID
    ts: datetime.datetime
    instrument: str
    action: str
    status: str
    conviction: float | None
    thesis_text: str
    rejection_reason: str | None
    research_items: list[ResearchRefOut]
    expected: DecisionExpectationOut
    outcome: DecisionOutcomeOut | None
    review: DecisionReviewOut | None
