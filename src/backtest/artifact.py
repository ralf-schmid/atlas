"""Result assembly, honesty thresholds and persistence — F111 §4, §5.4, §6.5/§6.6.

The thresholds here are the whole point of the "hard" option Ralf picked: a run
below them still produces an artefact, but without a Sortino ratio and without a
§4.7 score. A number that cannot carry its claim is not shipped in a shape that
looks like it can.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.backtest.data import BarUniverse
from src.backtest.engine import EngineConfig, EngineResult, Trade, symbols_for
from src.backtest.spec import StrategySpec, screen_not_modelled
from src.db.models import BacktestRun, BacktestRunStatus
from src.metrics.competition_score import (
    CompetitionScore,
    PersonaCriteria,
    ReliabilityInputs,
    score_personas,
)
from src.metrics.performance import daily_returns, max_drawdown, simple_return, sortino_ratio

DISCLAIMER = (
    "Ein Backtest beschreibt die Vergangenheit unter idealisierten Annahmen und ist "
    "keine Aussage über künftige Ergebnisse. Er ersetzt den laufenden Wettbewerb "
    "nicht, er stellt eine zweite Erkenntnisquelle daneben (ADR-0015, F111 §11)."
)

# Present in every run, regardless of outcome — see F111 §6.6.
FIXED_CAVEATS = [
    "Survivorship Bias: das Universum stammt aus dem HEUTIGEN Screener. Symbole, die "
    "es nie ins Universum geschafft haben oder wieder herausgefallen sind, fehlen.",
    "Charter-Proxy ≠ Charter: die Persona entscheidet live per LLM-Urteil auf dem "
    "gemeinsamen Research-Pool. Hier läuft eine deterministische Näherung ihrer "
    "Preis-/Volumenregeln.",
    "Der §4.7-Score ist feldrelativ: er hängt davon ab, welche Strategien im selben "
    "Lauf standen, und ist zwischen Läufen mit anderer Besetzung nicht vergleichbar.",
    "Kandidaten eines Tages werden alphabetisch abgearbeitet, bis das Trade-Limit "
    "oder das Kapital greift — eine echte Persona wählt nach Überzeugung.",
    "Slippage nutzt den Flat-Satz je Assetklasse (F083). Historische Bid/Ask-Quotes "
    "existieren nicht, die gemessene Variante aus F104 ist hier prinzipbedingt aus.",
    "Die Slippage ist bereits als echter Cash-Abfluss in der Equity-Kurve enthalten; "
    "die ausgewiesene Rendite ist eine Netto-Rendite, kein zweites Mal zu kürzen.",
]


@dataclass(frozen=True, slots=True)
class Thresholds:
    min_trading_days: int
    min_trades: int


@dataclass(frozen=True, slots=True)
class StrategyResult:
    spec: StrategySpec
    status: BacktestRunStatus
    period_start: datetime.date
    period_end: datetime.date
    metrics: dict[str, Any]
    caveats: list[str]
    equity_curve: list[tuple[datetime.date, float]]
    trades: list[Trade]

    @property
    def ok(self) -> bool:
        return self.status is BacktestRunStatus.OK


def build_result(
    spec: StrategySpec,
    universe: BarUniverse,
    engine_result: EngineResult,
    engine_config: EngineConfig,
    thresholds: Thresholds,
) -> StrategyResult:
    values = [Decimal(str(value)) for _, value in engine_result.equity_curve]
    trading_days = len(values)
    entries = sum(1 for trade in engine_result.trades if trade.action == "buy")

    below_days = trading_days < thresholds.min_trading_days
    below_trades = entries < thresholds.min_trades
    status = (
        BacktestRunStatus.INSUFFICIENT_DATA if below_days or below_trades else BacktestRunStatus.OK
    )

    net_return = simple_return(values)
    returns = daily_returns(values)
    # Sortino is withheld below the threshold even though the arithmetic would
    # succeed: a ratio over a handful of trades is a measurement artefact.
    sortino = sortino_ratio(returns) if status is BacktestRunStatus.OK else None

    participating = symbols_for(spec, universe)
    metrics: dict[str, Any] = {
        "trading_days": trading_days,
        "universe_symbols": len(participating),
        "traded_symbols": len({trade.symbol for trade in engine_result.trades}),
        "entries": entries,
        "exits": sum(1 for trade in engine_result.trades if trade.action == "sell"),
        "start_capital_usd": engine_config.start_capital_usd,
        "final_equity_usd": round(float(values[-1]), 2) if values else None,
        "return_net": round(net_return, 6),
        "sortino": round(sortino, 4) if sortino is not None else None,
        "max_drawdown": round(max_drawdown(values), 6),
        "slippage_total_usd": round(engine_result.slippage_total_usd, 4),
        "risk_gate_rejections": dict(sorted(engine_result.rejections.items())),
        "competition_score": None,  # filled by attach_scores once the field is known
        "score_field": [],
    }

    caveats = list(FIXED_CAVEATS)
    caveats.extend(_dynamic_caveats(spec, universe, status, below_days, below_trades, thresholds))

    return StrategyResult(
        spec=spec,
        status=status,
        period_start=universe.start,
        period_end=universe.end,
        metrics=metrics,
        caveats=caveats,
        equity_curve=engine_result.equity_curve,
        trades=engine_result.trades,
    )


def _dynamic_caveats(
    spec: StrategySpec,
    universe: BarUniverse,
    status: BacktestRunStatus,
    below_days: bool,
    below_trades: bool,
    thresholds: Thresholds,
) -> list[str]:
    caveats: list[str] = []
    if status is BacktestRunStatus.INSUFFICIENT_DATA:
        parts = []
        if below_days:
            parts.append(f"weniger als {thresholds.min_trading_days} Handelstage")
        if below_trades:
            parts.append(f"weniger als {thresholds.min_trades} Einstiege")
        caveats.append(
            f"STATUS insufficient_data ({', '.join(parts)}): kein Sortino, kein "
            "§4.7-Score. Die übrigen Zahlen sind beschreibend, nicht belastbar."
        )
    if not symbols_for(spec, universe):
        # Live-hit on 15.08.2026: in a shared run the window is set by the longest
        # series, which is an equity. Crypto has been ingested only since April and
        # trades seven days a week, so BTC/ETH/SOL had 30 of the required 60 warmup
        # bars and CRYPTOR silently produced a zero. A zero that means "no window"
        # must not read like a zero that means "no signal".
        caveats.append(
            "Kein einziges Symbol dieser Strategie hat den Datenqualitäts-Filter "
            f"überstanden (Fenster {universe.start} bis {universe.end}). Das Ergebnis "
            "ist leer, nicht schlecht — die Strategie einzeln laufen lassen "
            f"(--strategy {spec.name}), dann bestimmt ihr eigenes Universum das Fenster."
        )
    not_modelled = screen_not_modelled(spec)
    if not_modelled:
        caveats.append(
            "Nicht abbildbare Screen-Kriterien der Persona (fehlen im Proxy): "
            + ", ".join(sorted(not_modelled))
        )
    if spec.not_modelled:
        caveats.append("Nicht abbildbare Charter-Signale: " + ", ".join(sorted(spec.not_modelled)))
    if universe.excluded:
        sample = sorted(universe.excluded)[:5]
        caveats.append(
            f"{len(universe.excluded)} Symbole wegen Datenqualität ausgeschlossen "
            f"(Warmup/Preisniveau-Bruch, F108), u. a.: {', '.join(sample)}"
        )
    return caveats


def attach_scores(results: list[StrategyResult]) -> CompetitionScore | None:
    """The §4.7 score over the strategies of this run.

    Reuses `score_personas` unchanged. Thesis quality and operational reliability do
    not exist in a backtest (no reviews, no agent_runs); the existing logic drops any
    criterion that not every entrant has and redistributes its weight, which is
    exactly the wanted behaviour — see F111 §6.5.
    """
    scorable = [result for result in results if result.ok]
    if len(scorable) < 2:
        return None

    criteria = [
        PersonaCriteria(
            persona=result.spec.name,
            sortino=result.metrics["sortino"],
            adjusted_return=result.metrics["return_net"],
            max_drawdown=result.metrics["max_drawdown"],
            thesis_quality=None,
            reliability=None,
            reliability_inputs=ReliabilityInputs(None, None, None),
            reviews_total=0,
            trades=result.metrics["entries"],
        )
        for result in scorable
    ]
    score = score_personas(criteria, since=scorable[0].period_start)
    field = sorted(result.spec.name for result in scorable)
    by_name = {entry.persona: entry for entry in score.personas}
    for result in scorable:
        entry = by_name[result.spec.name]
        result.metrics["competition_score"] = round(entry.total_score, 6)
        result.metrics["score_rank"] = entry.rank
        result.metrics["score_field"] = field
        result.metrics["score_counted_criteria"] = score.counted_criteria
    return score


def reference_return(universe: BarUniverse, symbol: str) -> float | None:
    """Price return of a single symbol over the window — the SPY reference line.

    Deliberately not a simulated portfolio (F111 §6.4): the risk gate caps any single
    position at 25 %, so a "100 % buy and hold" strategy could never exist inside the
    engine, and presenting a capped version as the benchmark would understate it.
    """
    series = universe.series.get(symbol)
    if series is None:
        return None
    window = [bar for bar in series.bars if universe.start <= bar.day <= universe.end]
    if len(window) < 2 or window[0].close <= 0:
        return None
    return window[-1].close / window[0].close - 1.0


def build_payload(
    result: StrategyResult, universe: BarUniverse, engine_config: EngineConfig
) -> dict[str, Any]:
    """The artefact contract from F111 §4, as one JSON-serialisable mapping."""
    return {
        "spec_name": result.spec.name,
        "status": result.status,
        "period_start": result.period_start,
        "period_end": result.period_end,
        "strategy_spec": result.spec.raw,
        "config": {
            "start_capital_usd": engine_config.start_capital_usd,
            "conviction": engine_config.conviction,
            "slippage": engine_config.slippage,
            "universe_symbols": len(universe.series),
            "excluded_symbols": len(universe.excluded),
            "trading_days": len(universe.trading_days),
            "disclaimer": DISCLAIMER,
        },
        "data_fingerprint": universe.fingerprint,
        "metrics": result.metrics,
        "caveats": result.caveats,
        "equity_curve": [[day.isoformat(), round(value, 4)] for day, value in result.equity_curve],
        "trades": [trade.as_dict() for trade in result.trades],
    }


def save_run(session: Session, payload: dict[str, Any]) -> BacktestRun:
    """Persist one strategy run and link it to the previous run of the same spec."""
    parent = session.scalar(
        select(BacktestRun)
        .where(BacktestRun.spec_name == payload["spec_name"])
        .order_by(BacktestRun.created_at.desc())
        .limit(1)
    )
    run = BacktestRun(
        spec_name=payload["spec_name"],
        status=payload["status"],
        period_start=payload["period_start"],
        period_end=payload["period_end"],
        strategy_spec=payload["strategy_spec"],
        config=payload["config"],
        data_fingerprint=payload["data_fingerprint"],
        metrics=payload["metrics"],
        caveats=payload["caveats"],
        equity_curve=payload["equity_curve"],
        trades=payload["trades"],
        parent_run_id=parent.id if parent else None,
        lineage=compute_lineage(parent, payload),
    )
    session.add(run)
    session.flush()
    return run


def compute_lineage(parent: BacktestRun | None, payload: dict[str, Any]) -> dict[str, Any]:
    """ "Was wurde gegenüber dem Vorlauf geändert" (F111 §4).

    Without this a changed number is unattributable: a different result may come
    from a changed rule, a changed parameter, or simply from re-synced bars.
    """
    if parent is None:
        return {"parent_run_id": None, "changed": {}, "note": "erster Lauf dieser Spec"}
    changed: dict[str, dict[str, Any]] = {}
    for field_name in ("strategy_spec", "config", "data_fingerprint"):
        before = getattr(parent, field_name)
        after = payload[field_name]
        if before != after:
            changed[field_name] = _diff(before, after)
    for field_name, before_value, after_value in (
        ("period_start", parent.period_start, payload["period_start"]),
        ("period_end", parent.period_end, payload["period_end"]),
    ):
        if before_value != after_value:
            changed[field_name] = {
                "before": before_value.isoformat(),
                "after": after_value.isoformat(),
            }
    return {
        "parent_run_id": str(parent.id),
        "parent_created_at": parent.created_at.isoformat(),
        "changed": changed,
    }


def _diff(before: Any, after: Any) -> dict[str, Any]:
    """Key-level diff for the two mappings that matter; anything else is reported
    whole rather than pretending to a structural comparison."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {"before": before, "after": after}
    out: dict[str, Any] = {}
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            out[key] = {"before": before.get(key), "after": after.get(key)}
    return out


def latest_run_id(session: Session, spec_name: str) -> uuid.UUID | None:
    return session.scalar(
        select(BacktestRun.id)
        .where(BacktestRun.spec_name == spec_name)
        .order_by(BacktestRun.created_at.desc())
        .limit(1)
    )
