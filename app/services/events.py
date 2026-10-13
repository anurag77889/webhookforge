"""Atomic event ingestion and recoverable dispatch handoff."""

import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.outbox import OutboxRecord
from app.models.subscription import Subscription

logger = structlog.get_logger()


@dataclass(frozen=True)
class IngestedEvent:
    event_id: uuid.UUID
    created: bool
    subscriptions_notified: int = 0


async def ingest_event(session: AsyncSession, *, idempotency_key: str, event_type: str, payload: dict[str, Any]) -> IngestedEvent:
    """Create an event once and write its dispatch record in the same transaction."""
    statement = (
        pg_insert(Event)
        .values(idempotency_key=idempotency_key, event_type=event_type, payload=payload)
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(Event.id)
    )
    event_id = (await session.execute(statement)).scalar_one_or_none()
    if event_id is None:
        existing_event_id = await session.scalar(select(Event.id).where(Event.idempotency_key == idempotency_key))
        if existing_event_id is None:  # pragma: no cover
            raise RuntimeError("idempotency conflict did not return an existing event")
        return IngestedEvent(event_id=existing_event_id, created=False)

    subscription_count = await session.scalar(
        select(func.count(Subscription.id)).where(
            Subscription.active.is_(True), Subscription.event_types.contains([event_type])
        )
    )
    session.add(OutboxRecord(event_id=event_id, topic="event.received", payload={"event_id": str(event_id), "event_type": event_type}))
    await session.commit()
    logger.info("event_ingested", event_id=str(event_id), event_type=event_type, status="queued")
    return IngestedEvent(event_id=event_id, created=True, subscriptions_notified=subscription_count or 0)
