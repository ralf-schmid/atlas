"""Manually processes whatever PDFs currently sit in PUBLICATIONS_INGEST_DIR —
see docs/features/F011-publications-pdf-fallback.md §5 ("Noch offen": no
poller/cron calls scan_ingest_directory()/process_pdf_fallback_file() yet).
Idempotent (F011 §2): safe to re-run, already-synced files just upsert again.

Usage: DATABASE_URL=... PUBLICATIONS_INGEST_DIR=... uv run python scripts/ingest_publications.py
"""

from __future__ import annotations

import os
from pathlib import Path

from src.db.base import get_session_factory
from src.ingestion.publications_pipeline import (
    process_pdf_fallback_file,
    scan_ingest_directory,
)


def main() -> None:
    base_dir = Path(os.environ["PUBLICATIONS_INGEST_DIR"])
    session_factory = get_session_factory()

    pdf_paths = scan_ingest_directory(base_dir)
    if not pdf_paths:
        print(f"No PDFs found under {base_dir}")
        return

    with session_factory() as session:
        for pdf_path in pdf_paths:
            article_count = process_pdf_fallback_file(session, base_dir, pdf_path)
            print(f"{pdf_path}: {article_count} article(s) synced")
        session.commit()


if __name__ == "__main__":
    main()
