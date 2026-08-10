"""Configuration, and the reading of `.env` without a dependency to do it.

Every client-side limit here is *below* the matching gateway limit. That is the
whole idea of the two layers: the tool self-throttles so a normal run never
trips the gateway, and the gateway is what happens when the tool is wrong,
misconfigured, or talked into something. `docs/adr/0002-guardrail-hai-lop.md`.

The one number that goes the other way is the timeout: the tool waits *longer*
than the gateway does, so a slow upstream produces the gateway's 504 rather than
a client-side timeout that would tell us nothing about the gateway.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
DEFAULT_LOG = REPO_ROOT / "data" / "probe" / "requests.jsonl"

# Gateway policy, for reference (gateway/policy.yml):
#   rate_per_minute 30 | upstream_timeout_s 5 | request 64 KB | response 256 KB
DEFAULT_RATE_PER_MINUTE = 20
DEFAULT_TIMEOUT_S = 8.0
DEFAULT_MAX_REQUEST_BYTES = 32_768
DEFAULT_MAX_RESPONSE_BYTES = 64_000

# How long the tool will sit waiting for its own rate limiter before giving up
# and reporting `refused_by_client`. Without this a suite could block for
# minutes with no output.
DEFAULT_MAX_WAIT_S = 15.0

# How much of the body ends up in a ProbeResult and in the log. The task asks
# for "a part of the response"; a whole one would make the log unreadable.
BODY_EXCERPT_CHARS = 800


class ConfigError(RuntimeError):
    """Something required is missing. Raised before any request is attempted."""


def load_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Parse `.env` into a dict. Real environment variables win.

    A four-line parser instead of python-dotenv: AGENTS.md forbids a dependency
    for convenience, and the file this reads is one we write ourselves.
    """
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            values[name.strip()] = value.strip().strip('"').strip("'")
    for name in list(values) + [
        "PROBE_API_KEY",
        "GATEWAY_URL",
        "OPENCODE_API_KEY",
        "OPENCODE_BASE_URL",
        "CUSTOM_SCAN_MODEL",
    ]:
        if name in os.environ:
            values[name] = os.environ[name]
    return values


@dataclass(frozen=True)
class Config:
    gateway_url: str
    api_key: str
    rate_per_minute: int = DEFAULT_RATE_PER_MINUTE
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_wait_s: float = DEFAULT_MAX_WAIT_S
    log_path: Path = DEFAULT_LOG
    # Turns off the tool's own rate limit and size caps, leaving only the
    # gateway. This is how the repo demonstrates that the server-side controls
    # are the ones with teeth -- see scripts/smoke.sh and reports/.
    client_limits: bool = True

    def __repr__(self) -> str:
        # The default dataclass repr would print the key. This class ends up in
        # tracebacks and debug output, so it must not be able to.
        return (
            f"Config(gateway_url={self.gateway_url!r}, api_key=***REDACTED***, "
            f"rate_per_minute={self.rate_per_minute}, timeout_s={self.timeout_s}, "
            f"client_limits={self.client_limits})"
        )

    @classmethod
    def from_env(cls, **overrides: object) -> Config:
        env = load_env()
        key = env.get("PROBE_API_KEY", "").strip()
        if not key:
            raise ConfigError(
                "PROBE_API_KEY is empty. Run `bash scripts/up.sh` to generate one into .env."
            )
        base = {
            "gateway_url": env.get("GATEWAY_URL", "http://localhost:8000").rstrip("/"),
            "api_key": key,
        }
        base.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**base)  # type: ignore[arg-type]
