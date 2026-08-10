"""The tool's own limits: rate, wait, and how much of a response is read.

These duplicate what the gateway enforces, and the duplication is deliberate.
The client-side copy exists so a normal run is well-behaved and produces clear
local errors; the gateway's copy exists because the client is the component that
might be wrong. Neither replaces the other.

Nothing here is a security boundary. Anything in this file can be turned off
with `--no-client-limits`, which is exactly how the reports show that the
gateway still refuses.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


class ClientLimitExceeded(RuntimeError):
    """Refused before anything was sent. Carries a reason for the audit log."""


@dataclass
class TokenBucket:
    """Rate limit that waits rather than fails.

    A probing tool that errors out at the limit is annoying; one that paces
    itself is useful. `acquire` therefore returns how long it slept, which the
    caller records -- a run that spent 40 seconds waiting should say so.
    """

    per_minute: int
    capacity: float = 0.0
    _tokens: float = 0.0
    _last: float = 0.0

    def __post_init__(self) -> None:
        self.capacity = float(self.per_minute)
        self._tokens = self.capacity
        self._last = time.monotonic()

    @property
    def rate(self) -> float:
        return self.per_minute / 60.0

    def _refill(self, now: float) -> None:
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now

    def wait_time(self) -> float:
        """Seconds until a token is available. 0 if one is available now."""
        self._refill(time.monotonic())
        if self._tokens >= 1.0:
            return 0.0
        return (1.0 - self._tokens) / self.rate

    def acquire(self, max_wait_s: float, sleep=time.sleep) -> float:
        """Take a token, sleeping if needed. Raises if the wait is too long."""
        wait = self.wait_time()
        if wait > max_wait_s:
            raise ClientLimitExceeded(
                f"rate limit: would need to wait {wait:.1f}s (max {max_wait_s:.1f}s)"
            )
        if wait > 0:
            sleep(wait)
            self._refill(time.monotonic())
        self._tokens -= 1.0
        return wait


def check_request_size(body: bytes, limit: int) -> None:
    if len(body) > limit:
        raise ClientLimitExceeded(
            f"request body is {len(body)} bytes, client cap is {limit} "
            f"(use --no-client-limits to let the gateway answer instead)"
        )


def read_capped(fp, limit: int) -> tuple[bytes, bool]:
    """Read at most `limit` bytes and say whether there was more.

    Reading `limit + 1` is what makes `truncated` honest: a body of exactly
    `limit` bytes is complete, not truncated.
    """
    data = fp.read(limit + 1)
    if len(data) > limit:
        return data[:limit], True
    return data, False
