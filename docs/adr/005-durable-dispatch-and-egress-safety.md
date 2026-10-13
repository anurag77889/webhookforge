# ADR-005: Make dispatch recoverable and restrict webhook egress

**Date:** 2026-10-13
**Status:** Accepted

## Context

Writing an event and enqueueing its delivery are separate systems. If the API
commits an event but fails before Celery receives the task, the event can remain
undelivered. Also, accepting arbitrary callback URLs can let an authenticated
caller use the worker to access private network services.

## Decision

Event creation will write a transactional outbox record in the same PostgreSQL
transaction. A dispatcher will enqueue pending records and mark them dispatched
only after successful broker publication; it will also retry recoverable pending
records. Subscription URLs must use HTTPS and pass egress validation: resolved
addresses may not be loopback, private, link-local, multicast, unspecified, or
reserved. Redirects will not be followed.

## Consequences

An event cannot be permanently stranded by a broker outage between commit and
publish, at the cost of one additional table and dispatcher path. Endpoint
validation requires DNS resolution and careful test coverage; local HTTP test
servers need an explicit test-only bypass.
