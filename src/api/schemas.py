"""Pydantic response models for the FastAPI layer. See F007."""

from __future__ import annotations

import datetime

from pydantic import BaseModel


class PositionOut(BaseModel):
    instrument: str
    qty: float
    avg_price: float
    market_value: float
    pnl_unrealized: float


class PortfolioSnapshotOut(BaseModel):
    persona: str
    ts: datetime.datetime
    total_value: float
    cash: float
    pnl_realized: float
    pnl_unrealized: float
    positions: list[PositionOut]
