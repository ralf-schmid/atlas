from unittest.mock import patch

import pytest
from alpaca.trading.enums import PositionSide
from alpaca.trading.models import Order as AlpacaOrder
from alpaca.trading.models import Position as AlpacaPosition
from alpaca.trading.models import TradeAccount

from src.broker.alpaca_paper import AlpacaPaperAdapter
from src.broker.protocol import OrderSide


@pytest.fixture
def mock_client():
    with patch("src.broker.alpaca_paper.TradingClient") as mock_cls:
        yield mock_cls.return_value


@pytest.fixture
def adapter(mock_client):
    return AlpacaPaperAdapter(api_key="key", secret_key="secret")


def test_adapter_always_uses_paper_endpoint():
    with patch("src.broker.alpaca_paper.TradingClient") as mock_cls:
        AlpacaPaperAdapter(api_key="key", secret_key="secret")
        mock_cls.assert_called_once_with("key", "secret", paper=True)


def test_place_order_requires_decision_id(adapter):
    with pytest.raises(TypeError):
        adapter.place_order(  # type: ignore[call-arg]
            symbol="AAPL", qty=1, side=OrderSide.BUY, stop_loss_price=100.0
        )


def test_place_order_requires_stop_loss_price(adapter):
    with pytest.raises(TypeError):
        adapter.place_order(  # type: ignore[call-arg]
            decision_id=1, symbol="AAPL", qty=1, side=OrderSide.BUY
        )


def test_place_order_submits_oto_bracket_with_gtc_stop_leg(adapter, mock_client):
    # A single OTO order with the stop as a child leg — not two separate submit_order
    # calls. Alpaca rejects a standalone opposite-side stop order as a "potential wash
    # trade" whenever the entry hasn't filled yet (e.g. market closed); the stop must
    # be submitted as part of the same order so Alpaca activates it only after fill.
    stop_leg = AlpacaOrder.model_construct(id="stop-456")
    entry_result = AlpacaOrder.model_construct(id="entry-123", legs=[stop_leg])
    mock_client.submit_order.return_value = entry_result

    result = adapter.place_order(
        decision_id=42,
        symbol="AAPL",
        qty=1,
        side=OrderSide.BUY,
        stop_loss_price=150.0,
    )

    assert mock_client.submit_order.call_count == 1
    (call,) = mock_client.submit_order.call_args_list

    entry_request = call.kwargs["order_data"]
    assert entry_request.symbol == "AAPL"
    assert entry_request.qty == 1
    assert entry_request.side.value == "buy"
    assert entry_request.time_in_force.value == "gtc"  # DAY is rejected for crypto symbols
    assert entry_request.order_class.value == "oto"
    assert entry_request.stop_loss.stop_price == 150.0

    assert result.entry_order_id == "entry-123"
    assert result.stop_order_id == "stop-456"
    assert result.stop_loss_price == 150.0


def test_place_order_rejects_unexpected_response_type(adapter, mock_client):
    mock_client.submit_order.return_value = {"id": "raw-dict"}

    with pytest.raises(TypeError, match="Unexpected submit_order response"):
        adapter.place_order(
            decision_id=1, symbol="AAPL", qty=1, side=OrderSide.BUY, stop_loss_price=150.0
        )


def test_place_order_rejects_missing_stop_leg(adapter, mock_client):
    mock_client.submit_order.return_value = AlpacaOrder.model_construct(id="entry-123", legs=None)

    with pytest.raises(RuntimeError, match="without exactly one stop leg"):
        adapter.place_order(
            decision_id=1, symbol="AAPL", qty=1, side=OrderSide.BUY, stop_loss_price=150.0
        )


def test_place_order_rejects_multiple_legs(adapter, mock_client):
    legs = [AlpacaOrder.model_construct(id="a"), AlpacaOrder.model_construct(id="b")]
    mock_client.submit_order.return_value = AlpacaOrder.model_construct(id="entry-123", legs=legs)

    with pytest.raises(RuntimeError, match="without exactly one stop leg"):
        adapter.place_order(
            decision_id=1, symbol="AAPL", qty=1, side=OrderSide.BUY, stop_loss_price=150.0
        )


def test_cancel_order(adapter, mock_client):
    adapter.cancel_order("order-789")
    mock_client.cancel_order_by_id.assert_called_once_with("order-789")


def test_get_positions_normalizes_alpaca_positions(adapter, mock_client):
    alpaca_position = AlpacaPosition.model_construct(
        symbol="AAPL",
        qty="10",
        side=PositionSide.LONG,
        avg_entry_price="145.5",
        market_value="1500.0",
        unrealized_pl="45.0",
    )
    mock_client.get_all_positions.return_value = [alpaca_position]

    positions = adapter.get_positions()

    assert len(positions) == 1
    p = positions[0]
    assert p.symbol == "AAPL"
    assert p.qty == 10.0
    assert p.side == OrderSide.BUY
    assert p.avg_entry_price == 145.5
    assert p.market_value == 1500.0
    assert p.unrealized_pl == 45.0


def test_get_account_balance_normalizes_alpaca_account(adapter, mock_client):
    alpaca_account = TradeAccount.model_construct(
        cash="5000.0", equity="5200.0", buying_power="5000.0"
    )
    mock_client.get_account.return_value = alpaca_account

    balance = adapter.get_account_balance()

    assert balance.cash == 5000.0
    assert balance.equity == 5200.0
    assert balance.buying_power == 5000.0
