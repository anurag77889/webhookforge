"""Subscription persistence operations, independent of FastAPI."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription
from app.schemas.subscription import SubscriptionCreate


async def create_subscription(
    session: AsyncSession, subscription_input: SubscriptionCreate
) -> Subscription:
    subscription = Subscription(
        endpoint_url=str(subscription_input.endpoint_url),
        event_types=subscription_input.event_types,
        secret=subscription_input.secret.get_secret_value(),
    )
    session.add(subscription)
    await session.commit()
    await session.refresh(subscription)
    return subscription


async def list_active_subscriptions(
    session: AsyncSession, event_type: str | None = None
) -> list[Subscription]:
    statement = select(Subscription).where(Subscription.active.is_(True))
    if event_type is not None:
        statement = statement.where(Subscription.event_types.contains([event_type]))
    result = await session.scalars(statement.order_by(Subscription.created_at.desc()))
    return list(result)


async def deactivate_subscription(session: AsyncSession, subscription_id: uuid.UUID) -> bool:
    subscription = await session.get(Subscription, subscription_id)
    if subscription is None:
        return False
    if subscription.active:
        subscription.active = False
        await session.commit()
    return True
