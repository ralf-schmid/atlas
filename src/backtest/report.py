"""Markdown rendering of a backtest run — F111 §5.3.

German output, like every other reader-facing text in this project. The disclaimer
and the caveats are part of the report, not an appendix: a table of returns without
them would be read as a promise.
"""

from __future__ import annotations

from src.backtest.artifact import DISCLAIMER, StrategyResult
from src.backtest.data import BarUniverse
from src.backtest.engine import EngineConfig
from src.db.models import BacktestRunStatus
from src.metrics.competition_score import CRITERION_LABELS, CompetitionScore


def render_report(
    results: list[StrategyResult],
    universe: BarUniverse,
    engine_config: EngineConfig,
    score: CompetitionScore | None,
    reference_symbol: str,
    reference: float | None,
) -> str:
    lines: list[str] = []
    fingerprint = universe.fingerprint
    lines.append("# ATLAS-Backtest")
    lines.append("")
    lines.append(
        f"**Zeitraum:** {universe.start} bis {universe.end} "
        f"({len(universe.trading_days)} Handelstage)"
    )
    lines.append(
        f"**Universum:** {len(universe.series)} Symbole "
        f"({len(universe.excluded)} wegen Datenqualität ausgeschlossen)"
    )
    lines.append(f"**Startkapital je Strategie:** {engine_config.start_capital_usd:,.0f} USD")
    lines.append(
        f"**Data-Fingerprint:** `{str(fingerprint['sha256'])[:16]}…` "
        f"({fingerprint['bars']} Bars, {fingerprint['first_bar']} bis "
        f"{fingerprint['last_bar']})"
    )
    lines.append("")

    lines.append("## Ergebnisse")
    lines.append("")
    lines.append(
        "| Strategie | Status | Rendite (netto) | Sortino | Max DD | Einstiege | "
        "Symbole Univ./gehandelt | Slippage USD |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for result in sorted(results, key=lambda item: item.spec.name):
        metrics = result.metrics
        lines.append(
            f"| {result.spec.name} "
            f"| {_status_label(result.status)} "
            f"| {_pct(metrics['return_net'])} "
            f"| {_num(metrics['sortino'])} "
            f"| {_pct(metrics['max_drawdown'])} "
            f"| {metrics['entries']} "
            f"| {metrics['universe_symbols']} / {metrics['traded_symbols']} "
            f"| {metrics['slippage_total_usd']:.2f} |"
        )
    lines.append("")
    if reference is not None:
        lines.append(
            f"**Referenzlinie {reference_symbol} (Buy & Hold, reine Kursrendite):** "
            f"{_pct(reference)} — kein simuliertes Portfolio, kein Risk-Gate, kein "
            "Score (F111 §6.4)."
        )
        lines.append("")

    if score is not None:
        lines.append("## §4.7-Score (feldrelativ, nur messbare Kriterien)")
        lines.append("")
        counted = ", ".join(CRITERION_LABELS[name] for name in score.counted_criteria)
        weights = ", ".join(
            f"{CRITERION_LABELS[name]} {weight:.0%}"
            for name, weight in sorted(score.effective_weights.items())
        )
        lines.append(f"Gezählte Kriterien: {counted or '—'}")
        lines.append(f"Effektive Gewichte: {weights or '—'}")
        lines.append("")
        lines.append("| Rang | Strategie | Score |")
        lines.append("|---:|---|---:|")
        for entry in score.personas:
            lines.append(f"| {entry.rank} | {entry.persona} | {entry.total_score:.3f} |")
        lines.append("")

    rejecting = [result for result in results if result.metrics["risk_gate_rejections"]]
    if rejecting:
        lines.append("## Risk-Gate-Ablehnungen")
        lines.append("")
        lines.append("Dieselbe Funktion wie im Live-Pfad (`src/risk/gate.py`).")
        lines.append("")
        for result in sorted(rejecting, key=lambda item: item.spec.name):
            counts = ", ".join(
                f"{reason}: {count}"
                for reason, count in result.metrics["risk_gate_rejections"].items()
            )
            lines.append(f"- **{result.spec.name}** — {counts}")
        lines.append("")

    lines.append("## Einschränkungen")
    lines.append("")
    for result in sorted(results, key=lambda item: item.spec.name):
        lines.append(f"### {result.spec.name}")
        lines.append("")
        for caveat in result.caveats:
            lines.append(f"- {caveat}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(DISCLAIMER)
    lines.append("")
    return "\n".join(lines)


def render_strategy_list(specs: list[tuple[str, str]], not_backtestable: dict[str, str]) -> str:
    lines = ["Verfügbare Strategien:", ""]
    for name, description in specs:
        lines.append(f"  {name}")
        lines.append(f"    {description.strip()}")
    if not_backtestable:
        lines.append("")
        lines.append("Nicht backtestbar (F111 §5.1):")
        for persona, reason in sorted(not_backtestable.items()):
            lines.append(f"  {persona}: {reason}")
    return "\n".join(lines)


def _status_label(status: BacktestRunStatus) -> str:
    return "ok" if status is BacktestRunStatus.OK else "**insufficient_data**"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:+.2f} %"


def _num(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"
