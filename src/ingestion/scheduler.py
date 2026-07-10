"""Wires the ingestion `run_*` entry points (EDGAR, VULTURE-Screener, Markt-Bar-
Sync) into the same long-lived APScheduler instance the orchestrator scheduler
already builds — see docs/features/F035-ingestion-scheduler-activation.md.

Own non-fatal-job contract (try/except + consecutive-failure counter + Telegram
alert after 2 in a row), deliberately *not* sharing state with
`src.orchestrator.scheduler` — that module's tests assert on its private
`_consecutive_failures` dict and `_run_cycle_job`'s exact log call directly (see
F029), so refactoring a shared helper out of well-tested code wasn't worth the
risk for ~15 lines of duplication (F035 §2 Design-Entscheidungen).
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from collections.abc import Callable
from pathlib import Path

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from src.ingestion.aktienfinder_blog import run_aktienfinder_blog_sync
from src.ingestion.aktienfinder_grabbing import run_daily_grab_configured
from src.ingestion.coingecko_global import run_coingecko_sync
from src.ingestion.edgar_rss import run_current_filings_sync
from src.ingestion.market_data_sync import run_daily_sync
from src.ingestion.reddit_sentiment import run_reddit_sync
from src.ingestion.vulture_screener import run_daily_screener
from src.ingestion.yahoo_finance_news import run_market_news_sync
from src.orchestrator.symbol_universe import resolve_symbol_universe
from src.telegram.config import load_config as load_telegram_config

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"

_CONSECUTIVE_FAILURE_ALERT_THRESHOLD = 2
_consecutive_failures: dict[str, int] = {}


def register_ingestion_jobs(
    scheduler: BackgroundScheduler,
    session_factory: Callable[[], Session],
    config_path: Path = _DEFAULT_CONFIG_PATH,
) -> None:
    config = yaml.safe_load(config_path.read_text())
    schedule = config["schedule"]
    timezone = schedule["timezone"]

    scheduler.add_job(
        _edgar_job,
        trigger="interval",
        minutes=schedule["edgar_rss"]["interval_minutes"],
        args=[session_factory, config_path],
        id="ingestion-edgar",
        replace_existing=True,
    )

    hour, minute = _parse_time(schedule["vulture_screener"]["time"])
    scheduler.add_job(
        _screener_job,
        trigger="cron",
        hour=hour,
        minute=minute,
        timezone=timezone,
        args=[session_factory, config_path],
        id="ingestion-vulture-screener",
        replace_existing=True,
    )

    hour, minute = _parse_time(schedule["market_data_sync"]["time"])
    scheduler.add_job(
        _market_data_job,
        trigger="cron",
        hour=hour,
        minute=minute,
        timezone=timezone,
        args=[session_factory, config_path],
        id="ingestion-market-data",
        replace_existing=True,
    )

    hour, minute = _parse_time(schedule["aktienfinder"]["time"])
    scheduler.add_job(
        _aktienfinder_job,
        trigger="cron",
        hour=hour,
        minute=minute,
        timezone=timezone,
        args=[session_factory, config_path],
        id="ingestion-aktienfinder",
        replace_existing=True,
    )

    scheduler.add_job(
        _coingecko_job,
        trigger="interval",
        minutes=schedule["coingecko"]["interval_minutes"],
        args=[session_factory, config_path],
        id="ingestion-coingecko",
        replace_existing=True,
    )

    if schedule["reddit"].get("enabled", True):
        scheduler.add_job(
            _reddit_job,
            trigger="interval",
            minutes=schedule["reddit"]["interval_minutes"],
            args=[session_factory, config_path],
            id="ingestion-reddit",
            replace_existing=True,
        )

    hour, minute = _parse_time(schedule["aktienfinder_blog"]["time"])
    scheduler.add_job(
        _aktienfinder_blog_job,
        trigger="cron",
        hour=hour,
        minute=minute,
        timezone=timezone,
        args=[session_factory, config_path],
        id="ingestion-aktienfinder-blog",
        replace_existing=True,
    )

    scheduler.add_job(
        _market_news_job,
        trigger="interval",
        minutes=schedule["market_news"]["interval_minutes"],
        args=[session_factory, config_path],
        id="ingestion-market-news",
        replace_existing=True,
    )


def _edgar_job(session_factory: Callable[[], Session], config_path: Path) -> None:
    def _run() -> None:
        with session_factory() as session:
            run_current_filings_sync(session, config_path=config_path)
            session.commit()

    _run_with_failure_alert("edgar_rss", "EDGAR-RSS-Sync", _run)


def _screener_job(session_factory: Callable[[], Session], config_path: Path) -> None:
    def _run() -> None:
        with session_factory() as session:
            run_daily_screener(session, datetime.date.today(), config_path=config_path)
            session.commit()

    _run_with_failure_alert("vulture_screener", "VULTURE-Screener", _run)


def _market_data_job(session_factory: Callable[[], Session], config_path: Path) -> None:
    def _run() -> None:
        with session_factory() as session:
            config = yaml.safe_load(config_path.read_text())
            market_data_config = config["market_data"]
            seed_watchlist: list[str] = market_data_config["watchlist"]
            lookback_days: int = market_data_config.get("lookback_days", 1)
            watchlist = resolve_symbol_universe(session, seed_watchlist)
            run_daily_sync(
                session,
                datetime.date.today(),
                config_path=config_path,
                watchlist_override=watchlist,
                lookback_days=lookback_days,
            )
            session.commit()

    _run_with_failure_alert("market_data_sync", "Markt-Bar-Sync", _run)


def _aktienfinder_job(session_factory: Callable[[], Session], config_path: Path) -> None:
    def _run() -> None:
        with session_factory() as session:
            run_daily_grab_configured(session, datetime.date.today(), config_path=config_path)
            session.commit()

    _run_with_failure_alert("aktienfinder", "aktienfinder-Snapshot", _run)


def _coingecko_job(session_factory: Callable[[], Session], config_path: Path) -> None:
    def _run() -> None:
        with session_factory() as session:
            run_coingecko_sync(session, config_path=config_path)
            session.commit()

    _run_with_failure_alert("coingecko", "CoinGecko-BTC-Dominanz", _run)


def _reddit_job(session_factory: Callable[[], Session], config_path: Path) -> None:
    def _run() -> None:
        with session_factory() as session:
            run_reddit_sync(session, config_path=config_path)
            session.commit()

    _run_with_failure_alert("reddit", "Reddit-Sync", _run)


def _aktienfinder_blog_job(session_factory: Callable[[], Session], config_path: Path) -> None:
    def _run() -> None:
        with session_factory() as session:
            run_aktienfinder_blog_sync(session, config_path=config_path)
            session.commit()

    _run_with_failure_alert("aktienfinder_blog", "aktienfinder-Blog-Sync", _run)


def _market_news_job(session_factory: Callable[[], Session], config_path: Path) -> None:
    def _run() -> None:
        with session_factory() as session:
            run_market_news_sync(session, config_path=config_path)
            session.commit()

    _run_with_failure_alert("market_news", "Market-News-Sync", _run)


def _run_with_failure_alert(job_key: str, job_label: str, fn: Callable[[], None]) -> None:
    try:
        fn()
        _consecutive_failures[job_key] = 0
    except Exception:
        logger.error("%s failed", job_label, exc_info=True, extra={"job_key": job_key})
        failure_count = _consecutive_failures.get(job_key, 0) + 1
        _consecutive_failures[job_key] = failure_count
        if failure_count >= _CONSECUTIVE_FAILURE_ALERT_THRESHOLD:
            _consecutive_failures[job_key] = 0  # re-arm: alert again after 2 more fails
            _send_failure_alert(job_label, failure_count)


def _send_failure_alert(job_label: str, failure_count: int) -> None:
    """Best-effort — a Telegram outage must not take down the scheduler thread
    either (same non-fatal contract as the job failure itself)."""
    from src.telegram.alerts import send_alert

    try:
        telegram_config = load_telegram_config()
        text = f"⚠️ ATLAS-Ingestion {job_label} ist {failure_count}x in Folge fehlgeschlagen."
        asyncio.run(send_alert(telegram_config, text))
    except Exception:
        logger.error("failed to send ingestion-failure Telegram alert", exc_info=True)


def _parse_time(value: str) -> tuple[int, int]:
    hour_str, minute_str = value.split(":")
    return int(hour_str), int(minute_str)
