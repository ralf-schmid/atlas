"""AlpacaPaperAdapter — BrokerAdapter implementation for native Alpaca paper accounts.

Used by the native personas (VULTURE, GUARDIAN, CHARTIST) per
docs/adr/0001-alpaca-paper-account-limit.md. Always talks to Alpaca's paper
endpoint (Invariant #5) — there is no live code path here.
"""

from __future__ import annotations

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide as AlpacaOrderSide
from alpaca.trading.enums import TimeInForce
from alpaca.trading.models import Order as AlpacaOrder
from alpaca.trading.models import Position as AlpacaPosition
from alpaca.trading.models import TradeAccount
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest

from src.broker.protocol import AccountBalance, OrderResult, OrderSide, Position

_TO_ALPACA_SIDE = {
    OrderSide.BUY: AlpacaOrderSide.BUY,
    OrderSide.SELL: AlpacaOrderSide.SELL,
}
_OPPOSITE_SIDE = {
    OrderSide.BUY: AlpacaOrderSide.SELL,
    OrderSide.SELL: AlpacaOrderSide.BUY,
}


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
        del decision_id  # not persisted here yet — order_record is a later feature (F001 §1)

        entry = self._client.submit_order(
            order_data=MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=_TO_ALPACA_SIDE[side],
                time_in_force=TimeInForce.DAY,
            )
        )
        stop = self._client.submit_order(
            order_data=StopOrderRequest(
                symbol=symbol,
                qty=qty,
                side=_OPPOSITE_SIDE[side],
                time_in_force=TimeInForce.GTC,
                stop_price=stop_loss_price,
            )
        )
        assert isinstance(entry, AlpacaOrder)
        assert isinstance(stop, AlpacaOrder)
        return OrderResult(
            entry_order_id=str(entry.id),
            stop_order_id=str(stop.id),
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
