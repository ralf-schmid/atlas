import datetime
from pathlib import Path

from src.ingestion.publications_notify import (
    Magazine,
    format_fallback_alert,
    identify_magazine,
    load_magazines,
)

_MAGAZINES = [
    Magazine(
        slug="euro_am_sonntag",
        subject_keyword="Euro am Sonntag",
        overview_url="https://konto.boersenmedien.com/produkte/abonnements/2778324/A-10529198/ausgaben",
    ),
    Magazine(
        slug="boerse_online",
        subject_keyword="BÖRSE ONLINE",
        overview_url="https://konto.boersenmedien.com/produkte/abonnements/2778326/A-10510298/ausgaben",
    ),
    Magazine(
        slug="der_aktionaer",
        subject_keyword="DER AKTIONÄR",
        overview_url="https://konto.boersenmedien.com/produkte/abonnements/2778322/A-10510232/ausgaben",
    ),
]


def test_load_magazines_reads_real_config():
    magazines = load_magazines()
    assert {m.slug for m in magazines} == {"euro_am_sonntag", "boerse_online", "der_aktionaer"}


def test_identify_magazine_matches_euro_am_sonntag_with_changing_issue_number():
    magazine = identify_magazine("Neuer Inhalt - Euro am Sonntag 23/26", _MAGAZINES)
    assert magazine is not None
    assert magazine.slug == "euro_am_sonntag"


def test_identify_magazine_matches_boerse_online():
    magazine = identify_magazine("Neuer Inhalt - BÖRSE ONLINE E-Paper", _MAGAZINES)
    assert magazine is not None
    assert magazine.slug == "boerse_online"


def test_identify_magazine_matches_der_aktionaer():
    magazine = identify_magazine("Neuer Inhalt - DER AKTIONÄR E-Paper", _MAGAZINES)
    assert magazine is not None
    assert magazine.slug == "der_aktionaer"


def test_identify_magazine_is_case_insensitive():
    magazine = identify_magazine("neuer inhalt - börse online e-paper", _MAGAZINES)
    assert magazine is not None
    assert magazine.slug == "boerse_online"


def test_identify_magazine_returns_none_for_unrelated_subject():
    assert identify_magazine("Ihre Rechnung liegt bereit", _MAGAZINES) is None


def test_format_fallback_alert_includes_target_path_and_overview_url():
    magazine = _MAGAZINES[0]
    message = format_fallback_alert(
        magazine,
        "Neuer Inhalt - Euro am Sonntag 23/26",
        base_dir=Path("/data/ingest/publications"),
        today=datetime.date(2026, 7, 6),
    )

    assert "Neuer Inhalt - Euro am Sonntag 23/26" in message
    assert "/data/ingest/publications/euro_am_sonntag/2026-07-06.pdf" in message
    assert magazine.overview_url in message
