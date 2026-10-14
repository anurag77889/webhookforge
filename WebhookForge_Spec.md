# WebhookForge — Technical Specification

> **Version:** 1.0 | **Last updated:** October 2026  
> **Purpose:** Complete build specification for a production-grade webhook delivery engine.  
> **Intended reader:** The developer building this project.

---

## Table of Contents

1. [Project Summary](#1-project-summary)
2. [Goals and Non-Goals](#2-goals-and-non-goals)
3. [Architecture Overview](#3-architecture-overview)
4. [Technology Stack](#4-technology-stack)
5. [Database Schema](#5-database-schema)
6. [API Reference](#6-api-reference)
7. [Celery Task Design](#7-celery-task-design)
8. [Idempotency Design](#8-idempotency-design)
9. [Security Controls](#9-security-controls)
10. [Observability](#10-observability)
11. [Testing Strategy](#11-testing-strategy)
12. [Repository Structure](#12-repository-structure)
13. [Local Development Setup](#13-local-development-setup)
14. [Deployment](#14-deployment)
15. [Build Milestones](#15-build-milestones)
16. [Architecture Decision Records](#16-architecture-decision-records)
17. [Runbook](#17-runbook)
18. [Success Criteria](#18-success-criteria)

---

## 1. Project Summary

**WebhookForge** is a reliable webhook delivery engine. Its job: when an event happens on a platform, deliver an HTTP notification to every registered subscriber endpoint — and do so reliably, even when subscriber servers are temporarily unavailable.

### The core problem

Webhooks are simple to receive but surprisingly hard to make reliable. Common failure modes:
- Subscriber server is temporarily down (transient failure)
- Network timeout between delivery and acknowledgement
- Client sends the same event twice (duplicate delivery)
- Worker process crashes after delivery but before marking success (phantom failure)
- Subscriber endpoint is permanently unreachable (needs DLQ and manual recovery)

WebhookForge solves all five. Each solution is a distinct engineering decision worth explaining in an interview.

### What a 5-minute demo shows

1. Register a subscription (endpoint URL + event types + secret).
2. Fire 10 events via a seed script, including 2 intentional subscriber failures.
3. Watch the WebSocket dashboard: live delivery status, retrying events, dead-letter entry.
4. Send the same event twice with the same `idempotency_key` — only one delivery record appears.
5. Open `/metrics` — show Prometheus counters for queue depth, success rate, DLQ backlog.

---

## 2. Goals and Non-Goals

### Goals (MVP)

- Register webhook subscriptions (endpoint URL + event types + secret)
- Ingest events via POST endpoint; enqueue a Celery delivery task
- Deliver events to subscriber endpoints via HTTP POST
- Retry on failure with exponential backoff (configurable attempts)
- Dead-letter queue (DLQ) for permanently failed deliveries
- Idempotency: duplicate events with the same key are delivered exactly once
- Delivery attempt log queryable via API
- WebSocket real-time dashboard showing live delivery state
- HMAC-SHA256 signature on outgoing webhooks
- Prometheus metrics endpoint
- Structured JSON logging

### Goals (flagship, after MVP is solid)

- Manual replay of dead-lettered events via API
- Subscription filtering by event type
- Rate-limiting per subscriber endpoint
- Grafana dashboard connected to Prometheus

### Non-Goals (do not build these)

- Multi-tenant billing or subscription management
- Full admin UI
- Kafka-based event ingestion
- ML components
- React frontend
- Any mobile interface

Scope discipline is the hardest part. When in doubt: if it is not in the MVP or Flagship list above, it does not belong in this project.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        Client / API Consumer                │
└───────────────────────────┬─────────────────────────────────┘
                            │ POST /events
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                       │
│  - Idempotency check (PostgreSQL ON CONFLICT)               │
│  - Enqueue Celery delivery task                             │
│  - WebSocket handler (subscribes to Redis Pub/Sub)          │
│  - REST endpoints (subscriptions, events, deliveries)       │
└────────┬────────────────────────────────────┬───────────────┘
         │ Celery task enqueue                │ WebSocket stream
         ▼                                    ▼
┌─────────────────┐                ┌────────────────────────┐
│  Redis Broker   │                │  Dashboard Client      │
│  (task queue +  │                │  (browser / curl)      │
│   Pub/Sub)      │                └────────────────────────┘
└────────┬────────┘
         │ BRPOP
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Celery Worker                             │
│  - HTTP POST to subscriber endpoint                         │
│  - Capture response (code + body)                           │
│  - Exponential backoff retry on failure                     │
│  - Write delivery attempt to PostgreSQL                     │
│  - Publish state update to Redis Pub/Sub                    │
│  - Move to DLQ after max retries                            │
└────────┬──────────────────────────────────────┬─────────────┘
         │ Write attempt record                  │ Publish update
         ▼                                       ▼
┌─────────────────────┐              ┌───────────────────────┐
│    PostgreSQL DB     │              │   Redis Pub/Sub       │
│  - events            │              │   channel:            │
│  - subscriptions     │              │   delivery_updates    │
│  - delivery_attempts │              └───────────────────────┘
│  - dlq_records       │
└──────────────────────┘
         │ Counter updates
         ▼
┌──────────────────────┐
│  Prometheus /metrics │
└──────────────────────┘
```

### Component responsibilities

| Component | Responsibility |
|---|---|
| **FastAPI API** | Event ingestion, idempotency check, subscription CRUD, WebSocket endpoint, health check |
| **Celery Worker** | HTTP delivery, retry logic, DLQ handling, status persistence, Pub/Sub publishing |
| **Redis** | Celery broker + result backend; Pub/Sub channel for dashboard live feed |
| **PostgreSQL** | Durable event log, subscription registry, delivery attempt history, DLQ records |
| **Prometheus** | Metrics scraping (queue depth, delivery rate, latency) |
| **Grafana** (stretch) | Dashboard visualization |

---

## 4. Technology Stack

| Layer | Technology | Reason |
|---|---|---|
| Web framework | **FastAPI** | Async-native; clean for both REST and WebSocket; Pydantic validation |
| Task queue | **Celery 5** | The canonical Python async task queue; required for production reliability |
| Broker / Pub/Sub | **Redis** | Celery broker + result backend; Pub/Sub for dashboard feed |
| Database | **PostgreSQL 15+** | `ON CONFLICT` for idempotency; durable delivery log |
| ORM | **SQLAlchemy 2.0** | Async ORM support; well understood |
| Migrations | **Alembic** | Schema versioning |
| Validation | **Pydantic v2** | Request/response schemas |
| Logging | **structlog** | Structured JSON logs with consistent fields |
| Metrics | **prometheus-client** | Prometheus counters and histograms |
| Testing | **pytest + pytest-asyncio** | Unit + integration tests |
| HTTP mocking | **responses** or **httpretty** | Mock subscriber endpoints in tests |
| Containerisation | **Docker + Docker Compose** | Single-command local setup |
| CI | **GitHub Actions** | Linting, tests, security scan on every push |

### Python dependencies (add to `requirements.txt`)

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
celery[redis]>=5.3.0
redis>=5.0.0
sqlalchemy>=2.0.0
alembic>=1.13.0
psycopg2-binary>=2.9.0
pydantic>=2.0.0
python-dotenv>=1.0.0
structlog>=24.0.0
prometheus-client>=0.20.0
httpx>=0.27.0       # for async HTTP delivery
responses>=0.25.0   # test mocking
pytest>=8.0.0
pytest-asyncio>=0.23.0
pytest-cov>=5.0.0
ruff                # linting
mypy                # type checking
```

---

## 5. Database Schema

Run all schema changes through Alembic migrations. Never modify the database manually.

```sql
-- ============================================================
-- SUBSCRIPTIONS
-- Who receives which events, with what secret for signing
-- ============================================================
CREATE TABLE subscriptions (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_url    TEXT        NOT NULL,
    event_types     TEXT[]      NOT NULL,       -- e.g. ['payment.success', 'order.created']
    secret          TEXT        NOT NULL,       -- used for HMAC-SHA256 signing
    active          BOOLEAN     NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for filtering by event type (GIN index on array)
CREATE INDEX idx_subscriptions_event_types ON subscriptions USING gin(event_types);


-- ============================================================
-- EVENTS
-- Inbound events; idempotency_key is the deduplication anchor
-- ============================================================
CREATE TABLE events (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key TEXT        NOT NULL,
    event_type      TEXT        NOT NULL,
    payload         JSONB       NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- UNIQUE constraint on idempotency_key — this is the idempotency mechanism
CREATE UNIQUE INDEX idx_events_idempotency_key ON events(idempotency_key);


-- ============================================================
-- DELIVERY ATTEMPTS
-- Full history of every delivery attempt per event per subscription
-- ============================================================
CREATE TABLE delivery_attempts (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id          UUID        NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    subscription_id   UUID        NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    attempt_number    INT         NOT NULL DEFAULT 1,
    status            TEXT        NOT NULL CHECK (status IN (
                          'pending', 'in_progress', 'success', 'failed', 'dead_lettered'
                      )),
    response_code     INT,            -- HTTP status from subscriber
    response_body     TEXT,           -- first 1000 chars of response body
    error_detail      TEXT,           -- exception message on network error
    attempted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at      TIMESTAMPTZ,

    UNIQUE (event_id, subscription_id, attempt_number)
);

CREATE INDEX idx_delivery_event_id ON delivery_attempts(event_id);
CREATE INDEX idx_delivery_status ON delivery_attempts(status);


-- ============================================================
-- DLQ RECORDS
-- Events that exhausted all retries; ready for manual replay
-- ============================================================
CREATE TABLE dlq_records (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id          UUID        NOT NULL REFERENCES events(id),
    subscription_id   UUID        NOT NULL REFERENCES subscriptions(id),
    final_attempt_id  UUID        REFERENCES delivery_attempts(id),
    reason            TEXT        NOT NULL,     -- last error detail
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    replayed_at       TIMESTAMPTZ,              -- set on manual replay
    UNIQUE (event_id, subscription_id)          -- one DLQ record per event+sub pair
);
```

### Key design decisions in the schema

**Why `idempotency_key TEXT UNIQUE` instead of checking before insert?**
A SELECT followed by an INSERT has a race condition: two concurrent requests both pass the SELECT check and both insert. Using `INSERT ... ON CONFLICT DO NOTHING RETURNING id` is atomic. If the INSERT returns a row, it's new. If it returns nothing, the event already exists. See Section 8.

**Why store `response_body` truncated at 1000 chars?**
Subscriber error bodies can be arbitrarily large. Store enough to debug (the first 1000 chars of the response), not enough to overflow the column.

**Why `UNIQUE (event_id, subscription_id, attempt_number)` on delivery_attempts?**
Because Celery's `task_acks_late` means a task can run more than once after a worker crash. This constraint prevents duplicate attempt records for the same attempt number.

---

## 6. API Reference

### Authentication

For simplicity at this stage: API key authentication via `X-API-Key` header on all write endpoints. Store keys in environment variables or a separate `api_keys` table. Do not hardcode them.

### Endpoints

---

#### `POST /subscriptions`

Register a new webhook subscription.

**Request body:**
```json
{
  "endpoint_url": "https://example.com/webhooks",
  "event_types": ["payment.success", "order.created"],
  "secret": "your-hmac-secret"
}
```

**Response `201 Created`:**
```json
{
  "id": "uuid",
  "endpoint_url": "https://example.com/webhooks",
  "event_types": ["payment.success", "order.created"],
  "active": true,
  "created_at": "2026-10-11T09:00:00Z"
}
```

**Notes:** The `secret` is stored server-side and used to sign outgoing webhooks. The caller is responsible for verifying signatures on received webhooks.

---

#### `GET /subscriptions`

List all active subscriptions. Optional query param: `?event_type=payment.success`.

---

#### `DELETE /subscriptions/{subscription_id}`

Deactivate a subscription. Sets `active = false`. Does not delete records (preserves delivery history).

---

#### `POST /events`

Ingest a new event and enqueue delivery tasks.

**Required header:** `Idempotency-Key: <unique string>` — used as the deduplication key.

**Request body:**
```json
{
  "event_type": "payment.success",
  "payload": {
    "payment_id": "pay_123",
    "amount": 9900,
    "currency": "INR"
  }
}
```

**Response `202 Accepted` (new event):**
```json
{
  "event_id": "uuid",
  "status": "queued",
  "subscriptions_notified": 3
}
```

**Response `200 OK` (duplicate idempotency key):**
```json
{
  "event_id": "uuid",
  "status": "already_processed",
  "message": "Event with this idempotency key was already received."
}
```

**Error `400` if `Idempotency-Key` header is missing.**

---

#### `GET /events/{event_id}/deliveries`

Return the full delivery attempt history for an event.

**Response:**
```json
{
  "event_id": "uuid",
  "event_type": "payment.success",
  "deliveries": [
    {
      "subscription_id": "uuid",
      "endpoint_url": "https://example.com/webhooks",
      "attempts": [
        {
          "attempt_number": 1,
          "status": "failed",
          "response_code": 503,
          "attempted_at": "2026-10-11T09:00:01Z"
        },
        {
          "attempt_number": 2,
          "status": "success",
          "response_code": 200,
          "attempted_at": "2026-10-11T09:00:11Z"
        }
      ]
    }
  ]
}
```

---

#### `POST /events/{event_id}/replay`

Manually re-enqueue a dead-lettered event for a specific subscription.

**Request body:**
```json
{
  "subscription_id": "uuid"
}
```

**Response `202 Accepted`.**

---

#### `GET /health`

System health check. Returns status of Redis and PostgreSQL connectivity and Celery worker count.

**Response:**
```json
{
  "status": "healthy",
  "redis": "connected",
  "postgres": "connected",
  "celery_workers": 2
}
```

---

#### `GET /ws`

WebSocket endpoint. Connect to receive real-time delivery state updates.

**Message format (server → client):**
```json
{
  "event_id": "uuid",
  "subscription_id": "uuid",
  "status": "success",
  "attempt_number": 2,
  "response_code": 200,
  "timestamp": "2026-10-11T09:00:11Z"
}
```

---

#### `GET /metrics`

Prometheus metrics scrape endpoint. Returns plain text in Prometheus exposition format.

---

## 7. Celery Task Design

### Configuration (celery_app.py)

```python
from celery import Celery

celery_app = Celery("webhookforge")

celery_app.conf.update(
    broker_url=settings.REDIS_URL,
    result_backend=settings.REDIS_URL,

    # CRITICAL: Delay acknowledgement until task completes.
    # This enables at-least-once delivery even on worker crash.
    # Tradeoff: a crashed worker may re-deliver a task that already ran.
    # The delivery_attempts UNIQUE constraint handles duplicates.
    task_acks_late=True,

    # CRITICAL: If a worker crashes mid-task (not just an exception),
    # this ensures the task is re-queued rather than silently dropped.
    task_reject_on_worker_lost=True,

    # Prevent runaway tasks from blocking the queue
    task_soft_time_limit=30,  # seconds; raises SoftTimeLimitExceeded
    task_time_limit=60,       # hard kill after 60 seconds

    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone
    timezone="UTC",
    enable_utc=True,
)
```

### Delivery task (tasks/deliver.py)

```python
import httpx
import structlog
from celery import Task
from celery.exceptions import MaxRetriesExceededError

from app.celery_app import celery_app
from app.services.delivery import (
    build_signed_request,
    record_attempt,
    move_to_dlq,
    publish_status_update,
)

logger = structlog.get_logger()

MAX_RETRIES = 5

def _backoff_seconds(attempt: int) -> int:
    """Exponential backoff with jitter.
    
    Attempt 1 →  5s
    Attempt 2 → 10s
    Attempt 3 → 20s
    Attempt 4 → 40s
    Attempt 5 → 80s
    """
    import random
    base = 5 * (2 ** attempt)
    jitter = random.uniform(0, base * 0.1)
    return int(base + jitter)


@celery_app.task(
    bind=True,
    max_retries=MAX_RETRIES,
    autoretry_for=(httpx.RequestError, httpx.TimeoutException),
    retry_backoff=False,  # We implement custom backoff below
    name="webhookforge.deliver_webhook",
)
def deliver_webhook(self: Task, event_id: str, subscription_id: str) -> None:
    log = logger.bind(event_id=event_id, subscription_id=subscription_id, attempt=self.request.retries + 1)
    log.info("delivery_attempt_started")

    try:
        # Build and send the signed HTTP request
        headers, payload = build_signed_request(event_id, subscription_id)
        
        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                subscription.endpoint_url,
                headers=headers,
                content=payload,
            )

        # Treat 2xx as success; anything else as failure
        if response.is_success:
            record_attempt(
                event_id, subscription_id,
                attempt_number=self.request.retries + 1,
                status="success",
                response_code=response.status_code,
                response_body=response.text[:1000],
            )
            publish_status_update(event_id, subscription_id, "success", response.status_code)
            log.info("delivery_success", response_code=response.status_code)
            return

        # Non-2xx: treat as failure, retry
        error_detail = f"HTTP {response.status_code}: {response.text[:200]}"
        raise httpx.HTTPStatusError(error_detail, request=None, response=response)

    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        record_attempt(
            event_id, subscription_id,
            attempt_number=self.request.retries + 1,
            status="failed",
            error_detail=str(exc),
        )
        publish_status_update(event_id, subscription_id, "failed")
        log.warning("delivery_failed", error=str(exc), retries_remaining=MAX_RETRIES - self.request.retries)

        try:
            raise self.retry(
                exc=exc,
                countdown=_backoff_seconds(self.request.retries),
            )
        except MaxRetriesExceededError:
            # All retries exhausted → move to DLQ
            move_to_dlq(event_id, subscription_id, reason=str(exc))
            publish_status_update(event_id, subscription_id, "dead_lettered")
            log.error("delivery_dead_lettered", reason=str(exc))
```

### Key design points to understand before implementing

1. **Why `autoretry_for` + manual `self.retry`?** `autoretry_for` handles network-level exceptions. `self.retry` with manual `countdown` gives you control over the backoff interval, which `autoretry_for` alone does not.

2. **Why jitter in backoff?** If 100 tasks all fail at the same time (e.g., subscriber restart), exponential backoff without jitter causes a "thundering herd" — all 100 tasks retry simultaneously. Jitter spreads them out.

3. **Why `task_acks_late=True` + `UNIQUE (event_id, subscription_id, attempt_number)`?** `task_acks_late` prevents silent task loss on worker crash, but means the same task might run twice. The UNIQUE constraint on the delivery_attempts table prevents duplicate records.

---

## 8. Idempotency Design

This is the most interview-valuable design decision in the project. Understand it deeply.

### The problem

A client sends `POST /events` with `Idempotency-Key: evt_abc123`. Due to a network timeout, the client never receives the 202 response and retries the request. Now the same event is ingested twice and delivered to the subscriber twice — which might charge a customer twice, send two confirmation emails, etc.

### The naive (wrong) approach

```python
# RACE CONDITION — do not do this
existing = db.query(Event).filter_by(idempotency_key=key).first()
if existing:
    return existing
new_event = Event(idempotency_key=key, ...)
db.add(new_event)
db.commit()
```

Two concurrent requests both execute the SELECT before either executes the INSERT. Both see `existing = None`. Both proceed to insert. Race condition.

### The correct approach

```python
# ATOMIC — use this
from sqlalchemy.dialects.postgresql import insert as pg_insert

stmt = (
    pg_insert(Event)
    .values(
        idempotency_key=idempotency_key,
        event_type=event_type,
        payload=payload,
    )
    .on_conflict_do_nothing(index_elements=["idempotency_key"])
    .returning(Event.id)
)

result = await db.execute(stmt)
row = result.fetchone()

if row is None:
    # Event already exists — fetch it and return 200
    existing = await db.scalar(select(Event).where(Event.idempotency_key == idempotency_key))
    return EventResponse(event_id=existing.id, status="already_processed")

# New event — enqueue delivery tasks
event_id = row[0]
await enqueue_delivery_tasks(event_id)
return EventResponse(event_id=event_id, status="queued")
```

`ON CONFLICT DO NOTHING` is handled by the database atomically. No race condition is possible.

### Test for this (required)

```python
import asyncio

async def test_idempotency_concurrent():
    """100 concurrent requests with the same idempotency key 
    must produce exactly 1 event record and 1 delivery attempt."""
    
    idempotency_key = "test-idem-key-concurrent"
    
    async def send_event():
        return await client.post(
            "/events",
            json={"event_type": "test", "payload": {}},
            headers={"Idempotency-Key": idempotency_key},
        )
    
    responses = await asyncio.gather(*[send_event() for _ in range(100)])
    
    # All should succeed (200 or 202)
    assert all(r.status_code in (200, 202) for r in responses)
    
    # Exactly one event record in the database
    events = await db.scalars(select(Event).where(Event.idempotency_key == idempotency_key))
    assert len(list(events)) == 1
```

This test must pass before you consider idempotency done.

---

## 9. Security Controls

### HMAC-SHA256 Webhook Signing

Every outgoing HTTP request includes an `X-Webhook-Signature` header. This allows the subscriber to verify the request came from WebhookForge and was not tampered with.

```python
import hashlib
import hmac
import time

def sign_payload(payload: bytes, secret: str) -> str:
    """
    Returns 'sha256=<hex_digest>' for the X-Webhook-Signature header.
    Include a timestamp to prevent replay attacks:
        payload_to_sign = f"{timestamp}.{payload_str}".encode()
    """
    timestamp = int(time.time())
    payload_with_ts = f"{timestamp}.".encode() + payload
    
    signature = hmac.new(
        secret.encode("utf-8"),
        payload_with_ts,
        hashlib.sha256,
    ).hexdigest()
    
    return f"t={timestamp},sha256={signature}"
```

**Headers to include on outgoing webhook:**
```
Content-Type: application/json
X-Webhook-Signature: t=1728634800,sha256=<hex>
X-Webhook-Event: payment.success
X-Webhook-Delivery: <delivery_attempt_id>
```

**How the subscriber verifies (include this in README for documentation completeness):**
```python
import hashlib, hmac, time

def verify_signature(payload: bytes, header: str, secret: str, tolerance_seconds: int = 300) -> bool:
    parts = dict(item.split("=", 1) for item in header.split(","))
    timestamp = int(parts["t"])
    received_sig = parts["sha256"]
    
    # Reject old signatures (replay attack prevention)
    if abs(time.time() - timestamp) > tolerance_seconds:
        return False
    
    expected = hmac.new(
        secret.encode(),
        f"{timestamp}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    
    return hmac.compare_digest(expected, received_sig)
```

### Rate Limiting on Event Ingestion

Use the Redis `INCR`-based pattern (you already know this from PulseBoard):

```python
async def check_rate_limit(redis: Redis, client_key: str, limit: int = 100, window: int = 60) -> bool:
    """Returns True if under limit, False if exceeded."""
    key = f"rl:{client_key}:{int(time.time()) // window}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window * 2)
    return count <= limit
```

### Secret Management

- All secrets in environment variables. Never hardcode.
- `.env.example` committed with placeholder values.
- `.env` in `.gitignore`.
- In CI: use GitHub Actions secrets for `POSTGRES_URL`, `REDIS_URL`, `API_KEY`.
- In production: use the platform's secret store (Render environment variables, AWS Secrets Manager if on ECS).

### Input Validation

- All request bodies validated by Pydantic v2 schemas.
- `endpoint_url` validated as a valid HTTPS URL (`AnyHttpUrl` type).
- `payload` accepted as arbitrary JSON (`Dict[str, Any]`) but size-limited (reject payloads > 64KB).
- `event_type` validated against an allowlist or a regex pattern `^[a-z][a-z0-9_.]{1,63}$`.

---

## 10. Observability

### Structured Logging (structlog)

Configure structlog to emit JSON to stdout. Every log entry must include:

```python
import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)

# Usage — bind context fields to every log line in a request
log = structlog.get_logger().bind(
    event_id="uuid",
    subscription_id="uuid",
    attempt=2,
)
log.info("delivery_attempt_started")
log.warning("delivery_failed", response_code=503, error="Service Unavailable")
log.error("delivery_dead_lettered", reason="max retries exceeded")
```

Every log line must include: `timestamp`, `level`, `event_id`, `subscription_id`, `attempt_number`, `status`.

### Prometheus Metrics

```python
from prometheus_client import Counter, Histogram, Gauge

# Counters (monotonically increasing)
EVENTS_INGESTED = Counter(
    "webhookforge_events_ingested_total",
    "Total events received",
    ["event_type"],
)
DELIVERIES_SUCCESS = Counter(
    "webhookforge_deliveries_success_total",
    "Total successful deliveries",
)
DELIVERIES_FAILED = Counter(
    "webhookforge_deliveries_failed_total",
    "Total failed delivery attempts",
)
DELIVERIES_DLQ = Counter(
    "webhookforge_dlq_total",
    "Total events moved to dead-letter queue",
)

# Histogram (for latency percentiles)
DELIVERY_LATENCY = Histogram(
    "webhookforge_delivery_latency_seconds",
    "Time from task enqueue to first delivery attempt",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# Gauge (can go up and down)
DLQ_BACKLOG = Gauge(
    "webhookforge_dlq_backlog_size",
    "Current number of unresolved DLQ records",
)
```

Expose at `GET /metrics` using the `prometheus_client` ASGI middleware or a manual endpoint.

### Health Check

`GET /health` must actively check all dependencies:

```python
@router.get("/health")
async def health(db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)):
    checks = {}
    
    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = "connected"
    except Exception as e:
        checks["postgres"] = f"error: {e}"
    
    try:
        await redis.ping()
        checks["redis"] = "connected"
    except Exception as e:
        checks["redis"] = f"error: {e}"
    
    # Check Celery worker count via inspect
    from app.celery_app import celery_app
    inspector = celery_app.control.inspect(timeout=1.0)
    active = inspector.active() or {}
    checks["celery_workers"] = len(active)
    
    status = "healthy" if all("error" not in v for v in checks.values() if isinstance(v, str)) else "degraded"
    return {"status": status, **checks}
```

---

## 11. Testing Strategy

### Coverage target: ≥ 80%

Every feature must have a corresponding test before that milestone is considered complete. Test behaviour, not implementation.

### Unit tests

| Module | What to test |
|---|---|
| `services/signing.py` | `sign_payload` produces correct HMAC; `verify_signature` rejects tampered payloads; rejects old timestamps |
| `services/backoff.py` | `_backoff_seconds(0)` ≈ 5; `_backoff_seconds(4)` ≈ 80; jitter is within ±10% of base |
| `services/idempotency.py` | Duplicate key returns existing event_id; new key creates event |
| `services/dlq.py` | DLQ record is created after max retries; UNIQUE constraint prevents double-insertion |
| `tasks/deliver.py` | Retry is triggered on network error; no retry on 200; `move_to_dlq` called after `MaxRetriesExceededError` |

### Integration tests

| Scenario | Expected behaviour |
|---|---|
| POST /events with a fresh key, healthy subscriber | Returns 202; 1 delivery record with status=success |
| POST /events with duplicate key | Returns 200 with `already_processed`; 1 event record in DB |
| 100 concurrent POST /events with same key | 1 event record in DB; 1 delivery attempt |
| Subscriber returns 500 three times, then 200 | 3 failed attempts + 1 success attempt in DB |
| Subscriber always returns 500 (max retries exceeded) | DLQ record created; status=dead_lettered on all attempts |
| POST /events/replay on DLQ record | New delivery task enqueued; delivery attempt created |
| GET /events/{id}/deliveries | Returns correct attempt history |
| HMAC signature verification on outgoing request | Signature valid when verified with correct secret; invalid with wrong secret |

### Failure injection test (document this in README)

```bash
# Start all services
docker compose up -d

# Kill the Celery worker mid-task
docker compose kill celery_worker

# Send an event
curl -X POST http://localhost:8000/events \
  -H "Idempotency-Key: kill-test-001" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "test", "payload": {}}'

# Restart the worker
docker compose start celery_worker

# Within 30 seconds, verify the delivery completed
curl http://localhost:8000/events/$(EVENT_ID)/deliveries
# Expect: status=success on attempt 1 or 2
```

Document the actual output in `docs/failure-injection/worker-kill-test.md`. This is your most credible debugging story.

### Load test

Use `k6` or `locust`. Target: 50 events/second sustained for 60 seconds.

```javascript
// k6 load test script (load_test.js)
import http from 'k6/http';
import { check } from 'k6';

export const options = {
  vus: 50,
  duration: '60s',
};

let counter = 0;

export default function () {
  const key = `load-test-${__VU}-${__ITER}`;  // unique per VU per iteration
  const res = http.post(
    'http://localhost:8000/events',
    JSON.stringify({ event_type: 'load.test', payload: { n: counter++ } }),
    {
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': key,
      },
    }
  );
  check(res, { 'status is 202': (r) => r.status === 202 });
}
```

Record and commit the k6 summary output to `docs/benchmarks/load-test-results.md`.

---

## 12. Repository Structure

```
webhookforge/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app factory
│   ├── config.py                # Settings (pydantic-settings)
│   ├── celery_app.py            # Celery application instance + config
│   ├── database.py              # SQLAlchemy async engine + session
│   ├── redis_client.py          # Redis connection factory
│   │
│   ├── api/                     # FastAPI routers
│   │   ├── __init__.py
│   │   ├── events.py            # POST /events, GET /events/{id}/deliveries, replay
│   │   ├── subscriptions.py     # CRUD for subscriptions
│   │   ├── websocket.py         # WebSocket /ws endpoint
│   │   ├── health.py            # GET /health
│   │   └── metrics.py           # GET /metrics (Prometheus)
│   │
│   ├── models/                  # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── event.py
│   │   ├── subscription.py
│   │   ├── delivery_attempt.py
│   │   └── dlq_record.py
│   │
│   ├── schemas/                 # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── event.py
│   │   ├── subscription.py
│   │   └── delivery.py
│   │
│   ├── services/                # Business logic (no FastAPI dependencies)
│   │   ├── __init__.py
│   │   ├── signing.py           # HMAC-SHA256 signing + verification
│   │   ├── idempotency.py       # ON CONFLICT insert logic
│   │   ├── delivery.py          # record_attempt, move_to_dlq, publish_update
│   │   └── rate_limiting.py     # Redis-based rate limiter
│   │
│   └── tasks/                   # Celery task definitions
│       ├── __init__.py
│       └── deliver.py           # deliver_webhook task
│
├── alembic/                     # Database migrations
│   ├── env.py
│   └── versions/
│
├── tests/
│   ├── conftest.py              # Fixtures (test DB, test Redis, mock subscriber)
│   ├── unit/
│   │   ├── test_signing.py
│   │   ├── test_idempotency.py
│   │   ├── test_backoff.py
│   │   └── test_dlq.py
│   └── integration/
│       ├── test_events_api.py
│       ├── test_delivery_flow.py
│       ├── test_idempotency_concurrent.py
│       └── test_replay.py
│
├── docs/
│   ├── architecture.md          # Architecture diagram + narrative
│   ├── adr/
│   │   ├── 001-idempotency-design.md
│   │   ├── 002-celery-acks-late.md
│   │   └── 003-dlq-postgres-vs-redis.md
│   ├── benchmarks/
│   │   └── load-test-results.md
│   └── failure-injection/
│       └── worker-kill-test.md
│
├── scripts/
│   └── seed.py                  # Populate test subscriptions + fire events
│
├── .github/
│   └── workflows/
│       └── ci.yml               # Lint + test + security scan
│
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── Makefile
├── requirements.txt
├── pyproject.toml               # ruff + mypy config
└── README.md
```

---

## 13. Local Development Setup

### Prerequisites

- Docker + Docker Compose
- Python 3.12+
- `make` (optional but recommended)

### docker-compose.yml

```yaml
version: "3.9"

services:
  api:
    build: .
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    ports:
      - "8000:8000"
    environment:
      - POSTGRES_URL=postgresql+asyncpg://webhookforge:webhookforge@postgres:5432/webhookforge
      - REDIS_URL=redis://redis:6379/0
      - API_KEY=${API_KEY}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    volumes:
      - .:/app

  celery_worker:
    build: .
    command: celery -A app.celery_app worker --loglevel=info --concurrency=4
    environment:
      - POSTGRES_URL=postgresql+asyncpg://webhookforge:webhookforge@postgres:5432/webhookforge
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
      - postgres

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: webhookforge
      POSTGRES_PASSWORD: webhookforge
      POSTGRES_DB: webhookforge
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U webhookforge"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"
```

### Makefile

```makefile
.PHONY: dev test seed lint migrate

dev:
	docker compose up

test:
	docker compose run --rm api pytest tests/ -v --cov=app --cov-report=term-missing

seed:
	docker compose run --rm api python scripts/seed.py

lint:
	ruff check app/ tests/
	mypy app/

migrate:
	docker compose run --rm api alembic upgrade head

shell:
	docker compose exec api bash

logs:
	docker compose logs -f api celery_worker
```

### First-time setup

```bash
# Clone the repo
git clone https://github.com/your-username/webhookforge.git
cd webhookforge

# Copy env file and fill in values
cp .env.example .env

# Start all services
make dev

# In a new terminal — run migrations
make migrate

# Seed test data and fire events
make seed

# Run tests
make test
```

### Environment variables (.env.example)

```
# Database
POSTGRES_URL=postgresql+asyncpg://webhookforge:webhookforge@postgres:5432/webhookforge

# Redis
REDIS_URL=redis://redis:6379/0

# API authentication
API_KEY=your-api-key-here

# Celery
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# Delivery settings
MAX_DELIVERY_RETRIES=5
DELIVERY_TIMEOUT_SECONDS=5
MAX_PAYLOAD_SIZE_BYTES=65536

# Rate limiting
RATE_LIMIT_EVENTS_PER_MINUTE=100
```

---

## 14. Deployment

### Low-cost option (zero AWS charges)

| Service | Provider | Cost |
|---|---|---|
| FastAPI API | Render (free tier) | Free |
| Celery Worker | Render background worker | Free |
| PostgreSQL | Supabase (free tier) | Free |
| Redis | Upstash (free tier, 10k commands/day) | Free |

**Important:** Render free tier spins down after 15 minutes of inactivity. For demo purposes this is acceptable. For a live load test, upgrade to the $7/month Render plan or switch to Fly.io.

### AWS learning option (for portfolio signal)

| Service | AWS Equivalent | Estimated cost |
|---|---|---|
| FastAPI API | ECS Fargate (1 vCPU / 0.5GB) | ~$0.01/hr when running |
| Celery Worker | ECS Fargate (same) | ~$0.01/hr when running |
| PostgreSQL | RDS PostgreSQL (db.t3.micro) | ~$0.02/hr |
| Redis | ElastiCache (cache.t3.micro) | ~$0.02/hr |

**Stop all AWS resources when not demoing. Set up a CloudWatch billing alarm at $5/month.**

**Cleanup checklist (always run after demo):**
- [ ] Stop ECS services (set desired count to 0)
- [ ] Stop RDS instance
- [ ] Stop ElastiCache cluster
- [ ] Confirm no NAT Gateways running (they charge $0.045/hr)
- [ ] Check AWS Cost Explorer the next day

---

## 15. Build Milestones

Work through these in order. Do not move to the next milestone until the current one's acceptance criteria are met.

| Week | Milestone | Deliverable | Acceptance Criteria |
|---|---|---|---|
| 1 | Infrastructure | Docker Compose running, schema migrated, Celery worker starting | `make dev` → all 4 containers healthy; `make migrate` → no errors |
| 2 | Event ingestion + task dispatch | POST /events enqueues Celery task; event stored in DB | Celery worker logs receipt of task; event row in `events` table |
| 3 | HTTP delivery + basic retry | Worker POSTs to subscriber; retries on failure | 3 retries with increasing delays visible in worker logs |
| 4 | Idempotency | Duplicate key detection; concurrent request test | `test_idempotency_concurrent` passes: 100 concurrent requests → 1 event record |
| 5 | DLQ + delivery log API | After max retries, write to DLQ; GET /events/{id}/deliveries works | DLQ record appears in DB after permanent failure; API returns attempt history |
| 6 | HMAC signing + WebSocket dashboard | Signature on outgoing requests; dashboard streams live events | Signature verifiable with reference code; dashboard shows state changes in real time |
| 7 | Prometheus metrics + test suite | /metrics endpoint live; coverage ≥ 80% | `pytest --cov` shows ≥ 80%; Prometheus page returns valid metrics |
| 8 | Load test + documentation | k6 output committed; README complete; ADRs written; deployed | Load test results in `docs/benchmarks/`; README passes the "fresh developer" test |

**Stopping rule:** After Week 8 criteria are met, the project is done. Do not add multi-tenancy, Kafka, a full admin UI, or a React frontend. The project is complete when it is demonstrably working, tested, measured, and documented.

---

## 16. Architecture Decision Records

Create one ADR per major design decision. ADRs are short (one page), use a consistent format, and never change after the decision is made (add a new ADR if you reverse a decision).

### ADR format

```markdown
# ADR-001: [Title]

**Date:** YYYY-MM-DD  
**Status:** Accepted

## Context
What was the situation? What problem were you solving?

## Decision
What did you decide? Be specific.

## Consequences
What are the tradeoffs? What becomes easier? What becomes harder?
```

### ADRs to write for this project

| ADR | Decision | Write after |
|---|---|---|
| ADR-001 | Idempotency via PostgreSQL `ON CONFLICT` vs application-level check | Week 4 |
| ADR-002 | `task_acks_late=True` and its tradeoff | Week 3 |
| ADR-003 | DLQ in PostgreSQL vs separate Redis list | Week 5 |
| ADR-004 | Exponential backoff with jitter vs fixed interval | Week 3 |

These ADRs are as valuable as the code. They demonstrate that you thought about alternatives and made reasoned choices — which is exactly what interviewers are probing for.

---

## 17. Runbook

A runbook is a short document that tells an on-call engineer what to do when things go wrong. Write this after the project is deployed.

### Scenario 1: DLQ backlog growing

**Symptom:** `webhookforge_dlq_backlog_size` metric is increasing; alerts are not resolving.

**Investigation:**
```bash
# Check what's in the DLQ
psql $POSTGRES_URL -c "
SELECT e.event_type, s.endpoint_url, d.reason, d.created_at
FROM dlq_records d
JOIN events e ON e.id = d.event_id
JOIN subscriptions s ON s.id = d.subscription_id
WHERE d.replayed_at IS NULL
ORDER BY d.created_at DESC
LIMIT 20;
"

# Check if the subscriber endpoint is reachable
curl -v https://subscriber-endpoint.example.com/webhooks
```

**Resolution:** If subscriber is down, wait and replay when it recovers:
```bash
# Replay all DLQ records for a subscription
curl -X POST http://localhost:8000/events/{event_id}/replay \
  -d '{"subscription_id": "uuid"}'
```

---

### Scenario 2: Redis connection lost

**Symptom:** 500 errors on POST /events; Celery worker logs connection errors.

**Investigation:**
```bash
docker compose logs redis
redis-cli -u $REDIS_URL ping
```

**Behavior:** Celery tasks stop processing (broker unavailable). Events queued in API in-memory buffer (if implemented) or rejected with 503. PostgreSQL continues working (events already stored before enqueue attempt).

**Resolution:** Restart Redis, verify connectivity, check for `REDIS_URL` misconfiguration.

---

### Scenario 3: Database migration failed in deployment

**Symptom:** API returns 500 on startup; logs show `relation does not exist`.

**Investigation:**
```bash
# Check migration state
alembic current
alembic history
```

**Resolution:**
```bash
# Roll back to previous revision
alembic downgrade -1

# Fix the migration script, then re-apply
alembic upgrade head
```

**Prevention:** Always run `alembic check` in CI to confirm migrations are up to date before deploying.

---

## 18. Success Criteria

These are the metrics to measure, not the values to claim. Do not write results in your resume until you have run these tests.

| Metric | How to measure | Target threshold | Placeholder for resume |
|---|---|---|---|
| Delivery success rate (healthy subscriber) | Send 1000 events; count `status=success` | ≥ 99% | `[measured delivery success rate]%` |
| Delivery success rate (30% transient failure) | Mock subscriber returns 500 on 30% of requests; observe after retries | ≥ 95% | `[measured recovery rate]%` |
| p95 delivery latency | k6 histogram output | ≤ 500ms | `[measured p95 latency]ms` |
| Idempotency correctness | 100 concurrent same-key requests | 100% (1 delivery record) | Measurable, not a percentage claim |
| DLQ accuracy | Mock subscriber always returning 500; assert DLQ records appear | 100% | Measurable |
| Test coverage | `pytest --cov` | ≥ 80% | `[measured coverage]%` |
| k6 throughput | 50 VUs, 60s duration | ≥ 50 req/s | `[measured throughput] events/min` |

---

*End of WebhookForge Technical Specification v1.0*
