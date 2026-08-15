"""`.eml` adapter for the newsletter catch-up path — F117 §4.

The parsing here is the only new logic; everything downstream is the pipeline the
webhook already uses. So these tests concentrate on the ways a real mail file
differs from the clean string the webhook receives: multipart, quoted-printable,
charsets, a display name around the address, and a missing plain-text part.
"""

from __future__ import annotations

import datetime
from email.message import EmailMessage
from pathlib import Path

import pytest

from src.ingestion.crypto_newsletter import identify_newsletter, load_newsletters
from src.ingestion.newsletter_eml import EmlError, parse_eml, scan_eml_directory

_BODY = "TOP STORY\n\nBitcoin steigt.\nhttps://example.org/story\n"


def _write(
    tmp_path: Path,
    name: str = "issue.eml",
    *,
    sender: str = '"CryptoCrunch" <cryptocrunch@m6.morningcrunch.de>',
    subject: str = "Bitcoin auf Rekordkurs",
    date: str | None = "Fri, 14 Aug 2026 05:59:00 +0200",
    message_id: str | None = "<abc123@morningcrunch.de>",
    plain: str | None = _BODY,
    html: str | None = None,
    charset: str = "utf-8",
) -> Path:
    message = EmailMessage()
    message["From"] = sender
    message["Subject"] = subject
    if date:
        message["Date"] = date
    if message_id:
        message["Message-ID"] = message_id
    if plain is not None:
        message.set_content(plain, charset=charset)
    if html is not None:
        if plain is None:
            message.set_content("placeholder")
            message.clear_content()
            message.set_content(html, subtype="html")
        else:
            message.add_alternative(html, subtype="html")
    path = tmp_path / name
    path.write_bytes(message.as_bytes())
    return path


def test_extracts_the_four_fields_the_pipeline_needs(tmp_path: Path) -> None:
    mail = parse_eml(_write(tmp_path))

    assert mail.sender == "cryptocrunch@m6.morningcrunch.de"
    assert mail.subject == "Bitcoin auf Rekordkurs"
    assert mail.message_id == "<abc123@morningcrunch.de>"
    assert "Bitcoin steigt." in mail.body_text


def test_display_name_is_stripped_from_the_sender(tmp_path: Path) -> None:
    """`identify_newsletter` matches the bare address — a `"Name" <addr>` header
    would otherwise never match and the issue would be silently skipped."""
    mail = parse_eml(_write(tmp_path, sender='"Morning Crunch" <HELLO@morningcrunch.de>'))

    assert mail.sender == "hello@morningcrunch.de"
    assert identify_newsletter(mail.sender, load_newsletters()) is not None


def test_multipart_prefers_the_plain_text_alternative(tmp_path: Path) -> None:
    """These newsletters ship HTML plus plain text. `crypto_newsletter` parses the
    plain part; feeding it HTML would produce markup-shaped impulses."""
    path = _write(tmp_path, html="<h1>Bitcoin</h1><p>steigt.</p>")

    mail = parse_eml(path)

    assert "<h1>" not in mail.body_text
    assert "Bitcoin steigt." in mail.body_text


def test_quoted_printable_and_umlauts_survive(tmp_path: Path) -> None:
    """Real issues arrive quoted-printable; a naive read would leave `=C3=BC` in
    the impulse text and thereby in the research pool."""
    path = _write(tmp_path, plain="ROHSTOFFE\n\nKupferpreis über 10.000 $ — Hütten drosseln.\n")

    mail = parse_eml(path)

    assert "über" in mail.body_text
    assert "Hütten" in mail.body_text
    assert "=C3" not in mail.body_text


def test_latin1_charset_is_decoded(tmp_path: Path) -> None:
    path = _write(tmp_path, plain="MÄRKTE\n\nÖlpreis fällt.\n", charset="iso-8859-1")

    mail = parse_eml(path)

    assert "Ölpreis fällt." in mail.body_text


def test_date_header_becomes_naive_utc(tmp_path: Path) -> None:
    """The issue is dated by its own header, not by when it is caught up — a
    backfill days later must not misdate the research."""
    mail = parse_eml(_write(tmp_path, date="Fri, 14 Aug 2026 05:59:00 +0200"))

    assert mail.received_at == datetime.datetime(2026, 8, 14, 3, 59)
    assert mail.received_at.tzinfo is None


def test_missing_date_falls_back_to_now(tmp_path: Path) -> None:
    mail = parse_eml(_write(tmp_path, date=None))

    assert mail.received_at.tzinfo is None
    assert mail.received_at.year >= 2026


def test_missing_message_id_falls_back_to_the_filename(tmp_path: Path) -> None:
    """The upsert key is (message_id, seq). A blank key would collide across files
    and issues would overwrite each other."""
    mail = parse_eml(_write(tmp_path, name="marketscrunch-2026-08-14.eml", message_id=None))

    assert mail.message_id == "file:marketscrunch-2026-08-14.eml"


def test_html_only_mail_is_refused(tmp_path: Path) -> None:
    """Refused loudly rather than ingested as zero impulses, which would look
    exactly like an ad-only issue."""
    path = _write(tmp_path, plain=None, html="<p>nur HTML</p>")

    with pytest.raises(EmlError, match="text/plain"):
        parse_eml(path)


def test_mail_without_sender_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "broken.eml"
    path.write_bytes(b"Subject: kein Absender\n\nText\n")

    with pytest.raises(EmlError, match="From"):
        parse_eml(path)


def test_scan_finds_eml_files_in_order(tmp_path: Path) -> None:
    _write(tmp_path, "b.eml")
    _write(tmp_path, "a.eml")
    (tmp_path / "ignored.txt").write_text("nope")
    (tmp_path / "sub").mkdir()
    _write(tmp_path / "sub", "c.eml")

    found = scan_eml_directory(tmp_path)

    assert [path.name for path in found] == ["a.eml", "b.eml"]


def test_scan_of_a_missing_directory_is_empty(tmp_path: Path) -> None:
    assert scan_eml_directory(tmp_path / "gibt-es-nicht") == []


def test_end_to_end_an_eml_becomes_newsletter_item_rows(session, tmp_path: Path) -> None:
    """F117 §4 test 12 — the point of the whole adapter.

    Runs a real issue body through the identical chain the webhook uses
    (identify -> parse -> upsert) and checks that rows land, so a change to the
    adapter cannot pass while the pipeline it feeds is broken.
    """
    from src.db.models import NewsletterItem
    from src.ingestion.crypto_newsletter import (
        extract_issue_url,
        parse_newsletter,
        sync_newsletter_items,
    )
    from tests.ingestion.test_crypto_newsletter import MARKETS_ISSUE

    path = _write(
        tmp_path,
        sender="<markets@m.morningcrunch.de>",
        subject="Ein Autobauer plant",
        plain=MARKETS_ISSUE,
    )
    mail = parse_eml(path)
    newsletter = identify_newsletter(mail.sender, load_newsletters())
    assert newsletter is not None and newsletter.slug == "marketscrunch"

    written = sync_newsletter_items(
        session,
        newsletter.slug,
        mail.message_id,
        mail.subject,
        extract_issue_url(mail.body_text),
        mail.received_at,
        parse_newsletter(mail.body_text, newsletter),
    )
    session.flush()

    assert written > 0
    rows = session.query(NewsletterItem).filter_by(message_id=mail.message_id).all()
    assert len(rows) == written
    assert all(row.newsletter_slug == "marketscrunch" for row in rows)
    # The ad section configured in config/ingestion.yaml must not survive.
    assert not [row for row in rows if "APP-PFIFF" in row.section]


def test_end_to_end_is_idempotent(session, tmp_path: Path) -> None:
    """Re-running over the same file updates in place — the operator will re-run
    this after fixing one bad file in the directory."""
    from src.db.models import NewsletterItem
    from src.ingestion.crypto_newsletter import (
        extract_issue_url,
        parse_newsletter,
        sync_newsletter_items,
    )
    from tests.ingestion.test_crypto_newsletter import MARKETS_ISSUE

    path = _write(tmp_path, sender="<markets@m.morningcrunch.de>", plain=MARKETS_ISSUE)
    mail = parse_eml(path)
    newsletter = identify_newsletter(mail.sender, load_newsletters())
    assert newsletter is not None

    def _ingest() -> int:
        count = sync_newsletter_items(
            session,
            newsletter.slug,
            mail.message_id,
            mail.subject,
            extract_issue_url(mail.body_text),
            mail.received_at,
            parse_newsletter(mail.body_text, newsletter),
        )
        session.flush()
        return count

    first = _ingest()
    second = _ingest()

    assert first == second
    assert session.query(NewsletterItem).filter_by(message_id=mail.message_id).count() == first


def test_reingest_after_a_config_change_prunes_the_dropped_tail(session, tmp_path: Path) -> None:
    """F117 §8 — the case that let advertising into the pool on 15.08.2026.

    An issue is ingested, then a section is added to `drop_sections`. Re-ingesting
    now yields fewer impulses; without pruning, the rows beyond the new count would
    survive at their old seq — and they are exactly the ones that were just
    declared unwanted, so no re-run could ever remove them.
    """
    from src.db.models import NewsletterItem
    from src.ingestion.crypto_newsletter import (
        NewsletterConfig,
        extract_issue_url,
        parse_newsletter,
        sync_newsletter_items,
    )
    from tests.ingestion.test_crypto_newsletter import MARKETS_ISSUE

    path = _write(tmp_path, sender="<markets@m.morningcrunch.de>", plain=MARKETS_ISSUE)
    mail = parse_eml(path)
    lenient = identify_newsletter(mail.sender, load_newsletters())
    assert lenient is not None

    def _ingest(config: NewsletterConfig) -> int:
        count = sync_newsletter_items(
            session,
            config.slug,
            mail.message_id,
            mail.subject,
            extract_issue_url(mail.body_text),
            mail.received_at,
            parse_newsletter(mail.body_text, config),
        )
        session.flush()
        return count

    before = _ingest(lenient)

    stricter = NewsletterConfig(
        slug=lenient.slug,
        sender=lenient.sender,
        subject_marker=lenient.subject_marker,
        drop_sections=[*lenient.drop_sections, "WHAT TO WATCH", "MARKET MOVER"],
        blocked_link_domains=lenient.blocked_link_domains,
        ticker_map=lenient.ticker_map,
        single_item_sections=lenient.single_item_sections,
    )
    after = _ingest(stricter)

    assert after < before, "the stricter config must drop something, or the test proves nothing"
    rows = session.query(NewsletterItem).filter_by(message_id=mail.message_id).all()
    assert len(rows) == after, "orphaned tail rows survived the re-ingest"
    assert not [row for row in rows if "WHAT TO WATCH" in row.section]
    assert not [row for row in rows if "MARKET MOVER" in row.section]


def test_shipped_config_drops_the_two_ad_sections_found_on_15_08() -> None:
    """Both gaps that put advertising into the pool, pinned per newsletter."""
    for newsletter in load_newsletters():
        assert "APP-PFIFF" in newsletter.drop_sections, newsletter.slug
        assert "UNSER PARTNER" in newsletter.drop_sections, newsletter.slug
