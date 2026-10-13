"""Integration tests for PostgreSQL-backed subscription queries."""

import uuid

import pytest

from app.database import SessionFactory
from app.schemas.subscription import SubscriptionCreate
from app.services.subscriptions import (
    create_subscription,
    deactivate_subscription,
    list_active_subscriptions,
)


@pytest.mark.asyncio
async def test_event_type_filter_and_deactivation() -> None:
    marker = uuid.uuid4().hex
    subscription_input = SubscriptionCreate(
        endpoint_url=f"https://{marker}.example/webhooks",
        event_types=["payment.success", "order.created"],
        secret="integration-secret",
    )

    async with SessionFactory() as session:
        subscription = await create_subscription(session, subscription_input)
        matching = await list_active_subscriptions(session, "payment.success")
        assert subscription.id in {item.id for item in matching}

        assert await deactivate_subscription(session, subscription.id) is True
        remaining = await list_active_subscriptions(session, "payment.success")
        assert subscription.id not in {item.id for item in remaining}

        await session.delete(subscription)
        await session.commit()
