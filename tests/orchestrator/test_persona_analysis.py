"""See docs/features/F021-persona-analysis-agent.md §3, tests 11-18."""

from __future__ import annotations

import datetime
import json
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.broker.protocol import AccountBalance, OrderResult, Position
from src.db.models import (
    AgentRun,
    Decision,
    DecisionAction,
    DecisionStatus,
    MarketBar,
    MarketBarTimeframe,
    MarketSession,
    Persona,
    Portfolio,
    ResearchItem,
)
from src.llm.client import LiteLLMClient
from src.llm.config import CostCaps, LlmConfig, RoleConfig
from src.orchestrator.graph import create_cycle
from src.orchestrator.persona_analysis import analyze_persona_cycle
from src.orchestrator.seed import seed_personas_and_portfolios


class _FakeAdapter:
    def __init__(self, balance: AccountBalance, positions: list[Position] | None = None) -> None:
        self._balance = balance
        self._positions = positions or []

    def place_order(self, **kwargs: object) -> OrderResult:
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError

    def get_positions(self) -> list[Position]:
        return self._positions

    def get_account_balance(self) -> AccountBalance:
        return self._balance


def _llm_config() -> LlmConfig:
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


def _fake_client(content: str, cost_usd: str = "0.02") -> LiteLLMClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 500, "completion_tokens": 100},
            },
            headers={"x-litellm-response-cost": cost_usd},
        )

    return LiteLLMClient(
        base_url="http://test",
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _seed_vulture(session: Session) -> tuple[Persona, Portfolio]:
    seed_personas_and_portfolios(session)
    persona = session.scalar(select(Persona).filter_by(name="VULTURE"))
    assert persona is not None
    portfolio = session.scalar(select(Portfolio).filter_by(persona_id=persona.id))
    assert portfolio is not None
    return persona, portfolio


def _make_cycle_with_research_item(session: Session) -> tuple[object, ResearchItem]:
    cycle = create_cycle(session, datetime.date(2026, 7, 7), 1, MarketSession.US_EQUITY)
    item = ResearchItem(
        cycle_id=cycle.id,
        agent="market_research",
        source_type="screener_result",
        source_ref="AAPL",
        summary="AAPL volume spike",
        instruments=["AAPL"],
        raw={},
    )
    session.add(item)
    session.flush()
    return cycle, item


def test_empty_research_pool_produces_no_decision_and_no_agent_run(session: Session) -> None:
    _persona, portfolio = _seed_vulture(session)
    cycle = create_cycle(session, datetime.date(2026, 7, 7), 1, MarketSession.US_EQUITY)
    adapter = _FakeAdapter(AccountBalance(cash=5000, equity=5000, buying_power=5000))

    decision = analyze_persona_cycle(
        session,
        _fake_client("{}"),
        _llm_config(),
        cycle.id,
        portfolio.id,
        _persona.id,
        "VULTURE",
        adapter,
    )

    assert decision is None
    assert session.scalars(select(AgentRun).where(AgentRun.cycle_id == cycle.id)).all() == []


def test_hold_response_persists_recorded_decision(session: Session) -> None:
    persona, portfolio = _seed_vulture(session)
    cycle, item = _make_cycle_with_research_item(session)
    content = json.dumps(
        {
            "action": "hold",
            "instrument": "PORTFOLIO",
            "thesis_text": "nothing compelling this cycle",
            "input_research_ids": [str(item.id)],
        }
    )
    adapter = _FakeAdapter(AccountBalance(cash=5000, equity=5000, buying_power=5000))

    decision = analyze_persona_cycle(
        session,
        _fake_client(content),
        _llm_config(),
        cycle.id,
        portfolio.id,
        persona.id,
        "VULTURE",
        adapter,
    )

    assert decision is not None
    assert decision.status == DecisionStatus.RECORDED
    assert decision.action == DecisionAction.HOLD
    assert decision.input_research_ids == [item.id]


def test_reject_idea_response_persists_with_rejection_reason(session: Session) -> None:
    persona, portfolio = _seed_vulture(session)
    cycle, item = _make_cycle_with_research_item(session)
    content = json.dumps(
        {
            "action": "reject_idea",
            "instrument": "AAPL",
            "thesis_text": "too expensive for our universe",
            "rejection_reason": "price_too_high",
            "input_research_ids": [str(item.id)],
        }
    )
    adapter = _FakeAdapter(AccountBalance(cash=5000, equity=5000, buying_power=5000))

    decision = analyze_persona_cycle(
        session,
        _fake_client(content),
        _llm_config(),
        cycle.id,
        portfolio.id,
        persona.id,
        "VULTURE",
        adapter,
    )

    assert decision is not None
    assert decision.status == DecisionStatus.RECORDED
    assert decision.action == DecisionAction.REJECT_IDEA
    assert decision.rejection_reason == "price_too_high"


def _seed_market_bars(session: Session, symbol: str) -> None:
    base = datetime.datetime(2026, 6, 1)
    for i in range(5):
        session.add(
            MarketBar(
                symbol=symbol,
                timeframe=MarketBarTimeframe.DAY,
                ts=base + datetime.timedelta(days=i),
                open=Decimal("4.00"),
                high=Decimal("4.20"),
                low=Decimal("3.90"),
                close=Decimal("4.00"),
                volume=Decimal("1000000"),
            )
        )
    session.flush()


def test_buy_response_approved_by_risk_gate(session: Session) -> None:
    persona, portfolio = _seed_vulture(session)
    cycle, item = _make_cycle_with_research_item(session)
    _seed_market_bars(session, "AAPL")
    content = json.dumps(
        {
            "action": "buy",
            "instrument": "AAPL",
            "conviction": 0.5,
            "thesis_text": "volume spike + insider buy filing",
            "input_research_ids": [str(item.id)],
        }
    )
    adapter = _FakeAdapter(AccountBalance(cash=5000, equity=5000, buying_power=5000))

    decision = analyze_persona_cycle(
        session,
        _fake_client(content),
        _llm_config(),
        cycle.id,
        portfolio.id,
        persona.id,
        "VULTURE",
        adapter,
    )

    assert decision is not None
    assert decision.action == DecisionAction.BUY
    assert decision.status == DecisionStatus.APPROVED
    assert decision.risk_check is not None
    assert decision.risk_check["approved"] is True
    assert decision.quantity is not None and decision.quantity > 0


def test_buy_response_rejected_by_risk_gate_when_trades_today_exceeded(
    session: Session,
) -> None:
    persona, portfolio = _seed_vulture(session)
    cycle, item = _make_cycle_with_research_item(session)
    _seed_market_bars(session, "AAPL")
    content = json.dumps(
        {
            "action": "buy",
            "instrument": "AAPL",
            "conviction": 0.5,
            "thesis_text": "volume spike",
            "input_research_ids": [str(item.id)],
        }
    )

    # VULTURE max_trades_per_day = 10 (config/personas/vulture.yaml) — force a
    # portfolio state whose trades-today count already exceeds it by seeding 10
    # real order_records for this portfolio today.
    from src.db.models import OrderRecord, OrderRecordStatus, PortfolioMode

    for i in range(10):
        other_cycle = create_cycle(
            session, datetime.date(2026, 7, 7), 100 + i, MarketSession.US_EQUITY
        )
        other_item = ResearchItem(
            cycle_id=other_cycle.id,
            agent="market_research",
            source_type="screener_result",
            source_ref="MSFT",
            summary="x",
            instruments=["MSFT"],
            raw={},
        )
        session.add(other_item)
        session.flush()
        other_decision = Decision(
            cycle_id=other_cycle.id,
            portfolio_id=portfolio.id,
            instrument="MSFT",
            action=DecisionAction.BUY,
            quantity=Decimal("1"),
            thesis_text="x",
            expected_outcome={},
            input_research_ids=[other_item.id],
            status=DecisionStatus.EXECUTED,
        )
        session.add(other_decision)
        session.flush()
        session.add(
            OrderRecord(
                decision_id=other_decision.id,
                broker="alpaca_paper",
                mode=PortfolioMode.PAPER,
                submitted_at=datetime.datetime(2026, 7, 7, 9, 0),
                status=OrderRecordStatus.FILLED,
            )
        )
    session.flush()

    adapter = _FakeAdapter(AccountBalance(cash=5000, equity=5000, buying_power=5000))

    decision = analyze_persona_cycle(
        session,
        _fake_client(content),
        _llm_config(),
        cycle.id,
        portfolio.id,
        persona.id,
        "VULTURE",
        adapter,
    )

    assert decision is not None
    assert decision.status == DecisionStatus.RISK_REJECTED
    assert decision.risk_check is not None
    assert decision.risk_check["approved"] is False


def test_invalid_research_ids_falls_back_to_reject_idea(session: Session) -> None:
    persona, portfolio = _seed_vulture(session)
    cycle, _item = _make_cycle_with_research_item(session)
    content = json.dumps(
        {
            "action": "buy",
            "instrument": "AAPL",
            "conviction": 0.9,
            "thesis_text": "made up citation",
            "input_research_ids": ["00000000-0000-0000-0000-000000000000"],
        }
    )
    adapter = _FakeAdapter(AccountBalance(cash=5000, equity=5000, buying_power=5000))

    decision = analyze_persona_cycle(
        session,
        _fake_client(content),
        _llm_config(),
        cycle.id,
        portfolio.id,
        persona.id,
        "VULTURE",
        adapter,
    )

    assert decision is not None
    assert decision.action == DecisionAction.REJECT_IDEA
    assert decision.rejection_reason == "invalid_research_ids"


def test_buy_without_market_data_falls_back_to_reject_idea(session: Session) -> None:
    persona, portfolio = _seed_vulture(session)
    cycle, item = _make_cycle_with_research_item(session)
    content = json.dumps(
        {
            "action": "buy",
            "instrument": "NODATA",
            "conviction": 0.5,
            "thesis_text": "no bars exist for this symbol",
            "input_research_ids": [str(item.id)],
        }
    )
    adapter = _FakeAdapter(AccountBalance(cash=5000, equity=5000, buying_power=5000))

    decision = analyze_persona_cycle(
        session,
        _fake_client(content),
        _llm_config(),
        cycle.id,
        portfolio.id,
        persona.id,
        "VULTURE",
        adapter,
    )

    assert decision is not None
    assert decision.action == DecisionAction.REJECT_IDEA
    assert decision.rejection_reason == "insufficient_price_history"


def test_every_call_writes_exactly_one_agent_run(session: Session) -> None:
    persona, portfolio = _seed_vulture(session)
    cycle, item = _make_cycle_with_research_item(session)
    content = json.dumps(
        {
            "action": "hold",
            "instrument": "PORTFOLIO",
            "thesis_text": "nothing new",
            "input_research_ids": [str(item.id)],
        }
    )
    adapter = _FakeAdapter(AccountBalance(cash=5000, equity=5000, buying_power=5000))

    analyze_persona_cycle(
        session,
        _fake_client(content),
        _llm_config(),
        cycle.id,
        portfolio.id,
        persona.id,
        "VULTURE",
        adapter,
    )

    runs = session.scalars(select(AgentRun).where(AgentRun.cycle_id == cycle.id)).all()
    assert len(runs) == 1
    assert runs[0].agent == "persona_analysis"
