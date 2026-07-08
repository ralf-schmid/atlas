"""Publications PDF-Fallback-Pipeline — manually-dropped PDF -> segmented articles
in `publication_article`. See docs/features/F011-publications-pdf-fallback.md,
docs/features/F038-publications-column-aware-extraction.md.

Fallback-first (ARCHITECTURE.md §3.5.1): this operates purely on a PDF already sitting
in the ingest directory — the Playwright auto-download/login is separate, later work.
Directory convention: `<base_dir>/<publication>/<issue_date:YYYY-MM-DD>.pdf`.

Idempotent: re-processing the same (publication, issue_date) replaces its full
article set (delete-then-insert, not upsert-by-seq) — `extract_articles`'s `seq`
values aren't stable across runs (assigned during the walk *before* the
min-length filter drops some, see F038 §2), so a run producing fewer articles
than a previous one (e.g. after a heuristic improvement, or a corrected PDF)
would otherwise leave the previous run's higher-seq rows as permanent orphans.
Found live while re-processing a real issue with F038's improved heuristic —
874 stale rows would have silently stuck around forever under the old
upsert-only approach.
"""

from __future__ import annotations

import datetime
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from sqlalchemy import delete
from sqlalchemy.orm import Session

from src.db.models import PublicationArticle

_ISSUE_FILENAME_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})\.pdf$")
_HEADLINE_SIZE_RATIO = 1.3  # a span this much bigger than the page's median counts as a headline
_BOILERPLATE_MIN_PAGES = 3  # an identical line on >= this many pages is a running header/footer
_MIN_ARTICLE_BODY_LENGTH = 80  # drops TOC entries/ad pages with a big "headline" but no real body


@dataclass(frozen=True, slots=True)
class Article:
    seq: int
    page: int
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class _Span:
    text: str
    size: float
    column: int
    y0: float


def extract_articles(pdf_path: Path) -> list[Article]:
    """Segments a PDF into articles using a font-size heuristic: a text span whose
    size is notably larger than the page's median span size starts a new article;
    everything until the next such span is that article's body.

    Three refinements over the original single-column heuristic (F038, see
    docs/features/F038-publications-column-aware-extraction.md §2 for rationale):
    spans are read column-by-column (left column top-to-bottom, then right column)
    rather than PyMuPDF's raw block order, which otherwise interleaves real
    multi-column layouts; a line repeated verbatim across several pages (running
    headers/footers) is dropped before segmentation; and a resulting "article"
    shorter than a small threshold (TOC entries, ad pages) is dropped entirely.

    Still a heuristic, not full document-layout understanding — good enough for
    the fallback path; Docling/vision-based segmentation remains a possible future
    escalation if this proves insufficient in practice.
    """
    with pymupdf.open(pdf_path) as doc:
        pages_spans = [_extract_page_spans(page) for page in doc]

    boilerplate = _detect_boilerplate_lines(pages_spans)

    articles: list[Article] = []
    current_title: str | None = None
    current_page = 1
    current_lines: list[str] = []
    seq = 0

    for page_index, spans in enumerate(pages_spans, start=1):
        if not spans:
            continue
        sizes = [span.size for span in spans]
        median_size = sorted(sizes)[len(sizes) // 2]
        threshold = median_size * _HEADLINE_SIZE_RATIO

        for span in sorted(spans, key=lambda s: (s.column, s.y0)):
            if span.text in boilerplate:
                continue
            is_headline = span.size >= threshold and span.size > median_size
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
                current_title = span.text
                current_page = page_index
                current_lines = []
            else:
                current_lines.append(span.text)

    if current_title is not None:
        articles.append(
            Article(
                seq=seq,
                page=current_page,
                title=current_title,
                text="\n".join(current_lines).strip(),
            )
        )

    return [a for a in articles if len(a.text) >= _MIN_ARTICLE_BODY_LENGTH]


def _extract_page_spans(page: pymupdf.Page) -> list[_Span]:
    page_dict = page.get_text("dict")
    midpoint = page.rect.width / 2
    spans = []
    for block in page_dict["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = span["text"].strip()
                if not text:
                    continue
                x0 = span["bbox"][0]
                column = 0 if x0 < midpoint else 1
                spans.append(_Span(text=text, size=span["size"], column=column, y0=span["bbox"][1]))
    return spans


def _detect_boilerplate_lines(pages_spans: list[list[_Span]]) -> set[str]:
    page_counts: Counter[str] = Counter()
    for spans in pages_spans:
        for text in {span.text for span in spans}:
            page_counts[text] += 1
    return {text for text, count in page_counts.items() if count >= _BOILERPLATE_MIN_PAGES}


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
    """Replaces this issue's full article set. Empty `articles` is a no-op
    (leaves any previously-synced rows untouched) rather than wiping existing
    data on e.g. a transient extraction failure — see module docstring."""
    if not articles:
        return 0

    session.execute(
        delete(PublicationArticle).where(
            PublicationArticle.publication == publication,
            PublicationArticle.issue_date == issue_date,
        )
    )
    session.add_all(
        PublicationArticle(
            publication=publication,
            issue_date=issue_date,
            seq=a.seq,
            page=a.page,
            title=a.title,
            text=a.text,
            source_file=source_file,
        )
        for a in articles
    )
    session.flush()
    return len(articles)


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
