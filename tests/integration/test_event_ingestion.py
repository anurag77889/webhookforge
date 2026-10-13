"""Integration tests for atomic event ingestion."""

import uuid

import pytest
from sqlalchemy import func, select

from app.database import SessionFactory
from app.models.event import Event
from app.models.outbox import OutboxRecord
from app.models.subscription import Subscription
from app.services.events import ingest_event


@pytest.mark.asyncio
async def test_duplicate_key_creates_one_event_and_one_outbox_record() -> None:
    marker = uuid.uuid4().hex
    key = f"test-idempotency-{marker}"
    event_type = f"test.{marker}"
    subscription = Subscription(
        endpoint_url=f"https://{marker}.example/webhooks",
        event_types=[event_type],
        secret="integration-secret",
    )

    async with SessionFactory() as session:
        session.add(subscription)
        await session.commit()

        created = await ingest_event(
            session,
            idempotency_key=key,
            event_type=event_type,
            payload={"payment_id": marker},
        )
        duplicate = await ingest_event(
            session,
            idempotency_key=key,
            event_type=event_type,
            payload={"payment_id": marker},
        )

        assert created.created is True
        assert created.subscriptions_notified == 1
        assert duplicate.created is False
        assert duplicate.event_id == created.event_id

        event_count = await session.scalar(
            select(func.count(Event.id)).where(Event.idempotency_key == key)
        )
        outbox_count = await session.scalar(
            select(func.count(OutboxRecord.id)).where(OutboxRecord.event_id == created.event_id)
        )
        assert event_count == 1
        assert outbox_count == 1

        await session.delete(subscription)
        event = await session.get(Event, created.event_id)
        assert event is not None
        await session.delete(event)
        await session.commit()
