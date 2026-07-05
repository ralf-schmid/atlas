"""Publications PDF-Fallback-Pipeline — manually-dropped PDF -> segmented articles
in `publication_article`. See docs/features/F011-publications-pdf-fallback.md.

Fallback-first (ARCHITECTURE.md §3.5.1): this operates purely on a PDF already sitting
in the ingest directory — the Playwright auto-download/login is separate, later work.
Directory convention: `<base_dir>/<publication>/<issue_date:YYYY-MM-DD>.pdf`.

Idempotent: upsert on the (publication, issue_date, seq) unique constraint, so
re-processing the same file (crash-recovery, manual re-trigger) never duplicates.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import PublicationArticle

_ISSUE_FILENAME_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})\.pdf$")
_HEADLINE_SIZE_RATIO = 1.3  # a span this much bigger than the page's median counts as a headline


@dataclass(frozen=True, slots=True)
class Article:
    seq: int
    page: int
    title: str
    text: str


def extract_articles(pdf_path: Path) -> list[Article]:
    """Segments a PDF into articles using a font-size heuristic: a text span whose
    size is notably larger than the page's median span size starts a new article;
    everything until the next such span is that article's body.

    A simple heuristic (not full document-layout understanding) — good enough for the
    fallback path; Docling/vision-based segmentation can replace this later without
    changing the DB schema or the sync function.
    """
    articles: list[Article] = []
    current_title: str | None = None
    current_page = 1
    current_lines: list[str] = []
    seq = 0

    with pymupdf.open(pdf_path) as doc:
        for page_index, page in enumerate(doc, start=1):
            page_dict = page.get_text("dict")
            sizes = [
                span["size"]
                for block in page_dict["blocks"]
                for line in block.get("lines", [])
                for span in line["spans"]
                if span["text"].strip()
            ]
            if not sizes:
                continue
            median_size = sorted(sizes)[len(sizes) // 2]
            threshold = median_size * _HEADLINE_SIZE_RATIO

            for block in page_dict["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if not text:
                            continue
                        is_headline = span["size"] >= threshold and span["size"] > median_size
                        if is_headline:
                            if current_title is not None:
                                articles.append(
                                    Article(
                                        seq=seq,
                                        page=current_page,
                                        title=current_title,
                                        text="\n".join(current_lines).strip(),
                                    )
                                )
                                seq += 1
                            current_title = text
                            current_page = page_index
                            current_lines = []
                        else:
                            current_lines.append(text)

    if current_title is not None:
        articles.append(
            Article(
                seq=seq,
                page=current_page,
                title=current_title,
                text="\n".join(current_lines).strip(),
            )
        )

    return articles


def parse_issue_path(publications_base_dir: Path, pdf_path: Path) -> tuple[str, datetime.date]:
    """Derives `(publication, issue_date)` from the directory convention
    `<base_dir>/<publication>/<issue_date>.pdf`."""
    relative = pdf_path.resolve().relative_to(publications_base_dir.resolve())
    if len(relative.parts) != 2:
        raise ValueError(
            f"Expected <publication>/<issue_date>.pdf under {publications_base_dir}, got {relative}"
        )
    publication, filename = relative.parts
    match = _ISSUE_FILENAME_RE.match(filename)
    if match is None:
        raise ValueError(f"Filename {filename!r} doesn't match <YYYY-MM-DD>.pdf")
    issue_date = datetime.date.fromisoformat(match.group("date"))
    return publication, issue_date


def sync_publication_articles(
    session: Session,
    publication: str,
    issue_date: datetime.date,
    source_file: str,
    articles: list[Article],
) -> int:
    if not articles:
        return 0

    rows = [
        {
            "publication": publication,
            "issue_date": issue_date,
            "seq": a.seq,
            "page": a.page,
            "title": a.title,
            "text": a.text,
            "source_file": source_file,
        }
        for a in articles
    ]

    stmt = insert(PublicationArticle).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_publication_article_issue_seq",
        set_={
            "page": stmt.excluded.page,
            "title": stmt.excluded.title,
            "text": stmt.excluded.text,
            "source_file": stmt.excluded.source_file,
            "synced_at": datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        },
    )
    session.execute(stmt)
    session.flush()
    return len(rows)


def process_pdf_fallback_file(session: Session, publications_base_dir: Path, pdf_path: Path) -> int:
    """Full fallback pipeline for one already-dropped PDF: derive metadata from the
    path convention, extract + segment, upsert. This is what a directory watcher (n8n
    File-Watcher or a simple poller) calls once a new PDF is detected."""
    publication, issue_date = parse_issue_path(publications_base_dir, pdf_path)
    articles = extract_articles(pdf_path)
    return sync_publication_articles(session, publication, issue_date, str(pdf_path), articles)


def scan_ingest_directory(publications_base_dir: Path) -> list[Path]:
    """Lists all PDFs currently in the ingest directory, across all publications.
    A poller calls this on an interval; idempotency of `process_pdf_fallback_file`
    means re-scanning and re-processing an already-synced file is harmless."""
    if not publications_base_dir.exists():
        return []
    return sorted(publications_base_dir.glob("*/*.pdf"))
