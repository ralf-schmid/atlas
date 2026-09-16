"""F121: renders the Endabrechnung (§4.7 final report) as Markdown.

The Telegram push happens automatically on the last competition day; this script
produces the long artefact the winner ADR references. Reads only — it computes
nothing that is not already in the DB, and re-running it after the season returns
the same numbers (the scoring window is closed on both ends).

Usage:
  DATABASE_URL=... uv run python scripts/final_report.py --out docs/reports/endabrechnung.md
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.db.base import get_session_factory
from src.metrics.final_report import build_final_report, render_final_report_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the competition final report")
    parser.add_argument("--out", help="write Markdown to this path instead of stdout")
    args = parser.parse_args()

    session_factory = get_session_factory()
    with session_factory() as session:
        report = build_final_report(session)
    text = render_final_report_markdown(report)

    if args.out:
        Path(args.out).write_text(text)
        print(f"written: {args.out}")
    else:
        print(text)

    if report.missing_closing_valuation:
        print(
            "WARNING: no post-close valuation for "
            f"{', '.join(report.missing_closing_valuation)} — run scripts/final_settlement.py"
        )


if __name__ == "__main__":
    main()
