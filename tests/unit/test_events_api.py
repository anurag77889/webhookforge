"""Route-level tests for the event ingestion endpoint."""

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_post_event_without_idempotency_key_returns_400() -> None:
    response = client.post(
        "/events",
        json={"event_type": "payment.success", "payload": {"amount": 100}},
        headers={"X-API-Key": settings.API_KEY},
    )
    assert response.status_code == 400
    assert "Idempotency-Key" in response.json()["detail"]