"""F078 — auto-download selection logic, exercised against a fake portal.

The real Playwright path (`PlaywrightBoersenmedienPortal`, `run_auto_download_live`)
isn't covered here — no browser in the default test run, same split as F012.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from src.ingestion.publications_download import (
    BoersenmedienSessionExpired,
    DownloadResult,
    IssueLink,
    IssueNotFound,
    SubscriptionCard,
    SubscriptionNotFound,
    download_latest_issue,
    format_download_success,
    parse_active_flag,
    select_latest_issue,
    select_subscription,
    target_pdf_path,
)
from src.ingestion.publications_notify import Magazine, format_fallback_alert

_AKTIONAER = Magazine(
    slug="der_aktionaer",
    subject_keyword="DER AKTIONÄR",
    overview_url="https://konto.boersenmedien.com/produkte/abonnements",
)

_ACTIVE_CARD = SubscriptionCard(
    title="DER AKTIONÄR E-Paper",
    issues_url="https://konto.boersenmedien.com/produkte/abonnements/2877536/A-10546504/ausgaben",
    active=True,
)


class FakePortal:
    def __init__(
        self,
        cards: list[SubscriptionCard] | None = None,
        issues: list[IssueLink] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._cards = cards if cards is not None else [_ACTIVE_CARD]
        self._issues = (
            issues
            if issues is not None
            else [
                IssueLink(label="DER AKTIONÄR 31/26", href="/produkte/content/13601/download"),
                IssueLink(label="DER AKTIONÄR 30/26", href="/produkte/content/13600/download"),
            ]
        )
        self._raises = raises
        self.downloaded: list[tuple[str, Path]] = []

    def list_subscriptions(self) -> list[SubscriptionCard]:
        if self._raises is not None:
            raise self._raises
        return self._cards

    def list_issue_downloads(self, issues_url: str) -> list[IssueLink]:
        return self._issues

    def download(self, href: str, target: Path) -> None:
        self.downloaded.append((href, target))
        target.write_bytes(b"%PDF-1.7 fake")


def test_select_subscription_matches_keyword_case_insensitively():
    cards = [
        SubscriptionCard(title="BÖRSE ONLINE E-Paper", issues_url="/bo", active=True),
        SubscriptionCard(title="der aktionär e-paper", issues_url="/da", active=True),
    ]
    assert select_subscription(cards, "DER AKTIONÄR").issues_url == "/da"


def test_select_subscription_prefers_active_over_expired_same_title():
    cards = [
        SubscriptionCard(title="DER AKTIONÄR E-Paper", issues_url="/old", active=False),
        SubscriptionCard(title="DER AKTIONÄR E-Paper", issues_url="/new", active=True),
    ]
    assert select_subscription(cards, "DER AKTIONÄR").issues_url == "/new"


def test_select_subscription_rejects_inactive_only_match():
    cards = [SubscriptionCard(title="DER AKTIONÄR E-Paper", issues_url="/old", active=False)]
    with pytest.raises(SubscriptionNotFound):
        select_subscription(cards, "DER AKTIONÄR")


def test_select_subscription_rejects_missing_magazine():
    cards = [SubscriptionCard(title="BÖRSE ONLINE E-Paper", issues_url="/bo", active=True)]
    with pytest.raises(SubscriptionNotFound):
        select_subscription(cards, "Euro am Sonntag")


def test_parse_active_flag_distinguishes_aktiv_from_inaktiv():
    assert parse_active_flag("DER AKTIONÄR E-Paper AKTIV Abo-Nummer A-1") is True
    assert parse_active_flag("DER AKTIONÄR E-Paper INAKTIV Abo-Nummer A-1") is False


def test_select_latest_issue_takes_first_in_document_order():
    links = [
        IssueLink(label="DER AKTIONÄR 31/26", href="/produkte/content/13601/download"),
        IssueLink(label="DER AKTIONÄR 30/26", href="/produkte/content/13600/download"),
    ]
    assert select_latest_issue(links).label == "DER AKTIONÄR 31/26"


def test_select_latest_issue_rejects_empty_list():
    with pytest.raises(IssueNotFound):
        select_latest_issue([])


def test_target_pdf_path_follows_f011_convention(tmp_path):
    path = target_pdf_path(tmp_path, "der_aktionaer", datetime.date(2026, 7, 22))
    assert path == tmp_path / "der_aktionaer" / "2026-07-22.pdf"


def test_download_latest_issue_writes_pdf_to_convention_path(tmp_path):
    portal = FakePortal()

    result = download_latest_issue(portal, _AKTIONAER, tmp_path, datetime.date(2026, 7, 22))

    expected = tmp_path / "der_aktionaer" / "2026-07-22.pdf"
    assert result == DownloadResult(
        magazine_slug="der_aktionaer",
        issue_label="DER AKTIONÄR 31/26",
        pdf_path=expected,
        skipped=False,
    )
    assert expected.read_bytes().startswith(b"%PDF")
    assert portal.downloaded == [("/produkte/content/13601/download", expected)]


def test_download_latest_issue_creates_missing_publication_directory(tmp_path):
    download_latest_issue(FakePortal(), _AKTIONAER, tmp_path, datetime.date(2026, 7, 22))
    assert (tmp_path / "der_aktionaer").is_dir()


def test_download_latest_issue_skips_when_target_already_exists(tmp_path):
    existing = tmp_path / "der_aktionaer" / "2026-07-22.pdf"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"%PDF-1.7 already here")
    portal = FakePortal()

    result = download_latest_issue(portal, _AKTIONAER, tmp_path, datetime.date(2026, 7, 22))

    assert result.skipped is True
    assert result.pdf_path == existing
    assert portal.downloaded == []
    assert existing.read_bytes() == b"%PDF-1.7 already here"


def test_download_latest_issue_propagates_expired_session(tmp_path):
    portal = FakePortal(raises=BoersenmedienSessionExpired("session gone"))
    with pytest.raises(BoersenmedienSessionExpired):
        download_latest_issue(portal, _AKTIONAER, tmp_path, datetime.date(2026, 7, 22))


def test_format_download_success_names_issue_and_article_count(tmp_path):
    result = DownloadResult(
        magazine_slug="der_aktionaer",
        issue_label="DER AKTIONÄR 31/26",
        pdf_path=tmp_path / "der_aktionaer" / "2026-07-22.pdf",
        skipped=False,
    )
    message = format_download_success(result, 142)
    assert "DER AKTIONÄR 31/26" in message
    assert "142" in message
    assert "2026-07-22.pdf" in message


def test_format_fallback_alert_includes_failure_reason():
    message = format_fallback_alert(
        _AKTIONAER,
        "Neuer Inhalt - DER AKTIONÄR E-Paper",
        Path("/data/ingest/publications"),
        today=datetime.date(2026, 7, 22),
        reason="Stored session no longer authenticates",
    )
    assert "Auto-Download fehlgeschlagen" in message
    assert "Stored session no longer authenticates" in message
    assert "/data/ingest/publications/der_aktionaer/2026-07-22.pdf" in message


def test_format_fallback_alert_without_reason_is_unchanged():
    message = format_fallback_alert(
        _AKTIONAER,
        "Neuer Inhalt - DER AKTIONÄR E-Paper",
        Path("/data/ingest/publications"),
        today=datetime.date(2026, 7, 22),
    )
    assert "Auto-Download fehlgeschlagen" not in message
    assert message.startswith("📰 Neue Ausgabe erkannt:")
