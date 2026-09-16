"""AlpacaLiveAdapter — the same order path as the paper adapter, against the live
endpoint. Phase 6 (ARCHITECTURE.md §8), dormant until then.

**Nothing routes here yet.** An adapter is only built for a persona whose
`config/broker.yaml` entry says `adapter: alpaca_live`; no entry does, no live key
exists in any environment, and `src/broker/registry.py` additionally refuses to
construct this class unless `ATLAS_LIVE_TRADING_ENABLED=true` is set explicitly
(Invariant #5 — paper/live separation, live only by a deliberate act).

Deliberately a subclass rather than a copy: the order path (bracket order with the
mandatory GTC stop leg, whole-share rounding, the client_order_id replay recovery,
the F077 cancel-then-sell dance) has been hardened against a real broker for
months. Live money is the worst possible place for a second, less-tested
implementation of it. The only difference between paper and live at Alpaca is the
endpoint, and that is the one thing this class changes.
"""

from __future__ import annotations

from typing import ClassVar

from src.broker.alpaca_paper import AlpacaPaperAdapter


class AlpacaLiveAdapter(AlpacaPaperAdapter):
    """BrokerAdapter for the live Alpaca account of the competition winner."""

    _paper: ClassVar[bool] = False
