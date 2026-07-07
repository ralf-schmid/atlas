"""Persistence for InternalLedgerAdapter state — one JSON file per persona.

Deliberately simple (no DB layer exists yet, see F002 §6). Swappable later for a
Postgres-backed store without changing InternalLedgerAdapter, since it only talks
to the LedgerStore protocol.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from src.broker.protocol import OrderSide

_DEFAULT_BASE_DIR = Path(__file__).resolve().parents[2] / "data" / "ledger"


@dataclass(slots=True)
class PositionState:
    qty: float
    side: OrderSide
    avg_entry_price: float


@dataclass(slots=True)
class PendingStop:
    order_id: str
    symbol: str
    qty: float
    side: OrderSide
    stop_price: float


@dataclass(slots=True)
class ExecutedOrder:
    """Recorded per `decision_id` so a crash-replay of `place_order` (LangGraph
    replay before the DB commit, see F027/security-audit P2) returns the original
    fill instead of applying it twice."""

    entry_order_id: str
    stop_order_id: str
    symbol: str
    qty: float
    side: OrderSide
    stop_loss_price: float


@dataclass(slots=True)
class LedgerState:
    cash: float
    positions: dict[str, PositionState] = field(default_factory=dict)
    pending_stops: dict[str, PendingStop] = field(default_factory=dict)
    executed_decisions: dict[str, ExecutedOrder] = field(default_factory=dict)


class LedgerStore(Protocol):
    def load(self, persona: str, default_cash: float) -> LedgerState: ...

    def save(self, persona: str, state: LedgerState) -> None: ...


class JSONLedgerStore:
    def __init__(self, base_dir: Path = _DEFAULT_BASE_DIR) -> None:
        self._base_dir = base_dir

    def load(self, persona: str, default_cash: float) -> LedgerState:
        path = self._path_for(persona)
        if not path.exists():
            return LedgerState(cash=default_cash)

        raw = json.loads(path.read_text())
        return LedgerState(
            cash=raw["cash"],
            positions={
                symbol: PositionState(
                    qty=p["qty"], side=OrderSide(p["side"]), avg_entry_price=p["avg_entry_price"]
                )
                for symbol, p in raw["positions"].items()
            },
            pending_stops={
                order_id: PendingStop(
                    order_id=s["order_id"],
                    symbol=s["symbol"],
                    qty=s["qty"],
                    side=OrderSide(s["side"]),
                    stop_price=s["stop_price"],
                )
                for order_id, s in raw["pending_stops"].items()
            },
            # .get(..., {}): older ledger files predate this field (F027) — treat as empty.
            executed_decisions={
                decision_id: ExecutedOrder(
                    entry_order_id=e["entry_order_id"],
                    stop_order_id=e["stop_order_id"],
                    symbol=e["symbol"],
                    qty=e["qty"],
                    side=OrderSide(e["side"]),
                    stop_loss_price=e["stop_loss_price"],
                )
                for decision_id, e in raw.get("executed_decisions", {}).items()
            },
        )

    def save(self, persona: str, state: LedgerState) -> None:
        path = self._path_for(persona)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(asdict(state), indent=2))
        tmp_path.replace(path)

    def _path_for(self, persona: str) -> Path:
        return self._base_dir / f"{persona}.json"
