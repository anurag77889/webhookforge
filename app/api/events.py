"""Inbound event API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_api_key
from app.database import get_db
from app.schemas.event import EventAcceptedResponse, EventCreate, EventDuplicateResponse
from app.services.events import ingest_event
from app.tasks.dispatch import dispatch_event

router = APIRouter(prefix="/events", tags=["events"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
WriteAuthorized = Annotated[None, Depends(require_api_key)]


@router.post("", response_model=EventAcceptedResponse | EventDuplicateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_event(event_input: EventCreate, session: DatabaseSession, _: WriteAuthorized, response: Response, idempotency_key: Annotated[str | None, Header()] = None) -> EventAcceptedResponse | EventDuplicateResponse:
    if not idempotency_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Idempotency-Key header is required.")
    result = await ingest_event(session, idempotency_key=idempotency_key, event_type=event_input.event_type, payload=event_input.payload)
    if not result.created:
        response.status_code = status.HTTP_200_OK
        return EventDuplicateResponse(event_id=result.event_id)
    dispatch_event.delay(str(result.event_id))
    return EventAcceptedResponse(event_id=result.event_id, status="queued", subscriptions_notified=result.subscriptions_notified)
