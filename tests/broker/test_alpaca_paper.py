import datetime
from unittest.mock import MagicMock, patch

import pytest
from alpaca.common.exceptions import APIError
from alpaca.trading.enums import OrderStatus as AlpacaOrderStatus
from alpaca.trading.enums import PositionSide
from alpaca.trading.models import Order as AlpacaOrder
from alpaca.trading.models import Position as AlpacaPosition
from alpaca.trading.models import TradeAccount

from src.broker.alpaca_paper import (
    AlpacaOrderState,
    AlpacaPaperAdapter,
    _is_duplicate_client_order_id,
)
from src.broker.protocol import OrderSide


def _duplicate_client_order_id_error() -> APIError:
    # Real Alpaca Paper response, confirmed via the CI integration test — the
    # message uses an underscore ("client_order_id"), not a space.
    http_error = MagicMock()
    http_error.response.status_code = 422
    return APIError('{"code":40010001,"message":"client_order_id must be unique"}', http_error)


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
    assert entry_request.time_in_force.value == "gtc"
    assert entry_request.order_class.value == "oto"
    assert entry_request.stop_loss.stop_price == 150.0

    assert result.entry_order_id == "entry-123"
    assert result.stop_order_id == "stop-456"
    assert result.qty == 1
    assert result.stop_loss_price == 150.0


def test_place_order_rounds_fractional_qty_to_whole_shares(adapter, mock_client):
    # Live-confirmed 2026-07-10 (F052): Alpaca rejects bracket/OTO orders outright
    # for a fractional qty (`422 "fractional orders must be simple orders"`) — and
    # this system's position sizing (amount_usd / entry_price) produces a
    # fractional qty for essentially every real decision, so this was blocking
    # every native-adapter buy order that reached the broker.
    stop_leg = AlpacaOrder.model_construct(id="stop-456")
    mock_client.submit_order.return_value = AlpacaOrder.model_construct(
        id="entry-123", legs=[stop_leg]
    )

    result = adapter.place_order(
        decision_id=42,
        symbol="AAPL",
        qty=0.869813,
        side=OrderSide.BUY,
        stop_loss_price=150.0,
    )

    (call,) = mock_client.submit_order.call_args_list
    entry_request = call.kwargs["order_data"]
    assert entry_request.qty == 1
    assert entry_request.time_in_force.value == "gtc"
    assert result.qty == 1


def test_place_order_rejects_qty_that_rounds_to_zero(adapter, mock_client):
    with pytest.raises(ValueError, match="rounds to 0 whole shares"):
        adapter.place_order(
            decision_id=42,
            symbol="ALDX",
            qty=0.3,
            side=OrderSide.BUY,
            stop_loss_price=1.5,
        )

    mock_client.submit_order.assert_not_called()


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


@pytest.mark.parametrize(
    ("alpaca_status", "expected_state"),
    [
        (AlpacaOrderStatus.FILLED, AlpacaOrderState.FILLED),
        (AlpacaOrderStatus.PARTIALLY_FILLED, AlpacaOrderState.PARTIALLY_FILLED),
        (AlpacaOrderStatus.CANCELED, AlpacaOrderState.CANCELED),
        (AlpacaOrderStatus.REJECTED, AlpacaOrderState.REJECTED),
        (AlpacaOrderStatus.EXPIRED, AlpacaOrderState.EXPIRED),
        (AlpacaOrderStatus.NEW, AlpacaOrderState.OPEN),
        (AlpacaOrderStatus.ACCEPTED, AlpacaOrderState.OPEN),
    ],
)
def test_get_order_status_maps_alpaca_status(adapter, mock_client, alpaca_status, expected_state):
    alpaca_order = AlpacaOrder.model_construct(
        status=alpaca_status, filled_at=None, filled_avg_price=None
    )
    mock_client.get_order_by_id.return_value = alpaca_order

    result = adapter.get_order_status("entry-123")

    assert result.state == expected_state
    mock_client.get_order_by_id.assert_called_once_with("entry-123")


def test_get_order_status_extracts_fill_price_and_time_when_filled(adapter, mock_client):
    filled_at = datetime.datetime(2026, 7, 14, 10, 0, tzinfo=datetime.UTC)
    alpaca_order = AlpacaOrder.model_construct(
        status=AlpacaOrderStatus.FILLED, filled_at=filled_at, filled_avg_price="151.25"
    )
    mock_client.get_order_by_id.return_value = alpaca_order

    result = adapter.get_order_status("entry-123")

    assert result.state == AlpacaOrderState.FILLED
    assert result.filled_at == datetime.datetime(2026, 7, 14, 10, 0)  # tzinfo stripped
    assert result.fill_price == 151.25


def test_get_order_status_no_fill_info_when_still_open(adapter, mock_client):
    alpaca_order = AlpacaOrder.model_construct(
        status=AlpacaOrderStatus.NEW, filled_at=None, filled_avg_price=None
    )
    mock_client.get_order_by_id.return_value = alpaca_order

    result = adapter.get_order_status("entry-123")

    assert result.state == AlpacaOrderState.OPEN
    assert result.filled_at is None
    assert result.fill_price is None


# F077: close_position tests.


def test_close_position_cancels_every_stop_then_sells(adapter, mock_client):
    mock_client.submit_order.return_value = AlpacaOrder.model_construct(id="sell-123", legs=None)

    result = adapter.close_position(
        decision_id=99, symbol="AAPL", qty=10, stop_order_ids=["stop-1", "stop-2"]
    )

    assert mock_client.cancel_order_by_id.call_count == 2
    mock_client.cancel_order_by_id.assert_any_call("stop-1")
    mock_client.cancel_order_by_id.assert_any_call("stop-2")
    (call,) = mock_client.submit_order.call_args_list
    sell_request = call.kwargs["order_data"]
    assert sell_request.symbol == "AAPL"
    assert sell_request.qty == 10
    assert sell_request.side.value == "sell"
    assert sell_request.time_in_force.value == "day"
    assert sell_request.order_class is None
    assert result.order_id == "sell-123"
    assert result.qty == 10
    assert result.side == OrderSide.SELL


def test_close_position_ignores_cancel_failure_for_already_filled_stop(adapter, mock_client):
    http_error = MagicMock()
    http_error.response.status_code = 422
    mock_client.cancel_order_by_id.side_effect = [
        APIError('{"code": 42210000, "message": "order not found"}', http_error),
        None,
    ]
    mock_client.submit_order.return_value = AlpacaOrder.model_construct(id="sell-123", legs=None)

    result = adapter.close_position(
        decision_id=99, symbol="AAPL", qty=10, stop_order_ids=["already-filled", "stop-2"]
    )

    assert mock_client.cancel_order_by_id.call_count == 2
    mock_client.submit_order.assert_called_once()
    assert result.order_id == "sell-123"


def test_close_position_recovers_existing_order_on_duplicate_client_order_id(adapter, mock_client):
    mock_client.submit_order.side_effect = _duplicate_client_order_id_error()
    mock_client.get_order_by_client_id.return_value = AlpacaOrder.model_construct(
        id="sell-123", legs=None
    )

    result = adapter.close_position(decision_id=99, symbol="AAPL", qty=10, stop_order_ids=[])

    mock_client.get_order_by_client_id.assert_called_once_with("99")
    assert result.order_id == "sell-123"


def test_close_position_reraises_non_duplicate_api_errors(adapter, mock_client):
    http_error = MagicMock()
    http_error.response.status_code = 403
    mock_client.submit_order.side_effect = APIError(
        '{"code": 40310000, "message": "insufficient buying power"}', http_error
    )

    with pytest.raises(APIError):
        adapter.close_position(decision_id=99, symbol="AAPL", qty=10, stop_order_ids=[])


def test_close_position_rejects_unexpected_response_type(adapter, mock_client):
    mock_client.submit_order.return_value = {"id": "raw-dict"}

    with pytest.raises(TypeError, match="Unexpected submit_order response"):
        adapter.close_position(decision_id=99, symbol="AAPL", qty=10, stop_order_ids=[])
