"""Run the whole catalogue against the whole allowlist and tabulate the result.

Two things the suite is careful about.

**Where a payload goes is a property of the route, not of the payload.** A search
endpoint takes it in `?q=`; a login endpoint takes it in a JSON field. That
mapping is `INJECTION_POINTS` below and it is written by hand, because guessing
it is how a "safe" tool ends up POSTing to something that writes.

**The allowlist comes from the gateway.** The suite asks `GET /_gateway/routes`
and works from the answer, so a route removed from `policy.yml` disappears from
the suite without anyone editing this file. Routes the consumer's groups exclude
are still probed -- getting the 403 is a result worth recording.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from safe_probe.client import ProbeClient, ProbeResult
from safe_probe.payloads import SAFE_PAYLOADS, Payload, check_safe


@dataclass(frozen=True)
class InjectionPoint:
    """How a payload is carried to one route."""

    where: str  # "query" | "json" | "none"
    field: str = ""
    # Sent alongside the payload so the request is otherwise well-formed. A
    # malformed *everything* would only ever prove the endpoint rejects garbage.
    fixed: dict[str, Any] | None = None


# Hand-written, and deliberately so. Every entry is a claim that sending a
# malformed value here changes nothing that matters.
INJECTION_POINTS: dict[str, InjectionPoint] = {
    # Juice Shop's product search. Reads only.
    "products-search": InjectionPoint("query", "q"),
    # Wrong credentials return 401 and write nothing, so the shape of the
    # credentials is free to be as wrong as we like.
    "login": InjectionPoint("json", "email", fixed={"password": "not-a-real-password"}),
    # lab-app reflects the body, which is what makes "it arrived intact" visible.
    "echo": InjectionPoint("json", "value"),
    # No parameter to abuse; probed once to confirm it is reachable at all.
    "products": InjectionPoint("none"),
    "app-version": InjectionPoint("none"),
    "metrics": InjectionPoint("none"),
    # These exist to exercise limits, not input handling. The suite covers them
    # with fixed arguments rather than the catalogue.
    "slow": InjectionPoint("query", "ms"),
    "big": InjectionPoint("query", "kb"),
    "status": InjectionPoint("none"),
}

# For routes whose point is a limit rather than a payload.
#
# There is no "over the gateway's cap" case here, and that is not an oversight:
# the suite runs with client limits on, so the tool's own 64 KB cap always cuts
# the body first and the gateway's 256 KB cap would never be the thing observed.
# Proving the gateway's cap needs a client that obeys nothing -- curl, in
# scripts/smoke.sh, evidence 12.
LIMIT_CASES: dict[str, list[tuple[str, dict[str, Any]]]] = {
    "slow": [("under-timeout", {"ms": 200}), ("over-timeout", {"ms": 9000})],
    "big": [("under-client-cap", {"kb": 4}), ("over-client-cap", {"kb": 200})],
}


@dataclass
class SuiteCase:
    route_id: str
    method: str
    path: str
    label: str
    payload: Payload | None
    result: ProbeResult


def _first_path(route: dict[str, Any]) -> str:
    if route.get("path"):
        return str(route["path"])
    # A prefix route needs a concrete suffix. 418 is chosen because it cannot be
    # confused with anything the gateway itself returns.
    return str(route["path_prefix"]) + "418"


def run_suite(
    client: ProbeClient,
    payloads: tuple[Payload, ...] = SAFE_PAYLOADS,
    only_route: str | None = None,
) -> list[SuiteCase]:
    published = client.routes()
    cases: list[SuiteCase] = []

    for route in published["routes"]:
        rid = route["id"]
        if only_route and rid != only_route:
            continue
        point = INJECTION_POINTS.get(rid, InjectionPoint("none"))
        path = _first_path(route)
        method = route["methods"][0]

        if rid in LIMIT_CASES:
            for label, params in LIMIT_CASES[rid]:
                cases.append(
                    SuiteCase(
                        rid, method, path, label, None, client.request(method, path, params=params)
                    )
                )
            continue

        if point.where == "none":
            cases.append(
                SuiteCase(rid, method, path, "baseline", None, client.request(method, path))
            )
            continue

        for payload in payloads:
            # Re-checked here rather than trusted from the catalogue: this is the
            # last point before the value reaches a socket.
            check_safe(payload)
            if point.where == "query":
                # A query string cannot carry a list or an object; those payloads
                # are only meaningful against a JSON body.
                if isinstance(payload.value, (list, dict)):
                    continue
                value = "" if payload.value is None else payload.value
                result = client.request(
                    method, path, params={point.field: value}, payload_id=payload.id
                )
            else:
                body = dict(point.fixed or {})
                body[point.field] = payload.value
                result = client.request(method, path, json_body=body, payload_id=payload.id)
            cases.append(SuiteCase(rid, method, path, payload.kind, payload, result))

    return cases


def to_markdown(cases: list[SuiteCase]) -> str:
    """A table a human reads, grouped by route."""
    lines = [
        "| route | case | payload | status | outcome | answered by | bytes | ms |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for case in cases:
        r = case.result
        lines.append(
            f"| `{case.route_id}` | {case.label} | `{case.payload.id if case.payload else '-'}` | "
            f"{r.status if r.status is not None else '-'} | {r.outcome} | {r.answered_by} | "
            f"{r.response_bytes} | {r.elapsed_ms} |"
        )
    return "\n".join(lines)


def to_json(cases: list[SuiteCase]) -> str:
    return json.dumps(
        [
            {
                "route": c.route_id,
                "case": c.label,
                "payload": c.payload.id if c.payload else None,
                "asks": c.payload.asks if c.payload else None,
                "method": c.method,
                "path": c.path,
                "status": c.result.status,
                "outcome": c.result.outcome,
                "answered_by": c.result.answered_by,
                "response_bytes": c.result.response_bytes,
                "truncated": c.result.truncated or c.result.gateway_truncated,
                "elapsed_ms": c.result.elapsed_ms,
                "error": c.result.error,
                "body_excerpt": c.result.body_excerpt[:300],
            }
            for c in cases
        ],
        ensure_ascii=False,
        indent=2,
    )


def tally(cases: list[SuiteCase]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in cases:
        counts[case.result.outcome] = counts.get(case.result.outcome, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
