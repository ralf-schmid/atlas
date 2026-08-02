"""The five §4.7 selection criteria as code — no LLM, no free-text judgement.

ARCHITECTURE.md §4.7 fixes *what* counts and with which weight:

    1. Risiko-adjustierte Rendite (Sortino)                      40 %
    2. Gesamtrendite nach synthetischen Kosten (Slippage-Malus)  25 %
    3. Max Drawdown (invers)                                     15 %
    4. Thesen-Qualität (Anteil thesis_confirmed)                 10 %
    5. Operative Zuverlässigkeit                                 10 %

It does *not* fix how five quantities in five different units become one score.
Two decisions were made here and are open to revision (F089 §2):

* **Min-max over the field, not against absolute targets.** Per criterion the
  best persona scores 1.0, the worst 0.0, the rest linearly in between. This is
  a competition between six agents on identical data, so "best in field" is the
  meaningful reference; an absolute scale would need target numbers nobody has
  fixed. When all six are equal (the normal state in week one — everybody at
  0.00 %), everyone gets 0.5 rather than an arbitrary winner.
* **Unavailable criteria drop out and their weight is redistributed** over the
  remaining ones, proportionally. Sortino needs 20 daily returns (F082) and
  simply does not exist in week one; thesis quality needs closed reviews. Scoring
  a persona 0 for data that cannot exist yet would be a measurement artefact, not
  a result. The report always names which criteria were counted.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import (
    AgentRun,
    AgentRunStatus,
    Decision,
    DecisionStatus,
    OrderRecord,
    OrderRecordStatus,
    Review,
    ReviewVerdict,
)

# §4.7, verbatim. Changing these changes who wins — never silently (CLAUDE.md).
CRITERION_WEIGHTS: dict[str, float] = {
    "sortino": 0.40,
    "adjusted_return": 0.25,
    "max_drawdown": 0.15,
    "thesis_quality": 0.10,
    "reliability": 0.10,
}

CRITERION_LABELS: dict[str, str] = {
    "sortino": "Risiko-adj. Rendite (Sortino)",
    "adjusted_return": "Rendite nach Kosten",
    "max_drawdown": "Max Drawdown (invers)",
    "thesis_quality": "Thesen-Qualität",
    "reliability": "Operative Zuverlässigkeit",
}


@dataclass(frozen=True, slots=True)
class ReliabilityInputs:
    """The three sub-signals §4.7 criterion 5 names, each as a raw rate."""

    error_rate: float | None  # failed agent_runs / all agent_runs
    risk_reject_rate: float | None  # risk-rejected / decisions that reached the gate
    fill_rate: float | None  # filled orders / orders with a terminal outcome

    def score(self) -> float | None:
        """Equal thirds over whichever sub-signals exist (F089 §2).

        No sub-weights are fixed in §4.7, so inventing a 40/30/30 split would be
        a second undocumented decision on top of the normalisation. Equal
        weighting is the assumption that adds the least.
        """
        parts = [
            1.0 - self.error_rate if self.error_rate is not None else None,
            1.0 - self.risk_reject_rate if self.risk_reject_rate is not None else None,
            self.fill_rate,
        ]
        available = [part for part in parts if part is not None]
        if not available:
            return None
        return sum(available) / len(available)


@dataclass(frozen=True, slots=True)
class PersonaCriteria:
    """One persona's raw (un-normalised) value per criterion. None = not measurable."""

    persona: str
    sortino: float | None
    adjusted_return: float
    max_drawdown: float
    thesis_quality: float | None
    reliability: float | None
    reliability_inputs: ReliabilityInputs
    reviews_total: int
    trades: int


@dataclass(frozen=True, slots=True)
class ScoredPersona:
    rank: int
    persona: str
    total_score: float
    criteria: PersonaCriteria
    normalized: dict[str, float]


@dataclass(frozen=True, slots=True)
class CompetitionScore:
    since: datetime.date
    counted_criteria: list[str]
    skipped_criteria: list[str]
    effective_weights: dict[str, float]
    personas: list[ScoredPersona]


def normalize_min_max(values: dict[str, float], higher_is_better: bool = True) -> dict[str, float]:
    """Field-relative 0..1 per criterion; all-equal input maps to 0.5 for everyone."""
    if not values:
        return {}
    low = min(values.values())
    high = max(values.values())
    if high == low:
        return dict.fromkeys(values, 0.5)
    span = high - low
    if higher_is_better:
        return {key: (value - low) / span for key, value in values.items()}
    return {key: (high - value) / span for key, value in values.items()}


def score_personas(criteria: list[PersonaCriteria], since: datetime.date) -> CompetitionScore:
    """Weighted §4.7 score over the criteria that are measurable for the field."""
    raw_by_criterion: dict[str, dict[str, float]] = {
        "sortino": {c.persona: c.sortino for c in criteria if c.sortino is not None},
        "adjusted_return": {c.persona: c.adjusted_return for c in criteria},
        "max_drawdown": {c.persona: c.max_drawdown for c in criteria},
        "thesis_quality": {
            c.persona: c.thesis_quality for c in criteria if c.thesis_quality is not None
        },
        "reliability": {c.persona: c.reliability for c in criteria if c.reliability is not None},
    }

    # A criterion only counts when *every* persona has a value: a partial field
    # would score personas against a yardstick that does not apply to all of them.
    counted = [
        name for name, values in raw_by_criterion.items() if values and len(values) == len(criteria)
    ]
    skipped = [name for name in CRITERION_WEIGHTS if name not in counted]

    weight_sum = sum(CRITERION_WEIGHTS[name] for name in counted)
    effective = (
        {name: CRITERION_WEIGHTS[name] / weight_sum for name in counted} if weight_sum else {}
    )

    normalized_by_criterion = {
        name: normalize_min_max(raw_by_criterion[name], higher_is_better=name != "max_drawdown")
        for name in counted
    }

    scored: list[ScoredPersona] = []
    for entry in criteria:
        normalized = {name: normalized_by_criterion[name][entry.persona] for name in counted}
        total = sum(normalized[name] * effective[name] for name in counted)
        scored.append(
            ScoredPersona(
                rank=0,
                persona=entry.persona,
                total_score=total,
                criteria=entry,
                normalized=normalized,
            )
        )

    scored.sort(key=lambda item: item.total_score, reverse=True)
    ranked = [
        ScoredPersona(
            rank=index,
            persona=item.persona,
            total_score=item.total_score,
            criteria=item.criteria,
            normalized=item.normalized,
        )
        for index, item in enumerate(scored, start=1)
    ]

    return CompetitionScore(
        since=since,
        counted_criteria=counted,
        skipped_criteria=skipped,
        effective_weights=effective,
        personas=ranked,
    )


# ---------------------------------------------------------------------------
# DB-backed inputs
# ---------------------------------------------------------------------------


def thesis_quality(
    session: Session, portfolio_id: uuid.UUID, since: datetime.datetime
) -> tuple[float | None, int]:
    """§4.7 criterion 4: share of `thesis_confirmed` among that portfolio's reviews.

    Returns (share, review_count); share is None while no review exists — a
    persona that has not closed a position yet has no thesis quality, which is
    not the same as a bad one.
    """
    rows = session.execute(
        select(Review.verdict, func.count())
        .join(Decision, Decision.id == Review.decision_id)
        .where(Decision.portfolio_id == portfolio_id, Review.reviewed_at >= since)
        .group_by(Review.verdict)
    ).all()
    total = sum(count for _, count in rows)
    if total == 0:
        return None, 0
    confirmed = sum(count for verdict, count in rows if verdict == ReviewVerdict.THESIS_CONFIRMED)
    return confirmed / total, total


def reliability_inputs(
    session: Session, portfolio_id: uuid.UUID, since: datetime.datetime
) -> ReliabilityInputs:
    """§4.7 criterion 5: error rate, risk-gate reject rate, fill plausibility."""
    runs = session.execute(
        select(AgentRun.status, func.count())
        .where(AgentRun.portfolio_id == portfolio_id)
        .group_by(AgentRun.status)
    ).all()
    run_counts = {status: count for status, count in runs}
    runs_total = sum(run_counts.values())
    error_rate = run_counts.get(AgentRunStatus.FAILED, 0) / runs_total if runs_total else None

    # Only decisions that actually reached the gate count; `hold` and
    # `reject_idea` never do, and counting them would dilute the rate.
    #
    # Deliberately keyed on `status`, not on `risk_check IS NOT NULL`: a JSON
    # column assigned Python `None` stores JSON `null`, not SQL NULL (SQLAlchemy
    # `none_as_null` default), so every hold decision would pass an IS NOT NULL
    # filter while reading back as `None` in the ORM. Status is unambiguous.
    gate_reached = (
        DecisionStatus.RISK_REJECTED,
        DecisionStatus.HITL_PENDING,
        DecisionStatus.HITL_REJECTED,
        DecisionStatus.APPROVED,
        DecisionStatus.EXECUTED,
        DecisionStatus.EXECUTION_FAILED,
    )
    gated = session.scalar(
        select(func.count())
        .select_from(Decision)
        .where(Decision.portfolio_id == portfolio_id, Decision.status.in_(gate_reached))
    )
    rejected = session.scalar(
        select(func.count())
        .select_from(Decision)
        .where(
            Decision.portfolio_id == portfolio_id,
            Decision.status == DecisionStatus.RISK_REJECTED,
        )
    )
    risk_reject_rate = (rejected or 0) / gated if gated else None

    # "Fill-Plausibilität": of the orders that reached a terminal state, how many
    # actually filled. Still-open NEW orders are excluded — they have no outcome
    # yet and would otherwise punish a persona for trading late in the day.
    terminal = (
        OrderRecordStatus.FILLED,
        OrderRecordStatus.PARTIALLY_FILLED,
        OrderRecordStatus.CANCELED,
        OrderRecordStatus.REJECTED,
        OrderRecordStatus.EXPIRED,
    )
    order_rows = session.execute(
        select(OrderRecord.status, func.count())
        .join(Decision, Decision.id == OrderRecord.decision_id)
        .where(
            Decision.portfolio_id == portfolio_id,
            OrderRecord.submitted_at >= since,
            OrderRecord.status.in_(terminal),
        )
        .group_by(OrderRecord.status)
    ).all()
    order_total = sum(count for _, count in order_rows)
    filled = sum(
        count
        for status, count in order_rows
        if status in (OrderRecordStatus.FILLED, OrderRecordStatus.PARTIALLY_FILLED)
    )
    fill_rate = filled / order_total if order_total else None

    return ReliabilityInputs(
        error_rate=error_rate, risk_reject_rate=risk_reject_rate, fill_rate=fill_rate
    )
