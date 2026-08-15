"""Bar loading, data fingerprint and the data-quality gate — F111 §4 and §6.6.

`market_bar` is the only data source (Leitplanke 4). Nothing here calls an API.
"""

from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.backtest.signals import Bar
from src.db.models import MarketBar, MarketBarTimeframe


class InsufficientDataError(RuntimeError):
    """Not enough history to define a simulation window at all."""


@dataclass(frozen=True, slots=True)
class SymbolSeries:
    symbol: str
    bars: list[Bar]
    index_by_day: dict[datetime.date, int]


@dataclass(frozen=True, slots=True)
class BarUniverse:
    series: dict[str, SymbolSeries]
    trading_days: list[datetime.date]
    excluded: dict[str, str]  # symbol -> reason
    fingerprint: dict[str, object]

    @property
    def start(self) -> datetime.date:
        return self.trading_days[0]

    @property
    def end(self) -> datetime.date:
        return self.trading_days[-1]


def load_universe(
    session: Session,
    *,
    symbols: list[str] | None,
    start: datetime.date | None,
    end: datetime.date | None,
    warmup_bars: int,
    max_gap_factor: float,
) -> BarUniverse:
    """Load every daily bar up to *end*, then decide which symbols may take part.

    Warmup bars are loaded from *before* `start` on purpose: an indicator that is
    only defined from day 50 onwards would otherwise make the first weeks of every
    simulation silently signal-free.
    """
    stmt = select(MarketBar).where(MarketBar.timeframe == MarketBarTimeframe.DAY)
    if symbols is not None:
        stmt = stmt.where(MarketBar.symbol.in_(symbols))
    if end is not None:
        stmt = stmt.where(MarketBar.ts <= datetime.datetime.combine(end, datetime.time.max))
    stmt = stmt.order_by(MarketBar.symbol, MarketBar.ts)

    by_symbol: dict[str, list[Bar]] = {}
    for row in session.scalars(stmt):
        by_symbol.setdefault(row.symbol, []).append(
            Bar(
                day=row.ts.date(),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
        )
    if not by_symbol:
        raise InsufficientDataError("no daily bars found for the requested symbols")

    if start is None:
        start = _auto_start(by_symbol, warmup_bars)

    series: dict[str, SymbolSeries] = {}
    excluded: dict[str, str] = {}
    for symbol, bars in by_symbol.items():
        reason = _exclusion_reason(bars, start, warmup_bars, max_gap_factor)
        if reason is not None:
            excluded[symbol] = reason
            continue
        series[symbol] = SymbolSeries(
            symbol=symbol,
            bars=bars,
            index_by_day={bar.day: index for index, bar in enumerate(bars)},
        )

    # The calendar comes from the symbols that actually take part, never from every
    # row that was loaded. Crypto trades weekends and equities do not, so a union
    # calendar would hand an equities-only run ~17 flat Saturdays and Sundays — days
    # on which nothing could have happened, diluting the daily-return series that
    # Sortino is computed from.
    trading_days = sorted(
        {
            bar.day
            for item in series.values()
            for bar in item.bars
            if bar.day >= start and (end is None or bar.day <= end)
        }
    )
    if not trading_days:
        raise InsufficientDataError(
            f"no symbol has usable bars between {start} and {end} "
            f"({len(excluded)} symbols excluded by the data-quality gate)"
        )

    return BarUniverse(
        series=series,
        trading_days=trading_days,
        excluded=excluded,
        fingerprint=fingerprint(series),
    )


def _auto_start(by_symbol: dict[str, list[Bar]], warmup_bars: int) -> datetime.date:
    """First simulation day when the caller gives no `--from`.

    Derived from the *longest* series, not from the union of all bar dates: the
    union mixes crypto weekends into an otherwise weekday calendar, so its 61st
    entry is only the ~43rd trading day for an equity — and every equity symbol
    would then fail the 60-bar warmup check. Measured live on 15.08.2026: all 656
    symbols were excluded and the run produced an empty universe.
    """
    longest = max(by_symbol.values(), key=len)
    if len(longest) <= warmup_bars:
        raise InsufficientDataError(
            f"the longest series has {len(longest)} bars, {warmup_bars} are needed for warmup"
        )
    return longest[warmup_bars].day


def _exclusion_reason(
    bars: list[Bar], start: datetime.date, warmup_bars: int, max_gap_factor: float
) -> str | None:
    warmup = sum(1 for bar in bars if bar.day < start)
    if warmup < warmup_bars:
        return f"insufficient_warmup ({warmup}/{warmup_bars} bars before {start})"
    break_ = find_price_level_break(bars, max_gap_factor)
    if break_ is not None:
        return f"price_level_break (factor {break_[1]:.2f} on {break_[0]})"
    return None


def find_price_level_break(
    bars: list[Bar], max_gap_factor: float
) -> tuple[datetime.date, float] | None:
    """The largest overnight gap (`open[t]` vs `close[t-1]`) if it reaches
    *max_gap_factor*, else None.

    The pure twin of `indicators.detect_price_level_break` (F108), which is bound to
    the DB and to the last 51 bars and therefore cannot judge a historical window.
    Same rule, same reasoning: a series with a level break cannot be averaged, and
    the cause — broken split history or real corporate action — is indistinguishable
    from the bars alone. `tests/backtest/test_data.py` pins the two against each
    other so they cannot drift.
    """
    worst: tuple[datetime.date, float] | None = None
    for previous, current in zip(bars, bars[1:], strict=False):
        if previous.close <= 0 or current.open <= 0:
            continue
        ratio = current.open / previous.close
        factor = max(ratio, 1 / ratio)
        if factor >= max_gap_factor and (worst is None or factor > worst[1]):
            worst = (current.day, factor)
    return worst


def fingerprint(series: dict[str, SymbolSeries]) -> dict[str, object]:
    """SHA-256 over every bar that took part, plus the shape of the data.

    This is the reproducibility anchor from F111 §4: a later run over "the same"
    period gets a different digest the moment a single bar was re-synced, so a
    changed number can be traced to changed data rather than to a changed rule.
    Values are formatted at the column precision (Numeric(x, 6)) so the digest does
    not depend on float repr.
    """
    digest = hashlib.sha256()
    bar_count = 0
    first: datetime.date | None = None
    last: datetime.date | None = None
    for symbol in sorted(series):
        for bar in series[symbol].bars:
            digest.update(
                f"{symbol}|{bar.day.isoformat()}|{bar.open:.6f}|{bar.high:.6f}|"
                f"{bar.low:.6f}|{bar.close:.6f}|{bar.volume:.6f}\n".encode()
            )
            bar_count += 1
            first = bar.day if first is None or bar.day < first else first
            last = bar.day if last is None or bar.day > last else last
    return {
        "sha256": digest.hexdigest(),
        "bars": bar_count,
        "symbols": len(series),
        "first_bar": first.isoformat() if first else None,
        "last_bar": last.isoformat() if last else None,
    }
