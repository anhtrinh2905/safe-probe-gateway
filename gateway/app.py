"""The gateway. Everything the probing tool can reach, it reaches through here.

This process is the only one on the `edge` network. `juice-shop` and `lab-app`
sit on a network declared `internal: true` and publish no ports, so "every
request goes through the gateway" is a property of the topology rather than a
convention the tool is trusted to honour. See docs/adr/0003-topology-la-bang-chung.md.

The file is deliberately generic. Which paths exist, who may call them, and every
limit are read from `policy.yml`; nothing here decides policy. If you find
yourself adding an `if path == ...`, it belongs in the YAML.

Checks run in a fixed order, and the order is itself a decision:

    1  request size      413   before the body is read, so an oversized body is
                               never buffered
    2  api key           401   an unknown caller learns nothing else
    3  route allowlist   404   *not* 403 -- a caller outside the allowlist should
                               not be able to map what exists behind the gateway
    4  method            405   only once the path is known to be allowlisted
    5  acl group         403   the caller is known and the route exists
    6  rate limit        429   with Retry-After
    7  upstream          504 / 502
    8  response cap      body cut at max_response_bytes

Credentials are stripped before proxying: the upstream never sees the gateway
key. Nothing that could carry one reaches the audit log -- see `_redact`.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from policy import Policy, Route, load_policy

POLICY_PATH = Path(os.environ.get("GATEWAY_POLICY", Path(__file__).with_name("policy.yml")))
LOG_PATH = Path(os.environ.get("GATEWAY_LOG", "/var/log/gateway/access.jsonl"))

# Headers that belong to a single hop and must not be forwarded either way.
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)

# Stripped on the way in. The gateway credential is for the gateway; forwarding
# it would hand the application under test a working key.
STRIP_REQUEST = HOP_BY_HOP | {"host", "content-length", "x-api-key", "authorization", "cookie"}

# httpx decodes the body for us, so the upstream's framing headers would lie.
STRIP_RESPONSE = HOP_BY_HOP | {"content-length", "content-encoding", "set-cookie"}

# Never written to the audit log, whatever their value.
SENSITIVE_HEADERS = frozenset({"x-api-key", "authorization", "cookie", "set-cookie"})
SENSITIVE_QUERY = frozenset({"apikey", "api_key", "key", "token", "password"})

PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class TokenBucket:
    """Per-consumer rate limit.

    A bucket rather than a fixed window so that a caller who has been quiet for a
    minute is not punished for the previous minute's burst, and so `retry_after`
    is an actual number of seconds rather than "wait for the window to roll".
    """

    def __init__(self, per_minute: int) -> None:
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self._tokens: dict[str, float] = {}
        self._last: dict[str, float] = {}

    def take(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        last = self._last.get(key, now)
        tokens = min(self.capacity, self._tokens.get(key, self.capacity) + (now - last) * self.rate)
        self._last[key] = now

        if tokens < 1.0:
            self._tokens[key] = tokens
            return False, max(1, math.ceil((1.0 - tokens) / self.rate))
        self._tokens[key] = tokens - 1.0
        return True, 0


def _redact(value: str, secrets: Iterable[str]) -> str:
    """Last line of defence: blank any known credential found in a free string.

    The header allowlist below already keeps keys out of the log. This exists
    because a key can also end up in a query string or an upstream error message,
    and the audit log must be safe to paste into a report either way.
    """
    for secret in secrets:
        if secret and secret in value:
            value = value.replace(secret, "***REDACTED***")
    return value


def _safe_headers(headers: Any, secrets: Iterable[str]) -> dict[str, str]:
    return {
        k: ("***REDACTED***" if k.lower() in SENSITIVE_HEADERS else _redact(v, secrets))
        for k, v in headers.items()
    }


def _safe_query(query: str, secrets: Iterable[str]) -> str:
    if not query:
        return ""
    parts = []
    for pair in query.split("&"):
        name, sep, value = pair.partition("=")
        parts.append(
            f"{name}=***REDACTED***" if name.lower() in SENSITIVE_QUERY else name + sep + value
        )
    return _redact("&".join(parts), secrets)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    policy = load_policy(POLICY_PATH)
    app.state.policy = policy
    app.state.bucket = TokenBucket(policy.limits.rate_per_minute)
    app.state.secrets = policy.secret_values()
    # No timeout on the client: the per-request timeout below comes from policy,
    # and a client-level default would silently win over it.
    app.state.http = httpx.AsyncClient(timeout=None, follow_redirects=False)

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    for skipped in policy.skipped_consumers:
        print(f"[gateway] consumer skipped: {skipped}", flush=True)
    print(
        f"[gateway] policy loaded: {len(policy.routes)} routes, "
        f"{policy.limits.rate_per_minute} req/min, "
        f"{policy.limits.upstream_timeout_s}s upstream timeout",
        flush=True,
    )
    try:
        yield
    finally:
        await app.state.http.aclose()


app = FastAPI(title="week4 api gateway", lifespan=lifespan)


def _audit(request: Request, entry: dict[str, Any]) -> None:
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "method": request.method,
        "path": request.url.path,
        "query": _safe_query(request.url.query, request.app.state.secrets),
        "client": request.client.host if request.client else None,
        **entry,
    }
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _deny(request: Request, status: int, decision: str, detail: str, **extra: Any) -> Response:
    _audit(request, {"status": status, "decision": decision, "detail": detail, **extra})
    return JSONResponse(
        {"error": decision, "detail": detail},
        status_code=status,
        headers={"X-Gateway-Decision": decision},
    )


@app.get("/_gateway/health")
async def health() -> dict[str, Any]:
    """Unauthenticated on purpose: `scripts/up.sh` polls it before a key exists."""
    policy: Policy = app.state.policy
    return {"status": "ok", "routes": len(policy.routes)}


@app.get("/_gateway/routes")
async def routes(request: Request) -> Response:
    """The allowlist, as published to an authenticated caller.

    The tool reads this instead of carrying its own copy. It means the tool can
    never drift from the gateway, and it makes the allowlist something the tool
    *learns* rather than something it *asserts*.
    """
    policy: Policy = app.state.policy
    consumer = policy.consumer_for(request.headers.get("x-api-key"))
    if consumer is None:
        return _deny(request, 401, "unauthorized", "missing or unknown API key")
    _audit(request, {"status": 200, "decision": "allowed", "consumer": consumer.name})
    return JSONResponse(
        {
            "consumer": consumer.name,
            "groups": sorted(consumer.groups),
            "limits": {
                "rate_per_minute": policy.limits.rate_per_minute,
                "upstream_timeout_s": policy.limits.upstream_timeout_s,
                "max_request_bytes": policy.limits.max_request_bytes,
                "max_response_bytes": policy.limits.max_response_bytes,
            },
            "routes": [r.public() for r in policy.routes],
        }
    )


async def _read_body(request: Request, limit: int) -> bytes | None:
    """Read at most `limit` bytes. None means the caller went over.

    Streamed rather than `await request.body()` so that a chunked request with no
    Content-Length cannot get a large body buffered before the check happens.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@app.api_route("/{full_path:path}", methods=PROXY_METHODS)
async def proxy(request: Request, full_path: str) -> Response:
    policy: Policy = app.state.policy
    limits = policy.limits
    secrets = app.state.secrets
    path = request.url.path

    # 1. size, from the declared length first so an oversized body is refused
    #    before a single byte of it is read.
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limits.max_request_bytes:
        return _deny(
            request,
            413,
            "request-too-large",
            f"body of {declared} bytes exceeds max_request_bytes={limits.max_request_bytes}",
        )

    # 2. authentication
    consumer = policy.consumer_for(request.headers.get("x-api-key"))
    if consumer is None:
        return _deny(request, 401, "unauthorized", "missing or unknown API key")

    # 3. allowlist. 404 and not 403: a caller who is off the allowlist should not
    #    be able to use the gateway to discover what is behind it.
    route: Route | None = policy.match(request.method, path)
    if route is None:
        return _deny(
            request, 404, "blocked-route", f"{path} is not in the allowlist", consumer=consumer.name
        )

    # 4. method
    if request.method not in route.methods:
        return _deny(
            request,
            405,
            "blocked-method",
            f"{request.method} not allowed on {route.id}; allowed: {sorted(route.methods)}",
            consumer=consumer.name,
            route=route.id,
        )

    # 5. acl
    if route.groups and not (route.groups & consumer.groups):
        return _deny(
            request,
            403,
            "forbidden-group",
            f"{consumer.name} is not in {sorted(route.groups)}",
            consumer=consumer.name,
            route=route.id,
        )

    # 6. rate limit
    ok, retry_after = app.state.bucket.take(consumer.name)
    if not ok:
        _audit(
            request,
            {
                "status": 429,
                "decision": "rate-limited",
                "consumer": consumer.name,
                "route": route.id,
                "retry_after_s": retry_after,
            },
        )
        return JSONResponse(
            {
                "error": "rate-limited",
                "detail": f"limit is {limits.rate_per_minute} requests/minute",
            },
            status_code=429,
            headers={"X-Gateway-Decision": "rate-limited", "Retry-After": str(retry_after)},
        )

    body = await _read_body(request, limits.max_request_bytes)
    if body is None:
        return _deny(
            request,
            413,
            "request-too-large",
            f"body exceeds max_request_bytes={limits.max_request_bytes}",
            consumer=consumer.name,
            route=route.id,
        )

    upstream_headers = {k: v for k, v in request.headers.items() if k.lower() not in STRIP_REQUEST}
    url = route.upstream_url + path
    if request.url.query:
        url += "?" + request.url.query

    # 7 + 8. proxy with the policy timeout, cutting the body at the cap as it
    # streams so an oversized response is never fully held in memory.
    started = time.monotonic()
    client: httpx.AsyncClient = app.state.http
    try:
        async with client.stream(
            request.method,
            url,
            headers=upstream_headers,
            content=body or None,
            timeout=limits.upstream_timeout_s,
        ) as upstream:
            chunks: list[bytes] = []
            total = 0
            truncated = False
            async for chunk in upstream.aiter_bytes():
                room = limits.max_response_bytes - total
                if len(chunk) >= room:
                    chunks.append(chunk[:room])
                    total += room
                    truncated = True
                    break
                chunks.append(chunk)
                total += len(chunk)
            payload = b"".join(chunks)
            status = upstream.status_code
            out_headers = {
                k: v for k, v in upstream.headers.items() if k.lower() not in STRIP_RESPONSE
            }
    except httpx.TimeoutException:
        return _deny(
            request,
            504,
            "upstream-timeout",
            f"{route.upstream} did not answer within {limits.upstream_timeout_s}s",
            consumer=consumer.name,
            route=route.id,
        )
    except httpx.HTTPError as exc:
        return _deny(
            request,
            502,
            "upstream-error",
            _redact(f"{type(exc).__name__}: {exc}", secrets),
            consumer=consumer.name,
            route=route.id,
        )

    elapsed_ms = int((time.monotonic() - started) * 1000)
    out_headers["X-Gateway-Decision"] = "allowed"
    out_headers["X-Gateway-Route"] = route.id
    out_headers["X-Gateway-Truncated"] = "true" if truncated else "false"

    _audit(
        request,
        {
            "status": status,
            "decision": "allowed",
            "consumer": consumer.name,
            "route": route.id,
            "request_bytes": len(body or b""),
            "response_bytes": total,
            "truncated": truncated,
            "elapsed_ms": elapsed_ms,
            "request_headers": _safe_headers(request.headers, secrets),
        },
    )
    return Response(content=payload, status_code=status, headers=out_headers)
