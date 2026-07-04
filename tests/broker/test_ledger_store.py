from src.broker.ledger_store import JSONLedgerStore, PendingStop, PositionState
from src.broker.protocol import OrderSide


def test_load_returns_default_state_when_no_file(tmp_path):
    store = JSONLedgerStore(base_dir=tmp_path)

    state = store.load("HYPE", default_cash=5000.0)

    assert state.cash == 5000.0
    assert state.positions == {}
    assert state.pending_stops == {}


def test_save_and_load_roundtrip(tmp_path):
    store = JSONLedgerStore(base_dir=tmp_path)
    state = store.load("HYPE", default_cash=5000.0)
    state.cash = 3500.0
    state.positions["AAPL"] = PositionState(qty=10, side=OrderSide.BUY, avg_entry_price=150.0)
    state.pending_stops["stop-1"] = PendingStop(
        order_id="stop-1", symbol="AAPL", qty=10, side=OrderSide.SELL, stop_price=140.0
    )

    store.save("HYPE", state)
    reloaded = store.load("HYPE", default_cash=5000.0)

    assert reloaded.cash == 3500.0
    assert reloaded.positions["AAPL"] == PositionState(
        qty=10, side=OrderSide.BUY, avg_entry_price=150.0
    )
    assert reloaded.pending_stops["stop-1"] == PendingStop(
        order_id="stop-1", symbol="AAPL", qty=10, side=OrderSide.SELL, stop_price=140.0
    )


def test_different_personas_are_isolated(tmp_path):
    store = JSONLedgerStore(base_dir=tmp_path)
    hype_state = store.load("HYPE", default_cash=5000.0)
    hype_state.cash = 1000.0
    store.save("HYPE", hype_state)

    contra_state = store.load("CONTRA", default_cash=5000.0)

    assert contra_state.cash == 5000.0
