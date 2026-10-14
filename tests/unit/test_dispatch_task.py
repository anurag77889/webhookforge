"""Unit tests for app.tasks.dispatch (dispatch_event task)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from app.database import SyncSessionFactory
from app.models.event import Event
from app.models.outbox import OutboxRecord
from app.models.subscription import Subscription
from app.tasks.dispatch import dispatch_event


def _setup_event_and_outbox(event_type: str = "order.created"):
    evt_id = uuid.uuid4()
    event = Event(
        id=evt_id,
        idempotency_key=f"idemp-{evt_id}",
        event_type=event_type,
        payload={"item": "book"},
    )
    outbox = OutboxRecord(
        id=uuid.uuid4(),
        event_id=evt_id,
        topic="event.received",
        payload={"event_id": str(evt_id), "event_type": event_type},
        dispatch_attempts=0,
    )
    with SyncSessionFactory.begin() as session:
        session.add(event)
        session.add(outbox)
    return str(evt_id)


class TestDispatchEventTask:
    @patch("app.tasks.deliver.deliver_webhook.delay")
    def test_dispatch_event_success_enqueues_deliveries(self, mock_deliver_delay):
        unique_type = f"order.created.{uuid.uuid4().hex[:8]}"
        evt_id = _setup_event_and_outbox(unique_type)

        sub1_id = uuid.uuid4()
        sub2_id = uuid.uuid4()
        sub3_inactive_id = uuid.uuid4()
        sub4_other_type_id = uuid.uuid4()

        sub1 = Subscription(
            id=sub1_id,
            endpoint_url="https://sub1.test/wh",
            event_types=[unique_type, "order.cancelled"],
            secret="sec1",
            active=True,
        )
        sub2 = Subscription(
            id=sub2_id,
            endpoint_url="https://sub2.test/wh",
            event_types=[unique_type],
            secret="sec2",
            active=True,
        )
        sub3 = Subscription(
            id=sub3_inactive_id,
            endpoint_url="https://sub3.test/wh",
            event_types=[unique_type],
            secret="sec3",
            active=False,
        )
        sub4 = Subscription(
            id=sub4_other_type_id,
            endpoint_url="https://sub4.test/wh",
            event_types=["user.signup"],
            secret="sec4",
            active=True,
        )

        with SyncSessionFactory.begin() as session:
            session.add_all([sub1, sub2, sub3, sub4])

        try:
            queued_count = dispatch_event(evt_id)

            assert queued_count == 2
            assert mock_deliver_delay.call_count == 2
            called_subs = {call[0][1] for call in mock_deliver_delay.call_args_list}
            assert called_subs == {str(sub1_id), str(sub2_id)}

            # Verify outbox record updated
            with SyncSessionFactory() as session:
                outbox = session.query(OutboxRecord).filter_by(event_id=uuid.UUID(evt_id)).first()
                assert outbox.dispatch_attempts == 1
                assert outbox.dispatched_at is not None
        finally:
            with SyncSessionFactory.begin() as session:
                session.query(Subscription).filter(Subscription.id.in_([sub1_id, sub2_id, sub3_inactive_id, sub4_other_type_id])).delete(synchronize_session=False)
                session.query(OutboxRecord).filter_by(event_id=uuid.UUID(evt_id)).delete()
                session.query(Event).filter_by(id=uuid.UUID(evt_id)).delete()

    def test_dispatch_event_already_dispatched_returns_zero(self):
        unique_type = f"user.login.{uuid.uuid4().hex[:8]}"
        evt_id = _setup_event_and_outbox(unique_type)
        with SyncSessionFactory.begin() as session:
            outbox = session.query(OutboxRecord).filter_by(event_id=uuid.UUID(evt_id)).first()
            outbox.dispatched_at = datetime.now(UTC)

        try:
            with patch("app.tasks.deliver.deliver_webhook.delay") as mock_deliver_delay:
                result = dispatch_event(evt_id)

            assert result == 0
            mock_deliver_delay.assert_not_called()
        finally:
            with SyncSessionFactory.begin() as session:
                session.query(OutboxRecord).filter_by(event_id=uuid.UUID(evt_id)).delete()
                session.query(Event).filter_by(id=uuid.UUID(evt_id)).delete()

    def test_dispatch_event_nonexistent_outbox_returns_zero(self):
        fake_id = str(uuid.uuid4())
        with patch("app.tasks.deliver.deliver_webhook.delay") as mock_deliver_delay:
            result = dispatch_event(fake_id)

        assert result == 0
        mock_deliver_delay.assert_not_called()
