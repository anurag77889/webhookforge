# ADR-004: Exponential Backoff with Jitter vs Fixed Interval

**Date:** 2026-10-14  
**Status:** Accepted

## Context

When a subscriber endpoint fails (returns 5xx, times out, or is unreachable), the delivery task needs to retry. The retry interval strategy directly affects both recovery speed and system stability.

Three options were considered:

1. **Fixed interval** (e.g., retry every 10 seconds) — simple but causes thundering-herd: if a subscriber goes down and 500 tasks all fail at the same time, all 500 retry simultaneously 10 seconds later, overwhelming the recovering subscriber.

2. **Exponential backoff without jitter** (e.g., 5s, 10s, 20s, 40s, 80s) — spreads load over time but all tasks that failed at the same instant still retry at the same future instant.

3. **Exponential backoff with jitter** — exponential growth plus a random offset (up to 10% of the base delay). This both spreads retries over time and desynchronizes concurrent failures.

## Decision

We use exponential backoff with jitter: `base = 5 * 2^attempt`, `jitter = uniform(0, base * 0.1)`, `delay = int(base + jitter)`.

This gives delays of approximately 5s → 10s → 20s → 40s → 80s across 5 attempts (initial + 4 retries), with small random variation on each.

## Consequences

**What becomes easier:**
- Recovering subscribers are not hammered by synchronized retry storms.
- Total retry window (~155 seconds) is long enough for transient outages to resolve but short enough to not leave events undelivered for hours.

**What becomes harder:**
- Retry timing is non-deterministic, which makes exact timing assertions in tests impossible. Tests must assert on ranges (e.g., "attempt 4 delay is between 80 and 88 seconds").
- The jitter is small (10%) to keep delays predictable for operators while still achieving desynchronization.
