# ADR-002: Acknowledge delivery tasks only after completion

**Date:** 2026-10-13
**Status:** Accepted

## Context

A worker can terminate during webhook delivery. Acknowledging work before it
finishes can silently lose an event, while delaying acknowledgement can cause a
task to execute again after a crash.

## Decision

Celery will use `task_acks_late=True` and `task_reject_on_worker_lost=True`.
Delivery tasks are therefore processed at least once. The database uniqueness
constraint on `(event_id, subscription_id, attempt_number)` will make repeated
execution of the same logical attempt safe for the delivery ledger.

## Consequences

WebhookForge favors delivery over silent loss. A subscriber can receive a
duplicate request if the worker crashes after sending it and before persisting
success, so subscribers must verify the delivery identifier and implement their
own idempotency where effects are non-idempotent.
