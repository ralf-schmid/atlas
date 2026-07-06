"""Real integration test against aktienfinder.net — see docs/features/F012 §5.

Launches a real (headless) Chromium via Playwright, logs into Ralf's real
aktienfinder.de account, grabs two symbols (Apple, SAP — chosen because they're
stable, well-covered profiles unlikely to disappear), persists via
`run_daily_grab_live`. Live-verified once manually (see F012 §5); this test lets
that be re-verified on demand without repeating the manual exploration.

Skipped entirely unless real aktienfinder.de credentials are present in the
environment (local: from .env). Not wired into CI — see F012 §5 "Noch offen": adding
AKTIENFINDER_USERNAME/PASSWORD as GitHub Encrypted Secrets needs Ralf's go-ahead,
same as the Alpaca Paper integration secrets were added deliberately, not by default.
"""

from __future__ import annotations

import datetime
import os

import pytest
from sqlalchemy import select

from src.db.models import AktienfinderSnapshot
from src.ingestion.aktienfinder_grabbing import run_daily_grab_live

pytestmark = pytest.mark.integration

_ISINS = ["US0378331005", "DE0007164600"]  # Apple, SAP


def test_run_daily_grab_live_against_real_aktienfinder(session):
    if not os.environ.get("AKTIENFINDER_USERNAME") or not os.environ.get("AKTIENFINDER_PASSWORD"):
        pytest.skip("AKTIENFINDER_USERNAME/PASSWORD not set — needs real aktienfinder.de login")

    snapshot_date = datetime.date.today()
    count = run_daily_grab_live(session, _ISINS, snapshot_date)

    assert count == len(_ISINS)

    rows = session.scalars(
        select(AktienfinderSnapshot).where(AktienfinderSnapshot.snapshot_date == snapshot_date)
    ).all()
    assert {r.symbol for r in rows} == set(_ISINS)
    for row in rows:
        assert row.fields["price"] is not None
        assert row.fields["quality_score_dividend_yield"] is not None
        assert isinstance(row.fields["dividend_history"], list)
        assert len(row.fields["dividend_history"]) > 0
