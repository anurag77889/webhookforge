"""Webhook subscription API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_api_key
from app.database import get_db
from app.schemas.subscription import (
    EVENT_TYPE_PATTERN,
    SubscriptionCreate,
    SubscriptionListResponse,
    SubscriptionResponse,
)
from app.services.subscriptions import (
    create_subscription,
    deactivate_subscription,
    list_active_subscriptions,
)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
WriteAuthorized = Annotated[None, Depends(require_api_key)]


@router.post("", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def register_subscription(
    subscription_input: SubscriptionCreate,
    session: DatabaseSession,
    _: WriteAuthorized,
) -> SubscriptionResponse:
    return SubscriptionResponse.model_validate(
        await create_subscription(session, subscription_input)
    )


@router.get("", response_model=SubscriptionListResponse)
async def list_subscriptions(
    session: DatabaseSession,
    event_type: str | None = Query(default=None, pattern=EVENT_TYPE_PATTERN.pattern),
) -> SubscriptionListResponse:
    subscriptions = await list_active_subscriptions(session, event_type)
    return SubscriptionListResponse(
        subscriptions=[SubscriptionResponse.model_validate(subscription) for subscription in subscriptions]
    )


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    subscription_id: uuid.UUID,
    session: DatabaseSession,
    _: WriteAuthorized,
) -> None:
    if not await deactivate_subscription(session, subscription_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
