"""See docs/features/F035-ingestion-scheduler-activation.md §3. `register_ingestion_jobs`
is never `.start()`ed here — pure job-registration/non-fatal-job-contract inspection,
no real time trigger (mirrors tests/orchestrator/test_scheduler.py)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from src.ingestion import scheduler as scheduler_module
from src.ingestion.publications_download import BoersenmedienSessionExpired
from src.ingestion.scheduler import register_ingestion_jobs
from src.telegram.config import TelegramConfig

_SESSION_STATE = Path("/data/ingest/boersenmedien/session_state.json")


@pytest.fixture(autouse=True)
def _reset_failure_counters():
    scheduler_module._consecutive_failures.clear()
    yield
    scheduler_module._consecutive_failures.clear()


@pytest.fixture(autouse=True)
def _boersenmedien_session_state(monkeypatch):
    """F119 only registers its job when this is set; on the box it comes from
    docker-compose.yml. Autouse so the registration tests see the same world the
    scheduler container does."""
    monkeypatch.setenv("BOERSENMEDIEN_SESSION_STATE", str(_SESSION_STATE))


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
        "ingestion-alpaca-news",
        "ingestion-alpaca-screener",
        "ingestion-publications-session-check",
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


def _session_check_job(monkeypatch, outcome) -> list[str]:
    """Runs the F119 job with `run_session_check_live` replaced by `outcome`, and
    returns the Telegram texts it sent."""
    monkeypatch.setattr(scheduler_module, "run_session_check_live", outcome)
    sent: list[str] = []

    async def _fake_send_alert(config: object, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("src.telegram.alerts.send_alert", _fake_send_alert)
    return sent


def test_session_check_alerts_on_the_first_expired_run(monkeypatch, _fake_telegram_config) -> None:
    """The whole point of F119: at one run per week, waiting for a second failure
    would put the alert after the next issue instead of before it."""

    def _expired(*a: object, **k: object) -> None:
        raise BoersenmedienSessionExpired("landed on https://login.boersenmedien.de/?apiKey=x")

    sent = _session_check_job(monkeypatch, _expired)

    scheduler_module._publications_session_check_job(_SESSION_STATE)

    assert len(sent) == 1
    assert "Session abgelaufen" in sent[0]
    assert "scripts/boersenmedien_session.py" in sent[0]
    assert "login.boersenmedien.de" in sent[0]


def test_session_check_keeps_reminding_while_the_session_stays_dead(
    monkeypatch, _fake_telegram_config
) -> None:
    """Not deduplicated: an unrenewed session is still broken next week, and silence
    would read as 'fixed'."""

    def _expired(*a: object, **k: object) -> None:
        raise BoersenmedienSessionExpired("still dead")

    sent = _session_check_job(monkeypatch, _expired)

    scheduler_module._publications_session_check_job(_SESSION_STATE)
    scheduler_module._publications_session_check_job(_SESSION_STATE)

    assert len(sent) == 2


def test_session_check_stays_silent_while_the_session_is_valid(
    monkeypatch, _fake_telegram_config
) -> None:
    sent = _session_check_job(monkeypatch, lambda *a, **k: [object(), object()])

    scheduler_module._publications_session_check_job(_SESSION_STATE)

    assert sent == []


def test_session_check_treats_a_broken_portal_as_an_ordinary_job_failure(
    monkeypatch, _fake_telegram_config
) -> None:
    """A portal outage or a Playwright crash is not an expired session — that one
    keeps the usual 2-in-a-row contract, so a single hiccup stays quiet."""

    def _raise(*a: object, **k: object) -> None:
        raise RuntimeError("browser crashed")

    sent = _session_check_job(monkeypatch, _raise)

    scheduler_module._publications_session_check_job(_SESSION_STATE)
    assert sent == []

    scheduler_module._publications_session_check_job(_SESSION_STATE)
    assert len(sent) == 1
    assert "2x in Folge" in sent[0]
    assert "Boersenmedien-Session-Check" in sent[0]


def test_session_check_job_is_not_registered_when_disabled(tmp_path) -> None:
    import yaml

    config = yaml.safe_load(scheduler_module._DEFAULT_CONFIG_PATH.read_text())
    config["schedule"]["publications_session_check"]["enabled"] = False
    config_path = tmp_path / "ingestion.yaml"
    config_path.write_text(yaml.safe_dump(config))

    scheduler = BackgroundScheduler()
    register_ingestion_jobs(scheduler, session_factory=lambda: None, config_path=config_path)  # type: ignore[arg-type]

    assert "ingestion-publications-session-check" not in {job.id for job in scheduler.get_jobs()}


def test_session_check_job_is_not_registered_without_its_env_var(monkeypatch, caplog) -> None:
    """The gap that shipped with F119: the variable lived on `api` but not on
    `scheduler`. Failing at registration puts it in the startup log instead of in a
    generic failure alert two weekly runs later."""
    monkeypatch.delenv("BOERSENMEDIEN_SESSION_STATE")

    scheduler = BackgroundScheduler()
    caplog.set_level(logging.ERROR, logger="src.ingestion.scheduler")

    register_ingestion_jobs(scheduler, session_factory=lambda: None)  # type: ignore[arg-type]

    assert "ingestion-publications-session-check" not in {job.id for job in scheduler.get_jobs()}
    assert "BOERSENMEDIEN_SESSION_STATE is not set" in caplog.text


def test_session_check_runs_weekly_on_the_configured_day() -> None:
    """Monday, so an alert has two days of lead time before DER AKTIONÄR arrives."""
    scheduler = BackgroundScheduler()

    register_ingestion_jobs(scheduler, session_factory=lambda: None)  # type: ignore[arg-type]

    job = scheduler.get_job("ingestion-publications-session-check")
    fields = {field.name: str(field) for field in job.trigger.fields}
    assert fields["day_of_week"] == "mon"
    assert (fields["hour"], fields["minute"]) == ("7", "30")
    assert str(job.trigger.timezone) == "America/New_York"


class _FakeSession:
    """Minimal context-manager stand-in — the jobs under test either raise before
    touching the session or only need `.commit()` to be a no-op."""

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def commit(self) -> None:
        pass
