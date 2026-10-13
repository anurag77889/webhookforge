"""Request and response contracts for inbound events."""

import json
import re
import uuid
from typing import Any

from pydantic import BaseModel, field_validator

from app.config import settings

EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_.]{1,63}$")


class EventCreate(BaseModel):
    event_type: str
    payload: dict[str, Any]

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        if EVENT_TYPE_PATTERN.fullmatch(value) is None:
            raise ValueError("event_type must match ^[a-z][a-z0-9_.]{1,63}$")
        return value

    @field_validator("payload")
    @classmethod
    def validate_payload_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        size = len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        if size > settings.MAX_PAYLOAD_SIZE_BYTES:
            raise ValueError(f"payload must not exceed {settings.MAX_PAYLOAD_SIZE_BYTES} bytes")
        return value


class EventAcceptedResponse(BaseModel):
    event_id: uuid.UUID
    status: str
    subscriptions_notified: int


class EventDuplicateResponse(BaseModel):
    event_id: uuid.UUID
    status: str = "already_processed"
    message: str = "Event with this idempotency key was already received."
