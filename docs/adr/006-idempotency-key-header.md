# ADR-006: Require Idempotency-Key as an HTTP header

**Date:** 2026-10-13
**Status:** Accepted

## Context

Event publishers retry on network failures. Without deduplication, a retry
creates a second event and triggers duplicate deliveries to all subscribers.
The idempotency key must be supplied by the publisher — it cannot be
generated server-side because a server-generated key cannot survive a
publisher retry.

## Decision

The event ingestion endpoint requires an `Idempotency-Key` HTTP header.
A missing header is rejected with 400 Bad Request. The key is stored in
`events.idempotency_key` with a unique constraint; a conflict returns
200 OK with the original event rather than 202 Accepted.

## Consequences

Publishers must generate and persist their idempotency key before sending.
A UUID4 generated at request-build time and stored until the response is
confirmed is the standard pattern. The header approach follows Stripe's
webhook API design, keeps the request body schema clean, and allows
middleware or load balancers to log the key separately from the payload.
