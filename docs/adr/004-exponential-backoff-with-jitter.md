# ADR-004: Use capped exponential retry backoff with jitter

**Date:** 2026-10-13
**Status:** Accepted

## Context

Many deliveries can fail together when a subscriber restarts. Fixed retry
intervals synchronize retries and can overload the recovering service.

## Decision

Each failed delivery will retry using exponential delays with up to 10% positive
jitter. WebhookForge defines a delivery policy as **five total attempts**:
one initial attempt and four retries. The nominal retry delays are 5, 10, 20,
and 40 seconds, subject to jitter.

## Consequences

Recovery traffic is spread over time and the maximum time to dead-letter is
predictable. Celery's `max_retries` will be configured as four to align with
this policy; code and documentation must not describe it as five retries.
