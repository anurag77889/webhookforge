"""Celery task that delivers a webhook to a single subscriber endpoint."""

import httpx
import structlog
from celery import Task
from celery.exceptions import MaxRetriesExceededError

from app.celery_app import celery_app
from app.config import settings
from app.services.backoff import backoff_seconds
from app.services.delivery import (
    build_signed_request,
    move_to_dlq,
    publish_status_update,
    record_attempt,
)

logger = structlog.get_logger()


@celery_app.task(
    bind=True,
    max_retries=settings.MAX_DELIVERY_RETRIES,
    name="webhookforge.deliver_webhook",
)
def deliver_webhook(self: Task, event_id: str, subscription_id: str) -> None:
    """POST an event payload to a subscriber endpoint.

    On transient failure the task retries with exponential backoff + jitter.
    After all retries are exhausted the event is moved to the dead-letter
    queue.
    """
    attempt_number = self.request.retries + 1
    log = logger.bind(
        event_id=event_id,
        subscription_id=subscription_id,
        attempt=attempt_number,
    )
    log.info("delivery_attempt_started")

    try:
        endpoint_url, headers, payload_bytes = build_signed_request(
            event_id, subscription_id
        )

        with httpx.Client(timeout=settings.DELIVERY_TIMEOUT_SECONDS) as client:
            response = client.post(
                endpoint_url,
                headers=headers,
                content=payload_bytes,
            )

        if response.is_success:
            record_attempt(
                event_id,
                subscription_id,
                attempt_number=attempt_number,
                status="success",
                response_code=response.status_code,
                response_body=response.text[:1000],
            )
            publish_status_update(
                event_id, subscription_id, "success",
                response_code=response.status_code,
                attempt_number=attempt_number,
            )
            log.info("delivery_success", response_code=response.status_code)
            return

        # Non-2xx: record as failed and trigger retry path
        error_detail = f"HTTP {response.status_code}: {response.text[:200]}"
        record_attempt(
            event_id,
            subscription_id,
            attempt_number=attempt_number,
            status="failed",
            response_code=response.status_code,
            response_body=response.text[:1000],
            error_detail=error_detail,
        )
        raise httpx.HTTPStatusError(
            error_detail, request=response.request, response=response
        )

    except (httpx.RequestError, httpx.TimeoutException) as exc:
        # Network-level failure (connection refused, DNS error, timeout)
        record_attempt(
            event_id,
            subscription_id,
            attempt_number=attempt_number,
            status="failed",
            error_detail=str(exc),
        )
        publish_status_update(
            event_id, subscription_id, "failed",
            attempt_number=attempt_number,
        )
        log.warning(
            "delivery_failed",
            error=str(exc),
            retries_remaining=settings.MAX_DELIVERY_RETRIES - self.request.retries,
        )

        try:
            raise self.retry(
                exc=exc,
                countdown=backoff_seconds(self.request.retries),
            )
        except MaxRetriesExceededError:
            _dead_letter(self, event_id, subscription_id, str(exc), log)

    except httpx.HTTPStatusError as exc:
        # Non-2xx response — already recorded above
        publish_status_update(
            event_id, subscription_id, "failed",
            attempt_number=attempt_number,
        )
        log.warning(
            "delivery_failed",
            error=str(exc),
            retries_remaining=settings.MAX_DELIVERY_RETRIES - self.request.retries,
        )

        try:
            raise self.retry(
                exc=exc,
                countdown=backoff_seconds(self.request.retries),
            )
        except MaxRetriesExceededError:
            _dead_letter(self, event_id, subscription_id, str(exc), log)


def _dead_letter(
    task: Task,
    event_id: str,
    subscription_id: str,
    reason: str,
    log: structlog.stdlib.BoundLogger,
) -> None:
    """Move to the dead-letter queue after exhausting all retries."""
    # Record a final dead_lettered attempt
    final_attempt_id = record_attempt(
        event_id,
        subscription_id,
        attempt_number=task.request.retries + 1,
        status="dead_lettered",
        error_detail=reason,
    )
    move_to_dlq(
        event_id,
        subscription_id,
        reason=reason,
        final_attempt_id=final_attempt_id,
    )
    publish_status_update(
        event_id, subscription_id, "dead_lettered",
        attempt_number=task.request.retries + 1,
    )
    log.error("delivery_dead_lettered", reason=reason)
