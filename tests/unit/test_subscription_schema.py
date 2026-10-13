"""Validation tests for subscription API contracts."""

import pytest
from pydantic import ValidationError

from app.schemas.subscription import SubscriptionCreate


def test_subscription_requires_https_endpoint() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        SubscriptionCreate(
            endpoint_url="http://example.com/webhooks",
            event_types=["payment.success"],
            secret="signing-secret",
        )


def test_subscription_rejects_invalid_or_duplicate_event_types() -> None:
    with pytest.raises(ValidationError, match="event_types must not contain duplicates"):
        SubscriptionCreate(
            endpoint_url="https://example.com/webhooks",
            event_types=["payment.success", "payment.success"],
            secret="signing-secret",
        )

    with pytest.raises(ValidationError, match="event types must match"):
        SubscriptionCreate(
            endpoint_url="https://example.com/webhooks",
            event_types=["Payment Success"],
            secret="signing-secret",
        )


def test_subscription_response_input_keeps_secret_separate() -> None:
    subscription = SubscriptionCreate(
        endpoint_url="https://example.com/webhooks",
        event_types=["payment.success", "order.created"],
        secret="signing-secret",
    )

    assert subscription.secret.get_secret_value() == "signing-secret"
