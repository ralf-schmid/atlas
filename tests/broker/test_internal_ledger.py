import pytest

from src.broker.internal_ledger import InternalLedgerAdapter
from src.broker.ledger_store import JSONLedgerStore
from src.broker.protocol import OrderSide


class FakeMarketData:
    def __init__(self, prices: dict[str, float]) -> None:
        self.prices = prices

    def get_last_price(self, symbol: str) -> float:
        return self.prices[symbol]


@pytest.fixture
def market_data():
    return FakeMarketData({"AAPL": 150.0})


@pytest.fixture
def store(tmp_path):
    return JSONLedgerStore(base_dir=tmp_path)


@pytest.fixture
def adapter(market_data, store):
    return InternalLedgerAdapter(
        persona="HYPE", market_data=market_data, store=store, starting_cash=5000.0
    )


def test_place_order_requires_decision_id(adapter):
    with pytest.raises(TypeError):
        adapter.place_order(  # type: ignore[call-arg]
            symbol="AAPL", qty=1, side=OrderSide.BUY, stop_loss_price=140.0
        )


def test_place_order_requires_stop_loss_price(adapter):
    with pytest.raises(TypeError):
        adapter.place_order(  # type: ignore[call-arg]
            decision_id=1, symbol="AAPL", qty=1, side=OrderSide.BUY
        )


def test_place_order_buy_fills_at_market_price_and_books_cash(adapter):
    result = adapter.place_order(
        decision_id=1, symbol="AAPL", qty=10, side=OrderSide.BUY, stop_loss_price=140.0
    )

    balance = adapter.get_account_balance()
    positions = adapter.get_positions()

    assert result.stop_loss_price == 140.0
    assert balance.cash == 5000.0 - 10 * 150.0
    assert len(positions) == 1
    assert positions[0].symbol == "AAPL"
    assert positions[0].qty == 10
    assert positions[0].avg_entry_price == 150.0


def test_place_order_registers_opposite_side_pending_stop(adapter, store):
    adapter.place_order(
        decision_id=1, symbol="AAPL", qty=10, side=OrderSide.BUY, stop_loss_price=140.0
    )

    state = store.load("HYPE", default_cash=5000.0)
    (stop,) = state.pending_stops.values()
    assert stop.side == OrderSide.SELL
    assert stop.stop_price == 140.0
    assert stop.qty == 10


def test_place_order_sell_without_position_raises_no_shorting(adapter):
    with pytest.raises(ValueError, match="no shorting"):
        adapter.place_order(
            decision_id=1, symbol="AAPL", qty=10, side=OrderSide.SELL, stop_loss_price=160.0
        )


def test_place_order_buy_exceeding_cash_raises_no_margin(adapter):
    with pytest.raises(ValueError, match="no margin"):
        adapter.place_order(
            decision_id=1, symbol="AAPL", qty=1000, side=OrderSide.BUY, stop_loss_price=140.0
        )


def test_check_stop_orders_triggers_when_price_crosses_stop(adapter, market_data):
    adapter.place_order(
        decision_id=1, symbol="AAPL", qty=10, side=OrderSide.BUY, stop_loss_price=140.0
    )
    market_data.prices["AAPL"] = 139.0

    triggered = adapter.check_stop_orders()

    assert len(triggered) == 1
    assert adapter.get_positions() == []
    balance = adapter.get_account_balance()
    assert balance.cash == 5000.0 - 10 * 150.0 + 10 * 139.0


def test_place_order_buy_adds_to_existing_position_with_weighted_avg_price(adapter, market_data):
    adapter.place_order(
        decision_id=1, symbol="AAPL", qty=10, side=OrderSide.BUY, stop_loss_price=140.0
    )
    market_data.prices["AAPL"] = 160.0
    adapter.place_order(
        decision_id=2, symbol="AAPL", qty=10, side=OrderSide.BUY, stop_loss_price=150.0
    )

    (position,) = adapter.get_positions()
    assert position.qty == 20
    assert position.avg_entry_price == 155.0  # (10*150 + 10*160) / 20


def test_check_stop_orders_triggers_buy_side_stop_when_closing_a_position(adapter, market_data):
    adapter.place_order(
        decision_id=1, symbol="AAPL", qty=10, side=OrderSide.BUY, stop_loss_price=140.0
    )
    # Sell half — registers a BUY-side pending stop (opposite of SELL).
    adapter.place_order(
        decision_id=2, symbol="AAPL", qty=5, side=OrderSide.SELL, stop_loss_price=155.0
    )
    market_data.prices["AAPL"] = 156.0

    triggered = adapter.check_stop_orders()

    assert len(triggered) == 1
    (position,) = adapter.get_positions()
    assert position.qty == 10  # 5 remaining + 5 bought back by the triggered stop


def test_check_stop_orders_clamps_stale_sell_stop_to_held_qty(adapter, market_data):
    # The original qty-10 stop is stale after selling 6 of the shares it protected;
    # the sweep must fill only what is held instead of raising "no shorting".
    adapter.place_order(
        decision_id=1, symbol="AAPL", qty=10, side=OrderSide.BUY, stop_loss_price=140.0
    )
    market_data.prices["AAPL"] = 160.0
    adapter.place_order(
        decision_id=2, symbol="AAPL", qty=6, side=OrderSide.SELL, stop_loss_price=200.0
    )
    market_data.prices["AAPL"] = 139.0

    triggered = adapter.check_stop_orders()

    assert len(triggered) == 1
    assert adapter.get_positions() == []
    balance = adapter.get_account_balance()
    assert balance.cash == 5000.0 - 10 * 150.0 + 6 * 160.0 + 4 * 139.0


def test_check_stop_orders_drops_stale_sell_stop_when_position_fully_closed(
    adapter, market_data, store
):
    adapter.place_order(
        decision_id=1, symbol="AAPL", qty=10, side=OrderSide.BUY, stop_loss_price=140.0
    )
    adapter.place_order(
        decision_id=2, symbol="AAPL", qty=10, side=OrderSide.SELL, stop_loss_price=200.0
    )
    market_data.prices["AAPL"] = 139.0

    triggered = adapter.check_stop_orders()

    assert triggered == []  # nothing held anymore — stop removed without a fill
    state = store.load("HYPE", default_cash=5000.0)
    remaining_sides = {stop.side for stop in state.pending_stops.values()}
    assert remaining_sides == {OrderSide.BUY}  # only the close-out stop is left
    assert adapter.get_account_balance().cash == 5000.0


def test_check_stop_orders_clamps_buy_side_stop_to_available_cash(adapter, market_data):
    adapter.place_order(
        decision_id=1, symbol="AAPL", qty=10, side=OrderSide.BUY, stop_loss_price=140.0
    )
    adapter.place_order(
        decision_id=2, symbol="AAPL", qty=10, side=OrderSide.SELL, stop_loss_price=200.0
    )
    adapter.place_order(
        decision_id=3, symbol="AAPL", qty=33, side=OrderSide.BUY, stop_loss_price=140.0
    )
    market_data.prices["AAPL"] = 200.0  # cash is 50.0 -> buy-back clamps to 0.25 shares

    triggered = adapter.check_stop_orders()

    assert len(triggered) == 1
    (position,) = adapter.get_positions()
    assert position.qty == 33 + 0.25
    assert adapter.get_account_balance().cash == 0.0


def test_check_stop_orders_drops_buy_side_stop_when_no_cash(adapter, market_data, store):
    market_data.prices["AAPL"] = 100.0
    adapter.place_order(
        decision_id=1, symbol="AAPL", qty=10, side=OrderSide.BUY, stop_loss_price=90.0
    )
    adapter.place_order(
        decision_id=2, symbol="AAPL", qty=10, side=OrderSide.SELL, stop_loss_price=150.0
    )
    adapter.place_order(
        decision_id=3, symbol="AAPL", qty=50, side=OrderSide.BUY, stop_loss_price=90.0
    )
    market_data.prices["AAPL"] = 150.0  # cash is 0.0 -> buy-back stop is unexecutable

    triggered = adapter.check_stop_orders()

    assert triggered == []
    state = store.load("HYPE", default_cash=5000.0)
    remaining_sides = {stop.side for stop in state.pending_stops.values()}
    assert remaining_sides == {OrderSide.SELL}  # only the protective stops remain
    (position,) = adapter.get_positions()
    assert position.qty == 50


def test_check_stop_orders_does_not_trigger_when_price_above_stop(adapter, market_data):
    adapter.place_order(
        decision_id=1, symbol="AAPL", qty=10, side=OrderSide.BUY, stop_loss_price=140.0
    )
    market_data.prices["AAPL"] = 145.0

    triggered = adapter.check_stop_orders()

    assert triggered == []
    assert len(adapter.get_positions()) == 1


def test_cancel_order_removes_pending_stop_without_touching_position(adapter, store):
    result = adapter.place_order(
        decision_id=1, symbol="AAPL", qty=10, side=OrderSide.BUY, stop_loss_price=140.0
    )

    adapter.cancel_order(result.stop_order_id)

    state = store.load("HYPE", default_cash=5000.0)
    assert state.pending_stops == {}
    assert len(adapter.get_positions()) == 1


def test_get_account_balance_never_has_margin(adapter):
    adapter.place_order(
        decision_id=1, symbol="AAPL", qty=10, side=OrderSide.BUY, stop_loss_price=140.0
    )

    balance = adapter.get_account_balance()

    assert balance.buying_power == balance.cash


def test_state_persists_across_adapter_instances(market_data, store):
    first = InternalLedgerAdapter(
        persona="HYPE", market_data=market_data, store=store, starting_cash=5000.0
    )
    first.place_order(
        decision_id=1, symbol="AAPL", qty=10, side=OrderSide.BUY, stop_loss_price=140.0
    )

    second = InternalLedgerAdapter(
        persona="HYPE", market_data=market_data, store=store, starting_cash=5000.0
    )

    assert second.get_positions() == first.get_positions()
    assert second.get_account_balance() == first.get_account_balance()
