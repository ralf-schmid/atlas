"""Steuer-Export: realised trades of a portfolio as CSV (F123, P6 DoD).

ARCHITECTURE.md §8 P6 requires a "Steuer-Export (Trades-CSV für Anlage KAP)". This
module produces the *raw material* for that declaration, not the declaration: one
row per realised (closed) lot, FIFO-matched, with acquisition and disposal on the
same line.

Two things it deliberately does not do, because both are Ralf's decisions and
neither may be guessed (CLAUDE.md — keine stillen Annahmen bei Geld-Themen):

* **No currency conversion.** Every amount is in the account currency (USD at
  Alpaca). Anlage KAP wants EUR, and which FX rate applies (ECB reference rate of
  the trade day vs. the monthly average of the BMF list) is a tax decision. The
  CSV carries a `waehrung` column so the conversion can be added downstream
  without touching this code.
* **No tax opinion.** `paragraph_23` only marks what the rule keys on — a crypto
  disposal held for less than a year (§ 23 EStG, private Veräußerungsgeschäfte,
  FIFO) as opposed to a securities disposal under § 20. Which line of Anlage KAP
  or Anlage SO a row ends up in is not decided here.

FIFO is not a choice either: it is what § 23 EStG prescribes for crypto and what
the broker's own lot accounting does for shares.
"""

from __future__ import annotations

import csv
import datetime
import io
import logging
import uuid
from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Decision, DecisionAction, OrderRecord, OrderRecordStatus

logger = logging.getLogger(__name__)

_CSV_COLUMNS = [
    "verkauf_datum",
    "kauf_datum",
    "instrument",
    "assetklasse",
    "stueck",
    "kaufkurs",
    "verkaufskurs",
    "anschaffungskosten",
    "erloes",
    "gebuehren",
    "ergebnis",
    "waehrung",
    "haltedauer_tage",
    "paragraph_23",
]


@dataclass(frozen=True, slots=True)
class RealizedTrade:
    """One closed lot: bought once, sold once, FIFO-matched."""

    instrument: str
    asset_class: str
    buy_date: datetime.datetime
    sell_date: datetime.datetime
    qty: Decimal
    buy_price: Decimal
    sell_price: Decimal
    fees: Decimal
    currency: str

    @property
    def cost(self) -> Decimal:
        return self.qty * self.buy_price

    @property
    def proceeds(self) -> Decimal:
        return self.qty * self.sell_price

    @property
    def result(self) -> Decimal:
        return self.proceeds - self.cost - self.fees

    @property
    def holding_days(self) -> int:
        return (self.sell_date.date() - self.buy_date.date()).days

    @property
    def paragraph_23(self) -> bool:
        """Crypto sold inside the one-year holding period — the case § 23 EStG
        keys on. Shares are § 20 regardless of holding period."""
        return self.asset_class == "crypto" and self.holding_days < 365


@dataclass(frozen=True, slots=True)
class TaxExport:
    trades: list[RealizedTrade]
    #: Instruments whose sells exceeded the recorded buys — a data gap, not a
    #: trade. Named rather than swallowed: the export must not look complete
    #: while it is missing an acquisition.
    unmatched: list[str]

    @property
    def result_sum(self) -> Decimal:
        return sum((trade.result for trade in self.trades), start=Decimal("0"))


def build_tax_export(
    session: Session,
    portfolio_id: uuid.UUID,
    since: datetime.datetime | None = None,
    until: datetime.datetime | None = None,
    currency: str = "USD",
) -> TaxExport:
    """FIFO-matches the portfolio's filled buys and sells into realised lots.

    Only `FILLED` orders count — a partial fill has no final quantity, and an open
    position is not a realisation. `since`/`until` bound the *disposal* date: a lot
    sold in the export period is reported with its original acquisition, however
    far back that lies.
    """
    rows = session.execute(
        select(OrderRecord, Decision)
        .join(Decision, Decision.id == OrderRecord.decision_id)
        .where(
            Decision.portfolio_id == portfolio_id,
            OrderRecord.status == OrderRecordStatus.FILLED,
        )
        .order_by(OrderRecord.filled_at, OrderRecord.submitted_at)
    ).all()

    lots: dict[str, deque[tuple[datetime.datetime, Decimal, Decimal]]] = {}
    trades: list[RealizedTrade] = []
    unmatched: list[str] = []

    for order, decision in rows:
        when = order.filled_at or order.submitted_at
        qty = decision.quantity
        price = order.fill_price
        if qty is None or price is None:
            logger.warning(
                "F123: filled order without qty/price is skipped",
                extra={"order_id": str(order.id), "instrument": decision.instrument},
            )
            continue

        if decision.action == DecisionAction.BUY:
            lots.setdefault(decision.instrument, deque()).append((when, qty, price))
            continue
        if decision.action not in (DecisionAction.SELL, DecisionAction.CLOSE):
            continue

        open_lots = lots.setdefault(decision.instrument, deque())
        remaining = qty
        fees_left = order.fees or Decimal("0")
        while remaining > 0 and open_lots:
            buy_when, buy_qty, buy_price = open_lots[0]
            matched = min(remaining, buy_qty)
            # The disposal's fees belong to the disposal; they are split across the
            # lots it consumes, proportionally to the matched quantity.
            share = (matched / qty) if qty else Decimal("0")
            trades.append(
                RealizedTrade(
                    instrument=decision.instrument,
                    asset_class="crypto" if "/" in decision.instrument else "stock",
                    buy_date=buy_when,
                    sell_date=when,
                    qty=matched,
                    buy_price=buy_price,
                    sell_price=price,
                    fees=(fees_left * share).quantize(Decimal("0.000001")),
                    currency=currency,
                )
            )
            remaining -= matched
            if matched == buy_qty:
                open_lots.popleft()
            else:
                open_lots[0] = (buy_when, buy_qty - matched, buy_price)
        if remaining > 0:
            unmatched.append(decision.instrument)
            logger.warning(
                "F123: sell without a matching buy in the data",
                extra={"instrument": decision.instrument, "qty": str(remaining)},
            )

    in_window = [
        trade
        for trade in trades
        if (since is None or trade.sell_date >= since)
        and (until is None or trade.sell_date <= until)
    ]
    return TaxExport(trades=in_window, unmatched=sorted(set(unmatched)))


def render_tax_csv(export: TaxExport) -> str:
    """CSV with `;` and decimal commas — what Excel opens correctly in a German
    locale, and what every Anlage-KAP helper expects."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(_CSV_COLUMNS)
    for trade in export.trades:
        writer.writerow(
            [
                trade.sell_date.date().isoformat(),
                trade.buy_date.date().isoformat(),
                trade.instrument,
                trade.asset_class,
                _num(trade.qty, 6),
                _num(trade.buy_price, 6),
                _num(trade.sell_price, 6),
                _num(trade.cost, 2),
                _num(trade.proceeds, 2),
                _num(trade.fees, 2),
                _num(trade.result, 2),
                trade.currency,
                trade.holding_days,
                "ja" if trade.paragraph_23 else "nein",
            ]
        )
    return buffer.getvalue()


def _num(value: Decimal, places: int) -> str:
    quantized = value.quantize(Decimal(1).scaleb(-places))
    return f"{quantized}".replace(".", ",")
