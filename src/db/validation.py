"""Application-level lineage validation that Postgres can't express via a plain FK.

`decision.input_research_ids` is a Postgres ARRAY column — Postgres has no native way
to enforce that every element is a valid foreign key into `research_item` without a
trigger. ARCHITECTURE.md §3.6 (line 219) explicitly calls for this at the "Persistenz-
Layer" (application layer), which is what this module does. Call before every
`Decision` insert.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import ResearchItem


def validate_research_ids_exist(session: Session, research_ids: list[uuid.UUID]) -> None:
    if not research_ids:
        raise ValueError("input_research_ids must not be empty")

    existing_ids = set(
        session.scalars(select(ResearchItem.id).where(ResearchItem.id.in_(research_ids)))
    )
    missing = set(research_ids) - existing_ids
    if missing:
        raise ValueError(f"Unknown research_item id(s): {sorted(missing)}")
