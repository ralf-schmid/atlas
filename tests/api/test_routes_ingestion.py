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


def test_notify_publication_sends_telegram_alert_for_known_magazine(monkeypatch):
    monkeypatch.setenv("N8N_PUBLICATIONS_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("PUBLICATIONS_INGEST_DIR", "/data/ingest/publications")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "000000:dummy-bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")

    with patch("src.api.routes_ingestion.send_alert", new_callable=AsyncMock) as mock_send:
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
