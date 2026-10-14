# ADR-002: Celery `task_acks_late=True` and Its Tradeoff

**Date:** 2026-10-14  
**Status:** Accepted

## Context

The Celery worker processes webhook delivery tasks. By default, Celery acknowledges a task to Redis the moment the worker picks it up (before execution). If the worker process crashes mid-delivery (OOM kill, hardware failure, container eviction), the task is silently lost — the webhook is never delivered and no record of the failure exists.

This is unacceptable for a reliability-focused delivery engine. A payment notification that silently disappears is worse than one that arrives twice.

## Decision

We set `task_acks_late=True` globally in the Celery configuration. The task is only acknowledged after it completes successfully (or is explicitly rejected). Combined with `task_reject_on_worker_lost=True`, a crashed worker causes the task to be re-queued by Redis and picked up by another worker.

## Consequences

**What becomes easier:**
- At-least-once delivery guarantee: no task is silently dropped on worker crash.
- Operational confidence: crash-recovery is automatic without manual intervention.

**What becomes harder:**
- The same delivery task may execute more than once if the worker crashes after the HTTP POST succeeds but before acknowledging the task. This means a subscriber might receive the same webhook twice.
- To handle this, the `delivery_attempts` table has a `UNIQUE (event_id, subscription_id, attempt_number)` constraint. The `record_attempt` function uses `INSERT ... ON CONFLICT DO UPDATE` so that re-executed tasks overwrite their own record rather than crashing or creating duplicates.
- Subscribers should still implement their own idempotency (e.g., checking `X-Webhook-Delivery` header) as a defense-in-depth measure.

**The tradeoff in one sentence:** We accept the possibility of duplicate HTTP delivery to guarantee no silent delivery loss.
