"""Unit tests for app.services.delivery."""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.database import SyncSessionFactory
from app.models.delivery_attempt import DeliveryAttempt
from app.models.dlq_record import DLQRecord
from app.models.event import Event
from app.models.subscription import Subscription
from app.services.delivery import (
    build_signed_request,
    move_to_dlq,
    publish_status_update,
    record_attempt,
)
from app.services.signing import verify_signature


@pytest.fixture
def sample_event_and_subscription():
    sub_id = uuid.uuid4()
    evt_id = uuid.uuid4()
    unique_type = f"payment.completed.{uuid.uuid4().hex[:8]}"
    secret = "test-secret-key-12345"
    subscription = Subscription(
        id=sub_id,
        endpoint_url="https://example.com/webhook-receiver",
        event_types=[unique_type],
        secret=secret,
        active=True,
    )
    event = Event(
        id=evt_id,
        idempotency_key=f"test-key-{evt_id}",
        event_type=unique_type,
        payload={"order_id": "ord_999", "amount": 4999},
    )
    with SyncSessionFactory.begin() as session:
        session.add(subscription)
        session.add(event)

    yield str(evt_id), str(sub_id), secret, unique_type

    with SyncSessionFactory.begin() as session:
        session.query(DLQRecord).filter_by(event_id=evt_id).delete()
        session.query(DeliveryAttempt).filter_by(event_id=evt_id).delete()
        session.query(Event).filter_by(id=evt_id).delete()
        session.query(Subscription).filter_by(id=sub_id).delete()


class TestBuildSignedRequest:
    def test_build_signed_request_success(self, sample_event_and_subscription):
        evt_id, sub_id, secret, event_type = sample_event_and_subscription

        endpoint_url, headers, payload_bytes = build_signed_request(evt_id, sub_id)

        assert endpoint_url == "https://example.com/webhook-receiver"
        assert headers["Content-Type"] == "application/json"
        assert headers["X-Webhook-Event"] == event_type
        assert "X-Webhook-Delivery" in headers
        assert "X-Webhook-Signature" in headers

        # Verify the signature against the returned payload and subscription secret
        assert verify_signature(payload_bytes, headers["X-Webhook-Signature"], secret) is True

        # Verify payload content
        payload = json.loads(payload_bytes.decode("utf-8"))
        assert payload["event_id"] == evt_id
        assert payload["event_type"] == event_type
        assert payload["payload"] == {"order_id": "ord_999", "amount": 4999}

    def test_build_signed_request_missing_event_raises_value_error(self):
        sub_id = str(uuid.uuid4())
        fake_evt_id = str(uuid.uuid4())
        with pytest.raises(ValueError, match=f"Event {fake_evt_id} not found"):
            build_signed_request(fake_evt_id, sub_id)

    def test_build_signed_request_missing_subscription_raises_value_error(self, sample_event_and_subscription):
        evt_id, _, _, _ = sample_event_and_subscription
        fake_sub_id = str(uuid.uuid4())
        with pytest.raises(ValueError, match=f"Subscription {fake_sub_id} not found"):
            build_signed_request(evt_id, fake_sub_id)


class TestRecordAttempt:
    def test_record_attempt_and_upsert_on_conflict(self, sample_event_and_subscription):
        evt_id, sub_id, _, _ = sample_event_and_subscription

        # Initial attempt insert
        attempt_id = record_attempt(
            evt_id,
            sub_id,
            attempt_number=1,
            status="failed",
            response_code=500,
            response_body="Internal Server Error",
            error_detail="HTTP 500",
        )
        assert isinstance(attempt_id, uuid.UUID)

        with SyncSessionFactory() as session:
            attempt = session.get(DeliveryAttempt, attempt_id)
            assert attempt is not None
            assert attempt.status == "failed"
            assert attempt.response_code == 500
            assert attempt.attempt_number == 1
            assert attempt.error_detail == "HTTP 500"

        # Calling again with same attempt_number should update rather than fail with duplicate key
        updated_id = record_attempt(
            evt_id,
            sub_id,
            attempt_number=1,
            status="success",
            response_code=200,
            response_body='{"ok": true}',
        )
        assert updated_id == attempt_id

        with SyncSessionFactory() as session:
            attempt = session.get(DeliveryAttempt, attempt_id)
            assert attempt is not None
            assert attempt.status == "success"
            assert attempt.response_code == 200
            assert attempt.response_body == '{"ok": true}'


class TestMoveToDLQ:
    def test_move_to_dlq_creates_record_and_updates_attempt(self, sample_event_and_subscription):
        evt_id, sub_id, _, _ = sample_event_and_subscription

        attempt_id = record_attempt(
            evt_id,
            sub_id,
            attempt_number=1,
            status="failed",
            error_detail="Connection refused",
        )

        move_to_dlq(
            evt_id,
            sub_id,
            reason="Max retries reached: Connection refused",
            final_attempt_id=attempt_id,
        )

        with SyncSessionFactory() as session:
            attempt = session.get(DeliveryAttempt, attempt_id)
            assert attempt is not None
            assert attempt.status == "dead_lettered"

            dlq_rec = session.query(DLQRecord).filter_by(
                event_id=uuid.UUID(evt_id),
                subscription_id=uuid.UUID(sub_id),
            ).first()
            assert dlq_rec is not None
            assert dlq_rec.final_attempt_id == attempt_id
            assert "Connection refused" in dlq_rec.reason

    def test_move_to_dlq_is_idempotent(self, sample_event_and_subscription):
        evt_id, sub_id, _, _ = sample_event_and_subscription

        move_to_dlq(evt_id, sub_id, reason="Reason 1")
        # Duplicate call should not crash
        move_to_dlq(evt_id, sub_id, reason="Reason 2")

        with SyncSessionFactory() as session:
            dlq_count = session.query(DLQRecord).filter_by(
                event_id=uuid.UUID(evt_id),
                subscription_id=uuid.UUID(sub_id),
            ).count()
            assert dlq_count == 1


class TestPublishStatusUpdate:
    @patch("app.services.delivery._get_sync_redis")
    def test_publish_status_update_publishes_to_redis(self, mock_redis_factory):
        mock_redis = MagicMock()
        mock_redis_factory.return_value = mock_redis

        publish_status_update(
            event_id="evt-1",
            subscription_id="sub-1",
            status="success",
            response_code=200,
            attempt_number=1,
        )

        mock_redis.publish.assert_called_once()
        args, _ = mock_redis.publish.call_args
        assert args[0] == "delivery_updates"
        payload = json.loads(args[1])
        assert payload["event_id"] == "evt-1"
        assert payload["subscription_id"] == "sub-1"
        assert payload["status"] == "success"
        assert payload["response_code"] == 200
        assert payload["attempt_number"] == 1
        assert "timestamp" in payload

    @patch("app.services.delivery._get_sync_redis")
    def test_publish_status_update_handles_redis_failure(self, mock_redis_factory):
        mock_redis = MagicMock()
        mock_redis.publish.side_effect = Exception("Redis unreachable")
        mock_redis_factory.return_value = mock_redis

        # Must not raise an exception
        publish_status_update(
            event_id="evt-1",
            subscription_id="sub-1",
            status="failed",
        )
