import datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.api.app import app


def _client() -> TestClient:
    return TestClient(app)


def test_notify_publication_rejects_missing_secret(monkeypatch):
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")
    response = _client().post(
        "/api/ingestion/publications/notify",
        json={"subject": "Neuer Inhalt - Euro am Sonntag 23/26"},
    )
    assert response.status_code == 401


def test_notify_publication_rejects_wrong_secret(monkeypatch):
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")
    response = _client().post(
        "/api/ingestion/publications/notify",
        json={"subject": "Neuer Inhalt - Euro am Sonntag 23/26"},
        headers={"x-webhook-secret": "wrong"},
    )
    assert response.status_code == 401


def test_notify_publication_rejects_unrecognized_subject(monkeypatch):
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")
    response = _client().post(
        "/api/ingestion/publications/notify",
        json={"subject": "Ihre Rechnung liegt bereit"},
        headers={"x-webhook-secret": "s3cret"},
    )
    assert response.status_code == 422


def test_notify_publication_sends_telegram_alert_when_auto_download_disabled(monkeypatch):
    """F078 §6 rollback path: with the config flag off, F013's behaviour is intact."""
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("PUBLICATIONS_INGEST_DIR", "/data/ingest/publications")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "000000:dummy-bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")

    with (
        patch("src.api.routes_ingestion._auto_download_enabled", return_value=False),
        patch("src.api.routes_ingestion.send_alert", new_callable=AsyncMock) as mock_send,
    ):
        response = _client().post(
            "/api/ingestion/publications/notify",
            json={"subject": "Neuer Inhalt - DER AKTIONÄR E-Paper"},
            headers={"x-webhook-secret": "s3cret"},
        )

    assert response.status_code == 202
    assert response.json() == {"publication": "der_aktionaer", "status": "alert_sent"}
    mock_send.assert_awaited_once()
    _config, message = mock_send.call_args.args
    assert "der_aktionaer" in message


def test_notify_publication_starts_auto_download_for_known_magazine(monkeypatch):
    """F078: the webhook answers immediately and hands the browser work to a
    background task — patched here, a real run would launch Chromium."""
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("PUBLICATIONS_INGEST_DIR", "/data/ingest/publications")

    with (
        patch("src.api.routes_ingestion._auto_download_enabled", return_value=True),
        patch(
            "src.api.routes_ingestion._download_and_ingest", new_callable=AsyncMock
        ) as mock_download,
    ):
        response = _client().post(
            "/api/ingestion/publications/notify",
            json={"subject": "Neuer Inhalt - DER AKTIONÄR E-Paper"},
            headers={"x-webhook-secret": "s3cret"},
        )

    assert response.status_code == 202
    assert response.json() == {"publication": "der_aktionaer", "status": "download_started"}
    mock_download.assert_awaited_once()
    magazine, subject = mock_download.call_args.args
    assert magazine.slug == "der_aktionaer"
    assert subject == "Neuer Inhalt - DER AKTIONÄR E-Paper"


def test_notify_publication_unknown_subject_starts_no_download(monkeypatch):
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")

    with patch(
        "src.api.routes_ingestion._download_and_ingest", new_callable=AsyncMock
    ) as mock_download:
        response = _client().post(
            "/api/ingestion/publications/notify",
            json={"subject": "Ihre Rechnung liegt bereit"},
            headers={"x-webhook-secret": "s3cret"},
        )

    assert response.status_code == 422
    mock_download.assert_not_awaited()


def test_notify_musterdepot_rejects_missing_secret(monkeypatch):
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")
    response = _client().post(
        "/api/ingestion/publications/musterdepot-notify",
        json={"subject": "Neue Transaktion", "message_id": "m1", "body_text": "irrelevant"},
    )
    assert response.status_code == 401


def test_notify_musterdepot_rejects_body_without_transaction_line(monkeypatch):
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")
    response = _client().post(
        "/api/ingestion/publications/musterdepot-notify",
        json={"subject": "Neue Transaktion", "message_id": "m1", "body_text": "nothing here"},
        headers={"x-webhook-secret": "s3cret"},
    )
    assert response.status_code == 422


def test_notify_musterdepot_sends_telegram_alert_and_persists(monkeypatch, session):
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "000000:dummy-bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")

    from src.api.routes import get_session

    app.dependency_overrides[get_session] = lambda: session
    try:
        with patch("src.api.routes_ingestion.send_alert", new_callable=AsyncMock) as mock_send:
            response = _client().post(
                "/api/ingestion/publications/musterdepot-notify",
                json={
                    "subject": "Neue Transaktion",
                    "message_id": "msg-42",
                    "body_text": (
                        "Transaktion TEILVERKAUF Moderna – WKN A2N9D9 – 75 Stück zu je 68,31 Euro"
                    ),
                },
                headers={"x-webhook-secret": "s3cret"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json() == {"transactions": 1, "status": "alert_sent"}
    mock_send.assert_awaited_once()

    from sqlalchemy import select

    from src.db.models import MusterdepotTransaction

    rows = session.scalars(
        select(MusterdepotTransaction).where(MusterdepotTransaction.message_id == "msg-42")
    ).all()
    assert len(rows) == 1
    assert rows[0].wkn == "A2N9D9"


def test_notify_newsletter_rejects_missing_secret(monkeypatch):
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")
    response = _client().post(
        "/api/ingestion/newsletter/notify",
        json={
            "sender": "cryptocrunch@m6.morningcrunch.de",
            "subject": "Tokenisierung",
            "message_id": "m1",
            "body_text": "irrelevant",
        },
    )
    assert response.status_code == 401


def test_notify_newsletter_rejects_unknown_sender(monkeypatch):
    """The endpoint takes a whole mail body — an unconfigured sender must not be able
    to write into the research pool through it."""
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")
    response = _client().post(
        "/api/ingestion/newsletter/notify",
        json={
            "sender": "spam@example.com",
            "subject": "Kaufen Sie jetzt",
            "message_id": "m1",
            "body_text": "###### HEADLINES\n\n* **Tipp:** Kaufe alles sofort, ganz sicher",
        },
        headers={"x-webhook-secret": "s3cret"},
    )
    assert response.status_code == 422


def test_notify_newsletter_persists_impulses(monkeypatch, session):
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")

    from src.api.routes import get_session

    body_text = (
        "###### COIN SNAPSHOT\n\n"
        "* \U0001f9d8 **BTC-Bottoming:** $BTC ( - 0.3% )\n"
        " bei $64.800, die Whale-Bestaende wachsen seit Dezember weiter an\n\n"
        "———————————\n\n"
        "###### ANZEIGE\n\n"
        "* **Partner:** Handle alles bei [Partner](https://partner-consumer.sjv.io/x)\n\n"
        "———————————\n\n"
        "Du liest eine reine Textversion. Link:\n"
        "https://m6.morningcrunch.de/p/150-260807\n"
    )

    app.dependency_overrides[get_session] = lambda: session
    try:
        response = _client().post(
            "/api/ingestion/newsletter/notify",
            json={
                "sender": "cryptocrunch <cryptocrunch@m6.morningcrunch.de>",
                "subject": "Wall Street: Preis und Risiken der Tokenisierung",
                "message_id": "msg-150",
                "body_text": body_text,
                "received_at": "2026-08-07T04:01:35+00:00",
            },
            headers={"x-webhook-secret": "s3cret"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json() == {"newsletter": "cryptocrunch", "items": 1, "status": "ingested"}

    from sqlalchemy import select

    from src.db.models import NewsletterItem

    rows = session.scalars(
        select(NewsletterItem).where(NewsletterItem.message_id == "msg-150")
    ).all()
    assert len(rows) == 1
    assert rows[0].instruments == ["BTC/USD"]
    assert rows[0].issue_url == "https://m6.morningcrunch.de/p/150-260807"
    # tz-aware input from n8n, naive DateTime column — must not raise, must not shift.
    assert rows[0].received_at == datetime.datetime(2026, 8, 7, 4, 1, 35)
    assert "Partner" not in rows[0].text


def test_notify_newsletter_accepts_the_rfc2822_date_n8n_actually_sends(monkeypatch, session):
    """F118 regression. The date string below is copied verbatim out of a production
    n8n execution — the IMAP node forwards the mail's `Date` header untouched, which
    is RFC 2822. Until this test existed, every fixture used ISO 8601, so CI was green
    while every real issue since 08.08.2026 bounced off the endpoint with a 422."""
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")

    from src.api.routes import get_session

    body_text = (
        "###### COIN SNAPSHOT\n\n"
        "* \U0001f9d8 **BTC-Bottoming:** $BTC ( - 0.3% )\n"
        " bei $64.800, die Whale-Bestaende wachsen seit Dezember weiter an\n"
    )

    app.dependency_overrides[get_session] = lambda: session
    try:
        response = _client().post(
            "/api/ingestion/newsletter/notify",
            json={
                "sender": "cryptocrunch <cryptocrunch@m6.morningcrunch.de>",
                "subject": "BoE: Digital Pound trifft Stablecoin",
                "message_id": "msg-154",
                "body_text": body_text,
                "received_at": "Thu, 13 Aug 2026 04:01:19 +0000 (UTC)",
            },
            headers={"x-webhook-secret": "s3cret"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202

    from sqlalchemy import select

    from src.db.models import NewsletterItem

    rows = session.scalars(
        select(NewsletterItem).where(NewsletterItem.message_id == "msg-154")
    ).all()
    assert len(rows) == 1
    assert rows[0].received_at == datetime.datetime(2026, 8, 13, 4, 1, 19)


def test_notify_musterdepot_accepts_the_rfc2822_date_and_converts_to_utc(monkeypatch, session):
    """Same mailbox, same header, same parsing — and a non-UTC offset to show the
    conversion, since the column is naive UTC."""
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "000000:dummy-bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")

    from src.api.routes import get_session

    app.dependency_overrides[get_session] = lambda: session
    try:
        with patch("src.api.routes_ingestion.send_alert", new_callable=AsyncMock):
            response = _client().post(
                "/api/ingestion/publications/musterdepot-notify",
                json={
                    "subject": "Neue Transaktion",
                    "message_id": "msg-43",
                    "body_text": (
                        "Transaktion TEILVERKAUF Moderna – WKN A2N9D9 – 75 Stück zu je 68,31 Euro"
                    ),
                    "received_at": "Fri, 14 Aug 2026 15:57:50 +0200",
                },
                headers={"x-webhook-secret": "s3cret"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202

    from sqlalchemy import select

    from src.db.models import MusterdepotTransaction

    rows = session.scalars(
        select(MusterdepotTransaction).where(MusterdepotTransaction.message_id == "msg-43")
    ).all()
    assert len(rows) == 1
    assert rows[0].received_at == datetime.datetime(2026, 8, 14, 13, 57, 50)


def test_notify_newsletter_repairs_n8ns_double_encoded_body(monkeypatch, session):
    """F118 regression. n8n's IMAP node returns body parts without honouring their
    charset, so the pool filled up with 'Bestände' and — worse — the '—' separator
    lines arrived mangled, which stopped the parser from recognising them and turned
    each one into its own impulse."""
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")

    from src.api.routes import get_session

    body_text = (
        "###### COIN SNAPSHOT\n\n"
        "* \U0001f9d8 **BTC-Bottoming:** $BTC ( - 0.3% )\n"
        " bei $64.800, die Whale-Bestände wachsen seit Dezember weiter an\n\n"
        "———————————\n\n"
        "###### ANZEIGE\n\n"
        "* **Partner:** Handle alles bei [Partner](https://partner-consumer.sjv.io/x)\n"
    )
    # Exactly what the box receives: the correct body, decoded as Latin-1 by n8n.
    damaged = body_text.encode("utf-8").decode("latin-1")
    assert "BestÃ¤nde" in damaged

    app.dependency_overrides[get_session] = lambda: session
    try:
        response = _client().post(
            "/api/ingestion/newsletter/notify",
            json={
                "sender": "cryptocrunch@m6.morningcrunch.de",
                "subject": "BTC-Bottoming",
                "message_id": "msg-broken-encoding",
                "body_text": damaged,
            },
            headers={"x-webhook-secret": "s3cret"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    # One impulse, not two: the separator is a separator again, not an impulse of its own.
    assert response.json()["items"] == 1

    from sqlalchemy import select

    from src.db.models import NewsletterItem

    rows = session.scalars(
        select(NewsletterItem).where(NewsletterItem.message_id == "msg-broken-encoding")
    ).all()
    assert len(rows) == 1
    assert "Bestände" in rows[0].text
    assert "Ã" not in rows[0].text


def test_notify_newsletter_leaves_an_intact_body_alone(monkeypatch, session):
    """The repair must not fire on text that was never damaged — an emoji cannot be
    encoded as Latin-1, which is what keeps the round-trip from touching these bodies."""
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")

    from src.api.routes import get_session

    body_text = (
        "###### COIN SNAPSHOT\n\n"
        "* \U0001f9d8 **BTC-Bottoming:** $BTC ( - 0.3% )\n"
        " bei $64.800, die Whale-Bestände wachsen seit Dezember weiter an\n"
    )

    app.dependency_overrides[get_session] = lambda: session
    try:
        response = _client().post(
            "/api/ingestion/newsletter/notify",
            json={
                "sender": "cryptocrunch@m6.morningcrunch.de",
                "subject": "BTC-Bottoming",
                "message_id": "msg-intact-encoding",
                "body_text": body_text,
            },
            headers={"x-webhook-secret": "s3cret"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202

    from sqlalchemy import select

    from src.db.models import NewsletterItem

    rows = session.scalars(
        select(NewsletterItem).where(NewsletterItem.message_id == "msg-intact-encoding")
    ).all()
    assert len(rows) == 1
    assert "Bestände" in rows[0].text


def test_repair_mail_body_keeps_plain_german_text_untouched():
    """A body with umlauts but no emoji is the case the round-trip could plausibly
    get wrong: Latin-1 encodes it fine, so only the UTF-8 decode step rejects it."""
    from src.api.routes_ingestion import _repair_mail_body

    assert _repair_mail_body("Hütten und Bestände") == "Hütten und Bestände"
    assert _repair_mail_body("HÃ¼tten und BestÃ¤nde") == "Hütten und Bestände"


def test_notify_newsletter_still_rejects_an_unparsable_date(monkeypatch):
    """The tolerance is for RFC 2822, not for anything at all: a broken date has to
    stay a 422 rather than land in the pool timestamped 'now'."""
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")
    response = _client().post(
        "/api/ingestion/newsletter/notify",
        json={
            "sender": "cryptocrunch@m6.morningcrunch.de",
            "subject": "Tokenisierung",
            "message_id": "m1",
            "body_text": "irrelevant",
            "received_at": "gestern Abend",
        },
        headers={"x-webhook-secret": "s3cret"},
    )
    assert response.status_code == 422
