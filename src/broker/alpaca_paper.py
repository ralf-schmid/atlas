"""AlpacaPaperAdapter — BrokerAdapter implementation for native Alpaca paper accounts.

Used by the native personas (VULTURE, GUARDIAN, CHARTIST) per
docs/adr/0001-alpaca-paper-account-limit.md. Always talks to Alpaca's paper
endpoint (Invariant #5) — there is no live code path here.
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass
from enum import StrEnum

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, TimeInForce
from alpaca.trading.enums import OrderSide as AlpacaOrderSide
from alpaca.trading.enums import OrderStatus as AlpacaOrderStatus
from alpaca.trading.models import Order as AlpacaOrder
from alpaca.trading.models import Position as AlpacaPosition
from alpaca.trading.models import TradeAccount
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest

from src.broker.protocol import (
    AccountBalance,
    ClosePositionResult,
    OrderResult,
    OrderSide,
    Position,
)

_TO_ALPACA_SIDE = {
    OrderSide.BUY: AlpacaOrderSide.BUY,
    OrderSide.SELL: AlpacaOrderSide.SELL,
}


class AlpacaOrderState(StrEnum):
    """F075: broker-native fill state, kept out of `BrokerAdapter`'s shared
    Protocol (`InternalLedgerAdapter` never has an open/pending order — fills
    happen synchronously at `place_order()` time, see `OrderResult.filled_at`)
    — same "concrete-type, not uniform Protocol method" precedent as
    `persona_analysis._sweep_stop_orders`, which also only means something for
    one adapter."""

    OPEN = "open"  # still pending at Alpaca — no actionable change yet
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class AlpacaFillStatus:
    state: AlpacaOrderState
    filled_at: datetime.datetime | None
    fill_price: float | None


_TERMINAL_STATE_MAP = {
    AlpacaOrderStatus.FILLED: AlpacaOrderState.FILLED,
    AlpacaOrderStatus.PARTIALLY_FILLED: AlpacaOrderState.PARTIALLY_FILLED,
    AlpacaOrderStatus.CANCELED: AlpacaOrderState.CANCELED,
    AlpacaOrderStatus.REJECTED: AlpacaOrderState.REJECTED,
    AlpacaOrderStatus.EXPIRED: AlpacaOrderState.EXPIRED,
}

# F077 live-finding (2026-07-19, real Alpaca Paper): cancel_order_by_id returning
# without an error only *requests* cancellation — Alpaca resolves it asynchronously
# (observed: a stop-loss leg stuck in PENDING_CANCEL for 30s+ with the US market
# closed). A sell submitted right after the cancel call fails with "insufficient
# qty available" because the qty is still `held_for_orders` by the not-yet-resolved
# stop. These are the terminal states that release that hold.
_HOLD_RELEASED_STATES = {
    AlpacaOrderStatus.CANCELED,
    AlpacaOrderStatus.EXPIRED,
    AlpacaOrderStatus.REJECTED,
    AlpacaOrderStatus.FILLED,
}
_CANCEL_POLL_INTERVAL_S = 2.0
_CANCEL_POLL_TIMEOUT_S = 30.0


def _is_duplicate_client_order_id(exc: APIError) -> bool:
    """Narrow match on purpose: other 422s (e.g. insufficient buying power) must
    still propagate as real errors, not be mistaken for a crash-replay recovery.

    Real Alpaca Paper response (confirmed via the CI integration test, F027):
    `{"code":40010001,"message":"client_order_id must be unique"}` — underscore,
    not the "client order id" wording originally guessed here.
    """
    try:
        return exc.status_code == 422 and "client_order_id" in exc.message.lower()
    except Exception:
        return False


class AlpacaPaperAdapter:
    """BrokerAdapter for a single native Alpaca paper account."""

    def __init__(self, api_key: str, secret_key: str) -> None:
        self._client = TradingClient(api_key, secret_key, paper=True)

    def place_order(
        self,
        *,
        decision_id: int,
        symbol: str,
        qty: float,
        side: OrderSide,
        stop_loss_price: float,
    ) -> OrderResult:
        # client_order_id = decision_id (F027, security-audit P2): a LangGraph replay
        # after a crash between this call and the DB commit resubmits with the same
        # id, which Alpaca rejects as a duplicate — recovered below instead of placing
        # a second real order.
        client_order_id = str(decision_id)

        # Alpaca rejects bracket/OTO orders outright for a fractional qty
        # (`422 "fractional orders must be simple orders"`, live-confirmed
        # 2026-07-10, F052) — not just a stricter time-in-force, no attached stop
        # leg is possible at all. This system's position sizing (amount_usd /
        # entry_price) produces a fractional qty for essentially every real
        # decision, so every native-adapter buy order needs whole-share rounding
        # here to keep its mandatory GTC stop (Invariant #4). Ralf's explicit
        # choice (2026-07-10) over submitting the stop as a separate order after
        # a polled fill, which would need fill-reconciliation infra (F023 §1
        # non-scope) and leaves a window with no broker-side stop.
        rounded_qty = round(qty)
        if rounded_qty == 0:
            raise ValueError(
                f"Position size {qty} {symbol} rounds to 0 whole shares — Alpaca "
                "requires an integer qty for a stop-protected bracket order, cannot "
                "place a stop-loss-compliant order this small"
            )

        # Bracket order, not two separate submit_order calls: submitting the GTC stop
        # as its own order immediately after the entry gets rejected by Alpaca as a
        # "potential wash trade" whenever the entry hasn't filled yet (e.g. market
        # closed) — found by the real integration test against Alpaca Paper. A bracket
        # order attaches the stop as a child leg that Alpaca itself only activates once
        # the entry fills, which is also a closer match to Invariant #4 (a stop only
        # makes sense once the position exists).
        try:
            entry = self._client.submit_order(
                order_data=MarketOrderRequest(
                    symbol=symbol,
                    qty=rounded_qty,
                    side=_TO_ALPACA_SIDE[side],
                    time_in_force=TimeInForce.GTC,
                    order_class=OrderClass.OTO,  # one-triggers-other: stop only, no take_profit
                    stop_loss=StopLossRequest(stop_price=stop_loss_price),
                    client_order_id=client_order_id,
                )
            )
        except APIError as exc:
            if not _is_duplicate_client_order_id(exc):
                raise
            entry = self._client.get_order_by_client_id(client_order_id)
        # Real exceptions, not asserts: this is the money path, and asserts are
        # stripped under `python -O`. Invariant #4 depends on the stop leg existing.
        if not isinstance(entry, AlpacaOrder):
            raise TypeError(f"Unexpected submit_order response type: {type(entry)!r}")
        if entry.legs is None or len(entry.legs) != 1:
            raise RuntimeError(
                f"OTO order {entry.id} came back without exactly one stop leg: {entry.legs!r}"
            )
        stop_leg = entry.legs[0]
        return OrderResult(
            entry_order_id=str(entry.id),
            stop_order_id=str(stop_leg.id),
            symbol=symbol,
            qty=rounded_qty,
            side=side,
            stop_loss_price=stop_loss_price,
        )

    def close_position(
        self,
        *,
        decision_id: int,
        symbol: str,
        qty: float,
        stop_order_ids: list[str],
    ) -> ClosePositionResult:
        # F077 §2: best-effort — a stop already filled/canceled between the
        # persona's decision and this execution is not an error, just nothing left
        # to cancel. Only ids Alpaca actually accepted a cancel request for need
        # the wait below — one that errored (already filled/gone) is already in a
        # terminal state, that's *why* the cancel call failed.
        accepted_cancels = []
        for stop_order_id in stop_order_ids:
            try:
                self._client.cancel_order_by_id(stop_order_id)
            except APIError:
                continue
            accepted_cancels.append(stop_order_id)

        for stop_order_id in accepted_cancels:
            self._wait_for_hold_release(stop_order_id)

        client_order_id = str(decision_id)
        try:
            order = self._client.submit_order(
                order_data=MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=AlpacaOrderSide.SELL,
                    # F051: fractional qty needs DAY, not GTC — no bracket/stop leg
                    # here anyway (this is a full close, no new stop, see F077 §1).
                    time_in_force=TimeInForce.DAY,
                    client_order_id=client_order_id,
                )
            )
        except APIError as exc:
            if not _is_duplicate_client_order_id(exc):
                raise
            order = self._client.get_order_by_client_id(client_order_id)
        if not isinstance(order, AlpacaOrder):
            raise TypeError(f"Unexpected submit_order response type: {type(order)!r}")

        return ClosePositionResult(
            order_id=str(order.id), symbol=symbol, qty=qty, side=OrderSide.SELL
        )

    def _wait_for_hold_release(self, order_id: str) -> None:
        """F077 live-finding (2026-07-19): poll until Alpaca actually resolves the
        cancellation (releases the qty it was `held_for_orders`), instead of
        assuming a successful `cancel_order_by_id` call takes effect immediately.
        Raises rather than let the following sell fail with a cryptic
        "insufficient qty available" — a stuck cancel is real, actionable
        information (e.g. the market being closed), not something to silently
        retry into a broken order."""
        deadline = time.monotonic() + _CANCEL_POLL_TIMEOUT_S
        while True:
            order = self._client.get_order_by_id(order_id)
            if not isinstance(order, AlpacaOrder):
                raise TypeError(f"Unexpected get_order_by_id response type: {type(order)!r}")
            if order.status in _HOLD_RELEASED_STATES:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Stop order {order_id} did not resolve within "
                    f"{_CANCEL_POLL_TIMEOUT_S}s of being canceled (still "
                    f"{order.status!r}) — refusing to sell while its qty hold may "
                    "still be active"
                )
            time.sleep(_CANCEL_POLL_INTERVAL_S)

    def cancel_order(self, order_id: str) -> None:
        self._client.cancel_order_by_id(order_id)

    def get_order_status(self, order_id: str) -> AlpacaFillStatus:
        """F075: polled by `src.orchestrator.scheduler.reconcile_order_fills` for
        every `order_record` still `NEW` — Alpaca confirms fills asynchronously,
        never at `place_order()` submission time (unlike `InternalLedgerAdapter`,
        see `OrderResult.filled_at`)."""
        order = self._client.get_order_by_id(order_id)
        assert isinstance(order, AlpacaOrder)
        state = _TERMINAL_STATE_MAP.get(order.status, AlpacaOrderState.OPEN)
        filled_at = order.filled_at.replace(tzinfo=None) if order.filled_at is not None else None
        fill_price = float(order.filled_avg_price) if order.filled_avg_price is not None else None
        return AlpacaFillStatus(state=state, filled_at=filled_at, fill_price=fill_price)

    def get_positions(self) -> list[Position]:
        positions = self._client.get_all_positions()
        result = []
        for p in positions:
            assert isinstance(p, AlpacaPosition)
            result.append(
                Position(
                    symbol=p.symbol,
                    qty=float(p.qty),
                    side=OrderSide.BUY if p.side.value == "long" else OrderSide.SELL,
                    avg_entry_price=float(p.avg_entry_price),
                    market_value=float(p.market_value or 0),
                    unrealized_pl=float(p.unrealized_pl or 0),
                )
            )
        return result

    def get_account_balance(self) -> AccountBalance:
        account = self._client.get_account()
        assert isinstance(account, TradeAccount)
        return AccountBalance(
            cash=float(account.cash or 0),
            equity=float(account.equity or 0),
            buying_power=float(account.buying_power or 0),
        )
