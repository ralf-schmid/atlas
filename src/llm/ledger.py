"""The orchestrator-side half of Invariant #7's "doppelt durchgesetzt" cost brake.

F006 built the pure cap-comparison functions (src/llm/cost_guard.py) and the LiteLLM
client (src/llm/client.py) but nothing that actually reads/writes `cost_ledger` — this
module is that missing piece, wired in *before* any real LLM call happens in
production (see docs/features/F019-cost-ledger-enforcement.md).
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from src.db.models import CostLedger, CostLedgerScope
from src.llm.client import LiteLLMClient, LLMResponse
from src.llm.config import CostCaps, RoleConfig
from src.llm.cost_guard import (
    BudgetCheck,
    BudgetStatus,
    check_monthly_soft_cap,
    check_persona_budget,
    check_system_budget,
)


class BudgetExceededError(Exception):
    def __init__(self, check: BudgetCheck) -> None:
        self.check = check
        super().__init__(
            f"Budget exceeded: {check.spent_usd:.4f}/{check.cap_usd:.4f} USD ({check.pct_used:.0%})"
        )


@dataclass(frozen=True, slots=True)
class GuardedCompletionResult:
    response: LLMResponse
    system_check: BudgetCheck
    persona_check: BudgetCheck | None
    monthly_check: BudgetCheck


def record_llm_call(
    session: Session,
    *,
    ts: datetime.datetime,
    scope: CostLedgerScope,
    persona_id: uuid.UUID | None,
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
) -> CostLedger:
    entry = CostLedger(
        ts=ts,
        scope=scope,
        persona_id=persona_id,
        provider=provider,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
    )
    session.add(entry)
    session.flush()
    return entry


def sum_system_spend_today(session: Session, now: datetime.datetime) -> float:
    start, end = _day_bounds(now)
    return _sum_cost(session, CostLedger.ts >= start, CostLedger.ts < end)


def sum_persona_spend_today(
    session: Session, persona_id: uuid.UUID, now: datetime.datetime
) -> float:
    start, end = _day_bounds(now)
    return _sum_cost(
        session,
        CostLedger.ts >= start,
        CostLedger.ts < end,
        CostLedger.persona_id == persona_id,
    )


def sum_month_spend(session: Session, now: datetime.datetime) -> float:
    start = datetime.datetime(now.year, now.month, 1)
    if now.month == 12:
        end = datetime.datetime(now.year + 1, 1, 1)
    else:
        end = datetime.datetime(now.year, now.month + 1, 1)
    return _sum_cost(session, CostLedger.ts >= start, CostLedger.ts < end)


def guarded_complete(
    session: Session,
    client: LiteLLMClient,
    role: RoleConfig,
    caps: CostCaps,
    messages: list[dict[str, str]],
    *,
    persona_id: uuid.UUID | None = None,
) -> GuardedCompletionResult:
    if not role.shared and persona_id is None:
        raise ValueError(f"Role {role.name!r} is not shared and requires a persona_id")

    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)

    system_check = check_system_budget(sum_system_spend_today(session, now), caps)
    if system_check.status == BudgetStatus.BLOCKED:
        raise BudgetExceededError(system_check)

    persona_check: BudgetCheck | None = None
    if not role.shared:
        assert persona_id is not None
        persona_check = check_persona_budget(
            sum_persona_spend_today(session, persona_id, now), caps
        )
        if persona_check.status == BudgetStatus.BLOCKED:
            raise BudgetExceededError(persona_check)

    monthly_check = check_monthly_soft_cap(sum_month_spend(session, now), caps)

    response = client.complete(model=role.model, messages=messages)

    scope = CostLedgerScope.SYSTEM if role.shared else CostLedgerScope.PERSONA
    record_llm_call(
        session,
        ts=now,
        scope=scope,
        persona_id=None if role.shared else persona_id,
        provider=role.provider,
        model=role.model,
        tokens_in=response.tokens_in,
        tokens_out=response.tokens_out,
        cost_usd=response.cost_usd,
    )

    return GuardedCompletionResult(
        response=response,
        system_check=system_check,
        persona_check=persona_check,
        monthly_check=monthly_check,
    )


def _day_bounds(now: datetime.datetime) -> tuple[datetime.datetime, datetime.datetime]:
    start = datetime.datetime(now.year, now.month, now.day)
    return start, start + datetime.timedelta(days=1)


def _sum_cost(session: Session, *conditions: ColumnElement[bool]) -> float:
    stmt = select(func.coalesce(func.sum(CostLedger.cost_usd), 0)).where(*conditions)
    return float(session.scalar(stmt) or 0.0)
