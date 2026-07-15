import json

from src.broker.ledger_store import ExecutedOrder, JSONLedgerStore, PendingStop, PositionState
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


def test_save_and_load_roundtrip_preserves_executed_order_fill_info(tmp_path):
    store = JSONLedgerStore(base_dir=tmp_path)
    state = store.load("HYPE", default_cash=5000.0)
    state.executed_decisions["1"] = ExecutedOrder(
        entry_order_id="entry-1",
        stop_order_id="stop-1",
        symbol="AAPL",
        qty=10,
        side=OrderSide.BUY,
        stop_loss_price=140.0,
        fill_price=150.0,
        filled_at="2026-07-14T10:00:00",
    )

    store.save("HYPE", state)
    reloaded = store.load("HYPE", default_cash=5000.0)

    assert reloaded.executed_decisions["1"].fill_price == 150.0
    assert reloaded.executed_decisions["1"].filled_at == "2026-07-14T10:00:00"


def test_load_defaults_fill_info_to_none_for_legacy_files_without_it(tmp_path):
    # F075: files written before this feature existed lack `fill_price`/`filled_at`
    # in `executed_decisions` — loading one must not crash.
    path = tmp_path / "HYPE.json"
    path.write_text(
        json.dumps(
            {
                "cash": 5000.0,
                "positions": {},
                "pending_stops": {},
                "executed_decisions": {
                    "1": {
                        "entry_order_id": "entry-1",
                        "stop_order_id": "stop-1",
                        "symbol": "AAPL",
                        "qty": 10,
                        "side": "buy",
                        "stop_loss_price": 140.0,
                    }
                },
            }
        )
    )
    store = JSONLedgerStore(base_dir=tmp_path)

    state = store.load("HYPE", default_cash=5000.0)

    assert state.executed_decisions["1"].fill_price is None
    assert state.executed_decisions["1"].filled_at is None


def test_different_personas_are_isolated(tmp_path):
    store = JSONLedgerStore(base_dir=tmp_path)
    hype_state = store.load("HYPE", default_cash=5000.0)
    hype_state.cash = 1000.0
    store.save("HYPE", hype_state)

    contra_state = store.load("CONTRA", default_cash=5000.0)

    assert contra_state.cash == 5000.0
