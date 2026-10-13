# WebhookForge

Reliable webhook delivery engine: ingests events, fans them out to registered
subscriber endpoints via Celery workers, and guarantees delivery through
retries with exponential backoff, a dead-letter queue, and idempotent event
ingestion.

## Delivery guarantee

WebhookForge provides atomic idempotent event ingestion and **at-least-once**
delivery processing. It prevents duplicate event creation and duplicate
delivery-ledger records, but cannot promise exactly-once network delivery: a
worker may send a webhook and crash before recording its success. Each outgoing
request therefore includes a delivery identifier for subscriber-side
deduplication.

Architecture decisions are recorded in [`docs/adr`](docs/adr), including the
retry policy (five total attempts), transactional dispatch, and outbound request
safety controls.

## Status

Build in progress — see the technical specification for scope and milestones.

## Quickstart

```powershell
# 1. Configure
Copy-Item .env.example .env

# 2. Start all services
.\scripts\dev.ps1

# 3. Apply migrations (new terminal)
.\scripts\migrate.ps1

# 4. Seed test data (new terminal)
.\scripts\seed.ps1

# 5. Run tests (new terminal)
.\scripts\test.ps1
```

Linux/macOS users: use the `Makefile` targets (`make dev`, `make migrate`,
`make seed`, `make test`, `make lint`).

## Services

| Service | Port |
|---|---|
| API | http://localhost:8000 |
| Prometheus | http://localhost:9090 |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |
