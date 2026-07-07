"""Real integration test against Alpaca Paper — see ARCHITECTURE.md Phase-2 DoD
("Broker-Adapter: Paper-Order ... Integrationstest läuft in CI gegen Alpaca-Paper").

Uses a stock (AAPL), matching how AlpacaPaperAdapter is actually used in this
project — only the native/stock personas (VULTURE, GUARDIAN, CHARTIST) use this
adapter; CRYPTOR is a virtual persona on InternalLedgerAdapter (ADR-0001), so
crypto was never a real requirement here. (An earlier version of this test used
BTC/USD for 24/7 fill reliability; that surfaced two real Alpaca API
restrictions — crypto rejects `time_in_force=day`, and crypto rejects `stop`
orders entirely — neither applies to the personas that actually use this
adapter, so switched back to a stock.)

Because market orders outside NYSE hours don't fill immediately, this test
only asserts the broker *accepted* both the entry and the GTC stop (not
`rejected`/`expired`) rather than requiring an immediate fill — a real fill is
verified opportunistically when the market happens to be open.

Skipped entirely unless real Alpaca Paper keys are present in the environment
(local: from .env; CI: from GitHub Encrypted Secrets).
"""

from __future__ import annotations

import os
import time

import pytest

from src.broker.alpaca_paper import AlpacaPaperAdapter
from src.broker.protocol import OrderSide

# A unique decision_id per test run: client_order_id = str(decision_id) (F027),
# and Alpaca remembers client_order_id per account indefinitely — a hardcoded
# value would collide with whatever a *previous* CI run against this same paper
# account already submitted, permanently exercising only the duplicate-recovery
# path instead of the fresh-submission path this test is meant to verify.
_DECISION_ID = int(time.time())

pytestmark = pytest.mark.integration

_SYMBOL = "AAPL"
_QTY = 1
_TERMINAL_STATUSES = {"filled", "canceled", "rejected", "expired"}
_REJECTED_STATUSES = {"rejected", "expired"}


@pytest.fixture
def adapter() -> AlpacaPaperAdapter:
    key_id = os.environ.get("ALPACA_PAPER_VULTURE_KEY_ID")
    secret_key = os.environ.get("ALPACA_PAPER_VULTURE_SECRET_KEY")
    if not key_id or not secret_key:
        pytest.skip("ALPACA_PAPER_VULTURE_KEY_ID/SECRET_KEY not set — needs real Alpaca Paper keys")
    return AlpacaPaperAdapter(api_key=key_id, secret_key=secret_key)


def test_place_order_is_accepted_by_real_alpaca_paper_with_gtc_stop(
    adapter: AlpacaPaperAdapter,
):
    result = adapter.place_order(
        decision_id=_DECISION_ID,
        symbol=_SYMBOL,
        qty=_QTY,
        side=OrderSide.BUY,
        stop_loss_price=1.0,  # far below any realistic AAPL price, just needs to be valid
    )

    try:
        entry_status = _poll_status(adapter, result.entry_order_id)
        assert entry_status not in _REJECTED_STATUSES, f"entry order was {entry_status!r}"

        stop_status = _poll_status(adapter, result.stop_order_id)
        assert stop_status not in _REJECTED_STATUSES, f"GTC stop order was {stop_status!r}"

        if entry_status == "filled":
            positions = adapter.get_positions()
            assert any(p.symbol == _SYMBOL for p in positions)
    finally:
        _cleanup(adapter, result.entry_order_id, result.stop_order_id)


def _poll_status(adapter: AlpacaPaperAdapter, order_id: str, timeout_s: float = 15.0) -> str:
    deadline = time.monotonic() + timeout_s
    status = "new"
    while time.monotonic() < deadline:
        order = adapter._client.get_order_by_id(order_id)
        status = str(order.status.value)
        if status in _TERMINAL_STATUSES:
            return status
        time.sleep(1)
    return status  # market may be closed — not filled yet, but not rejected either


def _cleanup(adapter: AlpacaPaperAdapter, entry_order_id: str, stop_order_id: str) -> None:
    for order_id in (entry_order_id, stop_order_id):
        try:
            adapter.cancel_order(order_id)
        except Exception:  # noqa: BLE001 — best-effort cleanup, order may already be filled/gone
            pass
    try:
        adapter._client.close_position(_SYMBOL)
    except Exception:  # noqa: BLE001 — best-effort cleanup, position may not exist if unfilled
        pass
