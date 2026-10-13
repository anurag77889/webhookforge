"""Validation tests for inbound event contracts."""

import pytest
from pydantic import ValidationError

from app.schemas.event import EventCreate


def test_event_rejects_invalid_type() -> None:
    with pytest.raises(ValidationError, match="event_type must match"):
        EventCreate(event_type="Payment Success", payload={})


def test_event_rejects_payload_over_configured_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.schemas.event.settings.MAX_PAYLOAD_SIZE_BYTES", 10)

    with pytest.raises(ValidationError, match="must not exceed"):
        EventCreate(event_type="payment.success", payload={"value": "too large"})
