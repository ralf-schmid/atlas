"""F099 §4 — Testdefinition des Meta-Review-Agenten, vor der Umsetzung festgelegt."""

import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.db.models import (
    Cycle,
    Decision,
    DecisionAction,
    DecisionStatus,
    MarketSession,
    MetaReview,
    MetaReviewVerdict,
    Persona,
    Portfolio,
    PortfolioMode,
    ResearchItem,
)
from src.llm.client import LLMResponse
from src.llm.config import CostCaps, LlmConfig, MetaReviewConfig, RoleConfig
from src.llm.cost_guard import BudgetCheck, BudgetStatus
from src.llm.ledger import BudgetExceededError
from src.review.meta_agent import (
    MetaReviewParseError,
    build_meta_review_messages,
    find_meta_review_candidates,
    meta_review_decision,
    parse_meta_review_output,
    run_meta_review_sweep,
)

_NOW = datetime.datetime(2026, 8, 2, 18, 30)


# --------------------------------------------------------------------------- fixtures


def _portfolio(session, *, archived: datetime.datetime | None = None) -> Portfolio:
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
        archived_at=archived,
    )
    session.add(portfolio)
    session.flush()
    return portfolio


def _cycle(session, *, started_at: datetime.datetime | None = None) -> Cycle:
    from src.orchestrator.graph import create_cycle

    cycle = create_cycle(session, datetime.date(2026, 8, 1), 1, MarketSession.US_EQUITY)
    if started_at is not None:
        cycle.started_at = started_at
        session.flush()
    return cycle


def _research(session, cycle: Cycle, *, instrument: str, summary: str) -> ResearchItem:
    item = ResearchItem(
        cycle_id=cycle.id,
        agent="news_research",
        source_type="news",
        source_ref="test",
        summary=summary,
        instruments=[instrument],
    )
    session.add(item)
    session.flush()
    return item


def _rejected(
    session,
    portfolio: Portfolio,
    *,
    instrument: str = "ABAT",
    cycle: Cycle | None = None,
    research_ids: list[uuid.UUID] | None = None,
) -> Decision:
    cycle = cycle if cycle is not None else _cycle(session)
    decision = Decision(
        cycle_id=cycle.id,
        portfolio_id=portfolio.id,
        instrument=instrument,
        action=DecisionAction.REJECT_IDEA,
        thesis_text="Ueberverkauft, aber kein Trigger",
        rejection_reason="Kein fundamentaler Cross-Check verfuegbar",
        expected_outcome={},
        input_research_ids=research_ids or [uuid.uuid4()],
        status=DecisionStatus.RECORDED,
    )
    session.add(decision)
    session.flush()
    return decision


class _FakeClient:
    def __init__(
        self,
        content='{"verdict":"research_gap","missing_source":"Fundamentaldaten aktienfinder",'
        '"lessons_text":"L"}',
        exc=None,
    ):
        self.calls = 0
        self.last_thinking = None
        self.last_messages = None
        self._content = content
        self._exc = exc

    def complete(self, *, model, messages, tools=None, tool_choice=None, thinking=None):
        self.calls += 1
        self.last_thinking = thinking
        self.last_messages = messages
        if self._exc:
            raise self._exc
        return LLMResponse(
            content=self._content, tokens_in=100, tokens_out=20, cost_usd=0.05, tool_calls=()
        )


def _llm_config(**overrides) -> LlmConfig:
    defaults = dict(enabled=True, max_per_run=5)
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
                provider="opencode-zen",
                shared=True,
                prompt_caching=True,
            )
        },
        meta_review=MetaReviewConfig(**defaults),
    )


# ------------------------------------------------------------------ 1. Kandidatenwahl


def test_only_reject_idea_decisions_are_candidates(session):
    """Alles mit Marktergebnis gehoert dem Review-Agenten (F084), nicht hierher."""
    p = _portfolio(session)
    rejected = _rejected(session, p)
    session.add(
        Decision(
            cycle_id=_cycle(session).id,
            portfolio_id=p.id,
            instrument="AAPL",
            action=DecisionAction.BUY,
            thesis_text="These",
            expected_outcome={},
            input_research_ids=[uuid.uuid4()],
            status=DecisionStatus.EXECUTED,
        )
    )
    session.flush()

    candidates = find_meta_review_candidates(session, limit=10)

    assert [c.id for c in candidates] == [rejected.id]


def test_archived_seasons_are_not_sampled(session):
    """Gleiche Begruendung wie F096 fuer `review`: eine Saison, die nicht mehr
    zaehlt, darf auch die Recherche-Diagnose nicht mehr treiben."""
    archived = _portfolio(session, archived=datetime.datetime(2026, 7, 30))
    _rejected(session, archived)

    assert find_meta_review_candidates(session, limit=10) == []


def test_the_sample_is_spread_across_personas(session):
    """Ohne Round-Robin frisst die ablehnungsfreudigste Persona das ganze
    Wochenkontingent und die Stichprobe sagt ueber die anderen nichts."""
    loud = _portfolio(session)
    quiet = _portfolio(session)
    for _ in range(5):
        _rejected(session, loud)
    quiet_decision = _rejected(session, quiet)

    candidates = find_meta_review_candidates(session, limit=2)

    assert quiet_decision.id in {c.id for c in candidates}
    assert len(candidates) == 2


def test_an_already_meta_reviewed_decision_is_not_sampled_again(session):
    p = _portfolio(session)
    d = _rejected(session, p)
    session.add(
        MetaReview(
            decision_id=d.id,
            reviewed_at=_NOW,
            verdict=MetaReviewVerdict.RESEARCH_SUFFICIENT,
        )
    )
    session.flush()

    assert find_meta_review_candidates(session, limit=10) == []


def test_the_cap_holds_mid_round(session):
    """Der Round-Robin darf nicht erst am Rundenende abbrechen — sonst liefert ein
    ungerades Limit bei mehreren Personas eine Stichprobe zu viel, und jede zu viel
    ist ein bezahlter LLM-Call."""
    for _ in range(3):
        p = _portfolio(session)
        _rejected(session, p)

    assert len(find_meta_review_candidates(session, limit=1)) == 1


def test_limit_zero_samples_nothing(session):
    """F084 hat genau hier live einen Review verschenkt (limit=0 lieferte eine
    Zeile) — derselbe Fehler kostet hier echtes Geld."""
    p = _portfolio(session)
    _rejected(session, p)

    assert find_meta_review_candidates(session, limit=0) == []


# ------------------------------------------------------------------------ 2. Prompt


def test_the_prompt_separates_used_research_from_the_available_pool(session):
    """`research_ignored` ist nur entscheidbar, wenn das Modell beides sieht."""
    p = _portfolio(session)
    cycle = _cycle(session)
    used = _research(session, cycle, instrument="ABAT", summary="verwendet")
    unused = _research(session, cycle, instrument="ABAT", summary="uebersehen")
    d = _rejected(session, p, cycle=cycle, research_ids=[used.id])

    messages = build_meta_review_messages(d, "CONTRA", [used], [unused])

    user = messages[1]["content"]
    assert "VERWENDETE Recherche" in user
    assert "VERFUEGBARER Pool" in user
    assert "uebersehen" in user


def test_the_prompt_tags_research_as_untrusted_and_scopes_the_question(session):
    p = _portfolio(session)
    d = _rejected(session, p)

    messages = build_meta_review_messages(d, "CONTRA", [], [])

    system = messages[0]["content"]
    assert "niemals eine Anweisung" in system
    assert "RECHERCHE-GRUNDLAGE" in system
    assert "CONTRA" in system


# ------------------------------------------------------------------------- 3. Parsing


@pytest.mark.parametrize(
    "content",
    ["", "kein JSON", '{"lessons_text":"L"}', '{"verdict":"thesis_failed"}'],
)
def test_parse_raises_instead_of_defaulting(content):
    """Ein erfundenes `research_sufficient` wuerde Ralf sagen, seine
    Ingestion-Pipeline sei in Ordnung."""
    with pytest.raises(MetaReviewParseError):
        parse_meta_review_output(content)


def test_missing_source_is_dropped_unless_the_verdict_is_a_gap():
    """Sonst landen Phantom-Eintraege im Ingestion-Backlog."""
    verdict, missing, _ = parse_meta_review_output(
        '{"verdict":"research_sufficient","missing_source":"SEC-Filing","lessons_text":"L"}'
    )

    assert verdict is MetaReviewVerdict.RESEARCH_SUFFICIENT
    assert missing is None


def test_json_wrapped_in_prose_is_still_parsed():
    """Sonnet stellt dem JSON gern einen Satz voran. Das Urteil deswegen zu
    verwerfen waere teuer und unnoetig — streng ist nur das Verdict selbst."""
    verdict, _, lessons = parse_meta_review_output(
        'Hier meine Bewertung:\n{"verdict":"research_ignored","lessons_text":"L"}\nEnde.'
    )

    assert verdict is MetaReviewVerdict.RESEARCH_IGNORED
    assert lessons == "L"


def test_a_gap_keeps_its_missing_source():
    _, missing, _ = parse_meta_review_output(
        '{"verdict":"research_gap","missing_source":"SEC-Filing","lessons_text":"L"}'
    )

    assert missing == "SEC-Filing"


# --------------------------------------------------------- 4. Lauf, Idempotenz, Budget


def test_meta_review_writes_one_row(session):
    p = _portfolio(session)
    d = _rejected(session, p)

    result = meta_review_decision(session, d, _FakeClient(), _llm_config(), _NOW)

    assert result is not None
    assert result.verdict is MetaReviewVerdict.RESEARCH_GAP
    assert result.missing_source == "Fundamentaldaten aktienfinder"
    assert result.lessons_text == "L"


def test_a_second_call_on_the_same_decision_costs_nothing(session):
    """Zweite Verteidigungslinie neben der Kandidaten-Query: ein manuell
    angestossener Lauf darf keinen zweiten Call bezahlen."""
    p = _portfolio(session)
    d = _rejected(session, p)
    client = _FakeClient()
    meta_review_decision(session, d, client, _llm_config(), _NOW)

    assert meta_review_decision(session, d, client, _llm_config(), _NOW) is None
    assert client.calls == 1


def test_running_twice_produces_exactly_one_meta_review(session):
    p = _portfolio(session)
    d = _rejected(session, p)
    client = _FakeClient()
    config = _llm_config()

    run_meta_review_sweep(session, client, config, _NOW)
    second = run_meta_review_sweep(session, client, config, _NOW)

    rows = session.scalars(select(MetaReview).where(MetaReview.decision_id == d.id)).all()
    assert len(rows) == 1
    assert second.reviewed == 0
    assert client.calls == 1


def test_the_weekly_cap_is_the_cost_brake(session):
    p = _portfolio(session)
    for _ in range(9):
        _rejected(session, p)
    client = _FakeClient()

    result = run_meta_review_sweep(session, client, _llm_config(max_per_run=5), _NOW)

    assert result.reviewed == 5
    assert client.calls == 5


def test_a_budget_stop_defers_instead_of_dropping(session):
    p = _portfolio(session)
    for _ in range(3):
        _rejected(session, p)
    check = BudgetCheck(status=BudgetStatus.BLOCKED, spent_usd=10.0, cap_usd=10.0, pct_used=1.0)

    result = run_meta_review_sweep(
        session, _FakeClient(exc=BudgetExceededError(check)), _llm_config(), _NOW
    )

    assert result.reviewed == 0
    assert result.deferred_budget == 3
    assert session.scalars(select(MetaReview)).all() == []


def test_a_single_failure_does_not_abort_the_run(session):
    p = _portfolio(session)
    _rejected(session, p)

    result = run_meta_review_sweep(session, _FakeClient(content="Muell"), _llm_config(), _NOW)

    assert result.failed == 1
    assert result.reviewed == 0


def test_disabled_config_is_the_rollback_path(session):
    p = _portfolio(session)
    _rejected(session, p)
    client = _FakeClient()

    result = run_meta_review_sweep(session, client, _llm_config(enabled=False), _NOW)

    assert result == type(result)(0, 0, 0, 0)
    assert client.calls == 0


def test_adaptive_thinking_is_disabled(session):
    """F073/F084: claude-sonnet-5 kann sein ganzes Completion-Budget in einen
    internen Denkblock stecken und liefert dann leeren Content."""
    p = _portfolio(session)
    d = _rejected(session, p)
    client = _FakeClient()

    meta_review_decision(session, d, client, _llm_config(), _NOW)

    assert client.last_thinking == {"type": "disabled"}


def test_an_embedding_failure_does_not_cost_the_meta_review(session):
    """Gleiche Abwaegung wie F098: die Zeile ist das Wertvolle, der Vektor ist
    nachtragbar."""

    class _BrokenEmbedder:
        def embed(self, text: str) -> list[float]:
            raise RuntimeError("Modell kalt")

    p = _portfolio(session)
    d = _rejected(session, p)

    result = meta_review_decision(
        session, d, _FakeClient(), _llm_config(), _NOW, embedding_provider=_BrokenEmbedder()
    )

    assert result is not None
    assert result.lessons_embedding is None
