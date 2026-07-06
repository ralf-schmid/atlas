import datetime
from decimal import Decimal

from src.ingestion.musterdepot_transactions import (
    Transaction,
    format_transaction_alert,
    parse_transactions,
    strip_html,
    sync_musterdepot_transactions,
)

_REAL_HTML_SNIPPET = (
    '<p><strong>Transaktion</strong></p><p><strong style="color: rgb(227, 6, 19);">'
    "TEILVERKAUF</strong></p><p></p><ul><li><strong>Moderna</strong>&nbsp;– "
    "WKN A2N9D9 – 75 Stück zu je 68,31 Euro</li></ul>"
)


def test_strip_html_flattens_tags_and_decodes_entities():
    flat = strip_html(_REAL_HTML_SNIPPET)
    assert "Transaktion TEILVERKAUF Moderna" in flat
    assert "WKN A2N9D9" in flat
    assert "&nbsp;" not in flat
    assert "<" not in flat


def test_parse_transactions_extracts_real_mail_snippet():
    transactions = parse_transactions(_REAL_HTML_SNIPPET)

    assert transactions == [
        Transaction(
            seq=0,
            action="TEILVERKAUF",
            instrument_name="Moderna",
            wkn="A2N9D9",
            quantity=Decimal("75"),
            price=Decimal("68.31"),
            currency="Euro",
            raw_text="Transaktion TEILVERKAUF Moderna – WKN A2N9D9 – 75 Stück zu je 68,31 Euro",
        )
    ]


def test_parse_transactions_handles_thousands_separator():
    text = "Transaktion KAUF Deutsche Bank – WKN 514000 – 1.234 Stück zu je 12,50 Euro"
    transactions = parse_transactions(text)

    assert len(transactions) == 1
    assert transactions[0].quantity == Decimal("1234")
    assert transactions[0].price == Decimal("12.50")
    assert transactions[0].instrument_name == "Deutsche Bank"


def test_parse_transactions_returns_empty_list_for_unrelated_text():
    assert parse_transactions("Es gibt keine Transaktion in diesem Text.") == []


def test_parse_transactions_extracts_multiple_lines():
    text = (
        "Transaktion KAUF Apple – WKN 865985 – 10 Stück zu je 150,00 Euro. "
        "Transaktion VERKAUF SAP – WKN 716460 – 5 Stück zu je 200,00 Euro."
    )
    transactions = parse_transactions(text)

    assert [t.seq for t in transactions] == [0, 1]
    assert transactions[0].instrument_name == "Apple"
    assert transactions[1].instrument_name == "SAP"


def test_format_transaction_alert_includes_disclaimer():
    transaction = Transaction(
        seq=0,
        action="TEILVERKAUF",
        instrument_name="Moderna",
        wkn="A2N9D9",
        quantity=Decimal("75"),
        price=Decimal("68.31"),
        currency="Euro",
        raw_text="irrelevant",
    )
    message = format_transaction_alert(transaction)

    assert "TEILVERKAUF Moderna" in message
    assert "WKN A2N9D9" in message
    assert "keine ATLAS-Order" in message


def test_sync_musterdepot_transactions_returns_zero_for_empty_list(session):
    received_at = datetime.datetime(2026, 7, 6, 15, 48)
    assert sync_musterdepot_transactions(session, "msg-1", received_at, []) == 0


def test_sync_musterdepot_transactions_is_idempotent_on_rerun(session):
    received_at = datetime.datetime(2026, 7, 6, 15, 48)
    v1 = [
        Transaction(
            seq=0,
            action="TEILVERKAUF",
            instrument_name="Moderna",
            wkn="A2N9D9",
            quantity=Decimal("75"),
            price=Decimal("68.31"),
            currency="Euro",
            raw_text="old",
        )
    ]
    v2 = [
        Transaction(
            seq=0,
            action="VERKAUF",
            instrument_name="Moderna",
            wkn="A2N9D9",
            quantity=Decimal("100"),
            price=Decimal("70.00"),
            currency="Euro",
            raw_text="new",
        )
    ]

    first_count = sync_musterdepot_transactions(session, "msg-1", received_at, v1)
    second_count = sync_musterdepot_transactions(session, "msg-1", received_at, v2)

    assert first_count == 1
    assert second_count == 1

    from sqlalchemy import select

    from src.db.models import MusterdepotTransaction

    rows = session.scalars(
        select(MusterdepotTransaction).where(MusterdepotTransaction.message_id == "msg-1")
    ).all()
    assert len(rows) == 1
    assert rows[0].action == "VERKAUF"
    assert rows[0].quantity == Decimal("100.000000")
