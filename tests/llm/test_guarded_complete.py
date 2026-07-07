"""See docs/features/F019-cost-ledger-enforcement.md §3, tests 5-10."""

from __future__ import annotations

import datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import CostLedger, CostLedgerScope, Persona
from src.llm.client import LiteLLMClient
from src.llm.config import CostCaps, RoleConfig
from src.llm.cost_guard import BudgetStatus
from src.llm.ledger import BudgetExceededError, guarded_complete, record_llm_call
from src.orchestrator.seed import seed_personas_and_portfolios


@pytest.fixture(autouse=True)
def _apply_migration(_migrated_schema: None) -> None:
    """Opts this module into the real-Postgres schema — see tests/conftest.py."""


_CAPS = CostCaps(
    system_daily_usd=5.0,
    persona_daily_usd=1.0,
    monthly_soft_cap_usd=120.0,
    monthly_soft_cap_warn_pct=0.8,
)


def _fake_client(cost_usd: str = "0.05") -> LiteLLMClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
            headers={"x-litellm-response-cost": cost_usd},
        )

    return LiteLLMClient(
        base_url="http://test",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _get_persona_id(session: Session, name: str):
    persona = session.scalar(select(Persona).filter_by(name=name))
    assert persona is not None
    return persona.id


def test_guarded_complete_ok_writes_one_ledger_row(session: Session) -> None:
    seed_personas_and_portfolios(session)
    vulture_id = _get_persona_id(session, "VULTURE")
    role = RoleConfig(
        name="persona_analysis",
        model="claude-sonnet-5",
        provider="anthropic",
        shared=False,
        prompt_caching=True,
    )

    result = guarded_complete(session, _fake_client(), role, _CAPS, [], persona_id=vulture_id)

    assert result.response.content == "ok"
    rows = session.scalars(select(CostLedger)).all()
    assert len(rows) == 1
    assert rows[0].scope == CostLedgerScope.PERSONA
    assert rows[0].persona_id == vulture_id


def test_guarded_complete_blocked_by_persona_cap_does_not_call_llm(session: Session) -> None:
    seed_personas_and_portfolios(session)
    vulture_id = _get_persona_id(session, "VULTURE")
    record_llm_call(
        session,
        ts=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        scope=CostLedgerScope.PERSONA,
        persona_id=vulture_id,
        provider="anthropic",
        model="claude-sonnet-5",
        tokens_in=1,
        tokens_out=1,
        cost_usd=1.00,
    )
    role = RoleConfig(
        name="persona_analysis",
        model="claude-sonnet-5",
        provider="anthropic",
        shared=False,
        prompt_caching=True,
    )

    def failing_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("client.complete() must not be called when blocked")

    client = LiteLLMClient(
        base_url="http://test",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(failing_handler)),
    )

    with pytest.raises(BudgetExceededError):
        guarded_complete(session, client, role, _CAPS, [], persona_id=vulture_id)

    rows = session.scalars(select(CostLedger)).all()
    assert len(rows) == 1  # only the pre-seeded row, no new one


def test_guarded_complete_blocked_by_system_cap(session: Session) -> None:
    record_llm_call(
        session,
        ts=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        scope=CostLedgerScope.SYSTEM,
        persona_id=None,
        provider="anthropic",
        model="claude-haiku-4-5",
        tokens_in=1,
        tokens_out=1,
        cost_usd=5.00,
    )
    role = RoleConfig(
        name="market_research",
        model="claude-haiku-4-5",
        provider="anthropic",
        shared=True,
        prompt_caching=True,
    )

    def failing_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("client.complete() must not be called when blocked")

    client = LiteLLMClient(
        base_url="http://test",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(failing_handler)),
    )

    with pytest.raises(BudgetExceededError):
        guarded_complete(session, client, role, _CAPS, [])


def test_guarded_complete_shared_false_without_persona_id_raises(session: Session) -> None:
    role = RoleConfig(
        name="persona_analysis",
        model="claude-sonnet-5",
        provider="anthropic",
        shared=False,
        prompt_caching=True,
    )

    with pytest.raises(ValueError, match="persona_id"):
        guarded_complete(session, _fake_client(), role, _CAPS, [])


def test_guarded_complete_shared_role_writes_system_scope_ignoring_persona_id(
    session: Session,
) -> None:
    seed_personas_and_portfolios(session)
    vulture_id = _get_persona_id(session, "VULTURE")
    role = RoleConfig(
        name="market_research",
        model="claude-haiku-4-5",
        provider="anthropic",
        shared=True,
        prompt_caching=True,
    )

    guarded_complete(session, _fake_client(), role, _CAPS, [], persona_id=vulture_id)

    rows = session.scalars(select(CostLedger)).all()
    assert len(rows) == 1
    assert rows[0].scope == CostLedgerScope.SYSTEM
    assert rows[0].persona_id is None


def test_guarded_complete_warn_status_still_calls_llm(session: Session) -> None:
    record_llm_call(
        session,
        ts=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        scope=CostLedgerScope.SYSTEM,
        persona_id=None,
        provider="anthropic",
        model="claude-haiku-4-5",
        tokens_in=1,
        tokens_out=1,
        cost_usd=4.50,  # 90% of 5.0 system cap -> WARN, not BLOCKED
    )
    role = RoleConfig(
        name="market_research",
        model="claude-haiku-4-5",
        provider="anthropic",
        shared=True,
        prompt_caching=True,
    )

    result = guarded_complete(session, _fake_client(), role, _CAPS, [])

    assert result.system_check.status == BudgetStatus.WARN
    assert result.response.content == "ok"
    rows = session.scalars(select(CostLedger)).all()
    assert len(rows) == 2
