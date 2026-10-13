"""Celery task that consumes durable event-dispatch records."""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select

from app.celery_app import celery_app
from app.database import SyncSessionFactory
from app.models.event import Event
from app.models.outbox import OutboxRecord
from app.models.subscription import Subscription

logger = structlog.get_logger()


@celery_app.task(name="webhookforge.dispatch_event")
def dispatch_event(event_id: str) -> int:
    """Resolve eligible subscribers and mark the outbox record dispatched.

    The delivery phase will add one HTTP delivery task per eligible subscriber.
    """
    parsed_event_id = uuid.UUID(event_id)
    with SyncSessionFactory.begin() as session:
        outbox_record = session.scalar(select(OutboxRecord).where(OutboxRecord.event_id == parsed_event_id).with_for_update())
        if outbox_record is None or outbox_record.dispatched_at is not None:
            return 0
        event = session.get(Event, parsed_event_id)
        if event is None:  # pragma: no cover
            return 0
        subscription_count = session.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.active.is_(True), Subscription.event_types.contains([event.event_type])
            )
        )
        outbox_record.dispatch_attempts += 1
        outbox_record.dispatched_at = datetime.now(timezone.utc)
    logger.info("event_dispatch_completed", event_id=event_id, status="queued")
    return subscription_count or 0
