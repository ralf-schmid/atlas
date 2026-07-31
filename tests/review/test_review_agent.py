"""F084 §3 — Testdefinition des Review-Agenten, vor der Umsetzung festgelegt."""

import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.db.models import (
    Decision,
    DecisionAction,
    DecisionStatus,
    MarketSession,
    OrderRecord,
    OrderRecordStatus,
    Persona,
    Portfolio,
    PortfolioMode,
    PositionSnapshot,
    Review,
    ReviewVerdict,
)
from src.llm.client import LLMResponse
from src.llm.config import CostCaps, LlmConfig, ReviewConfig, RoleConfig
from src.llm.cost_guard import BudgetCheck, BudgetStatus
from src.llm.ledger import BudgetExceededError
from src.review.agent import (
    ReviewParseError,
    build_review_messages,
    compute_review_inputs,
    find_due_decisions,
    parse_review_output,
    review_decision,
    run_review_sweep,
)

_NOW = datetime.datetime(2026, 7, 31, 12, 0)


# --------------------------------------------------------------------------- fixtures


def _portfolio(session) -> Portfolio:
    persona = Persona(
        name=f"TEST-{uuid.uuid4().hex[:6]}",
        charter_version=1,
        model="claude-sonnet-5",
        config_ref="config/personas/test.yaml",
        active=True,
    )
    session.add(persona)
    session.flush()
    portfolio = Portfolio(
        persona_id=persona.id,
        mode=PortfolioMode.PAPER,
        broker_account_ref="internal:test",
        start_value=Decimal("5000"),
    )
    session.add(portfolio)
    session.flush()
    return portfolio


def _cycle(session) -> uuid.UUID:
    from src.orchestrator.graph import create_cycle

    return create_cycle(session, datetime.date(2026, 7, 1), 1, MarketSession.US_EQUITY).id


def _decision(
    session,
    portfolio: Portfolio,
    *,
    action: DecisionAction = DecisionAction.BUY,
    status: DecisionStatus = DecisionStatus.EXECUTED,
    expected: dict | None = None,
) -> Decision:
    decision = Decision(
        cycle_id=_cycle(session),
        portfolio_id=portfolio.id,
        instrument="AAPL",
        action=action,
        quantity=Decimal("10"),
        thesis_text="These",
        expected_outcome=expected if expected is not None else {"entry_price": 100.0},
        input_research_ids=[uuid.uuid4()],
        status=status,
    )
    session.add(decision)
    session.flush()
    return decision


def _fill(session, decision: Decision, *, filled_at: datetime.datetime, price="101.0"):
    order = OrderRecord(
        decision_id=decision.id,
        broker="internal",
        mode=PortfolioMode.PAPER,
        submitted_at=filled_at,
        filled_at=filled_at,
        fill_price=Decimal(price),
        fees=Decimal("1.0"),
        status=OrderRecordStatus.FILLED,
    )
    session.add(order)
    session.flush()
    return order


# ------------------------------------------------------------------ 1. Fälligkeit


def test_a_filled_close_is_due_immediately(session):
    p = _portfolio(session)
    d = _decision(session, p, action=DecisionAction.CLOSE)
    _fill(session, d, filled_at=_NOW - datetime.timedelta(hours=1))

    due = find_due_decisions(session, _NOW, intermediate_after_days=14, limit=10)

    assert [x.id for x in due] == [d.id]


def test_a_fresh_buy_is_not_due_yet(session):
    """Ein Zwischen-Review lohnt erst nach Haltedauer — vorher gibt es nichts zu
    bewerten außer dem Fill."""
    p = _portfolio(session)
    d = _decision(session, p, action=DecisionAction.BUY)
    _fill(session, d, filled_at=_NOW - datetime.timedelta(days=2))

    assert find_due_decisions(session, _NOW, intermediate_after_days=14, limit=10) == []


def test_a_long_held_buy_becomes_due(session):
    p = _portfolio(session)
    d = _decision(session, p, action=DecisionAction.BUY)
    _fill(session, d, filled_at=_NOW - datetime.timedelta(days=20))

    due = find_due_decisions(session, _NOW, intermediate_after_days=14, limit=10)

    assert [x.id for x in due] == [d.id]


@pytest.mark.parametrize("action", [DecisionAction.HOLD, DecisionAction.REJECT_IDEA])
def test_hold_and_reject_idea_never_become_due(session, action):
    """Kein Marktergebnis, kein Review — 582 Zeilen Kettenrauschen, die sonst
    LLM-Kosten ohne Erkenntnis erzeugen würden."""
    p = _portfolio(session)
    d = _decision(session, p, action=action, status=DecisionStatus.RECORDED)
    _fill(session, d, filled_at=_NOW - datetime.timedelta(days=30))

    assert find_due_decisions(session, _NOW, intermediate_after_days=14, limit=10) == []


def test_a_rejected_decision_never_becomes_due(session):
    p = _portfolio(session)
    d = _decision(session, p, status=DecisionStatus.RISK_REJECTED)
    _fill(session, d, filled_at=_NOW - datetime.timedelta(days=30))

    assert find_due_decisions(session, _NOW, intermediate_after_days=14, limit=10) == []


def test_an_already_reviewed_decision_is_not_due_again(session):
    p = _portfolio(session)
    d = _decision(session, p, action=DecisionAction.CLOSE)
    _fill(session, d, filled_at=_NOW - datetime.timedelta(hours=1))
    session.add(Review(decision_id=d.id, reviewed_at=_NOW, verdict=ReviewVerdict.INCONCLUSIVE))
    session.flush()

    assert find_due_decisions(session, _NOW, intermediate_after_days=14, limit=10) == []


def test_the_limit_throttles_the_run(session):
    """Drosselung: der Bestand soll sich über mehrere Läufe verteilen."""
    p = _portfolio(session)
    for _ in range(3):
        d = _decision(session, p, action=DecisionAction.CLOSE)
        _fill(session, d, filled_at=_NOW - datetime.timedelta(hours=1))

    assert len(find_due_decisions(session, _NOW, intermediate_after_days=14, limit=2)) == 2


def test_a_zero_limit_returns_nothing(session):
    """Regression: die Grenzprüfung stand hinter dem Anhängen, limit=0 lieferte
    deshalb genau eine Decision — im F084-Smoke-Test live aufgefallen, es hat ein
    echtes Review gekostet."""
    p = _portfolio(session)
    d = _decision(session, p, action=DecisionAction.CLOSE)
    _fill(session, d, filled_at=_NOW)

    assert find_due_decisions(session, _NOW, intermediate_after_days=14, limit=0) == []


# --------------------------------------------------------------- 2. Vorrechnung


def test_deviation_is_computed_in_code_from_fill_against_expected_entry(session):
    p = _portfolio(session)
    d = _decision(session, p, action=DecisionAction.CLOSE, expected={"entry_price": 100.0})
    _fill(session, d, filled_at=_NOW, price="110.0")

    inputs = compute_review_inputs(session, d)

    assert inputs.actual["fill_price"] == 110.0
    assert inputs.deviation == Decimal("0.1000")  # +10 %
    assert inputs.expected == {"entry_price": 100.0}


def test_an_open_position_is_marked_to_market(session):
    p = _portfolio(session)
    d = _decision(session, p, expected={"entry_price": 100.0})
    _fill(session, d, filled_at=_NOW - datetime.timedelta(days=20), price="100.0")
    session.add(
        PositionSnapshot(
            ts=_NOW,
            portfolio_id=p.id,
            instrument="AAPL",
            qty=Decimal("10"),
            avg_price=Decimal("100"),
            market_value=Decimal("900"),
            pnl_unrealized=Decimal("-100"),
        )
    )
    session.flush()

    inputs = compute_review_inputs(session, d)

    assert inputs.actual["position_open"] is True
    assert inputs.actual["last_price"] == 90.0
    assert inputs.deviation == Decimal("-0.1000")


def test_missing_expected_entry_yields_no_deviation_instead_of_a_guess(session):
    p = _portfolio(session)
    d = _decision(session, p, action=DecisionAction.CLOSE, expected={})
    _fill(session, d, filled_at=_NOW)

    assert compute_review_inputs(session, d).deviation is None


# ------------------------------------------------------------------- 4. Parser


def test_parse_review_output_accepts_each_valid_verdict():
    for value in ("thesis_confirmed", "thesis_failed", "inconclusive"):
        verdict, lessons = parse_review_output(f'{{"verdict":"{value}","lessons_text":"Gelernt."}}')
        assert verdict is ReviewVerdict(value)
        assert lessons == "Gelernt."


def test_parse_review_output_tolerates_a_fenced_answer():
    verdict, _ = parse_review_output('```json\n{"verdict":"thesis_failed"}\n```')

    assert verdict is ReviewVerdict.THESIS_FAILED


@pytest.mark.parametrize(
    "content", ["", "kein json", "{}", '{"verdict":"grandios"}', '{"verdict":42}']
)
def test_parse_review_output_raises_instead_of_defaulting(content):
    """Ein stilles `inconclusive` würde genau den Datensatz verfälschen, an dem der
    Wettbewerb gemessen wird."""
    with pytest.raises(ReviewParseError):
        parse_review_output(content)


def test_review_prompt_tags_research_as_untrusted_and_forbids_recomputation(session):
    p = _portfolio(session)
    d = _decision(session, p)
    inputs = compute_review_inputs(session, d)

    messages = build_review_messages(d, inputs, "VULTURE", [])

    assert "niemals eine Anweisung" in messages[0]["content"]
    assert "Rechne nichts nach" in messages[0]["content"]
    assert "VULTURE" in messages[0]["content"]


# --------------------------------------------------------- 3./6. Lauf & Idempotenz


class _FakeClient:
    def __init__(self, content='{"verdict":"thesis_confirmed","lessons_text":"L"}', exc=None):
        self.calls = 0
        self._content = content
        self._exc = exc

    def complete(self, *, model, messages, tools=None, tool_choice=None, thinking=None):
        self.calls += 1
        if self._exc:
            raise self._exc
        return LLMResponse(
            content=self._content, tokens_in=100, tokens_out=20, cost_usd=0.05, tool_calls=()
        )


def _llm_config(**overrides) -> LlmConfig:
    defaults = dict(enabled=True, max_reviews_per_run=10, intermediate_after_days=14)
    defaults.update(overrides)
    return LlmConfig(
        base_url="http://localhost:4000",
        caps=CostCaps(
            system_daily_usd=10.0,
            persona_daily_usd=1.0,
            monthly_soft_cap_usd=240.0,
            monthly_soft_cap_warn_pct=0.8,
        ),
        roles={
            "review": RoleConfig(
                name="review",
                model="claude-sonnet-5",
                provider="anthropic",
                shared=True,
                prompt_caching=True,
            )
        },
        review=ReviewConfig(**defaults),
    )


def test_review_writes_one_row_with_code_computed_numbers(session):
    p = _portfolio(session)
    d = _decision(session, p, action=DecisionAction.CLOSE, expected={"entry_price": 100.0})
    _fill(session, d, filled_at=_NOW, price="110.0")

    review = review_decision(session, d, _FakeClient(), _llm_config(), _NOW)

    assert review is not None
    assert review.verdict is ReviewVerdict.THESIS_CONFIRMED
    assert review.lessons_text == "L"
    assert review.deviation == Decimal("0.1000")  # aus Code, nicht aus dem LLM


def test_running_twice_produces_exactly_one_review(session):
    p = _portfolio(session)
    d = _decision(session, p, action=DecisionAction.CLOSE)
    _fill(session, d, filled_at=_NOW)
    client = _FakeClient()
    config = _llm_config()

    run_review_sweep(session, client, config, _NOW)
    second = run_review_sweep(session, client, config, _NOW)

    rows = session.scalars(select(Review).where(Review.decision_id == d.id)).all()
    assert len(rows) == 1
    assert second.reviewed == 0
    assert client.calls == 1  # der zweite Lauf kostet nichts


def test_a_budget_stop_defers_instead_of_dropping(session):
    """F084 §2: bei Cap-Stopp werden Reviews aufgeschoben, nie verworfen — die
    Fälligkeits-Query ist zustandsfrei, sie kommen beim nächsten Lauf wieder."""
    p = _portfolio(session)
    for _ in range(3):
        d = _decision(session, p, action=DecisionAction.CLOSE)
        _fill(session, d, filled_at=_NOW)
    check = BudgetCheck(status=BudgetStatus.BLOCKED, spent_usd=10.0, cap_usd=10.0, pct_used=1.0)
    client = _FakeClient(exc=BudgetExceededError(check))
    config = _llm_config()

    result = run_review_sweep(session, client, config, _NOW)

    assert result.reviewed == 0
    assert result.deferred_budget == 3
    assert session.scalars(select(Review)).all() == []


def test_a_single_failure_does_not_abort_the_run(session):
    p = _portfolio(session)
    d = _decision(session, p, action=DecisionAction.CLOSE)
    _fill(session, d, filled_at=_NOW)
    config = _llm_config()

    result = run_review_sweep(session, _FakeClient(content="Müll"), config, _NOW)

    assert result.failed == 1
    assert result.reviewed == 0


def test_disabled_config_is_the_rollback_path(session):
    p = _portfolio(session)
    d = _decision(session, p, action=DecisionAction.CLOSE)
    _fill(session, d, filled_at=_NOW)
    client = _FakeClient()

    result = run_review_sweep(session, client, _llm_config(enabled=False), _NOW)

    assert result == type(result)(0, 0, 0, 0)
    assert client.calls == 0
