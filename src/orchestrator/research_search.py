"""Read-only lookup over the historical `research_item` pool, exposed to
persona_analysis as an LLM tool call — see docs/features/F045-persona-search-tool.md.

Lets a persona pull in matching research from *before* its current cycle's
synthesis window (e.g. an aktienfinder recommendation that arrived days ago and
already scrolled out of the window) instead of only ever seeing whatever happened
to land in the current cycle. Deliberately still no LLM call here and no new data
source — this only queries `research_item` rows research_synthesis.py already
created (same "Agenten lesen ausschließlich aus der DB" boundary, CLAUDE.md).
"""

from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Cycle, ResearchItem

# Every persona gets the identical tool (Invariant #10 fairness) — schema is
# OpenAI-style function calling, which the LiteLLM proxy expects regardless of
# the underlying model.
SEARCH_RESEARCH_POOL_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "search_research_pool",
        "description": (
            "Durchsucht den gesamten bisherigen Research-Pool (nicht nur das aktuelle "
            "Zyklus-Fenster oben) nach Symbolen oder Stichworten — z. B. um gezielt "
            "nach aktienfinder-Empfehlungen, Blog-Beiträgen oder Filings zu einem "
            "Ticker zu suchen, die nicht im aktuellen Kontext aufgelistet sind. "
            "Gefundene Treffer kannst du wie jedes andere research_item über seine "
            "id in input_research_ids zitieren. Mindestens einer der drei Parameter "
            "muss angegeben werden."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'Ticker oder ISIN, z. B. ["AAPL"] oder ["DE0007164600"]',
                },
                "keyword": {
                    "type": "string",
                    "description": "Freitext-Suche in den Zusammenfassungen",
                },
                "source_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        'z. B. ["aktienfinder_blog", "aktienfinder_snapshot", '
                        '"edgar_filing", "publication_article"]'
                    ),
                },
            },
        },
    },
}

_MAX_RESULTS = 10
# Tighter than research_synthesis.py's 600 chars — a single tool call can return
# several items at once, so the per-item budget is more conservative (F044/F045
# cost invariant: bounding LLM context growth from ingested article text).
_TEXT_EXCERPT_MAX_CHARS = 400


def search_research_pool(
    session: Session,
    *,
    as_of: datetime.datetime,
    symbols: list[str] | None,
    keyword: str | None,
    source_types: list[str] | None,
) -> list[dict[str, object]]:
    stmt = (
        select(ResearchItem)
        .join(Cycle, ResearchItem.cycle_id == Cycle.id)
        .where(Cycle.started_at <= as_of)
        .order_by(ResearchItem.published_at.desc().nullslast())
        .limit(_MAX_RESULTS)
    )
    if symbols:
        stmt = stmt.where(ResearchItem.instruments.overlap(symbols))
    if keyword:
        escaped = keyword.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        stmt = stmt.where(ResearchItem.summary.ilike(f"%{escaped}%"))
    if source_types:
        stmt = stmt.where(ResearchItem.source_type.in_(source_types))

    items = session.scalars(stmt).all()
    return [_serialize(item) for item in items]


def _serialize(item: ResearchItem) -> dict[str, object]:
    return {
        "id": str(item.id),
        "source_type": item.source_type,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "summary": item.summary,
        "instruments": item.instruments,
        "raw": _capped_raw(item.raw),
    }


def _capped_raw(raw: dict[str, object]) -> dict[str, object]:
    text = raw.get("text_excerpt")
    if isinstance(text, str) and len(text) > _TEXT_EXCERPT_MAX_CHARS:
        return {**raw, "text_excerpt": text[:_TEXT_EXCERPT_MAX_CHARS] + "…"}
    return raw
