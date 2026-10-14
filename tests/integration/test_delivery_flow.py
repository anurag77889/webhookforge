"""Integration tests for the complete HTTP delivery flow and DLQ movement."""

import json
import uuid

import httpx
import pytest
import respx
from celery.exceptions import MaxRetriesExceededError

from app.database import SyncSessionFactory
from app.models.delivery_attempt import DeliveryAttempt
from app.models.dlq_record import DLQRecord
from app.models.event import Event
from app.models.outbox import OutboxRecord
from app.models.subscription import Subscription
from app.services.signing import verify_signature
from app.tasks.deliver import deliver_webhook
from app.tasks.dispatch import dispatch_event


@pytest.fixture
def test_setup():
    evt_id = uuid.uuid4()
    sub_id = uuid.uuid4()
    endpoint = f"https://client-{sub_id.hex[:8]}.example.com/webhook"
    secret = "integration-test-secret-key"

    event = Event(
        id=evt_id,
        idempotency_key=f"flow-test-{evt_id}",
        event_type="invoice.paid",
        payload={"invoice_id": "inv_12345", "total_cents": 15000},
    )
    outbox = OutboxRecord(
        id=uuid.uuid4(),
        event_id=evt_id,
        topic="event.received",
        payload={"event_id": str(evt_id), "event_type": "invoice.paid"},
        dispatch_attempts=0,
    )
    subscription = Subscription(
        id=sub_id,
        endpoint_url=endpoint,
        event_types=["invoice.paid"],
        secret=secret,
        active=True,
    )

    with SyncSessionFactory.begin() as session:
        session.add_all([event, outbox, subscription])

    yield {
        "event_id": str(evt_id),
        "subscription_id": str(sub_id),
        "endpoint": endpoint,
        "secret": secret,
    }

    # Cleanup
    with SyncSessionFactory.begin() as session:
        session.query(DLQRecord).filter_by(event_id=evt_id).delete()
        session.query(DeliveryAttempt).filter_by(event_id=evt_id).delete()
        session.query(OutboxRecord).filter_by(event_id=evt_id).delete()
        session.query(Event).filter_by(id=evt_id).delete()
        session.query(Subscription).filter_by(id=sub_id).delete()


class TestDeliveryFlow:
    @respx.mock
    def test_end_to_end_successful_delivery(self, test_setup):
        evt_id = test_setup["event_id"]
        sub_id = test_setup["subscription_id"]
        endpoint = test_setup["endpoint"]
        secret = test_setup["secret"]

        # Mock subscriber HTTP response
        mock_route = respx.post(endpoint).mock(
            return_value=httpx.Response(200, json={"ack": True})
        )

        # Execute task
        deliver_webhook.apply(args=[evt_id, sub_id], retries=0, throw=True)

        # 1. Verify HTTP request was sent with proper signature & headers
        assert mock_route.called
        sent_request = mock_route.calls.last.request
        assert sent_request.headers["Content-Type"] == "application/json"
        assert sent_request.headers["X-Webhook-Event"] == "invoice.paid"
        assert "X-Webhook-Delivery" in sent_request.headers
        assert "X-Webhook-Signature" in sent_request.headers

        # Verify HMAC signature
        raw_body = sent_request.content
        assert verify_signature(raw_body, sent_request.headers["X-Webhook-Signature"], secret) is True

        # Verify payload content
        body_json = json.loads(raw_body.decode("utf-8"))
        assert body_json["event_id"] == evt_id
        assert body_json["event_type"] == "invoice.paid"
        assert body_json["payload"] == {"invoice_id": "inv_12345", "total_cents": 15000}

        # 2. Verify database records
        with SyncSessionFactory() as session:
            attempt = session.query(DeliveryAttempt).filter_by(
                event_id=uuid.UUID(evt_id),
                subscription_id=uuid.UUID(sub_id),
            ).first()
            assert attempt is not None
            assert attempt.status == "success"
            assert attempt.response_code == 200
            assert attempt.attempt_number == 1
            assert attempt.completed_at is not None
            assert json.loads(attempt.response_body) == {"ack": True}

    @respx.mock
    def test_end_to_end_exhausted_retries_moves_to_dlq(self, test_setup):
        evt_id = test_setup["event_id"]
        sub_id = test_setup["subscription_id"]
        endpoint = test_setup["endpoint"]

        # Mock subscriber endpoint failing with 500
        respx.post(endpoint).mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        # Simulating delivery at max retries (retries=settings.MAX_DELIVERY_RETRIES)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                deliver_webhook,
                "retry",
                lambda *args, **kwargs: (_ for _ in ()).throw(MaxRetriesExceededError("Max retries")),
            )
            deliver_webhook.apply(args=[evt_id, sub_id], retries=4, throw=True)

        # Verify DB has DLQ record
        with SyncSessionFactory() as session:
            dlq = session.query(DLQRecord).filter_by(
                event_id=uuid.UUID(evt_id),
                subscription_id=uuid.UUID(sub_id),
            ).first()
            assert dlq is not None
            assert "HTTP 500" in dlq.reason

            # Verify the delivery attempt was marked dead_lettered
            attempt = session.query(DeliveryAttempt).filter_by(
                event_id=uuid.UUID(evt_id),
                subscription_id=uuid.UUID(sub_id),
                status="dead_lettered",
            ).first()
            assert attempt is not None
            assert dlq.final_attempt_id == attempt.id

    def test_dispatch_and_delivery_pipeline(self, test_setup):
        evt_id = test_setup["event_id"]
        sub_id = test_setup["subscription_id"]

        with pytest.MonkeyPatch.context() as mp:
            queued_tasks = []
            mp.setattr(
                "app.tasks.deliver.deliver_webhook.delay",
                lambda e, s: queued_tasks.append((e, s)),
            )
            count = dispatch_event(evt_id)
            assert count == 1
            assert queued_tasks == [(evt_id, sub_id)]

        with SyncSessionFactory() as session:
            outbox = session.query(OutboxRecord).filter_by(event_id=uuid.UUID(evt_id)).first()
            assert outbox.dispatched_at is not None
            assert outbox.dispatch_attempts == 1
