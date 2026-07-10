"""The orchestrator-side half of Invariant #7's "doppelt durchgesetzt" cost brake.

F006 built the pure cap-comparison functions (src/llm/cost_guard.py) and the LiteLLM
client (src/llm/client.py) but nothing that actually reads/writes `cost_ledger` — this
module is that missing piece, wired in *before* any real LLM call happens in
production (see docs/features/F019-cost-ledger-enforcement.md).
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
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

# Arbitrary fixed key for Postgres' session-level advisory lock (security-audit P3):
# serializes the recheck+insert below across the 6 parallel per-persona sessions a
# cycle's `Send` fanout opens, without holding a lock across the (slow) LLM call
# itself — that would serialize the very parallelism the fanout exists for. Any
# int64 works as long as it's the same constant everywhere this is taken.
_SYSTEM_BUDGET_LOCK_KEY = 875_309_142


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
    messages: list[dict[str, object]],
    *,
    persona_id: uuid.UUID | None = None,
    tools: list[dict[str, object]] | None = None,
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

    response = client.complete(model=role.model, messages=messages, tools=tools)

    # The LLM call above is unlocked and can run in parallel across personas — the
    # checks above may all have read a stale (pre-sibling-insert) total. What must be
    # atomic is only the brief recheck+insert here (see F0xx / security-audit P3): the
    # cost is real and already incurred, so it is recorded regardless of the recheck
    # outcome (losing it would desync cost_ledger from actual spend) — the recheck
    # only decides whether to *signal* an overrun via BudgetExceededError so the next
    # call sees an accurate total and gets blocked before its own LLM call.
    scope = CostLedgerScope.SYSTEM if role.shared else CostLedgerScope.PERSONA
    with _system_budget_lock(session):
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
        # Recheck *after* inserting this call's own cost — this is what tells us
        # whether this specific call (combined with whatever siblings committed while
        # its LLM round-trip was in flight) tipped the system over the cap.
        post_call_system_check = check_system_budget(sum_system_spend_today(session, now), caps)
        # F055: the persona cap needs the same post-call recheck as the system cap
        # above — without it, a single call that pushes one persona over its
        # (much tighter) daily cap goes unsignaled: the shared system cap is 5x
        # looser (one system-wide pool vs. six per-persona pools), so it rarely
        # trips at the same moment a lone persona blows through its own limit.
        # That persona would then keep spending unchecked until its *next* call,
        # whenever that is.
        post_call_persona_check: BudgetCheck | None = None
        if not role.shared:
            assert persona_id is not None
            post_call_persona_check = check_persona_budget(
                sum_persona_spend_today(session, persona_id, now), caps
            )

    if post_call_system_check.status == BudgetStatus.BLOCKED:
        raise BudgetExceededError(post_call_system_check)
    if (
        post_call_persona_check is not None
        and post_call_persona_check.status == BudgetStatus.BLOCKED
    ):
        raise BudgetExceededError(post_call_persona_check)

    return GuardedCompletionResult(
        response=response,
        system_check=system_check,
        persona_check=persona_check,
        monthly_check=monthly_check,
    )


@contextmanager
def _system_budget_lock(session: Session) -> Iterator[None]:
    """Postgres session-level advisory lock — explicitly released (not xact-scoped),
    so it doesn't linger for the rest of the caller's transaction (that transaction
    stays open well past this function, until the orchestrator's graph-node commit)."""
    session.execute(select(func.pg_advisory_lock(_SYSTEM_BUDGET_LOCK_KEY)))
    try:
        yield
    finally:
        session.execute(select(func.pg_advisory_unlock(_SYSTEM_BUDGET_LOCK_KEY)))


def _day_bounds(now: datetime.datetime) -> tuple[datetime.datetime, datetime.datetime]:
    start = datetime.datetime(now.year, now.month, now.day)
    return start, start + datetime.timedelta(days=1)


def _sum_cost(session: Session, *conditions: ColumnElement[bool]) -> float:
    stmt = select(func.coalesce(func.sum(CostLedger.cost_usd), 0)).where(*conditions)
    return float(session.scalar(stmt) or 0.0)
