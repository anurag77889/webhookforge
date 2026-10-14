"""Exponential backoff with jitter for delivery retries."""

import random


def backoff_seconds(attempt: int) -> int:
    """Return the retry delay in seconds for a given *attempt* index.

    Attempt 0 →  ~5 s
    Attempt 1 → ~10 s
    Attempt 2 → ~20 s
    Attempt 3 → ~40 s
    Attempt 4 → ~80 s

    Jitter adds up to ±10 % of the base delay to prevent thundering-herd
    when many tasks retry at the same time.
    """
    base = 5 * (2 ** attempt)
    jitter = random.uniform(0, base * 0.1)
    return int(base + jitter)
