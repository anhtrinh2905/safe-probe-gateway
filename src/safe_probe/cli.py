"""Command line for the tool. One subcommand per thing the brief asks for.

    routes    what the gateway says is allowed
    get       a GET, optionally with a payload in a query parameter
    post      a POST with a safe payload in a JSON body
    suite     the whole catalogue against the whole allowlist
    plan      the LLM proposes, the tool sends, the gateway decides

`--no-client-limits` turns off the tool's own rate limit and size cap. It exists
so a report can show that removing every client-side control changes nothing
about what the gateway allows. It is the honest way to demonstrate which layer
is load-bearing.
"""

from __future__ import annotations

import argparse
import json
import sys

from safe_probe import payloads as payload_mod
from safe_probe.audit import AuditLog
from safe_probe.client import ProbeClient
from safe_probe.config import REPO_ROOT, Config, ConfigError
from safe_probe.suite import run_suite, tally, to_json, to_markdown


def _client(args: argparse.Namespace) -> ProbeClient:
    config = Config.from_env(
        client_limits=not args.no_client_limits,
        timeout_s=args.timeout,
        rate_per_minute=args.rate,
        max_response_bytes=args.max_response_bytes,
    )
    return ProbeClient(config, audit=AuditLog(config.log_path, secrets=(config.api_key,)))


def _print_result(result, verbose: bool) -> None:
    print(result.summary())
    if result.error:
        print(f"      error: {result.error}")
    if result.decision and result.decision != "allowed":
        print(f"      gateway decision: {result.decision}")
    if result.gateway_truncated:
        print("      gateway truncated the response at its cap")
    elif result.truncated:
        print("      the tool truncated the response at its own cap")
    if verbose and result.body_excerpt:
        print("      ---")
        for line in result.body_excerpt.splitlines()[:12]:
            print(f"      {line[:160]}")


def cmd_routes(args: argparse.Namespace) -> int:
    client = _client(args)
    published = client.routes()
    limits = published["limits"]
    print(f"consumer: {published['consumer']}  groups: {', '.join(published['groups'])}")
    print(
        f"gateway limits: {limits['rate_per_minute']}/min, "
        f"{limits['upstream_timeout_s']}s upstream timeout, "
        f"{limits['max_request_bytes']}B request, {limits['max_response_bytes']}B response"
    )
    print()
    for route in published["routes"]:
        target = route["path"] or route["path_prefix"] + "*"
        allowed = (
            ""
            if not route["groups"] or set(route["groups"]) & set(published["groups"])
            else "  [403 for you]"
        )
        print(f"  {route['id']:<16} {','.join(route['methods']):<8} {target}{allowed}")
    print()
    print("Anything not listed is 404. See gateway/policy.yml for what was left out and why.")
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    client = _client(args)
    params = None
    if args.payload:
        payload = payload_mod.get(args.payload)
        value = "" if payload.value is None else payload.value
        params = {args.param: value if not isinstance(value, (list, dict)) else json.dumps(value)}
    elif args.param_value:
        params = {args.param: args.param_value}
    result = client.request(
        "GET",
        args.path,
        params=params,
        payload_id=args.payload or "",
        api_key="deliberately-wrong-key" if args.wrong_key else None,
    )
    _print_result(result, args.verbose)
    return 0 if result.ok else 1


def cmd_post(args: argparse.Namespace) -> int:
    client = _client(args)
    body: dict[str, object] = {}
    if args.field_value:
        for pair in args.field_value:
            name, _, value = pair.partition("=")
            body[name] = value
    if args.payload:
        payload = payload_mod.get(args.payload)
        body[args.field] = payload.value
    result = client.request(
        "POST",
        args.path,
        json_body=body,
        payload_id=args.payload or "",
        api_key="deliberately-wrong-key" if args.wrong_key else None,
    )
    _print_result(result, args.verbose)
    return 0 if result.ok else 1


def cmd_payloads(args: argparse.Namespace) -> int:
    for payload in payload_mod.SAFE_PAYLOADS:
        payload_mod.check_safe(payload)
        shown = repr(payload.value)
        if len(shown) > 46:
            shown = shown[:43] + "..."
        print(f"  {payload.id:<20} {payload.kind:<14} {shown:<48} {payload.asks}")
    print()
    print(
        f"  {len(payload_mod.SAFE_PAYLOADS)} payloads, all checked against "
        f"{len(payload_mod.FORBIDDEN_PATTERNS)} forbidden patterns: "
        f"{', '.join(sorted(payload_mod.FORBIDDEN_PATTERNS))}"
    )
    return 0


def cmd_suite(args: argparse.Namespace) -> int:
    client = _client(args)
    cases = run_suite(client, only_route=args.route)
    for case in cases:
        print(
            f"  {case.route_id:<16} {case.label:<16} "
            f"{case.payload.id if case.payload else '-':<20} {case.result.summary()}"
        )
    print()
    counts = tally(cases)
    print("  " + "  ".join(f"{k}={v}" for k, v in counts.items()))

    out_md = REPO_ROOT / "reports" / "suite-results.md"
    out_json = REPO_ROOT / "data" / "probe" / "suite.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(
        "# Kết quả suite\n\n"
        "Sinh bởi `probe suite`. Đừng sửa tay — chạy lại là mất.\n\n"
        + "  ".join(f"`{k}={v}`" for k, v in counts.items())
        + "\n\n"
        + to_markdown(cases)
        + "\n",
        encoding="utf-8",
    )
    out_json.write_text(to_json(cases), encoding="utf-8")
    print(f"\n  wrote {out_md.relative_to(REPO_ROOT)} and {out_json.relative_to(REPO_ROOT)}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    from safe_probe.llm import LLMError
    from safe_probe.plan import run_plan, summarise

    client = _client(args)
    try:
        run = run_plan(client, goal=args.goal, rounds=args.rounds)
    except LLMError as exc:
        print(f"LLM layer unavailable: {exc}", file=sys.stderr)
        return 2
    print(summarise(run))
    out = REPO_ROOT / "data" / "llm" / "plan-run.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(run.to_json(), encoding="utf-8")
    print(f"\n  wrote {out.relative_to(REPO_ROOT)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="probe",
        description="Send safe test requests through the API gateway.",
    )
    parser.add_argument(
        "--timeout", type=float, default=None, help="client-side timeout in seconds"
    )
    parser.add_argument("--rate", type=int, default=None, help="client-side requests per minute")
    parser.add_argument("--max-response-bytes", type=int, default=None)
    parser.add_argument(
        "--no-client-limits",
        action="store_true",
        help="turn off the tool's own rate limit and size cap, leaving only the gateway",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="show the response excerpt")

    # -v is accepted both before and after the subcommand: typing it at the end
    # is what everyone does, and argparse does not allow that by default.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true", help=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("routes", help="what the gateway allows", parents=[common])
    p.set_defaults(func=cmd_routes)

    p = sub.add_parser("payloads", parents=[common], help="the safe payload catalogue")
    p.set_defaults(func=cmd_payloads)

    p = sub.add_parser("get", parents=[common], help="send a GET")
    p.add_argument("path")
    p.add_argument("--param", default="q", help="query parameter to carry the payload")
    p.add_argument("--payload", help="payload id from `probe payloads`")
    p.add_argument("--param-value", help="a literal value instead of a catalogue payload")
    p.add_argument("--wrong-key", action="store_true", help="send a bad API key on purpose")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("post", parents=[common], help="send a POST with a JSON body")
    p.add_argument("path")
    p.add_argument("--field", default="value", help="JSON field to carry the payload")
    p.add_argument("--payload", help="payload id from `probe payloads`")
    p.add_argument("--field-value", action="append", help="extra name=value JSON fields")
    p.add_argument("--wrong-key", action="store_true", help="send a bad API key on purpose")
    p.set_defaults(func=cmd_post)

    p = sub.add_parser(
        "suite", parents=[common], help="the whole catalogue against the whole allowlist"
    )
    p.add_argument("--route", help="limit to one route id")
    p.set_defaults(func=cmd_suite)

    p = sub.add_parser(
        "plan", parents=[common], help="the LLM proposes probes, the tool sends them"
    )
    p.add_argument("--goal", default="input validation on the allowlisted endpoints")
    p.add_argument("--rounds", type=int, default=2)
    p.set_defaults(func=cmd_plan)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
