"""DER AKTIONÄR-Musterdepot transaction notifications -> `musterdepot_transaction`.

See docs/features/F014-musterdepot-transactions.md. A separate mail type from the
"Neuer Inhalt" publications notifications (F013): sender `noreply@boersenmedien.de`,
constant subject "Neue Transaktion", body contains a line like
"Transaktion TEILVERKAUF Moderna – WKN A2N9D9 – 75 Stück zu je 68,31 Euro".

Purely informational: this module only parses + persists + formats an alert. Nothing
here places, sizes, or even suggests an ATLAS order — see Invariant #2 (privilege
separation) and #3 (no order without a persisted Decision) in CLAUDE.md. The
Musterdepot is Boersenmedien AG's *own* real-money portfolio, not ATLAS's.

Idempotent: upsert on (message_id, seq) — a mail could theoretically list more than
one transaction, `seq` is the position within that mail.
"""

from __future__ import annotations

import datetime
import html
import re
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import MusterdepotTransaction

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_TRANSACTION_RE = re.compile(
    r"Transaktion\s+(?P<action>[A-ZÄÖÜ]+)\s+(?P<name>.+?)\s+[-–]\s+WKN\s+"
    r"(?P<wkn>[A-Z0-9]+)\s+[-–]\s+(?P<quantity>[\d.,]+)\s+Stück\s+zu\s+je\s+"
    r"(?P<price>[\d.,]+)\s+(?P<currency>\w+)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Transaction:
    seq: int
    action: str
    instrument_name: str
    wkn: str
    quantity: Decimal
    price: Decimal
    currency: str
    raw_text: str


def strip_html(text: str) -> str:
    """Flattens HTML into whitespace-normalized plain text. The Musterdepot mail's
    transaction line is split across several `<p>`/`<strong>` tags in the source HTML
    (`<strong>Transaktion</strong></p><p><strong>TEILVERKAUF</strong>...`) — replacing
    tags with a space and collapsing whitespace reassembles it into one matchable
    line, whether the input is HTML or already-plain text (a no-op tag-wise).
    Also decodes entities (`&nbsp;` shows up right next to the separator dash in the
    real mail, with no other whitespace around it)."""
    without_tags = _TAG_RE.sub(" ", text)
    unescaped = html.unescape(without_tags)
    return _WHITESPACE_RE.sub(" ", unescaped).strip()


def _parse_german_decimal(value: str) -> Decimal:
    return Decimal(value.replace(".", "").replace(",", "."))


def parse_transactions(text: str) -> list[Transaction]:
    """Extracts every "Transaktion ..." line from (HTML or plain) mail body text."""
    flat = strip_html(text)
    transactions = []
    for seq, match in enumerate(_TRANSACTION_RE.finditer(flat)):
        transactions.append(
            Transaction(
                seq=seq,
                action=match.group("action").upper(),
                instrument_name=match.group("name").strip(),
                wkn=match.group("wkn").upper(),
                quantity=_parse_german_decimal(match.group("quantity")),
                price=_parse_german_decimal(match.group("price")),
                currency=match.group("currency"),
                raw_text=match.group(0),
            )
        )
    return transactions


def format_transaction_alert(transaction: Transaction) -> str:
    return (
        f"📊 DER AKTIONÄR-Musterdepot: {transaction.action} {transaction.instrument_name} "
        f"(WKN {transaction.wkn}), {transaction.quantity} Stück @ "
        f"{transaction.price} {transaction.currency}\n\n"
        f"Nur Info aus einem fremden Echtgeld-Depot — keine ATLAS-Order, kein "
        f"automatischer Trade."
    )


def sync_musterdepot_transactions(
    session: Session,
    message_id: str,
    received_at: datetime.datetime,
    transactions: list[Transaction],
) -> int:
    if not transactions:
        return 0

    rows = [
        {
            "message_id": message_id,
            "seq": t.seq,
            "action": t.action,
            "instrument_name": t.instrument_name,
            "wkn": t.wkn,
            "quantity": t.quantity,
            "price": t.price,
            "currency": t.currency,
            "raw_text": t.raw_text,
            "received_at": received_at,
        }
        for t in transactions
    ]

    stmt = insert(MusterdepotTransaction).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_musterdepot_transaction_message_seq",
        set_={
            "action": stmt.excluded.action,
            "instrument_name": stmt.excluded.instrument_name,
            "wkn": stmt.excluded.wkn,
            "quantity": stmt.excluded.quantity,
            "price": stmt.excluded.price,
            "currency": stmt.excluded.currency,
            "raw_text": stmt.excluded.raw_text,
            "synced_at": datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        },
    )
    session.execute(stmt)
    session.flush()
    return len(rows)
