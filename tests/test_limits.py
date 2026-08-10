"""The tool's own limits: rate, size, and how much of a body is read."""

from __future__ import annotations

import io

import pytest

from safe_probe.limits import ClientLimitExceeded, TokenBucket, check_request_size, read_capped


class FakeClock:
    """Time the test controls, so a rate-limit test takes no wall-clock time."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept = 0.0

    def sleep(self, seconds: float) -> None:
        self.slept += seconds
        self.now += seconds


@pytest.fixture
def bucket(monkeypatch) -> tuple[TokenBucket, FakeClock]:
    clock = FakeClock()
    monkeypatch.setattr("safe_probe.limits.time.monotonic", lambda: clock.now)
    return TokenBucket(per_minute=60), clock


def test_a_full_bucket_does_not_wait(bucket) -> None:
    tb, clock = bucket
    for _ in range(60):
        assert tb.acquire(max_wait_s=10, sleep=clock.sleep) == 0.0
    assert clock.slept == 0.0


def test_an_empty_bucket_waits_for_exactly_one_token(bucket) -> None:
    tb, clock = bucket
    for _ in range(60):
        tb.acquire(max_wait_s=10, sleep=clock.sleep)
    # 60/minute is one per second, so the 61st request waits one second.
    assert tb.acquire(max_wait_s=10, sleep=clock.sleep) == pytest.approx(1.0, abs=0.01)


def test_it_refuses_rather_than_blocking_for_minutes(bucket) -> None:
    tb, clock = bucket
    for _ in range(60):
        tb.acquire(max_wait_s=10, sleep=clock.sleep)
    with pytest.raises(ClientLimitExceeded, match="rate limit"):
        tb.acquire(max_wait_s=0.5, sleep=clock.sleep)


def test_the_bucket_refills_while_idle(bucket) -> None:
    tb, clock = bucket
    for _ in range(60):
        tb.acquire(max_wait_s=10, sleep=clock.sleep)
    clock.now += 30  # half a minute of quiet
    assert tb.wait_time() == 0.0


def test_it_never_refills_past_capacity(bucket) -> None:
    tb, clock = bucket
    clock.now += 3600
    tb.acquire(max_wait_s=1, sleep=clock.sleep)
    assert tb._tokens == pytest.approx(59.0)


def test_request_size_check_names_the_escape_hatch() -> None:
    check_request_size(b"a" * 100, limit=100)  # exactly at the limit is fine
    with pytest.raises(ClientLimitExceeded, match="no-client-limits"):
        check_request_size(b"a" * 101, limit=100)


def test_a_body_exactly_at_the_cap_is_not_reported_as_truncated() -> None:
    data, truncated = read_capped(io.BytesIO(b"x" * 100), limit=100)
    assert (len(data), truncated) == (100, False)


def test_a_body_one_byte_over_is() -> None:
    data, truncated = read_capped(io.BytesIO(b"x" * 101), limit=100)
    assert (len(data), truncated) == (100, True)
