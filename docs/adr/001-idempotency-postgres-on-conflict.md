# ADR-001: Use PostgreSQL `ON CONFLICT` for idempotent event ingestion

**Date:** 2026-10-13
**Status:** Accepted

## Context

Webhook clients retry after connection failures and timeouts. A read-then-write
deduplication check races when requests carrying the same idempotency key arrive
concurrently, which can create multiple events and deliveries.

## Decision

The `events.idempotency_key` column will have a unique database constraint. The
event-ingestion service will use PostgreSQL `INSERT ... ON CONFLICT DO NOTHING
RETURNING id` as its single create-or-find operation. An inserted row returns
`202 Accepted`; a conflict fetches and returns the existing event with `200 OK`.

## Consequences

Idempotency is enforced atomically at the durable boundary and remains correct
across API replicas. This makes PostgreSQL a required dependency for ingestion
and uses PostgreSQL-specific SQL in a small, isolated service module.
