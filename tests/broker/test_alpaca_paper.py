from unittest.mock import MagicMock, patch

import pytest
from alpaca.common.exceptions import APIError
from alpaca.trading.enums import PositionSide
from alpaca.trading.models import Order as AlpacaOrder
from alpaca.trading.models import Position as AlpacaPosition
from alpaca.trading.models import TradeAccount

from src.broker.alpaca_paper import AlpacaPaperAdapter, _is_duplicate_client_order_id
from src.broker.protocol import OrderSide


def _duplicate_client_order_id_error() -> APIError:
    http_error = MagicMock()
    http_error.response.status_code = 422
    return APIError('{"code": 40010001, "message": "client order id must be unique"}', http_error)


def test_is_duplicate_client_order_id_false_on_malformed_error_body():
    """`.message`/`.status_code` parse the raw error body as JSON — a malformed
    body must not be mistaken for a duplicate (fail closed: propagate as a real
    error instead of silently treating it as a crash-replay recovery)."""
    http_error = MagicMock()
    http_error.response.status_code = 422
    exc = APIError("not valid json", http_error)

    assert _is_duplicate_client_order_id(exc) is False


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


def test_place_order_passes_decision_id_as_client_order_id(adapter, mock_client):
    stop_leg = AlpacaOrder.model_construct(id="stop-456")
    mock_client.submit_order.return_value = AlpacaOrder.model_construct(
        id="entry-123", legs=[stop_leg]
    )

    adapter.place_order(
        decision_id=42, symbol="AAPL", qty=1, side=OrderSide.BUY, stop_loss_price=150.0
    )

    (call,) = mock_client.submit_order.call_args_list
    assert call.kwargs["order_data"].client_order_id == "42"


def test_place_order_recovers_existing_order_on_duplicate_client_order_id(adapter, mock_client):
    mock_client.submit_order.side_effect = _duplicate_client_order_id_error()
    stop_leg = AlpacaOrder.model_construct(id="stop-456")
    mock_client.get_order_by_client_id.return_value = AlpacaOrder.model_construct(
        id="entry-123", legs=[stop_leg]
    )

    result = adapter.place_order(
        decision_id=42, symbol="AAPL", qty=1, side=OrderSide.BUY, stop_loss_price=150.0
    )

    mock_client.get_order_by_client_id.assert_called_once_with("42")
    assert result.entry_order_id == "entry-123"
    assert result.stop_order_id == "stop-456"


def test_place_order_reraises_non_duplicate_api_errors(adapter, mock_client):
    http_error = MagicMock()
    http_error.response.status_code = 403
    mock_client.submit_order.side_effect = APIError(
        '{"code": 40310000, "message": "insufficient buying power"}', http_error
    )

    with pytest.raises(APIError):
        adapter.place_order(
            decision_id=42, symbol="AAPL", qty=1, side=OrderSide.BUY, stop_loss_price=150.0
        )

    mock_client.get_order_by_client_id.assert_not_called()


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
