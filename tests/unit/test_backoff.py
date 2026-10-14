"""Unit tests for exponential backoff with jitter."""

from app.services.backoff import backoff_seconds


class TestBackoffSeconds:
    """Tests for the backoff_seconds function."""

    def test_attempt_0_approximately_5(self):
        """Attempt 0 should return ~5 seconds (base=5, jitter up to 0.5)."""
        result = backoff_seconds(0)
        assert 5 <= result <= 5  # int(5 + [0, 0.5]) → always 5

    def test_attempt_1_approximately_10(self):
        """Attempt 1 should return ~10 seconds."""
        result = backoff_seconds(1)
        assert 10 <= result <= 11

    def test_attempt_2_approximately_20(self):
        """Attempt 2 should return ~20 seconds."""
        result = backoff_seconds(2)
        assert 20 <= result <= 22

    def test_attempt_3_approximately_40(self):
        """Attempt 3 should return ~40 seconds."""
        result = backoff_seconds(3)
        assert 40 <= result <= 44

    def test_attempt_4_approximately_80(self):
        """Attempt 4 should return ~80 seconds."""
        result = backoff_seconds(4)
        assert 80 <= result <= 88

    def test_values_increase_monotonically(self):
        """Each successive attempt should have a higher base delay."""
        values = [backoff_seconds(i) for i in range(5)]
        for i in range(1, len(values)):
            # With jitter, we check that attempt N base > attempt N-1 max
            # Base(N) = 5 * 2^N; max(N-1) = 5 * 2^(N-1) * 1.1
            # Base(N) = 2 * Base(N-1) > 1.1 * Base(N-1), so this holds.
            assert values[i] >= values[i - 1]

    def test_returns_int(self):
        """backoff_seconds should always return an integer."""
        for attempt in range(5):
            assert isinstance(backoff_seconds(attempt), int)

    def test_jitter_produces_variation(self):
        """Running multiple times should occasionally produce different values
        (for attempts where jitter range > 1)."""
        # Attempt 4: base=80, jitter up to 8 → int range [80, 88]
        results = {backoff_seconds(4) for _ in range(100)}
        # With 100 runs over a range of 9 possible int values, we should see
        # at least 2 distinct values.
        assert len(results) >= 2
