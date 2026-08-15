"""Declarative strategy specs — see docs/features/F111-backtest-modul.md §6.2.

A spec is *data*, not code: it is stored verbatim in `backtest_run.strategy_spec`,
and that is what makes a run reproducible (§4). Anything that can change a result —
signal, operator, threshold, universe, guardrail source — has to be expressible
here rather than in Python, or the stored artefact would describe less than the run
actually did.

Validation happens at load time, never mid-run: a typo in a signal name must fail
before the engine has simulated 60 days, not after.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.risk.config import _DEFAULT_PERSONAS_DIR, load_persona_guardrails
from src.risk.models import PersonaGuardrails, StopLossPolicy, StopLossPolicyType

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STRATEGY_DIR = _REPO_ROOT / "config" / "backtest" / "strategies"

# Signals the engine can compute from `market_bar` alone. Everything a persona
# charter uses beyond this list (fundamentals, magazine tips, sentiment) is not
# backtestable and must be declared in `screen_not_modelled` / `not_modelled`.
NUMERIC_SIGNALS = frozenset(
    {
        "close",
        "volume",
        "dollar_volume",
        "sma20",
        "sma50",
        "rsi14",
        "macd_histogram",
        "drawdown_20d",
        "close_vs_sma20",
        "return_5d",
        "return_20d",
        "atr14_pct",
        "volume_ratio_20d",
    }
)
CATEGORICAL_SIGNALS = frozenset({"sma_crossover"})
SIGNALS = NUMERIC_SIGNALS | CATEGORICAL_SIGNALS

NUMERIC_OPS = frozenset({"lt", "lte", "gt", "gte", "eq", "ne"})
CATEGORICAL_OPS = frozenset({"eq", "ne"})


class SpecError(ValueError):
    """A strategy file is malformed. Raised at load time."""


@dataclass(frozen=True, slots=True)
class Condition:
    signal: str
    op: str
    value: float | str

    def matches(self, actual: float | str | None) -> bool:
        """An unavailable signal never satisfies a condition.

        This is deliberate in both directions: an entry does not fire on missing
        data, and an exit does not fire either — a position is closed by an actual
        signal or by its stop, never by a gap in the series.
        """
        if actual is None:
            return False
        if isinstance(self.value, str) or isinstance(actual, str):
            if self.op == "eq":
                return actual == self.value
            if self.op == "ne":
                return actual != self.value
            return False
        return bool(_NUMERIC_COMPARE[self.op](actual, self.value))


_NUMERIC_COMPARE: dict[str, Callable[[float, float], bool]] = {
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}


@dataclass(frozen=True, slots=True)
class Universe:
    """Which symbols may be considered at all, and under which per-day screen.

    `filters` is the machine-readable image of a persona's `universe_screen`. It uses
    the same Condition machinery as entry rules — the distinction is semantic, not
    mechanical: a filter says "this symbol is in scope today", an entry rule says
    "buy it today".
    """

    symbols: list[str] | None  # None = every symbol in market_bar
    filters: list[Condition]


@dataclass(frozen=True, slots=True)
class StrategySpec:
    name: str
    description: str
    persona: str | None
    guardrails: PersonaGuardrails
    universe: Universe
    entry: list[Condition]
    exit: list[Condition]
    max_hold_days: int | None
    not_modelled: list[str]
    raw: dict[str, Any]

    def referenced_signals(self) -> set[str]:
        """Only these get computed — see F111 §6.2. Saves the bulk of the runtime
        for specs that never look at MACD."""
        return {condition.signal for condition in (*self.universe.filters, *self.entry, *self.exit)}


def load_strategy(path: Path, personas_dir: Path = _DEFAULT_PERSONAS_DIR) -> StrategySpec:
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise SpecError(f"{path.name}: top level must be a mapping")

    name = _require(raw, "name", str, path)
    description = _require(raw, "description", str, path)
    persona = raw.get("persona")
    if persona is not None and not isinstance(persona, str):
        raise SpecError(f"{path.name}: persona must be a string")

    guardrails = _resolve_guardrails(raw, persona, path, personas_dir)
    universe = _parse_universe(raw.get("universe") or {}, path)
    entry = _parse_conditions(raw.get("entry") or [], path, "entry")
    exit_ = _parse_conditions(raw.get("exit") or [], path, "exit")
    if not entry:
        raise SpecError(f"{path.name}: entry needs at least one condition")

    max_hold_days = raw.get("max_hold_days")
    if max_hold_days is not None and (not isinstance(max_hold_days, int) or max_hold_days < 1):
        raise SpecError(f"{path.name}: max_hold_days must be a positive integer")

    not_modelled = [str(item) for item in raw.get("not_modelled") or []]

    if persona is not None:
        _check_screen_coverage(raw, persona, path, personas_dir)

    return StrategySpec(
        name=name,
        description=description,
        persona=persona,
        guardrails=guardrails,
        universe=universe,
        entry=entry,
        exit=exit_,
        max_hold_days=max_hold_days,
        not_modelled=not_modelled,
        raw=raw,
    )


def load_all_strategies(directory: Path = DEFAULT_STRATEGY_DIR) -> list[StrategySpec]:
    return [load_strategy(path) for path in sorted(directory.glob("*.yaml"))]


def _resolve_guardrails(
    raw: dict[str, Any], persona: str | None, path: Path, personas_dir: Path
) -> PersonaGuardrails:
    """Persona specs pull their risk parameters from `config/personas/` rather than
    restating them — a proxy that drifted from the persona's real limits would not
    be testing that persona at all. Baselines have no persona and declare their own.
    """
    if persona is not None:
        if "guardrails" in raw:
            raise SpecError(f"{path.name}: set either persona or guardrails, not both")
        return load_persona_guardrails(persona, personas_dir)

    block = raw.get("guardrails")
    if not isinstance(block, dict):
        raise SpecError(f"{path.name}: needs either a persona reference or a guardrails block")
    policy_raw = block.get("stop_loss_policy") or {}
    try:
        policy = StopLossPolicy(
            type=StopLossPolicyType(policy_raw["type"]),
            max_loss_pct=policy_raw.get("max_loss_pct"),
            atr_multiplier=policy_raw.get("atr_multiplier"),
            min_loss_pct=policy_raw.get("min_loss_pct"),
        )
        return PersonaGuardrails(
            name=block["name"],
            max_position_pct=float(block["max_position_pct"]),
            max_trades_per_day=int(block["max_trades_per_day"]),
            max_open_positions=block["max_open_positions"],
            min_cash_pct=float(block["min_cash_pct"]),
            stop_loss_policy=policy,
        )
    except (KeyError, ValueError) as exc:
        raise SpecError(f"{path.name}: invalid guardrails block — {exc}") from exc


def _parse_universe(block: dict[str, Any], path: Path) -> Universe:
    symbols = block.get("symbols")
    if symbols is not None:
        if not isinstance(symbols, list) or not all(isinstance(s, str) for s in symbols):
            raise SpecError(f"{path.name}: universe.symbols must be a list of strings")
        symbols = list(symbols)
    return Universe(
        symbols=symbols,
        filters=_parse_conditions(block.get("filters") or [], path, "universe.filters"),
    )


def _parse_conditions(items: object, path: Path, where: str) -> list[Condition]:
    if not isinstance(items, list):
        raise SpecError(f"{path.name}: {where} must be a list")
    conditions: list[Condition] = []
    for item in items:
        if not isinstance(item, dict):
            raise SpecError(f"{path.name}: {where} entries must be mappings")
        signal, op, value = item.get("signal"), item.get("op"), item.get("value")
        if signal not in SIGNALS:
            raise SpecError(
                f"{path.name}: {where} references unknown signal {signal!r} — "
                f"known signals: {', '.join(sorted(SIGNALS))}"
            )
        allowed = CATEGORICAL_OPS if signal in CATEGORICAL_SIGNALS else NUMERIC_OPS
        if op not in allowed:
            raise SpecError(
                f"{path.name}: {where} uses operator {op!r} on signal {signal!r} — "
                f"allowed: {', '.join(sorted(allowed))}"
            )
        if signal in CATEGORICAL_SIGNALS:
            if not isinstance(value, str):
                raise SpecError(f"{path.name}: {where} signal {signal!r} needs a string value")
        elif not isinstance(value, int | float) or isinstance(value, bool):
            raise SpecError(f"{path.name}: {where} signal {signal!r} needs a numeric value")
        conditions.append(
            Condition(
                signal=signal, op=str(op), value=value if isinstance(value, str) else float(value)
            )
        )
    return conditions


def _check_screen_coverage(
    raw: dict[str, Any], persona: str, path: Path, personas_dir: Path
) -> None:
    """Every key of the persona's `universe_screen` must be either modelled or
    explicitly declared unmodelled.

    This is the anti-drift guard from F111 §6.2. Without it, adding a screen
    criterion to a charter would silently produce a proxy that no longer resembles
    the persona, and the backtest would keep reporting numbers as if it did.
    """
    persona_path = personas_dir / f"{persona.lower()}.yaml"
    persona_raw = yaml.safe_load(persona_path.read_text()) or {}
    screen_keys = set((persona_raw.get("universe_screen") or {}).keys())
    declared = set(raw.get("screen_modelled") or []) | set(raw.get("screen_not_modelled") or [])
    missing = screen_keys - declared
    if missing:
        raise SpecError(
            f"{path.name}: persona {persona} has universe_screen keys that this spec "
            f"neither models nor declares unmodelled: {', '.join(sorted(missing))}. "
            "Add them to screen_modelled or screen_not_modelled."
        )
    unknown = declared - screen_keys
    if unknown:
        raise SpecError(
            f"{path.name}: declares screen keys that persona {persona} does not have: "
            f"{', '.join(sorted(unknown))}"
        )


def screen_not_modelled(spec: StrategySpec) -> list[str]:
    """Persona screen criteria this proxy cannot represent — feeds the caveats."""
    return [str(key) for key in spec.raw.get("screen_not_modelled") or []]


def _require(raw: dict[str, Any], key: str, kind: type, path: Path) -> Any:
    value = raw.get(key)
    if not isinstance(value, kind):
        raise SpecError(f"{path.name}: {key} is required and must be {kind.__name__}")
    return value
