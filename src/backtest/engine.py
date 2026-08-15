"""The simulation — see docs/features/F111-backtest-modul.md §6.3.

Deterministic by construction: same bars plus same spec produce the same trades in
the same order, every time. No randomness, no wall-clock, no LLM (Leitplanke 1).

The parts that decide money — stop price, position size, risk approval, slippage —
are not reimplemented here. They are the live modules: `decision_sizing`,
`risk.gate`, and the F083 slippage formula. A backtest that used softer rules than
the live path would flatter every strategy it tested.
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from typing import Any

from src.backtest.data import BarUniverse, SymbolSeries
from src.backtest.signals import SignalValue, atr14_at, compute_signals
from src.backtest.spec import Condition, StrategySpec
from src.orchestrator.decision_sizing import compute_position_value_usd, compute_stop_loss_price
from src.review.slippage import _compute_penalty, _flat_spread_bps
from src.risk.gate import evaluate_decision
from src.risk.models import SystemGuardrails, TradeAction

# Exit reasons, kept as constants because the report groups by them.
REASON_STOP_LOSS = "stop_loss"
REASON_EXIT_RULE = "exit_rule"
REASON_MAX_HOLD = "max_hold_days"
REASON_END_OF_RUN = "end_of_run"


@dataclass(frozen=True, slots=True)
class EngineConfig:
    start_capital_usd: float
    conviction: float
    slippage: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Trade:
    day: datetime.date
    symbol: str
    action: str  # buy | sell
    qty: int
    price: float
    gross_usd: float
    slippage_usd: float
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "day": self.day.isoformat(),
            "symbol": self.symbol,
            "action": self.action,
            "qty": self.qty,
            "price": round(self.price, 6),
            "gross_usd": round(self.gross_usd, 4),
            "slippage_usd": round(self.slippage_usd, 4),
            "reason": self.reason,
        }


@dataclass
class _Position:
    symbol: str
    qty: int
    entry_price: float
    entry_day: datetime.date
    stop_price: float
    last_close: float


@dataclass(frozen=True, slots=True)
class EngineResult:
    equity_curve: list[tuple[datetime.date, float]]
    trades: list[Trade]
    slippage_total_usd: float
    rejections: dict[str, int] = field(default_factory=dict)

    @property
    def trade_count(self) -> int:
        return len(self.trades)


def run_backtest(
    spec: StrategySpec,
    universe: BarUniverse,
    config: EngineConfig,
    system: SystemGuardrails,
) -> EngineResult:
    persona = spec.guardrails
    symbols = symbols_for(spec, universe)
    signals = {
        symbol: compute_signals(universe.series[symbol].bars, spec.referenced_signals())
        for symbol in symbols
    }

    cash = config.start_capital_usd
    peak_equity = config.start_capital_usd
    positions: dict[str, _Position] = {}
    trades: list[Trade] = []
    rejections: dict[str, int] = {}
    equity_curve: list[tuple[datetime.date, float]] = []
    slippage_total = 0.0

    for day in universe.trading_days:
        # Positions stay marked at *yesterday's* close for the whole decision pass.
        # Marking them to today's close here would size today's orders — which fill
        # at today's open — with a price that is not known until the close. That is
        # look-ahead, and it is the subtle kind that still produces plausible
        # numbers. Today's close is applied at the end of the day, below.
        trades_today = 0

        # 1. Stops first. They are resting GTC orders placed at entry (Invariante #4)
        #    and therefore are not subject to the daily trade cap — the cap governs
        #    new decisions, not an order the broker already holds.
        for symbol in sorted(positions):
            series = universe.series[symbol]
            bar_index = series.index_by_day.get(day)
            if bar_index is None:
                continue
            bar = series.bars[bar_index]
            position = positions[symbol]
            if bar.low > position.stop_price:
                continue
            # A gap below the stop fills at the open, not at the stop: the stop is a
            # trigger, not a guaranteed price.
            fill_price = min(position.stop_price, bar.open)
            cash, slippage = _close_position(
                position, fill_price, day, REASON_STOP_LOSS, cash, trades, config, series, bar_index
            )
            slippage_total += slippage
            del positions[symbol]

        # 2. Rule-based exits, decided on yesterday's signals, filled at today's open.
        for symbol in sorted(positions):
            series = universe.series[symbol]
            bar_index = series.index_by_day.get(day)
            if bar_index is None or bar_index == 0:
                continue
            position = positions[symbol]
            reason = _exit_reason(spec, signals[symbol], bar_index - 1, position, day)
            if reason is None:
                continue
            equity = cash + _positions_value(positions)
            verdict = evaluate_decision(
                action=TradeAction.SELL,
                position_value_usd=position.qty * series.bars[bar_index].open,
                entry_price=position.entry_price,
                stop_loss_price=position.stop_price,
                atr14=None,
                portfolio_equity_usd=equity,
                portfolio_cash_usd=cash,
                portfolio_peak_equity_usd=peak_equity,
                open_positions_count=len(positions),
                trades_today_count=trades_today,
                system=system,
                persona=persona,
            )
            if not verdict.approved:
                _count(rejections, verdict.rejection_reasons)
                continue
            cash, slippage = _close_position(
                position,
                series.bars[bar_index].open,
                day,
                reason,
                cash,
                trades,
                config,
                series,
                bar_index,
            )
            slippage_total += slippage
            del positions[symbol]
            trades_today += 1

        # 3. Entries. Candidates are evaluated in symbol order — see F111 §6.3: a
        #    real persona picks by conviction, and any other tie-break here would be
        #    an invented preference.
        peak_equity = max(peak_equity, cash + _positions_value(positions))
        max_trades = min(persona.max_trades_per_day, system.max_trades_per_day_ceiling)
        for symbol in symbols:
            if trades_today >= max_trades:
                # Counted once per day rather than once per remaining candidate: the
                # useful diagnostic is "on how many days did the cap bind", not "how
                # many alphabetically later symbols were behind the cap".
                _count(rejections, ["max_trades_per_day_exceeded"])
                break
            if symbol in positions:
                continue
            equity = cash + _positions_value(positions)
            series = universe.series[symbol]
            bar_index = series.index_by_day.get(day)
            if bar_index is None or bar_index == 0:
                continue
            if not _entry_matches(spec, signals[symbol], bar_index - 1):
                continue

            entry_price = series.bars[bar_index].open
            if entry_price <= 0:
                continue
            atr14 = atr14_at(series.bars, bar_index - 1)
            stop_price = compute_stop_loss_price(entry_price, persona.stop_loss_policy, atr14)
            if stop_price is None:
                _count(rejections, ["atr_required_but_missing"])
                continue

            max_position_pct = min(persona.max_position_pct, system.max_position_pct_ceiling)
            target_value = compute_position_value_usd(config.conviction, max_position_pct, equity)
            qty = math.floor(target_value / entry_price)
            if qty < 1:
                continue

            verdict = evaluate_decision(
                action=TradeAction.BUY,
                position_value_usd=qty * entry_price,
                entry_price=entry_price,
                stop_loss_price=stop_price,
                atr14=atr14,
                portfolio_equity_usd=equity,
                portfolio_cash_usd=cash,
                portfolio_peak_equity_usd=peak_equity,
                open_positions_count=len(positions),
                trades_today_count=trades_today,
                system=system,
                persona=persona,
            )
            if not verdict.approved:
                _count(rejections, verdict.rejection_reasons)
                continue

            gross = qty * entry_price
            slippage = _slippage_usd(gross, series, bar_index, config.slippage)
            if gross + slippage > cash:
                _count(rejections, ["insufficient_cash_no_margin"])
                continue
            cash -= gross + slippage
            slippage_total += slippage
            trades.append(
                Trade(
                    day=day,
                    symbol=symbol,
                    action="buy",
                    qty=qty,
                    price=entry_price,
                    gross_usd=gross,
                    slippage_usd=slippage,
                    reason="entry_rule",
                )
            )
            positions[symbol] = _Position(
                symbol=symbol,
                qty=qty,
                entry_price=entry_price,
                entry_day=day,
                stop_price=stop_price,
                last_close=entry_price,  # today's close is not known yet — see above
            )
            trades_today += 1

        for position in positions.values():
            bar_index = universe.series[position.symbol].index_by_day.get(day)
            if bar_index is not None:
                position.last_close = universe.series[position.symbol].bars[bar_index].close
        equity = cash + _positions_value(positions)
        peak_equity = max(peak_equity, equity)
        # Only days this strategy's own universe actually traded produce a curve
        # point. In a mixed run the shared calendar carries crypto weekends; giving
        # an equities strategy a flat Saturday would feed a zero return into the
        # Sortino denominator that no market ever offered it.
        if any(day in universe.series[symbol].index_by_day for symbol in symbols):
            equity_curve.append((day, equity))

    # Open positions are closed at the last close so the final equity is realised
    # rather than partly mark-to-market — otherwise a strategy could park a paper
    # gain in an open position and never pay its exit slippage.
    if positions and equity_curve:
        last_day = equity_curve[-1][0]
        for symbol in sorted(positions):
            position = positions[symbol]
            series = universe.series[symbol]
            bar_index = series.index_by_day.get(last_day, len(series.bars) - 1)
            cash, slippage = _close_position(
                position,
                position.last_close,
                last_day,
                REASON_END_OF_RUN,
                cash,
                trades,
                config,
                series,
                bar_index,
            )
            slippage_total += slippage
        positions.clear()
        equity_curve[-1] = (equity_curve[-1][0], cash)

    return EngineResult(
        equity_curve=equity_curve,
        trades=trades,
        slippage_total_usd=slippage_total,
        rejections=rejections,
    )


def symbols_for(spec: StrategySpec, universe: BarUniverse) -> list[str]:
    """The spec's symbols that survived the data-quality gate."""
    if spec.universe.symbols is None:
        return sorted(universe.series)
    return sorted(symbol for symbol in spec.universe.symbols if symbol in universe.series)


def _entry_matches(spec: StrategySpec, signals: dict[str, list[SignalValue]], index: int) -> bool:
    return _all_match(spec.universe.filters, signals, index) and _all_match(
        spec.entry, signals, index
    )


def _exit_reason(
    spec: StrategySpec,
    signals: dict[str, list[SignalValue]],
    index: int,
    position: _Position,
    day: datetime.date,
) -> str | None:
    if spec.max_hold_days is not None and (day - position.entry_day).days >= spec.max_hold_days:
        return REASON_MAX_HOLD
    if spec.exit and _any_match(spec.exit, signals, index):
        return REASON_EXIT_RULE
    return None


def _all_match(
    conditions: list[Condition], signals: dict[str, list[SignalValue]], index: int
) -> bool:
    return all(
        condition.matches(_value(signals, condition.signal, index)) for condition in conditions
    )


def _any_match(
    conditions: list[Condition], signals: dict[str, list[SignalValue]], index: int
) -> bool:
    return any(
        condition.matches(_value(signals, condition.signal, index)) for condition in conditions
    )


def _value(signals: dict[str, list[SignalValue]], name: str, index: int) -> SignalValue:
    series = signals.get(name)
    if series is None or index < 0 or index >= len(series):
        return None
    return series[index]


def _positions_value(positions: dict[str, _Position]) -> float:
    return sum(position.qty * position.last_close for position in positions.values())


def _close_position(
    position: _Position,
    fill_price: float,
    day: datetime.date,
    reason: str,
    cash: float,
    trades: list[Trade],
    config: EngineConfig,
    series: SymbolSeries,
    bar_index: int,
) -> tuple[float, float]:
    gross = position.qty * fill_price
    slippage = _slippage_usd(gross, series, bar_index, config.slippage)
    trades.append(
        Trade(
            day=day,
            symbol=position.symbol,
            action="sell",
            qty=position.qty,
            price=fill_price,
            gross_usd=gross,
            slippage_usd=slippage,
            reason=reason,
        )
    )
    return cash + gross - slippage, slippage


def _slippage_usd(
    order_value: float, series: SymbolSeries, bar_index: int, slippage_config: dict[str, Any]
) -> float:
    """The F083 malus as a real cash cost on both sides of the trade.

    Same formula and same parameters as `review.slippage.compute_slippage_malus`,
    minus its DB lookups. The measured-spread branch (F104) cannot apply: historical
    quotes do not exist, so the flat per-asset-class rate is the only honest input —
    stated as a caveat in every run.
    """
    if not slippage_config.get("enabled", True) or order_value <= 0:
        return 0.0
    spread_bps = _flat_spread_bps(series.symbol, slippage_config)
    spread_cost = 0.5 * spread_bps / 10_000 * order_value
    bar = series.bars[bar_index]
    daily_dollar_volume = bar.volume * bar.close
    penalty = (
        float(_compute_penalty(order_value, daily_dollar_volume, slippage_config))
        if daily_dollar_volume > 0
        else 0.0
    )
    return spread_cost + penalty


def _count(rejections: dict[str, int], reasons: list[str]) -> None:
    for reason in reasons:
        rejections[reason] = rejections.get(reason, 0) + 1
