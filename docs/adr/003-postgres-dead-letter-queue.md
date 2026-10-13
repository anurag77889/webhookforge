# ADR-003: Store dead-letter records in PostgreSQL

**Date:** 2026-10-13
**Status:** Accepted

## Context

Events that exhaust delivery attempts need durable operator-visible history and
targeted replay. A Redis list is convenient for queueing but is not the system
of record for delivery audit history.

## Decision

WebhookForge will persist dead-letter records in `dlq_records` in PostgreSQL,
with one record per event and subscription pair. The record links to the final
delivery attempt, records the failure reason, and records when an operator
replays it.

## Consequences

DLQ inspection, replay state, and metrics can use durable relational data and
survive Redis resets. Replay needs explicit database queries rather than Redis
queue primitives, but that is appropriate for a manual operational workflow.
