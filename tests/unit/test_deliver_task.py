"""Unit tests for app.tasks.deliver (deliver_webhook task)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from celery.exceptions import MaxRetriesExceededError, Retry

from app.tasks.deliver import deliver_webhook


@pytest.fixture
def mock_delivery_services():
    with patch("app.tasks.deliver.build_signed_request") as mock_build, \
         patch("app.tasks.deliver.record_attempt") as mock_record, \
         patch("app.tasks.deliver.publish_status_update") as mock_publish, \
         patch("app.tasks.deliver.move_to_dlq") as mock_dlq, \
         patch("app.tasks.deliver.backoff_seconds") as mock_backoff:

        mock_build.return_value = (
            "https://subscriber.test/webhook",
            {"Content-Type": "application/json", "X-Webhook-Signature": "sig"},
            b'{"event_id": "123"}',
        )
        mock_backoff.return_value = 5
        yield {
            "build": mock_build,
            "record": mock_record,
            "publish": mock_publish,
            "dlq": mock_dlq,
            "backoff": mock_backoff,
        }


class TestDeliverWebhookTask:
    def test_delivery_success_200(self, mock_delivery_services):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.status_code = 200
        mock_response.text = '{"received": true}'

        with patch("httpx.Client.post", return_value=mock_response):
            deliver_webhook.apply(args=["evt-1", "sub-1"], retries=0, throw=True)

        mock_delivery_services["record"].assert_called_once_with(
            "evt-1",
            "sub-1",
            attempt_number=1,
            status="success",
            response_code=200,
            response_body='{"received": true}',
        )
        mock_delivery_services["publish"].assert_called_once_with(
            "evt-1",
            "sub-1",
            "success",
            response_code=200,
            attempt_number=1,
        )
        mock_delivery_services["dlq"].assert_not_called()

    def test_delivery_non_2xx_triggers_retry(self, mock_delivery_services):
        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = False
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.request = mock_request

        with patch("httpx.Client.post", return_value=mock_response), \
             patch.object(deliver_webhook, "retry", side_effect=Retry()) as mock_retry:
            with pytest.raises(Retry):
                deliver_webhook.apply(args=["evt-1", "sub-1"], retries=1, throw=True)

        # Attempt recorded as failed
        mock_delivery_services["record"].assert_called_once_with(
            "evt-1",
            "sub-1",
            attempt_number=2,
            status="failed",
            response_code=500,
            response_body="Internal Server Error",
            error_detail="HTTP 500: Internal Server Error",
        )
        mock_delivery_services["publish"].assert_called_once_with(
            "evt-1",
            "sub-1",
            "failed",
            attempt_number=2,
        )
        mock_retry.assert_called_once()
        _, kwargs = mock_retry.call_args
        assert kwargs["countdown"] == 5

    def test_delivery_network_error_triggers_retry(self, mock_delivery_services):
        with patch("httpx.Client.post", side_effect=httpx.ConnectError("Connection refused")), \
             patch.object(deliver_webhook, "retry", side_effect=Retry()) as mock_retry:
            with pytest.raises(Retry):
                deliver_webhook.apply(args=["evt-1", "sub-1"], retries=0, throw=True)

        mock_delivery_services["record"].assert_called_once_with(
            "evt-1",
            "sub-1",
            attempt_number=1,
            status="failed",
            error_detail="Connection refused",
        )
        mock_delivery_services["publish"].assert_called_once_with(
            "evt-1",
            "sub-1",
            "failed",
            attempt_number=1,
        )
        mock_retry.assert_called_once()

    def test_delivery_exhausted_retries_moves_to_dlq(self, mock_delivery_services):
        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = False
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"
        mock_response.request = mock_request

        with patch("httpx.Client.post", return_value=mock_response), \
             patch.object(deliver_webhook, "retry", side_effect=MaxRetriesExceededError("Can't retry")):
            deliver_webhook.apply(args=["evt-1", "sub-1"], retries=4, throw=True)

        # Dead letter logic calls record_attempt with dead_lettered and move_to_dlq
        assert mock_delivery_services["dlq"].called
        args, kwargs = mock_delivery_services["dlq"].call_args
        assert args[0] == "evt-1"
        assert args[1] == "sub-1"
        assert "HTTP 503" in kwargs.get("reason", "")

        mock_delivery_services["publish"].assert_any_call(
            "evt-1",
            "sub-1",
            "dead_lettered",
            attempt_number=5,
        )
