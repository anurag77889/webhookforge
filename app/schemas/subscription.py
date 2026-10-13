"""Request and response contracts for webhook subscriptions."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, HttpUrl, SecretStr, field_validator

EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_.]{1,63}$")


class SubscriptionCreate(BaseModel):
    endpoint_url: HttpUrl
    event_types: list[str]
    secret: SecretStr

    @field_validator("endpoint_url")
    @classmethod
    def require_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("endpoint_url must use HTTPS")
        return value

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one event type is required")
        if len(set(value)) != len(value):
            raise ValueError("event_types must not contain duplicates")
        invalid = [event_type for event_type in value if EVENT_TYPE_PATTERN.fullmatch(event_type) is None]
        if invalid:
            raise ValueError("event types must match ^[a-z][a-z0-9_.]{1,63}$")
        return value

    @field_validator("secret")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("secret must not be blank")
        return value


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    endpoint_url: str
    event_types: list[str]
    active: bool
    created_at: datetime


class SubscriptionListResponse(BaseModel):
    subscriptions: list[SubscriptionResponse]
