"""See docs/features/F019-cost-ledger-enforcement.md §3, tests 1-4.

Module-local migration fixture (not a directory-wide conftest.py) — the other
tests/llm suites (test_client.py, test_config.py, test_cost_guard.py) are pure/mocked
and must keep running without a real Postgres.
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import CostLedgerScope, Persona
from src.llm.ledger import (
    record_llm_call,
    sum_month_spend,
    sum_persona_spend_today,
    sum_system_spend_today,
)
from src.orchestrator.seed import seed_personas_and_portfolios


@pytest.fixture(autouse=True)
def _apply_migration(_migrated_schema: None) -> None:
    """Opts this module into the real-Postgres schema — see tests/conftest.py."""


def test_record_llm_call_persists_expected_fields(session: Session) -> None:
    ts = datetime.datetime(2026, 7, 7, 10, 0)

    entry = record_llm_call(
        session,
        ts=ts,
        scope=CostLedgerScope.SYSTEM,
        persona_id=None,
        provider="anthropic",
        model="claude-haiku-4-5",
        tokens_in=1000,
        tokens_out=200,
        cost_usd=0.05,
    )

    assert entry.ts == ts
    assert entry.scope == CostLedgerScope.SYSTEM
    assert entry.provider == "anthropic"
    assert entry.model == "claude-haiku-4-5"
    assert entry.tokens_in == 1000
    assert entry.tokens_out == 200
    assert float(entry.cost_usd) == pytest.approx(0.05)


def test_sum_system_spend_today_ignores_yesterday(session: Session) -> None:
    today = datetime.datetime(2026, 7, 7, 9, 0)
    yesterday = datetime.datetime(2026, 7, 6, 9, 0)
    record_llm_call(
        session,
        ts=today,
        scope=CostLedgerScope.SYSTEM,
        persona_id=None,
        provider="anthropic",
        model="claude-haiku-4-5",
        tokens_in=100,
        tokens_out=10,
        cost_usd=0.10,
    )
    record_llm_call(
        session,
        ts=yesterday,
        scope=CostLedgerScope.SYSTEM,
        persona_id=None,
        provider="anthropic",
        model="claude-haiku-4-5",
        tokens_in=100,
        tokens_out=10,
        cost_usd=1.00,
    )

    total = sum_system_spend_today(session, datetime.datetime(2026, 7, 7, 12, 0))

    assert total == pytest.approx(0.10)


def test_sum_persona_spend_today_only_counts_matching_persona(session: Session) -> None:
    seed_personas_and_portfolios(session)
    vulture = session.scalar(select(Persona).filter_by(name="VULTURE"))
    hype = session.scalar(select(Persona).filter_by(name="HYPE"))
    assert vulture is not None
    assert hype is not None
    now = datetime.datetime(2026, 7, 7, 9, 0)

    record_llm_call(
        session,
        ts=now,
        scope=CostLedgerScope.PERSONA,
        persona_id=vulture.id,
        provider="anthropic",
        model="claude-sonnet-5",
        tokens_in=100,
        tokens_out=10,
        cost_usd=0.20,
    )
    record_llm_call(
        session,
        ts=now,
        scope=CostLedgerScope.PERSONA,
        persona_id=hype.id,
        provider="anthropic",
        model="claude-sonnet-5",
        tokens_in=100,
        tokens_out=10,
        cost_usd=0.30,
    )
    record_llm_call(
        session,
        ts=now,
        scope=CostLedgerScope.SYSTEM,
        persona_id=None,
        provider="anthropic",
        model="claude-haiku-4-5",
        tokens_in=100,
        tokens_out=10,
        cost_usd=0.40,
    )

    total = sum_persona_spend_today(session, vulture.id, datetime.datetime(2026, 7, 7, 12, 0))

    assert total == pytest.approx(0.20)


def test_sum_month_spend_ignores_previous_month(session: Session) -> None:
    record_llm_call(
        session,
        ts=datetime.datetime(2026, 7, 3, 9, 0),
        scope=CostLedgerScope.SYSTEM,
        persona_id=None,
        provider="anthropic",
        model="claude-haiku-4-5",
        tokens_in=100,
        tokens_out=10,
        cost_usd=1.50,
    )
    record_llm_call(
        session,
        ts=datetime.datetime(2026, 6, 30, 9, 0),
        scope=CostLedgerScope.SYSTEM,
        persona_id=None,
        provider="anthropic",
        model="claude-haiku-4-5",
        tokens_in=100,
        tokens_out=10,
        cost_usd=99.0,
    )

    total = sum_month_spend(session, datetime.datetime(2026, 7, 7, 12, 0))

    assert total == pytest.approx(1.50)
