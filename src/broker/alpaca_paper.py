"""AlpacaPaperAdapter — BrokerAdapter implementation for native Alpaca paper accounts.

Used by the native personas (VULTURE, GUARDIAN, CHARTIST) per
docs/adr/0001-alpaca-paper-account-limit.md. Always talks to Alpaca's paper
endpoint (Invariant #5) — there is no live code path here.
"""

from __future__ import annotations

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, TimeInForce
from alpaca.trading.enums import OrderSide as AlpacaOrderSide
from alpaca.trading.models import Order as AlpacaOrder
from alpaca.trading.models import Position as AlpacaPosition
from alpaca.trading.models import TradeAccount
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest

from src.broker.protocol import AccountBalance, OrderResult, OrderSide, Position

_TO_ALPACA_SIDE = {
    OrderSide.BUY: AlpacaOrderSide.BUY,
    OrderSide.SELL: AlpacaOrderSide.SELL,
}


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

        # Bracket order, not two separate submit_order calls: submitting the GTC stop
        # as its own order immediately after the entry gets rejected by Alpaca as a
        # "potential wash trade" whenever the entry hasn't filled yet (e.g. market
        # closed) — found by the real integration test against Alpaca Paper. A bracket
        # order attaches the stop as a child leg that Alpaca itself only activates once
        # the entry fills, which is also a closer match to Invariant #4 (a stop only
        # makes sense once the position exists).
        #
        # Alpaca rejects GTC on the *entry* leg whenever qty is fractional
        # (`422 "fractional orders must be DAY orders"`, live-confirmed 2026-07-10,
        # F051) — and this system's position sizing (amount_usd / entry_price)
        # produces a fractional qty for essentially every real decision. DAY only
        # affects the entry: a market order fills immediately whenever the market is
        # open, so this doesn't meaningfully change entry behaviour. The stop-loss
        # child leg is unaffected by the entry's time_in_force — Alpaca always keeps
        # bracket exit legs GTC regardless, verified below.
        entry_time_in_force = TimeInForce.DAY if qty != int(qty) else TimeInForce.GTC
        try:
            entry = self._client.submit_order(
                order_data=MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=_TO_ALPACA_SIDE[side],
                    time_in_force=entry_time_in_force,
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
            qty=qty,
            side=side,
            stop_loss_price=stop_loss_price,
        )

    def cancel_order(self, order_id: str) -> None:
        self._client.cancel_order_by_id(order_id)

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
