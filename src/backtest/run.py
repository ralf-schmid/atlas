"""CLI entrypoint — `python -m src.backtest.run`. See F111 §5.2 and §10.

Deliberately the only way to start a backtest: no scheduler job, no API route, no
Telegram command. Nothing runs unless a human asks for it, which is also the
rollback path (F111 §10).
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.backtest.artifact import (
    Thresholds,
    attach_scores,
    build_payload,
    build_result,
    reference_return,
    save_run,
)
from src.backtest.data import InsufficientDataError, load_universe
from src.backtest.engine import EngineConfig, run_backtest
from src.backtest.report import render_report, render_strategy_list
from src.backtest.spec import DEFAULT_STRATEGY_DIR, StrategySpec, load_all_strategies
from src.db.base import get_session_factory
from src.review.slippage import load_slippage_config
from src.risk.config import load_system_guardrails

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENGINE_CONFIG_PATH = _REPO_ROOT / "config" / "backtest" / "engine.yaml"


@dataclass(frozen=True, slots=True)
class RunSettings:
    engine: EngineConfig
    thresholds: Thresholds
    warmup_bars: int
    max_gap_factor: float
    reference_symbol: str
    not_backtestable: dict[str, str]


def load_settings(path: Path = _ENGINE_CONFIG_PATH) -> RunSettings:
    raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    return RunSettings(
        engine=EngineConfig(
            start_capital_usd=float(raw["start_capital_usd"]),
            conviction=float(raw["conviction"]),
            slippage=load_slippage_config(),
        ),
        thresholds=Thresholds(
            min_trading_days=int(raw["min_trading_days"]),
            min_trades=int(raw["min_trades"]),
        ),
        warmup_bars=int(raw["warmup_bars"]),
        max_gap_factor=float(raw["max_gap_factor"]),
        reference_symbol=str(raw["reference_symbol"]),
        not_backtestable=dict(raw.get("not_backtestable") or {}),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.backtest.run",
        description="Deterministischer ATLAS-Backtest (F111). Kein LLM, keine Orders.",
    )
    parser.add_argument("--strategy", action="append", default=[], help="Spec-Name (wiederholbar)")
    parser.add_argument(
        "--all", action="store_true", help="alle Specs aus config/backtest/strategies"
    )
    parser.add_argument("--list", action="store_true", help="Specs auflisten und beenden")
    parser.add_argument("--from", dest="start", type=_date, help="erster Handelstag (YYYY-MM-DD)")
    parser.add_argument("--to", dest="end", type=_date, help="letzter Handelstag (YYYY-MM-DD)")
    parser.add_argument("--no-save", action="store_true", help="nicht in backtest_run schreiben")
    parser.add_argument("--json", dest="json_path", type=Path, help="Artefakte zusätzlich als JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    args = build_parser().parse_args(argv)
    settings = load_settings()
    available = load_all_strategies(DEFAULT_STRATEGY_DIR)

    if args.list:
        print(
            render_strategy_list(
                [(spec.name, spec.description) for spec in available], settings.not_backtestable
            )
        )
        return 0

    specs = _select(available, args.strategy, args.all)
    if not specs:
        print("Keine Strategie gewählt — --strategy NAME, --all oder --list.", file=sys.stderr)
        return 2

    session_factory = get_session_factory()
    with session_factory() as session:
        try:
            universe = load_universe(
                session,
                symbols=_symbols_for(specs),
                start=args.start,
                end=args.end,
                warmup_bars=settings.warmup_bars,
                max_gap_factor=settings.max_gap_factor,
            )
        except InsufficientDataError as exc:
            print(f"Abbruch: {exc}", file=sys.stderr)
            return 1

        system = load_system_guardrails()
        results = []
        for spec in specs:
            logger.info("backtesting %s …", spec.name)
            engine_result = run_backtest(spec, universe, settings.engine, system)
            results.append(
                build_result(spec, universe, engine_result, settings.engine, settings.thresholds)
            )

        score = attach_scores(results)
        payloads = [build_payload(result, universe, settings.engine) for result in results]

        if not args.no_save:
            for payload in payloads:
                save_run(session, payload)
            session.commit()
            logger.info("%d Lauf/Läufe in backtest_run gespeichert", len(payloads))

        print(
            render_report(
                results,
                universe,
                settings.engine,
                score,
                settings.reference_symbol,
                reference_return(universe, settings.reference_symbol),
            )
        )

        if args.json_path is not None:
            args.json_path.write_text(
                json.dumps(payloads, indent=2, ensure_ascii=False, default=_json_default)
            )
            logger.info("Artefakte nach %s geschrieben", args.json_path)
    return 0


def _select(available: list[StrategySpec], names: list[str], take_all: bool) -> list[StrategySpec]:
    if take_all:
        return available
    by_name = {spec.name: spec for spec in available}
    selected = []
    for name in names:
        if name not in by_name:
            print(
                f"Unbekannte Strategie {name!r}. Bekannt: {', '.join(sorted(by_name))}",
                file=sys.stderr,
            )
            continue
        selected.append(by_name[name])
    return selected


def _symbols_for(specs: list[StrategySpec]) -> list[str] | None:
    """None means "every symbol in market_bar" — as soon as one spec needs the full
    universe, loading a subset for the others would fragment the data fingerprint."""
    if any(spec.universe.symbols is None for spec in specs):
        return None
    symbols: set[str] = set()
    for spec in specs:
        symbols.update(spec.universe.symbols or [])
    return sorted(symbols)


def _date(value: str) -> datetime.date:
    return datetime.date.fromisoformat(value)


def _json_default(value: object) -> str:
    if isinstance(value, datetime.date):
        return value.isoformat()
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
