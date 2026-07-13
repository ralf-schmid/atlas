"""Full compiled-graph run — see docs/features/F016-orchestrator-graph-skeleton.md §3
test 6 and docs/features/F021-persona-analysis-agent.md. Marked integration:
exercises real `Send`-based fanout end-to-end against a real (local) Postgres via
`get_session_factory()` — each node opens its own, independently-committed session
(see F016 §2, thread-safety), so this can't run inside the standard rolled-back
`session` fixture like tests/orchestrator/test_graph_nodes.py. `max_concurrency=1`
keeps the run deterministic for assertions; production concurrency is unaffected
(each node already uses its own session).

The LLM client is mocked (no real API calls in the default test suite) but responds
dynamically: it extracts the real research_item id(s) from the outgoing request body
and cites them back in a "hold" response, since the id is only known once
`_shared_research_node` has actually run inside this same `graph.invoke()` call.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import uuid

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import select

from src.broker.protocol import AccountBalance, OrderResult, OrderSide
from src.db.base import get_session_factory
from src.db.models import (
    AgentRun,
    Cycle,
    Decision,
    DecisionStatus,
    EdgarFiling,
    MarketBar,
    MarketBarTimeframe,
    MarketSession,
    ResearchItem,
)
from src.llm.client import LiteLLMClient
from src.llm.config import CostCaps, LlmConfig, RoleConfig
from src.orchestrator.graph import CycleState, build_and_compile_graph, list_active_portfolios
from src.orchestrator.seed import seed_personas_and_portfolios

pytestmark = pytest.mark.integration

_ID_RE = re.compile(r'"id":\s*"([0-9a-f-]{36})"')


class _FakeBrokerAdapter:
    """Never touches the real Alpaca API — see F023 §2: without this, resuming a
    `buy` interrupt to "approved" in a test would place a real Alpaca Paper order
    via the real `get_adapter()` registry."""

    def place_order(self, **kwargs: object) -> OrderResult:
        return OrderResult(
            entry_order_id="test-entry",
            stop_order_id="test-stop",
            symbol=str(kwargs["symbol"]),
            qty=float(kwargs["qty"]),  # type: ignore[arg-type]
            side=OrderSide.BUY,
            stop_loss_price=float(kwargs["stop_loss_price"]),  # type: ignore[arg-type]
        )

    def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError

    def get_positions(self) -> list[object]:
        return []

    def get_account_balance(self) -> AccountBalance:
        return AccountBalance(cash=5000.0, equity=5000.0, buying_power=5000.0)


def _fake_adapter_factory(persona_name: str) -> _FakeBrokerAdapter:
    return _FakeBrokerAdapter()


def _hold_response_client() -> LiteLLMClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        user_content = body["messages"][1]["content"]
        cited_ids = _ID_RE.findall(user_content)
        content = json.dumps(
            {
                "action": "hold",
                "instrument": "PORTFOLIO",
                "thesis_text": "integration test — no real analysis",
                "input_research_ids": cited_ids,
            }
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 200, "completion_tokens": 50},
            },
            headers={"x-litellm-response-cost": "0.001"},
        )

    return LiteLLMClient(
        base_url="http://test",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _test_llm_config() -> LlmConfig:
    return LlmConfig(
        base_url="http://test",
        caps=CostCaps(
            system_daily_usd=5.0,
            persona_daily_usd=1.0,
            monthly_soft_cap_usd=120.0,
            monthly_soft_cap_warn_pct=0.8,
        ),
        roles={
            "persona_analysis": RoleConfig(
                name="persona_analysis",
                model="claude-sonnet-5",
                provider="anthropic",
                shared=False,
                prompt_caching=True,
            )
        },
    )


def test_full_cycle_run_fans_out_to_all_six_portfolios_and_synthesizes_research() -> None:
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — needs a real local Postgres, see F016 §5")

    session_factory = get_session_factory()
    with session_factory() as seed_session:
        seed_personas_and_portfolios(seed_session)
        seed_session.add(
            EdgarFiling(
                accession_number=f"TEST-{uuid.uuid4().hex[:12]}",
                company_name="Test Corp",
                form_type="8-K",
                filed_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
                title="Test filing for F016/F017/F021 integration test",
                link="https://example.invalid/test-filing",
                summary="irrelevant raw feed summary",
            )
        )
        seed_session.commit()

    graph = build_and_compile_graph(
        session_factory,
        _hold_response_client(),
        _test_llm_config(),
        adapter_factory=_fake_adapter_factory,
    )
    trading_day = datetime.date.today()
    initial_state = CycleState(
        trading_day=trading_day.isoformat(),
        seq=1,
        market_session=MarketSession.US_EQUITY.value,
        cycle_id=None,
        research_item_ids=[],
    )

    final_state = graph.invoke(initial_state, config={"max_concurrency": 1})

    with session_factory() as session:
        cycle_id = final_state["cycle_id"]
        assert cycle_id is not None
        cycles = session.scalars(
            select(Cycle).where(Cycle.trading_day == trading_day, Cycle.seq == 1)
        ).all()
        assert len(cycles) == 1

        research_items = session.scalars(
            select(ResearchItem).where(ResearchItem.cycle_id == cycle_id)
        ).all()
        assert len(research_items) == 1
        assert research_items[0].source_type == "edgar_filing"

        agent_runs = session.scalars(select(AgentRun).where(AgentRun.cycle_id == cycle_id)).all()
        expected_portfolio_ids = {str(p.id) for p, _name in list_active_portfolios(session)}
        assert len(agent_runs) == 6
        assert {str(run.portfolio_id) for run in agent_runs} == expected_portfolio_ids
        assert all(run.agent == "persona_analysis" for run in agent_runs)

        decisions = session.scalars(select(Decision).where(Decision.cycle_id == cycle_id)).all()
        assert len(decisions) == 6
        assert {str(d.portfolio_id) for d in decisions} == expected_portfolio_ids


def _mixed_hold_and_buy_client() -> LiteLLMClient:
    """VULTURE and HYPE respond "buy" (AAPL); everyone else "hold" — see F022 §3
    test 5. Persona identity is read from the charter text in the system message
    (F018's render_charter always starts "Du bist <NAME> — ...")."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system_content = body["messages"][0]["content"]
        user_content = body["messages"][1]["content"]
        cited_ids = _ID_RE.findall(user_content)

        if "Du bist VULTURE" in system_content or "Du bist HYPE" in system_content:
            content = json.dumps(
                {
                    "action": "buy",
                    "instrument": "AAPL",
                    "conviction": 0.3,
                    "thesis_text": "integration test — buy path",
                    "input_research_ids": cited_ids,
                }
            )
        else:
            content = json.dumps(
                {
                    "action": "hold",
                    "instrument": "PORTFOLIO",
                    "thesis_text": "integration test — no real analysis",
                    "input_research_ids": cited_ids,
                }
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 200, "completion_tokens": 50},
            },
            headers={"x-litellm-response-cost": "0.001"},
        )

    return LiteLLMClient(
        base_url="http://test",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_multiple_simultaneous_hitl_interrupts_resume_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """See docs/features/F022-hitl-flow.md §3, test 5. `config/hitl.yaml` has HITL
    off for paper since F072 — force the HITL-required branch explicitly so this
    interrupt-based flow stays covered."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — needs a real local Postgres, see F016 §5")

    monkeypatch.setattr("src.orchestrator.persona_analysis.is_hitl_required", lambda mode: True)
    session_factory = get_session_factory()
    with session_factory() as seed_session:
        seed_personas_and_portfolios(seed_session)
        seed_session.add(
            EdgarFiling(
                accession_number=f"TEST-{uuid.uuid4().hex[:12]}",
                company_name="Test Corp",
                form_type="8-K",
                filed_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
                title="Test filing for F022 HITL integration test",
                link="https://example.invalid/test-filing",
                summary="irrelevant raw feed summary",
            )
        )
        base = datetime.datetime(2026, 6, 1)
        for i in range(5):
            seed_session.add(
                MarketBar(
                    symbol="AAPL",
                    timeframe=MarketBarTimeframe.DAY,
                    ts=base + datetime.timedelta(days=i),
                    open=180,
                    high=182,
                    low=178,
                    close=181,
                    volume=1000000,
                )
            )
        seed_session.commit()

    checkpointer = InMemorySaver()
    graph = build_and_compile_graph(
        session_factory,
        _mixed_hold_and_buy_client(),
        _test_llm_config(),
        checkpointer=checkpointer,
        adapter_factory=_fake_adapter_factory,
    )
    trading_day = datetime.date.today()
    initial_state = CycleState(
        trading_day=trading_day.isoformat(),
        seq=2,
        market_session=MarketSession.US_EQUITY.value,
        cycle_id=None,
        research_item_ids=[],
    )
    thread_id = "test-multi-hitl-thread"

    result = graph.invoke(
        initial_state, config={"max_concurrency": 1, "configurable": {"thread_id": thread_id}}
    )

    interrupts = result.get("__interrupt__")
    assert interrupts is not None
    assert len(interrupts) == 2  # VULTURE + HYPE

    with session_factory() as session:
        cycle_id = result["cycle_id"]
        pending = session.scalars(
            select(Decision).where(
                Decision.cycle_id == cycle_id, Decision.status == DecisionStatus.HITL_PENDING
            )
        ).all()
        assert len(pending) == 2

        recorded = session.scalars(
            select(Decision).where(
                Decision.cycle_id == cycle_id, Decision.status == DecisionStatus.RECORDED
            )
        ).all()
        assert len(recorded) == 4  # the 4 "hold" personas completed normally

    # Resume only the first interrupt — the second must remain pending.
    resumed = graph.invoke(
        Command(resume={interrupts[0].id: "approved"}),
        config={"configurable": {"thread_id": thread_id}},
    )
    assert resumed.get("__interrupt__")
    assert len(resumed["__interrupt__"]) == 1

    with session_factory() as session:
        # F023: approval flows straight into execution via the (fake) trading path.
        executed = session.scalars(
            select(Decision).where(
                Decision.cycle_id == cycle_id, Decision.status == DecisionStatus.EXECUTED
            )
        ).all()
        still_pending = session.scalars(
            select(Decision).where(
                Decision.cycle_id == cycle_id, Decision.status == DecisionStatus.HITL_PENDING
            )
        ).all()
        assert len(executed) == 1
        assert len(still_pending) == 1

    # Resume the second, no interrupts should remain.
    final = graph.invoke(
        Command(resume={resumed["__interrupt__"][0].id: "rejected"}),
        config={"configurable": {"thread_id": thread_id}},
    )
    assert not final.get("__interrupt__")
    with session_factory() as session:
        rejected = session.scalars(
            select(Decision).where(
                Decision.cycle_id == cycle_id, Decision.status == DecisionStatus.HITL_REJECTED
            )
        ).all()
        assert len(rejected) == 1
