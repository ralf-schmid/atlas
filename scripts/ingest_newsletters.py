"""Ingest saved newsletter mails (`.eml`) from a directory — see F117.

The counterpart to `scripts/ingest_publications.py`, which only ever looks at the
magazine PDFs under PUBLICATIONS_INGEST_DIR and knows nothing about mails.

Usage:
    DATABASE_URL=... uv run python scripts/ingest_newsletters.py [DIR] [--dry-run]

DIR defaults to NEWSLETTER_INGEST_DIR, else /data/ingest/newsletter.
`--dry-run` parses and reports without writing — worth doing first on a batch of
files whose layout nobody has seen yet, since a layout change shows up as an
issue that parses to zero impulses.

Idempotent: the upsert key is (message_id, seq), so re-running over the same
files updates the rows in place instead of duplicating the issue.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from src.db.base import get_session_factory
from src.ingestion.crypto_newsletter import (
    extract_issue_url,
    identify_newsletter,
    load_newsletters,
    parse_newsletter,
    sync_newsletter_items,
)
from src.ingestion.newsletter_eml import EmlError, parse_eml, scan_eml_directory

_DEFAULT_DIR = Path("/data/ingest/newsletter")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")
    positional = [arg for arg in args if not arg.startswith("-")]
    base_dir = (
        Path(positional[0])
        if positional
        else Path(os.environ.get("NEWSLETTER_INGEST_DIR", _DEFAULT_DIR))
    )

    paths = scan_eml_directory(base_dir)
    if not paths:
        print(f"Keine .eml-Dateien unter {base_dir}")
        return 0

    newsletters = load_newsletters()
    session_factory = get_session_factory()
    total = 0
    failed = 0

    with session_factory() as session:
        for path in paths:
            try:
                mail = parse_eml(path)
            except EmlError as exc:
                print(f"{path.name}: ÜBERSPRUNGEN — {exc}")
                failed += 1
                continue

            newsletter = identify_newsletter(mail.sender, newsletters)
            if newsletter is None:
                # Not an error the operator can ignore: it usually means the file
                # is the wrong mail, or a sender changed in config/ingestion.yaml.
                known = ", ".join(sorted(item.sender for item in newsletters))
                print(
                    f"{path.name}: ÜBERSPRUNGEN — Absender {mail.sender!r} passt zu keinem "
                    f"konfigurierten Newsletter (bekannt: {known})"
                )
                failed += 1
                continue

            impulses = parse_newsletter(mail.body_text, newsletter)
            if dry_run:
                print(
                    f"{path.name}: {newsletter.slug}, {mail.received_at:%Y-%m-%d %H:%M}, "
                    f"{len(impulses)} Impuls(e) — DRY RUN, nichts geschrieben"
                )
                total += len(impulses)
                continue
            written = sync_newsletter_items(
                session,
                newsletter.slug,
                mail.message_id,
                mail.subject,
                extract_issue_url(mail.body_text),
                mail.received_at,
                impulses,
            )
            total += written
            note = "" if written else "  (0 — Werbe-Ausgabe oder Layout-Wechsel?)"
            print(
                f"{path.name}: {newsletter.slug}, {mail.received_at:%Y-%m-%d %H:%M}, "
                f"{written} Impuls(e){note}"
            )
        if not dry_run:
            session.commit()

    suffix = " (DRY RUN — nichts geschrieben)" if dry_run else ""
    print(f"\nGesamt: {total} Impuls(e) aus {len(paths) - failed}/{len(paths)} Datei(en){suffix}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
