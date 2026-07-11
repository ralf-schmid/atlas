"""See docs/features/F035-ingestion-scheduler-activation.md §3. `register_ingestion_jobs`
is never `.start()`ed here — pure job-registration/non-fatal-job-contract inspection,
no real time trigger (mirrors tests/orchestrator/test_scheduler.py)."""

from __future__ import annotations

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from src.ingestion import scheduler as scheduler_module
from src.ingestion.scheduler import register_ingestion_jobs
from src.telegram.config import TelegramConfig


@pytest.fixture(autouse=True)
def _reset_failure_counters():
    scheduler_module._consecutive_failures.clear()
    yield
    scheduler_module._consecutive_failures.clear()


@pytest.fixture
def _fake_telegram_config(monkeypatch):
    monkeypatch.setattr(
        scheduler_module,
        "load_telegram_config",
        lambda: TelegramConfig(bot_token="test-token", allowed_chat_id=1),
    )


def test_register_ingestion_jobs_registers_six_jobs_reddit_disabled() -> None:
    """Reddit is disabled by default (config/ingestion.yaml) until F039 credentials
    are provisioned — see docs/deployment.md."""
    scheduler = BackgroundScheduler()

    register_ingestion_jobs(scheduler, session_factory=lambda: None)  # type: ignore[arg-type]

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {
        "ingestion-edgar",
        "ingestion-vulture-screener",
        "ingestion-aktienfinder-screener-discovery",
        "ingestion-market-data",
        "ingestion-crypto-market-data",
        "ingestion-aktienfinder",
        "ingestion-coingecko",
        "ingestion-aktienfinder-blog",
        "ingestion-market-news",
    }


def test_register_ingestion_jobs_registers_reddit_when_enabled(tmp_path) -> None:
    import yaml

    config = yaml.safe_load(scheduler_module._DEFAULT_CONFIG_PATH.read_text())
    config["schedule"]["reddit"]["enabled"] = True
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(yaml.safe_dump(config))

    scheduler = BackgroundScheduler()
    register_ingestion_jobs(
        scheduler,
        session_factory=lambda: None,
        config_path=config_path,  # type: ignore[arg-type]
    )

    assert "ingestion-reddit" in {job.id for job in scheduler.get_jobs()}


def test_screener_and_market_data_jobs_use_configured_timezone() -> None:
    scheduler = BackgroundScheduler()

    register_ingestion_jobs(scheduler, session_factory=lambda: None)  # type: ignore[arg-type]

    screener_job = scheduler.get_job("ingestion-vulture-screener")
    assert str(screener_job.trigger.timezone) == "America/New_York"


def test_edgar_job_does_not_alert_on_first_failure(monkeypatch, _fake_telegram_config) -> None:
    def _raise(*a: object, **k: object) -> None:
        raise RuntimeError("feed unreachable")

    monkeypatch.setattr(scheduler_module, "run_current_filings_sync", _raise)
    sent = []

    async def _fake_send_alert(config: object, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("src.telegram.alerts.send_alert", _fake_send_alert)

    scheduler_module._edgar_job(lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH)

    assert sent == []


def test_edgar_job_alerts_on_second_consecutive_failure(monkeypatch, _fake_telegram_config) -> None:
    def _raise(*a: object, **k: object) -> None:
        raise RuntimeError("feed unreachable")

    monkeypatch.setattr(scheduler_module, "run_current_filings_sync", _raise)
    sent = []

    async def _fake_send_alert(config: object, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("src.telegram.alerts.send_alert", _fake_send_alert)

    scheduler_module._edgar_job(lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH)
    scheduler_module._edgar_job(lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH)

    assert len(sent) == 1
    assert "2x in Folge" in sent[0]
    assert "EDGAR-RSS-Sync" in sent[0]


def test_market_data_job_resets_failure_streak_on_success(monkeypatch) -> None:
    monkeypatch.setattr(scheduler_module, "resolve_symbol_universe", lambda session, seed: seed)

    def _raise(*a: object, **k: object) -> None:
        raise RuntimeError("x")

    monkeypatch.setattr(scheduler_module, "run_daily_sync", _raise)
    scheduler_module._market_data_job(lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH)
    assert scheduler_module._consecutive_failures["market_data_sync"] == 1

    monkeypatch.setattr(scheduler_module, "run_daily_sync", lambda *a, **k: 0)
    scheduler_module._market_data_job(lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH)

    assert scheduler_module._consecutive_failures["market_data_sync"] == 0


def test_crypto_market_data_job_alerts_on_second_consecutive_failure(
    monkeypatch, _fake_telegram_config
) -> None:
    def _raise(*a: object, **k: object) -> None:
        raise RuntimeError("api unreachable")

    monkeypatch.setattr(scheduler_module, "run_daily_crypto_sync", _raise)
    sent = []

    async def _fake_send_alert(config: object, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("src.telegram.alerts.send_alert", _fake_send_alert)

    scheduler_module._crypto_market_data_job(
        lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH
    )
    scheduler_module._crypto_market_data_job(
        lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH
    )

    assert len(sent) == 1
    assert "Krypto-Markt-Bar-Sync" in sent[0]


def test_aktienfinder_screener_discovery_job_alerts_on_second_consecutive_failure(
    monkeypatch, _fake_telegram_config
) -> None:
    def _raise(*a: object, **k: object) -> None:
        raise RuntimeError("login failed")

    monkeypatch.setattr(scheduler_module, "run_screener_discovery_configured", _raise)
    sent = []

    async def _fake_send_alert(config: object, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("src.telegram.alerts.send_alert", _fake_send_alert)

    scheduler_module._aktienfinder_screener_discovery_job(
        lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH
    )
    scheduler_module._aktienfinder_screener_discovery_job(
        lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH
    )

    assert len(sent) == 1
    assert "aktienfinder-Screener-Discovery" in sent[0]


def test_aktienfinder_job_alerts_on_second_consecutive_failure(
    monkeypatch, _fake_telegram_config
) -> None:
    def _raise(*a: object, **k: object) -> None:
        raise RuntimeError("login failed")

    monkeypatch.setattr(scheduler_module, "run_daily_grab_configured", _raise)
    sent = []

    async def _fake_send_alert(config: object, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("src.telegram.alerts.send_alert", _fake_send_alert)

    scheduler_module._aktienfinder_job(
        lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH
    )
    scheduler_module._aktienfinder_job(
        lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH
    )

    assert len(sent) == 1
    assert "aktienfinder-Snapshot" in sent[0]


def test_coingecko_job_alerts_on_second_consecutive_failure(
    monkeypatch, _fake_telegram_config
) -> None:
    def _raise(*a: object, **k: object) -> None:
        raise RuntimeError("api unreachable")

    monkeypatch.setattr(scheduler_module, "run_coingecko_sync", _raise)
    sent = []

    async def _fake_send_alert(config: object, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("src.telegram.alerts.send_alert", _fake_send_alert)

    scheduler_module._coingecko_job(lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH)
    scheduler_module._coingecko_job(lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH)

    assert len(sent) == 1
    assert "CoinGecko-BTC-Dominanz" in sent[0]


def test_reddit_job_alerts_on_second_consecutive_failure(
    monkeypatch, _fake_telegram_config
) -> None:
    def _raise(*a: object, **k: object) -> None:
        raise RuntimeError("token request failed")

    monkeypatch.setattr(scheduler_module, "run_reddit_sync", _raise)
    sent = []

    async def _fake_send_alert(config: object, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("src.telegram.alerts.send_alert", _fake_send_alert)

    scheduler_module._reddit_job(lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH)
    scheduler_module._reddit_job(lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH)

    assert len(sent) == 1
    assert "Reddit-Sync" in sent[0]


def test_aktienfinder_blog_job_alerts_on_second_consecutive_failure(
    monkeypatch, _fake_telegram_config
) -> None:
    def _raise(*a: object, **k: object) -> None:
        raise RuntimeError("fetch failed")

    monkeypatch.setattr(scheduler_module, "run_aktienfinder_blog_sync", _raise)
    sent = []

    async def _fake_send_alert(config: object, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("src.telegram.alerts.send_alert", _fake_send_alert)

    scheduler_module._aktienfinder_blog_job(
        lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH
    )
    scheduler_module._aktienfinder_blog_job(
        lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH
    )

    assert len(sent) == 1
    assert "aktienfinder-Blog-Sync" in sent[0]


def test_market_news_job_alerts_on_second_consecutive_failure(
    monkeypatch, _fake_telegram_config
) -> None:
    def _raise(*a: object, **k: object) -> None:
        raise RuntimeError("fetch failed")

    monkeypatch.setattr(scheduler_module, "run_market_news_sync", _raise)
    sent = []

    async def _fake_send_alert(config: object, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("src.telegram.alerts.send_alert", _fake_send_alert)

    scheduler_module._market_news_job(lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH)
    scheduler_module._market_news_job(lambda: _FakeSession(), scheduler_module._DEFAULT_CONFIG_PATH)

    assert len(sent) == 1
    assert "Market-News-Sync" in sent[0]


class _FakeSession:
    """Minimal context-manager stand-in — the jobs under test either raise before
    touching the session or only need `.commit()` to be a no-op."""

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def commit(self) -> None:
        pass
