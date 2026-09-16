"""F123: writes the realised trades of one portfolio as CSV (P6 DoD, Steuer-Export).

Amounts are in the account currency (USD at Alpaca) — the EUR conversion for
Anlage KAP is a deliberate downstream step, see `src/metrics/tax_export.py`.

Usage:
  DATABASE_URL=... uv run python scripts/export_trades.py --persona CONTRA \
      --mode paper --year 2026 --out trades-2026.csv
"""

from __future__ import annotations

import argparse
import datetime
from pathlib import Path

from sqlalchemy import select

from src.db.base import get_session_factory
from src.db.models import Persona, Portfolio, PortfolioMode
from src.metrics.tax_export import build_tax_export, render_tax_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Export realised trades as CSV")
    parser.add_argument("--persona", required=True)
    parser.add_argument("--mode", default="live", choices=[m.value for m in PortfolioMode])
    parser.add_argument("--year", type=int, help="restrict to disposals in this calendar year")
    parser.add_argument("--out", help="write to this path instead of stdout")
    args = parser.parse_args()

    since = datetime.datetime(args.year, 1, 1) if args.year else None
    until = datetime.datetime(args.year, 12, 31, 23, 59, 59) if args.year else None

    session_factory = get_session_factory()
    with session_factory() as session:
        portfolio = session.scalars(
            select(Portfolio)
            .join(Persona, Portfolio.persona_id == Persona.id)
            .where(
                Persona.name == args.persona.upper(),
                Portfolio.mode == PortfolioMode(args.mode),
                Portfolio.archived_at.is_(None),
            )
        ).first()
        if portfolio is None:
            raise SystemExit(f"no active {args.mode} portfolio for persona {args.persona!r}")
        export = build_tax_export(session, portfolio.id, since, until)

    csv_text = render_tax_csv(export)
    if args.out:
        Path(args.out).write_text(csv_text)
        print(f"written: {args.out} ({len(export.trades)} realised trades)")
    else:
        print(csv_text)

    print(f"Summe Ergebnis: {export.result_sum} (Kontowährung, ohne EUR-Umrechnung)")
    if export.unmatched:
        print(f"WARNING: sells without a matching buy for: {', '.join(export.unmatched)}")


if __name__ == "__main__":
    main()
