"""Celery task that consumes durable event-dispatch records."""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select

from app.celery_app import celery_app
from app.database import SyncSessionFactory
from app.models.event import Event
from app.models.outbox import OutboxRecord
from app.models.subscription import Subscription

logger = structlog.get_logger()


@celery_app.task(name="webhookforge.dispatch_event")
def dispatch_event(event_id: str) -> int:
    """Resolve eligible subscribers, enqueue a delivery task for each, and
    mark the outbox record dispatched."""
    from app.tasks.deliver import deliver_webhook

    parsed_event_id = uuid.UUID(event_id)
    with SyncSessionFactory.begin() as session:
        outbox_record = session.scalar(select(OutboxRecord).where(OutboxRecord.event_id == parsed_event_id).with_for_update())
        if outbox_record is None or outbox_record.dispatched_at is not None:
            return 0
        event = session.get(Event, parsed_event_id)
        if event is None:  # pragma: no cover
            return 0
        subscription_ids = session.scalars(
            select(Subscription.id).where(
                Subscription.active.is_(True), Subscription.event_types.contains([event.event_type])
            )
        ).all()
        for sub_id in subscription_ids:
            deliver_webhook.delay(str(event_id), str(sub_id))
        outbox_record.dispatch_attempts += 1
        outbox_record.dispatched_at = datetime.now(UTC)
    logger.info("event_dispatch_completed", event_id=event_id, subscriptions=len(subscription_ids), status="queued")
    return len(subscription_ids)
