"""BrokerAdapter protocol — the only interface agents/UI code may use to reach a broker.

See ARCHITECTURE.md §3.1/§9 and docs/features/F001-broker-adapter.md.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class OrderResult:
    entry_order_id: str
    stop_order_id: str
    symbol: str
    qty: float
    side: OrderSide
    stop_loss_price: float
    # F075: set only by adapters that know the fill synchronously at placement
    # time (InternalLedgerAdapter — no real broker to confirm asynchronously).
    # AlpacaPaperAdapter leaves both None; its fills are confirmed later by
    # `get_order_status()` polling (see src/orchestrator/scheduler.py
    # `reconcile_order_fills`), never known at submit time.
    filled_at: datetime.datetime | None = None
    fill_price: float | None = None


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    qty: float
    side: OrderSide
    avg_entry_price: float
    market_value: float
    unrealized_pl: float


@dataclass(frozen=True, slots=True)
class AccountBalance:
    cash: float
    equity: float
    buying_power: float


class BrokerAdapter(Protocol):
    """Broker I/O only. No risk decisions, no persistence — see F001 §2."""

    def place_order(
        self,
        *,
        decision_id: int,
        symbol: str,
        qty: float,
        side: OrderSide,
        stop_loss_price: float,
    ) -> OrderResult:
        """Place a market entry order plus a mandatory GTC stop-loss order.

        `decision_id` and `stop_loss_price` are mandatory (Invariants #3 and #4) —
        there is no code path that places an order without a decision reference or
        without a broker-side stop-loss.
        """
        ...

    def cancel_order(self, order_id: str) -> None: ...

    def get_positions(self) -> list[Position]: ...

    def get_account_balance(self) -> AccountBalance: ...
