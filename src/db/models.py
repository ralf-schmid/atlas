"""Full DB schema per ARCHITECTURE.md §3.6: persona, portfolio, cycle, research_item,
decision, order_record, agent_run, position_snapshot, portfolio_snapshot, review,
cost_ledger.

See docs/features/F003-db-schema-decision-order-record.md for the design decisions not
literally specified there (status enums, UUID PKs, and why `input_research_ids[]`
existence is validated at the application layer, not via DB-level foreign key —
src/db/validation.py).
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class PortfolioMode(enum.Enum):
    PAPER = "paper"
    LIVE = "live"


class MarketSession(enum.Enum):
    US_EQUITY = "us_equity"
    CRYPTO = "crypto"


class DecisionAction(enum.Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE = "close"
    REJECT_IDEA = "reject_idea"


class DecisionStatus(enum.Enum):
    """Not literally specified in ARCHITECTURE.md §3.6 — proposed, see F003 §2."""

    PENDING = "pending"
    RISK_REJECTED = "risk_rejected"
    HITL_PENDING = "hitl_pending"
    HITL_REJECTED = "hitl_rejected"
    APPROVED = "approved"
    EXECUTED = "executed"
    RECORDED = "recorded"  # terminal status for hold / reject_idea — no order follows


class OrderRecordStatus(enum.Enum):
    """Reduced normalization of the broker's raw status — see F003 §2. Full broker
    payload is preserved in `order_record.raw`."""

    NEW = "new"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class AgentRunStatus(enum.Enum):
    """Not literally specified in ARCHITECTURE.md §3.6 — proposed, see F003 §2."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CostLedgerScope(enum.Enum):
    SYSTEM = "system"
    PERSONA = "persona"


class ReviewVerdict(enum.Enum):
    THESIS_CONFIRMED = "thesis_confirmed"
    THESIS_FAILED = "thesis_failed"
    INCONCLUSIVE = "inconclusive"


class Persona(Base):
    __tablename__ = "persona"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    charter_version: Mapped[int]
    model: Mapped[str] = mapped_column(String(100))
    config_ref: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class Portfolio(Base):
    __tablename__ = "portfolio"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    persona_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("persona.id"), nullable=False)
    mode: Mapped[PortfolioMode] = mapped_column(Enum(PortfolioMode, name="portfolio_mode"))
    broker_account_ref: Mapped[str] = mapped_column(String(100))
    base_ccy: Mapped[str] = mapped_column(String(3), default="USD")
    start_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class Cycle(Base):
    __tablename__ = "cycle"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trading_day: Mapped[date]
    seq: Mapped[int]
    started_at: Mapped[datetime]
    market_session: Mapped[MarketSession] = mapped_column(
        Enum(MarketSession, name="market_session")
    )


class ResearchItem(Base):
    """Shared across all personas — one research pool per cycle (Invariant #10)."""

    __tablename__ = "research_item"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cycle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cycle.id"), nullable=False)
    agent: Mapped[str] = mapped_column(String(100))
    source_type: Mapped[str] = mapped_column(String(50))
    source_ref: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    instruments: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    raw: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class Decision(Base):
    __tablename__ = "decision"
    __table_args__ = (
        CheckConstraint(
            "array_length(input_research_ids, 1) IS NOT NULL",
            name="ck_decision_input_research_ids_not_empty",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cycle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cycle.id"), nullable=False)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolio.id"), nullable=False)
    instrument: Mapped[str] = mapped_column(String(20))
    action: Mapped[DecisionAction] = mapped_column(Enum(DecisionAction, name="decision_action"))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    thesis_text: Mapped[str] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_outcome: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    input_research_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False
    )
    risk_check: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    hitl: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[DecisionStatus] = mapped_column(
        Enum(DecisionStatus, name="decision_status"), default=DecisionStatus.PENDING
    )


class OrderRecord(Base):
    __tablename__ = "order_record"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decision.id"), nullable=False)
    broker: Mapped[str] = mapped_column(String(50))
    broker_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mode: Mapped[PortfolioMode] = mapped_column(Enum(PortfolioMode, name="portfolio_mode"))
    submitted_at: Mapped[datetime]
    filled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    fill_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    fees: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0)
    status: Mapped[OrderRecordStatus] = mapped_column(
        Enum(OrderRecordStatus, name="order_record_status"), default=OrderRecordStatus.NEW
    )
    raw: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class AgentRun(Base):
    """One row per agent invocation. `portfolio_id` is NULL for shared agents
    (market_research, news_research) that run once per cycle, not once per persona."""

    __tablename__ = "agent_run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cycle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cycle.id"), nullable=False)
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("portfolio.id"), nullable=True
    )
    agent: Mapped[str] = mapped_column(String(100))
    status: Mapped[AgentRunStatus] = mapped_column(Enum(AgentRunStatus, name="agent_run_status"))
    tokens_in: Mapped[int | None] = mapped_column(nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class PositionSnapshot(Base):
    __tablename__ = "position_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ts: Mapped[datetime]
    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolio.id"), nullable=False)
    instrument: Mapped[str] = mapped_column(String(20))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    avg_price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    market_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    pnl_unrealized: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ts: Mapped[datetime]
    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolio.id"), nullable=False)
    total_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    cash: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    pnl_realized: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    pnl_unrealized: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    benchmark_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    max_drawdown: Mapped[Decimal] = mapped_column(Numeric(6, 4))


class Review(Base):
    __tablename__ = "review"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decision.id"), nullable=False)
    reviewed_at: Mapped[datetime]
    expected: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    actual: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    deviation: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    slippage_malus: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    verdict: Mapped[ReviewVerdict] = mapped_column(Enum(ReviewVerdict, name="review_verdict"))
    lessons_text: Mapped[str | None] = mapped_column(Text, nullable=True)


class CostLedger(Base):
    __tablename__ = "cost_ledger"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ts: Mapped[datetime]
    scope: Mapped[CostLedgerScope] = mapped_column(Enum(CostLedgerScope, name="cost_ledger_scope"))
    persona_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persona.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    tokens_in: Mapped[int] = mapped_column(default=0)
    tokens_out: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4))


class MarketBarTimeframe(enum.Enum):
    DAY = "1Day"


class MarketBar(Base):
    """OHLCV bars per instrument, see docs/features/F008-marktdaten-sync.md.

    Not part of the ARCHITECTURE.md §3.6 table list (which predates P3) — added here
    per §3.5.3 ("Kurse/Bars: Alpaca Market Data ... technische Indikatoren werden im
    Code berechnet"), which requires persisted history to compute indicators from.
    """

    __tablename__ = "market_bar"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "ts", name="uq_market_bar_symbol_timeframe_ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(20))
    timeframe: Mapped[MarketBarTimeframe] = mapped_column(
        Enum(MarketBarTimeframe, name="market_bar_timeframe")
    )
    ts: Mapped[datetime]
    open: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    high: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    low: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    close: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    volume: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    synced_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class EdgarFiling(Base):
    """Raw EDGAR filing metadata, see docs/features/F009-edgar-rss.md.

    Staging table, not `research_item` — this is the raw ingested feed entry, not yet
    an agent-produced research summary (agents read from here, not from EDGAR
    directly, per "Agenten lesen ausschliesslich aus der DB" in CLAUDE.md).
    """

    __tablename__ = "edgar_filing"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    accession_number: Mapped[str] = mapped_column(String(30), unique=True)
    cik: Mapped[str | None] = mapped_column(String(20), nullable=True)
    company_name: Mapped[str] = mapped_column(String(300))
    form_type: Mapped[str] = mapped_column(String(20))
    filed_at: Mapped[datetime]
    title: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class ScreenerResult(Base):
    """VULTURE-Screener candidate, see docs/features/F010-vulture-screener.md.

    Universum = komplettes tradable/active Alpaca-Asset-Verzeichnis (ARCHITECTURE.md
    §3.5.3) — kein Persona bekommt eine gefilterte Vorauswahl, das Ergebnis ist einfach
    für alle Personas in der DB sichtbar (Invariante #10).
    """

    __tablename__ = "screener_result"
    __table_args__ = (
        UniqueConstraint("symbol", "screened_at", name="uq_screener_result_symbol_screened_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    screened_at: Mapped[date]
    symbol: Mapped[str] = mapped_column(String(20))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    volume: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    synced_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class PublicationArticle(Base):
    """One segmented article from a Boersenmedien-PDF-Ausgabe, see
    docs/features/F011-publications-pdf-fallback.md.

    Full article text is stored here for agent consumption only — CLAUDE.md forbids
    surfacing Zeitschriften-Volltexte in UI or repo (metadata/summaries/source refs
    only); that constraint lives in the UI/API layer, not here.
    """

    __tablename__ = "publication_article"
    __table_args__ = (
        UniqueConstraint(
            "publication", "issue_date", "seq", name="uq_publication_article_issue_seq"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publication: Mapped[str] = mapped_column(String(100))
    issue_date: Mapped[date]
    seq: Mapped[int]
    page: Mapped[int]
    title: Mapped[str] = mapped_column(String(500))
    text: Mapped[str] = mapped_column(Text)
    source_file: Mapped[str] = mapped_column(String(500))
    synced_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class AktienfinderSnapshot(Base):
    """DOM-extracted aktienfinder.de view + screenshot evidence, see
    docs/features/F012-aktienfinder-grabbing.md.

    `fields` holds whatever was extracted per `config/ingestion.yaml`'s field->selector
    mapping (Fair-Value, Qualitäts-Score, Dividenden-Historie, ...) — kept as JSONB
    rather than fixed columns since the exact field set is expected to grow once the
    real (currently unbuilt) login session lets us see the live page structure.
    `screenshot_path` is the lineage evidence (§3.5.2), never the field values
    themselves — CLAUDE.md forbids aktienfinder-Volltexte in UI/Repo, only the
    structured fields + a screenshot reference.
    """

    __tablename__ = "aktienfinder_snapshot"
    __table_args__ = (
        UniqueConstraint("symbol", "snapshot_date", name="uq_aktienfinder_snapshot_symbol_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(20))
    snapshot_date: Mapped[date]
    fields: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    screenshot_path: Mapped[str] = mapped_column(String(500))
    synced_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class MusterdepotTransaction(Base):
    """A buy/sell posted from DER AKTIONÄR's own real-money model portfolio
    ("Musterdepot"), see docs/features/F014-musterdepot-transactions.md.

    Purely informational research data about a *different, external* portfolio —
    never auto-executed. No code path in this repo turns a row here into an order;
    that would violate Invariant #2 (privilege separation) and #3 (no order without
    a persisted Decision). Once P4's agents exist, this becomes one more
    research_item input, exactly like any other magazine content — read here by
    every persona equally (Invariant #10), never fed to one exclusively.
    """

    __tablename__ = "musterdepot_transaction"
    __table_args__ = (
        UniqueConstraint("message_id", "seq", name="uq_musterdepot_transaction_message_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[str] = mapped_column(String(300))
    seq: Mapped[int]
    action: Mapped[str] = mapped_column(String(30))
    instrument_name: Mapped[str] = mapped_column(String(200))
    wkn: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    currency: Mapped[str] = mapped_column(String(10))
    raw_text: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime]
    synced_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
