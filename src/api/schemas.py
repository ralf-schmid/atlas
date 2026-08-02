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
