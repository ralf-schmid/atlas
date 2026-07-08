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
