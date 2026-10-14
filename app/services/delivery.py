"""Delivery support functions used by the deliver_webhook Celery task.

Every function here uses **synchronous** DB sessions and Redis clients
because the Celery worker runs in a synchronous context.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import redis
import structlog
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.database import SyncSessionFactory
from app.models.delivery_attempt import DeliveryAttempt
from app.models.dlq_record import DLQRecord
from app.models.event import Event
from app.models.subscription import Subscription
from app.services.signing import sign_payload

logger = structlog.get_logger()

# Lazy-initialised sync Redis client for Pub/Sub inside the worker.
_sync_redis: redis.Redis | None = None


def _get_sync_redis() -> redis.Redis:
    global _sync_redis
    if _sync_redis is None:
        _sync_redis = redis.Redis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
    return _sync_redis


# ---------------------------------------------------------------------------
# build_signed_request
# ---------------------------------------------------------------------------

def build_signed_request(
    event_id: str,
    subscription_id: str,
) -> tuple[str, dict[str, str], bytes]:
    """Fetch event + subscription and return ``(endpoint_url, headers, payload_bytes)``.

    Headers include ``X-Webhook-Signature``, ``X-Webhook-Event``, and
    ``X-Webhook-Delivery`` as specified by the WebhookForge spec.
    """
    parsed_event_id = uuid.UUID(event_id)
    parsed_sub_id = uuid.UUID(subscription_id)

    with SyncSessionFactory() as session:
        event = session.get(Event, parsed_event_id)
        subscription = session.get(Subscription, parsed_sub_id)

    if event is None:
        raise ValueError(f"Event {event_id} not found")
    if subscription is None:
        raise ValueError(f"Subscription {subscription_id} not found")

    payload_dict = {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "payload": event.payload,
    }
    payload_bytes = json.dumps(payload_dict, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    delivery_id = str(uuid.uuid4())

    signature = sign_payload(payload_bytes, subscription.secret)

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": signature,
        "X-Webhook-Event": event.event_type,
        "X-Webhook-Delivery": delivery_id,
    }

    return subscription.endpoint_url, headers, payload_bytes


# ---------------------------------------------------------------------------
# record_attempt
# ---------------------------------------------------------------------------

def record_attempt(
    event_id: str,
    subscription_id: str,
    *,
    attempt_number: int,
    status: str,
    response_code: int | None = None,
    response_body: str | None = None,
    error_detail: str | None = None,
) -> uuid.UUID:
    """Persist a delivery attempt row.

    Uses ``ON CONFLICT … DO UPDATE`` on the
    ``(event_id, subscription_id, attempt_number)`` unique constraint so
    that ``task_acks_late`` re-delivery does not crash with a duplicate-key
    error — it simply overwrites the previous record.
    """
    now = datetime.now(UTC)
    attempt_id = uuid.uuid4()

    values = {
        "id": attempt_id,
        "event_id": uuid.UUID(event_id),
        "subscription_id": uuid.UUID(subscription_id),
        "attempt_number": attempt_number,
        "status": status,
        "response_code": response_code,
        "response_body": response_body,
        "error_detail": error_detail,
        "attempted_at": now,
        "completed_at": now if status in ("success", "failed", "dead_lettered") else None,
    }

    stmt = (
        pg_insert(DeliveryAttempt)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_delivery_attempt_event_subscription_number",
            set_={
                "status": status,
                "response_code": response_code,
                "response_body": response_body,
                "error_detail": error_detail,
                "attempted_at": now,
                "completed_at": now if status in ("success", "failed", "dead_lettered") else None,
            },
        )
        .returning(DeliveryAttempt.id)
    )

    with SyncSessionFactory.begin() as session:
        result_id = session.execute(stmt).scalar_one()

    return result_id


# ---------------------------------------------------------------------------
# move_to_dlq
# ---------------------------------------------------------------------------

def move_to_dlq(
    event_id: str,
    subscription_id: str,
    reason: str,
    final_attempt_id: uuid.UUID | None = None,
) -> None:
    """Insert a DLQ record and mark the last delivery attempt as dead-lettered.

    Uses ``ON CONFLICT DO NOTHING`` so duplicate calls (from
    ``task_acks_late`` re-delivery) are harmless.
    """
    stmt = (
        pg_insert(DLQRecord)
        .values(
            event_id=uuid.UUID(event_id),
            subscription_id=uuid.UUID(subscription_id),
            final_attempt_id=final_attempt_id,
            reason=reason[:2000],
        )
        .on_conflict_do_nothing(constraint="uq_dlq_event_subscription")
    )

    with SyncSessionFactory.begin() as session:
        session.execute(stmt)
        # Mark the final delivery attempt as dead_lettered
        if final_attempt_id is not None:
            session.execute(
                update(DeliveryAttempt)
                .where(DeliveryAttempt.id == final_attempt_id)
                .values(status="dead_lettered", completed_at=datetime.now(UTC))
            )

    logger.info(
        "dlq_record_created",
        event_id=event_id,
        subscription_id=subscription_id,
        reason=reason[:200],
    )


# ---------------------------------------------------------------------------
# publish_status_update
# ---------------------------------------------------------------------------

def publish_status_update(
    event_id: str,
    subscription_id: str,
    status: str,
    response_code: int | None = None,
    attempt_number: int | None = None,
) -> None:
    """Publish a delivery status update to the ``delivery_updates`` Redis
    Pub/Sub channel.

    Best-effort: Redis failures are logged but never crash the delivery
    task.
    """
    message = {
        "event_id": event_id,
        "subscription_id": subscription_id,
        "status": status,
        "attempt_number": attempt_number,
        "response_code": response_code,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    try:
        _get_sync_redis().publish(
            "delivery_updates",
            json.dumps(message),
        )
    except Exception:
        logger.warning(
            "redis_pubsub_publish_failed",
            event_id=event_id,
            subscription_id=subscription_id,
        )
