"""The probing tool: send one request, get one typed result back.

Two properties this module is built around.

**It cannot address anything but the gateway.** A path is joined onto the
configured gateway URL and the result is re-parsed and checked before it is
sent. The check is after construction rather than a pattern match on the input,
because it is the resolved host that matters -- `//evil.example/x` and
`/../..//evil.example` both look like paths. This is the same shape as week 3's
`_build_url`, kept for defence in depth, not because it is the boundary. The
boundary is that the targets publish no ports at all.

**Nothing raises.** Timeouts, refused connections, gateway denials and upstream
errors all come back as a `ProbeResult` with an `outcome`. A tool whose job is
to provoke failures should not treat failure as exceptional; the caller wants to
record a 429 the same way it records a 200. The one exception is a
misconfiguration (no API key), which is raised at construction, before anything
is sent.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

from safe_probe.audit import AuditLog, redact_headers, redact_query, scrub
from safe_probe.config import BODY_EXCERPT_CHARS, Config
from safe_probe.limits import ClientLimitExceeded, TokenBucket, check_request_size, read_capped

USER_AGENT = "safe-probe/0.1 (week4 api gateway exercise)"

# Gateway decision header -> outcome. Anything the gateway refuses says so in
# `X-Gateway-Decision`, which is what lets the tool tell "the gateway blocked
# this" apart from "the application itself returned 404".
GATEWAY_OUTCOMES = {
    "unauthorized": "unauthorized",
    "blocked-route": "blocked",
    "blocked-method": "blocked_method",
    "forbidden-group": "forbidden",
    "rate-limited": "rate_limited",
    "request-too-large": "too_large",
    "upstream-timeout": "upstream_timeout",
    "upstream-error": "upstream_error",
}


@dataclass(frozen=True)
class ProbeResult:
    """One request's outcome. Safe to print: it never holds a credential."""

    method: str
    path: str
    query: str
    outcome: str
    status: int | None
    answered_by: str  # gateway | upstream | none
    decision: str
    route: str
    request_bytes: int
    response_bytes: int
    truncated: bool
    gateway_truncated: bool
    elapsed_ms: int
    waited_s: float
    body_excerpt: str
    error: str = ""
    payload_id: str = ""
    # The whole body, for the one caller that needs it (`routes`). Never logged
    # and never printed -- `_log` drops it, so a 256 KB response cannot end up
    # in data/ just because someone added a field to the record.
    full_body: str = field(default="", repr=False, compare=False)

    @property
    def ok(self) -> bool:
        return self.outcome == "ok"

    def summary(self) -> str:
        status = self.status if self.status is not None else "-"
        mark = {"ok": "ok  ", "blocked": "block"}.get(self.outcome, "    ")
        return (
            f"{mark:5s} {self.method:4s} {self.path:38s} {str(status):>4} "
            f"{self.outcome:<18s} {self.response_bytes:>7}B {self.elapsed_ms:>5}ms"
        )


def _lower(headers: Any) -> dict[str, str]:
    """Response headers keyed by lower-case name.

    HTTP header names are case-insensitive and uvicorn sends them lower-case,
    but `dict(response.headers)` produces an ordinary case-sensitive dict. Every
    gateway decision is carried in a header, so getting this wrong silently
    turns "the gateway blocked it" into "the application returned 403".
    """
    return {str(k).lower(): v for k, v in dict(headers).items()}


class ScopeViolation(RuntimeError):
    """A path that would resolve off the gateway. Refused before sending."""


class ProbeClient:
    def __init__(self, config: Config, audit: AuditLog | None = None) -> None:
        self.config = config
        parts = urllib.parse.urlsplit(config.gateway_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(f"GATEWAY_URL is not a usable URL: {config.gateway_url!r}")
        self._scheme, self._netloc = parts.scheme, parts.netloc
        self._bucket = TokenBucket(config.rate_per_minute)
        self.audit = audit or AuditLog(config.log_path, secrets=(config.api_key,))
        self._routes: dict[str, Any] | None = None

    # -- addressing ---------------------------------------------------------

    def _build_url(self, path: str, params: dict[str, Any] | None) -> tuple[str, str]:
        if not isinstance(path, str) or not path.startswith("/"):
            raise ScopeViolation(f"path must begin with '/', got {path!r}")
        # A path beginning with '//' is a network-path reference: urlsplit would
        # read what follows as a host. Rejected outright rather than normalised.
        if path.startswith("//"):
            raise ScopeViolation(f"refused: {path!r} is a network-path reference")

        url = self.config.gateway_url + path
        if params:
            joiner = "&" if "?" in url else "?"
            url += joiner + urllib.parse.urlencode(params, doseq=True)

        parts = urllib.parse.urlsplit(url)
        if parts.scheme != self._scheme or parts.netloc != self._netloc:
            raise ScopeViolation(f"refused: {url!r} resolves to host {parts.netloc!r}")
        return url, parts.query

    # -- the allowlist, as published by the gateway -------------------------

    def routes(self, refresh: bool = False) -> dict[str, Any]:
        """Ask the gateway what it allows.

        The tool does not carry its own copy of the allowlist. It can guess
        wrong, and being told 404 by the gateway is the correct way to find out.
        """
        if self._routes is None or refresh:
            result = self.request("GET", "/_gateway/routes")
            if not result.ok:
                raise RuntimeError(
                    f"could not read the allowlist: {result.outcome} {result.status} "
                    f"{result.error or result.body_excerpt[:200]}"
                )
            self._routes = json.loads(result.full_body)
        return self._routes

    # -- the request --------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        raw_body: bytes | None = None,
        headers: dict[str, str] | None = None,
        payload_id: str = "",
        api_key: str | None = None,
    ) -> ProbeResult:
        cfg = self.config
        method = method.upper()
        waited = 0.0

        def refused(reason: str, outcome: str = "refused_by_client") -> ProbeResult:
            result = ProbeResult(
                method=method,
                path=path,
                query="",
                outcome=outcome,
                status=None,
                answered_by="none",
                decision="",
                route="",
                request_bytes=0,
                response_bytes=0,
                truncated=False,
                gateway_truncated=False,
                elapsed_ms=0,
                waited_s=waited,
                body_excerpt="",
                error=reason,
                payload_id=payload_id,
            )
            self._log(result)
            return result

        try:
            url, query = self._build_url(path, params)
        except ScopeViolation as exc:
            return refused(str(exc), outcome="scope_violation")

        body = raw_body
        request_headers = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        body = body or None

        if cfg.client_limits:
            try:
                check_request_size(body or b"", cfg.max_request_bytes)
                waited = self._bucket.acquire(cfg.max_wait_s)
            except ClientLimitExceeded as exc:
                return refused(str(exc))

        # The credential is applied last so that nothing a caller (or the LLM
        # planning layer) supplies can replace or read it. `api_key` is an
        # explicit argument, used only by the wrong-key demonstration.
        request_headers["User-Agent"] = USER_AGENT
        request_headers["X-API-Key"] = cfg.api_key if api_key is None else api_key

        # With client limits off, read whatever arrives: the point of that flag is
        # to let the *gateway's* cap be the one observed.
        read_limit = cfg.max_response_bytes if cfg.client_limits else 10_000_000

        req = urllib.request.Request(url, data=body, method=method, headers=request_headers)
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
                raw, truncated = read_capped(resp, read_limit)
                status, resp_headers = resp.status, _lower(resp.headers)
        except urllib.error.HTTPError as exc:
            # An HTTPError *is* the response. Every gateway denial arrives here.
            with exc:
                raw, truncated = read_capped(exc, read_limit)
                status, resp_headers = exc.code, _lower(exc.headers or {})
        except TimeoutError:
            return self._finish_error(
                method,
                path,
                query,
                "timeout",
                f"no response within {cfg.timeout_s}s (client-side timeout)",
                started,
                waited,
                len(body or b""),
                payload_id,
            )
        except urllib.error.URLError as exc:
            reason = exc.reason
            outcome = "timeout" if isinstance(reason, TimeoutError) else "connection_error"
            return self._finish_error(
                method,
                path,
                query,
                outcome,
                f"{type(reason).__name__}: {reason}",
                started,
                waited,
                len(body or b""),
                payload_id,
            )
        except OSError as exc:
            return self._finish_error(
                method,
                path,
                query,
                "connection_error",
                f"{type(exc).__name__}: {exc}",
                started,
                waited,
                len(body or b""),
                payload_id,
            )

        elapsed_ms = int((time.monotonic() - started) * 1000)
        decision = resp_headers.get("x-gateway-decision", "")
        outcome = self._outcome(status, decision)
        text = raw.decode("utf-8", errors="replace")

        result = ProbeResult(
            method=method,
            path=path,
            query=query,
            outcome=outcome,
            status=status,
            answered_by="upstream"
            if decision == "allowed"
            else "gateway"
            if decision
            else "unknown",
            decision=decision,
            route=resp_headers.get("x-gateway-route", ""),
            request_bytes=len(body or b""),
            response_bytes=len(raw),
            truncated=truncated,
            gateway_truncated=resp_headers.get("x-gateway-truncated") == "true",
            elapsed_ms=elapsed_ms,
            waited_s=round(waited, 2),
            body_excerpt=scrub(text[:BODY_EXCERPT_CHARS], (cfg.api_key,)),
            payload_id=payload_id,
            full_body=scrub(text, (cfg.api_key,)),
        )
        self._log(result, resp_headers)
        return result

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _outcome(status: int, decision: str) -> str:
        if decision and decision != "allowed":
            return GATEWAY_OUTCOMES.get(decision, "gateway_denied")
        if 200 <= status < 300:
            return "ok"
        if 300 <= status < 400:
            return "redirect"
        if status == 429:
            return "rate_limited"
        if 400 <= status < 500:
            return "upstream_client_error"
        return "upstream_server_error"

    def _finish_error(
        self,
        method: str,
        path: str,
        query: str,
        outcome: str,
        error: str,
        started: float,
        waited: float,
        request_bytes: int,
        payload_id: str,
    ) -> ProbeResult:
        result = ProbeResult(
            method=method,
            path=path,
            query=query,
            outcome=outcome,
            status=None,
            answered_by="none",
            decision="",
            route="",
            request_bytes=request_bytes,
            response_bytes=0,
            truncated=False,
            gateway_truncated=False,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            waited_s=round(waited, 2),
            body_excerpt="",
            error=error,
            payload_id=payload_id,
        )
        self._log(result)
        return result

    def _log(self, result: ProbeResult, resp_headers: dict[str, str] | None = None) -> None:
        record: dict[str, Any] = asdict(result)
        record.pop("full_body", None)
        record["query"] = redact_query(result.query, (self.config.api_key,))
        record["gateway_url"] = self.config.gateway_url
        if resp_headers:
            record["response_headers"] = redact_headers(resp_headers, (self.config.api_key,))
        self.audit.write(record)

    # -- convenience --------------------------------------------------------

    def get(self, path: str, **kwargs: Any) -> ProbeResult:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> ProbeResult:
        return self.request("POST", path, **kwargs)
