import datetime
from pathlib import Path

import pymupdf
import pytest

from src.ingestion.publications_pipeline import (
    Article,
    extract_articles,
    parse_issue_path,
    process_pdf_fallback_file,
    scan_ingest_directory,
    sync_publication_articles,
)


def _make_two_article_pdf(path: Path) -> None:
    # More body lines than headline lines — realistic for a magazine page and what
    # the median-based headline heuristic in extract_articles() relies on.
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "HEADLINE ONE", fontsize=18)
    page.insert_text((72, 100), "Body text for article one", fontsize=10)
    page.insert_text((72, 114), "goes here across two lines.", fontsize=10)
    page.insert_text((72, 140), "HEADLINE TWO", fontsize=18)
    page.insert_text((72, 168), "Body text for article two", fontsize=10)
    page.insert_text((72, 182), "goes here across two lines.", fontsize=10)
    doc.save(path)
    doc.close()


def _make_empty_pdf(path: Path) -> None:
    doc = pymupdf.open()
    doc.new_page()
    doc.save(path)
    doc.close()


def test_extract_articles_segments_on_headline_font_size(tmp_path):
    pdf_path = tmp_path / "issue.pdf"
    _make_two_article_pdf(pdf_path)

    articles = extract_articles(pdf_path)

    assert articles == [
        Article(
            seq=0,
            page=1,
            title="HEADLINE ONE",
            text="Body text for article one\ngoes here across two lines.",
        ),
        Article(
            seq=1,
            page=1,
            title="HEADLINE TWO",
            text="Body text for article two\ngoes here across two lines.",
        ),
    ]


def test_extract_articles_returns_empty_for_blank_page(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    _make_empty_pdf(pdf_path)

    assert extract_articles(pdf_path) == []


def test_parse_issue_path_extracts_publication_and_date(tmp_path):
    base_dir = tmp_path / "publications"
    pdf_path = base_dir / "euro_am_sonntag" / "2026-07-05.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.touch()

    publication, issue_date = parse_issue_path(base_dir, pdf_path)

    assert publication == "euro_am_sonntag"
    assert issue_date == datetime.date(2026, 7, 5)


def test_parse_issue_path_rejects_wrong_filename_format(tmp_path):
    base_dir = tmp_path / "publications"
    pdf_path = base_dir / "euro_am_sonntag" / "not-a-date.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.touch()

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_issue_path(base_dir, pdf_path)


def test_parse_issue_path_rejects_wrong_directory_depth(tmp_path):
    base_dir = tmp_path / "publications"
    pdf_path = base_dir / "2026-07-05.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.touch()

    with pytest.raises(ValueError, match="Expected"):
        parse_issue_path(base_dir, pdf_path)


def test_sync_publication_articles_returns_zero_for_empty_list(session):
    assert sync_publication_articles(session, "pub", datetime.date(2026, 7, 5), "x.pdf", []) == 0


def test_sync_publication_articles_is_idempotent_on_rerun(session):
    day = datetime.date(2026, 7, 5)
    v1 = [Article(seq=0, page=1, title="OLD TITLE", text="old text")]
    v2 = [Article(seq=0, page=1, title="NEW TITLE", text="new text")]

    first_count = sync_publication_articles(session, "pub", day, "x.pdf", v1)
    second_count = sync_publication_articles(session, "pub", day, "x.pdf", v2)

    assert first_count == 1
    assert second_count == 1

    from sqlalchemy import select

    from src.db.models import PublicationArticle

    rows = session.scalars(
        select(PublicationArticle).where(PublicationArticle.publication == "pub")
    ).all()
    assert len(rows) == 1
    assert rows[0].title == "NEW TITLE"


def test_process_pdf_fallback_file_end_to_end(session, tmp_path):
    base_dir = tmp_path / "publications"
    pdf_path = base_dir / "euro_am_sonntag" / "2026-07-05.pdf"
    pdf_path.parent.mkdir(parents=True)
    _make_two_article_pdf(pdf_path)

    count = process_pdf_fallback_file(session, base_dir, pdf_path)
    assert count == 2

    # re-processing (crash-recovery / re-trigger) must not duplicate
    count_again = process_pdf_fallback_file(session, base_dir, pdf_path)
    assert count_again == 2

    from sqlalchemy import select

    from src.db.models import PublicationArticle

    rows = session.scalars(
        select(PublicationArticle).where(PublicationArticle.publication == "euro_am_sonntag")
    ).all()
    assert len(rows) == 2


def test_scan_ingest_directory_lists_pdfs_across_publications(tmp_path):
    base_dir = tmp_path / "publications"
    (base_dir / "euro_am_sonntag").mkdir(parents=True)
    (base_dir / "boerse_online").mkdir(parents=True)
    _make_two_article_pdf(base_dir / "euro_am_sonntag" / "2026-07-05.pdf")
    _make_two_article_pdf(base_dir / "boerse_online" / "2026-07-06.pdf")

    found = scan_ingest_directory(base_dir)

    assert len(found) == 2


def test_scan_ingest_directory_returns_empty_for_missing_dir(tmp_path):
    assert scan_ingest_directory(tmp_path / "does-not-exist") == []
