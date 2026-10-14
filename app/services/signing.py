"""HMAC-SHA256 webhook signing and verification."""

import hashlib
import hmac
import time


def sign_payload(payload: bytes, secret: str) -> str:
    """Sign *payload* and return a header value with embedded timestamp.

    Format: ``t={unix_timestamp},sha256={hex_digest}``

    The timestamp is included in the signed material so a subscriber can
    reject replayed requests that are older than a tolerance window.
    """
    timestamp = int(time.time())
    payload_with_ts = f"{timestamp}.".encode() + payload

    signature = hmac.new(
        secret.encode("utf-8"),
        payload_with_ts,
        hashlib.sha256,
    ).hexdigest()

    return f"t={timestamp},sha256={signature}"


def verify_signature(
    payload: bytes,
    header: str,
    secret: str,
    tolerance_seconds: int = 300,
) -> bool:
    """Verify an ``X-Webhook-Signature`` header value.

    Returns ``False`` if the signature is invalid **or** the timestamp is
    outside *tolerance_seconds* of the current time (replay protection).
    """
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
        received_sig = parts["sha256"]
    except (KeyError, ValueError):
        return False

    if abs(time.time() - timestamp) > tolerance_seconds:
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, received_sig)
