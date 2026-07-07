"""InternalLedgerAdapter — BrokerAdapter fallback for virtual personas.

Used by HYPE, CONTRA, CRYPTOR per docs/adr/0001-alpaca-paper-account-limit.md.
No broker involved: cash/positions are booked locally, fills happen instantly at
the current market price (mirrors Alpaca Paper's own simplistic fill behaviour,
see docs/features/F002-internal-ledger-adapter.md §2 for the fairness rationale).

Long-only (no shorting, no margin) — consistent with the "Shorting Enabled = off"
/ "Max Margin Multiplier = 1" settings applied to the native accounts.
"""

from __future__ import annotations

import uuid

from src.broker.ledger_store import (
    ExecutedOrder,
    LedgerState,
    LedgerStore,
    PendingStop,
    PositionState,
)
from src.broker.market_data import MarketDataProvider
from src.broker.protocol import AccountBalance, OrderResult, OrderSide, Position

_OPPOSITE_SIDE = {OrderSide.BUY: OrderSide.SELL, OrderSide.SELL: OrderSide.BUY}


class InternalLedgerAdapter:
    """BrokerAdapter for a single virtual persona, backed by a LedgerStore."""

    def __init__(
        self,
        persona: str,
        market_data: MarketDataProvider,
        store: LedgerStore,
        starting_cash: float = 5000.0,
    ) -> None:
        self._persona = persona
        self._market_data = market_data
        self._store = store
        self._starting_cash = starting_cash

    def place_order(
        self,
        *,
        decision_id: int,
        symbol: str,
        qty: float,
        side: OrderSide,
        stop_loss_price: float,
    ) -> OrderResult:
        decision_key = str(decision_id)
        state = self._load()

        # Crash-idempotency (F027, security-audit P2): a LangGraph replay after a
        # crash between this call and the DB commit must not re-apply the fill —
        # return the original result instead.
        existing = state.executed_decisions.get(decision_key)
        if existing is not None:
            return OrderResult(
                entry_order_id=existing.entry_order_id,
                stop_order_id=existing.stop_order_id,
                symbol=existing.symbol,
                qty=existing.qty,
                side=existing.side,
                stop_loss_price=existing.stop_loss_price,
            )

        last_price = self._market_data.get_last_price(symbol)
        self._apply_fill(state, symbol=symbol, qty=qty, side=side, price=last_price)

        entry_order_id = str(uuid.uuid4())
        stop_order_id = str(uuid.uuid4())
        state.pending_stops[stop_order_id] = PendingStop(
            order_id=stop_order_id,
            symbol=symbol,
            qty=qty,
            side=_OPPOSITE_SIDE[side],
            stop_price=stop_loss_price,
        )
        state.executed_decisions[decision_key] = ExecutedOrder(
            entry_order_id=entry_order_id,
            stop_order_id=stop_order_id,
            symbol=symbol,
            qty=qty,
            side=side,
            stop_loss_price=stop_loss_price,
        )
        self._store.save(self._persona, state)

        return OrderResult(
            entry_order_id=entry_order_id,
            stop_order_id=stop_order_id,
            symbol=symbol,
            qty=qty,
            side=side,
            stop_loss_price=stop_loss_price,
        )

    def cancel_order(self, order_id: str) -> None:
        state = self._load()
        state.pending_stops.pop(order_id, None)
        self._store.save(self._persona, state)

    def get_positions(self) -> list[Position]:
        state = self._load()
        result = []
        for symbol, pos in state.positions.items():
            last_price = self._market_data.get_last_price(symbol)
            result.append(
                Position(
                    symbol=symbol,
                    qty=pos.qty,
                    side=pos.side,
                    avg_entry_price=pos.avg_entry_price,
                    market_value=pos.qty * last_price,
                    unrealized_pl=pos.qty * (last_price - pos.avg_entry_price),
                )
            )
        return result

    def get_account_balance(self) -> AccountBalance:
        state = self._load()
        market_value_total = sum(
            pos.qty * self._market_data.get_last_price(symbol)
            for symbol, pos in state.positions.items()
        )
        equity = state.cash + market_value_total
        return AccountBalance(cash=state.cash, equity=equity, buying_power=state.cash)

    def check_stop_orders(self) -> list[str]:
        """Check pending stops against current market prices, trigger crossed ones.

        Must be called once per orchestrator cycle for every virtual persona —
        see F002 §2 for why this is not a continuous, broker-grade guarantee.
        Returns the list of triggered stop order ids.
        """
        state = self._load()
        triggered: list[str] = []
        changed = False

        for order_id, stop in list(state.pending_stops.items()):
            last_price = self._market_data.get_last_price(stop.symbol)
            if not _is_triggered(stop, last_price):
                continue
            # A pending stop can be stale by the time it triggers: the position may
            # have been (partially) sold, or cash spent, since it was registered.
            # Clamp to what is actually executable (no shorting, no margin) instead
            # of raising mid-sweep — an exception here would abort the remaining
            # stops and lose the fills already applied in this pass.
            fill_qty = min(stop.qty, _max_executable_qty(state, stop, last_price))
            if fill_qty > 0:
                self._apply_fill(
                    state, symbol=stop.symbol, qty=fill_qty, side=stop.side, price=last_price
                )
                triggered.append(order_id)
            del state.pending_stops[order_id]
            changed = True

        if changed:
            self._store.save(self._persona, state)
        return triggered

    def _load(self) -> LedgerState:
        return self._store.load(self._persona, default_cash=self._starting_cash)

    @staticmethod
    def _apply_fill(
        state: LedgerState, *, symbol: str, qty: float, side: OrderSide, price: float
    ) -> None:
        existing = state.positions.get(symbol)

        if side == OrderSide.BUY:
            cost = qty * price
            if cost > state.cash:
                raise ValueError(
                    f"Insufficient cash for {symbol}: need {cost}, have {state.cash} "
                    "(no margin allowed)"
                )
            state.cash -= cost
            if existing is None:
                state.positions[symbol] = PositionState(
                    qty=qty, side=OrderSide.BUY, avg_entry_price=price
                )
            else:
                total_qty = existing.qty + qty
                existing.avg_entry_price = (
                    existing.avg_entry_price * existing.qty + price * qty
                ) / total_qty
                existing.qty = total_qty
        else:
            if existing is None or existing.qty < qty:
                raise ValueError(
                    f"Cannot sell {qty} {symbol}: only {existing.qty if existing else 0} held "
                    "(no shorting allowed)"
                )
            state.cash += qty * price
            existing.qty -= qty
            if existing.qty == 0:
                del state.positions[symbol]


def _max_executable_qty(state: LedgerState, stop: PendingStop, last_price: float) -> float:
    if stop.side == OrderSide.SELL:
        existing = state.positions.get(stop.symbol)
        return existing.qty if existing is not None else 0.0
    return state.cash / last_price  # BUY-side close-out stop: bounded by cash (no margin)


def _is_triggered(stop: PendingStop, last_price: float) -> bool:
    if stop.side == OrderSide.SELL:  # protects a long position
        return last_price <= stop.stop_price
    return last_price >= stop.stop_price  # protects a short-equivalent close
