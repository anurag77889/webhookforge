"""Unit tests for HMAC-SHA256 webhook signing and verification."""

import time
from unittest.mock import patch

from app.services.signing import sign_payload, verify_signature


class TestSignPayload:
    """Tests for the sign_payload function."""

    def test_produces_valid_format(self):
        result = sign_payload(b'{"test": true}', "my-secret")
        assert result.startswith("t=")
        assert ",sha256=" in result

    def test_signature_is_deterministic_for_same_timestamp(self):
        payload = b'{"amount": 100}'
        secret = "secret-key"
        with patch("app.services.signing.time") as mock_time:
            mock_time.time.return_value = 1700000000
            sig1 = sign_payload(payload, secret)
            sig2 = sign_payload(payload, secret)
        assert sig1 == sig2

    def test_different_secrets_produce_different_signatures(self):
        payload = b'{"amount": 100}'
        with patch("app.services.signing.time") as mock_time:
            mock_time.time.return_value = 1700000000
            sig1 = sign_payload(payload, "secret-a")
            sig2 = sign_payload(payload, "secret-b")
        assert sig1 != sig2

    def test_different_payloads_produce_different_signatures(self):
        secret = "same-secret"
        with patch("app.services.signing.time") as mock_time:
            mock_time.time.return_value = 1700000000
            sig1 = sign_payload(b'{"a": 1}', secret)
            sig2 = sign_payload(b'{"b": 2}', secret)
        assert sig1 != sig2


class TestVerifySignature:
    """Tests for the verify_signature function."""

    def test_valid_signature_accepted(self):
        payload = b'{"event": "test"}'
        secret = "my-secret"
        header = sign_payload(payload, secret)
        assert verify_signature(payload, header, secret) is True

    def test_tampered_payload_rejected(self):
        original = b'{"amount": 100}'
        secret = "my-secret"
        header = sign_payload(original, secret)
        tampered = b'{"amount": 999}'
        assert verify_signature(tampered, header, secret) is False

    def test_wrong_secret_rejected(self):
        payload = b'{"event": "test"}'
        header = sign_payload(payload, "correct-secret")
        assert verify_signature(payload, header, "wrong-secret") is False

    def test_expired_timestamp_rejected(self):
        payload = b'{"event": "test"}'
        secret = "my-secret"
        # Sign with a timestamp 600 seconds in the past
        with patch("app.services.signing.time") as mock_time:
            mock_time.time.return_value = time.time() - 600
            header = sign_payload(payload, secret)
        assert verify_signature(payload, header, secret, tolerance_seconds=300) is False

    def test_recent_timestamp_accepted(self):
        payload = b'{"event": "test"}'
        secret = "my-secret"
        # Sign with a timestamp 10 seconds in the past
        with patch("app.services.signing.time") as mock_time:
            mock_time.time.return_value = time.time() - 10
            header = sign_payload(payload, secret)
        assert verify_signature(payload, header, secret, tolerance_seconds=300) is True

    def test_malformed_header_rejected(self):
        assert verify_signature(b"payload", "garbage", "secret") is False

    def test_missing_fields_rejected(self):
        assert verify_signature(b"payload", "t=123", "secret") is False
        assert verify_signature(b"payload", "sha256=abc", "secret") is False
