"""What the tool does with each answer the gateway can give it.

The deliverable says the tool must handle timeout and connection errors. The
assertion that matters is not that it survives them, but that it reports them as
*distinguishable outcomes* -- a run that cannot tell "the gateway refused this"
from "nothing was listening" is not evidence of anything.
"""

from __future__ import annotations

import json

import pytest

from safe_probe.client import ProbeClient, ScopeViolation
from safe_probe.config import Config

from .conftest import SENTINEL_KEY

# -- outcomes ---------------------------------------------------------------


@pytest.mark.parametrize(
    "path,status,outcome,answered_by",
    [
        ("/allowed", 200, "ok", "upstream"),
        ("/blocked", 404, "blocked", "gateway"),
        ("/forbidden", 403, "forbidden", "gateway"),
        ("/toolarge", 413, "too_large", "gateway"),
        ("/ratelimited", 429, "rate_limited", "gateway"),
        ("/upstream-timeout", 504, "upstream_timeout", "gateway"),
    ],
)
def test_each_gateway_decision_becomes_its_own_outcome(
    make_client, path: str, status: int, outcome: str, answered_by: str
) -> None:
    result = make_client().get(path)
    assert (result.status, result.outcome, result.answered_by) == (status, outcome, answered_by)


def test_a_404_from_the_gateway_is_not_confused_with_a_404_from_the_app(make_client) -> None:
    """Both are 404. Only the decision header tells them apart, which is why the
    gateway sets one on every refusal."""
    blocked = make_client().get("/blocked")
    assert blocked.decision == "blocked-route"
    assert blocked.answered_by == "gateway"


def test_a_wrong_key_is_reported_as_unauthorized(make_client) -> None:
    result = make_client().get("/allowed", api_key="not-the-key")
    assert (result.status, result.outcome) == (401, "unauthorized")


# -- failures that never reach a response -----------------------------------


def test_a_timeout_is_an_outcome_not_an_exception(make_client) -> None:
    result = make_client(timeout_s=0.3).get("/slow")  # the stub sleeps 2s
    assert result.outcome == "timeout"
    assert result.status is None
    assert "0.3" in result.error


def test_a_refused_connection_is_an_outcome_not_an_exception(tmp_path) -> None:
    # Port 1 is reserved and nothing will be listening on it.
    config = Config(
        gateway_url="http://127.0.0.1:1", api_key=SENTINEL_KEY, log_path=tmp_path / "l.jsonl"
    )
    result = ProbeClient(config).get("/allowed")
    assert result.outcome == "connection_error"
    assert result.status is None
    assert result.error


def test_an_unresolvable_host_is_a_connection_error_too(tmp_path) -> None:
    config = Config(
        gateway_url="http://gateway.invalid:8000",
        api_key=SENTINEL_KEY,
        log_path=tmp_path / "l.jsonl",
    )
    assert ProbeClient(config).get("/allowed").outcome == "connection_error"


def test_every_failure_is_still_logged(make_client, tmp_path) -> None:
    """A run that fails silently is worse than one that fails loudly."""
    make_client(timeout_s=0.3).get("/slow")
    lines = (tmp_path / "requests.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[-1])["outcome"] == "timeout"


# -- addressing -------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "//evil.example/x",  # network-path reference
        "http://evil.example/x",  # absolute URL
        "evil.example/x",  # no leading slash
        "",
    ],
)
def test_nothing_but_the_gateway_can_be_addressed(make_client, path: str) -> None:
    result = make_client().get(path)
    assert result.outcome == "scope_violation"
    assert result.status is None


def test_a_scope_violation_is_recorded_rather_than_swallowed(make_client, tmp_path) -> None:
    make_client().get("//evil.example/x")
    entry = json.loads((tmp_path / "requests.jsonl").read_text().strip().splitlines()[-1])
    assert entry["outcome"] == "scope_violation"
    assert "evil.example" in entry["error"]


def test_the_scope_check_is_reachable_directly(make_client) -> None:
    with pytest.raises(ScopeViolation):
        make_client()._build_url("//evil.example/x", None)


# -- limits -----------------------------------------------------------------


def test_the_client_cap_truncates_and_says_so(make_client) -> None:
    result = make_client(max_response_bytes=1000).get("/big")  # stub returns 100 KB
    assert (result.response_bytes, result.truncated) == (1000, True)
    assert result.gateway_truncated is False


def test_turning_off_client_limits_lets_the_whole_body_through(make_client) -> None:
    result = make_client(max_response_bytes=1000, client_limits=False).get("/big")
    assert result.response_bytes == 100_000


def test_an_oversized_body_is_refused_before_it_is_sent(make_client) -> None:
    result = make_client(max_request_bytes=100).post("/echo", json_body={"v": "x" * 500})
    assert result.outcome == "refused_by_client"
    assert result.status is None
    assert result.request_bytes == 0


def test_with_client_limits_off_the_gateway_gets_to_answer(make_client) -> None:
    """The flag that makes the report honest: no client-side refusal, so whatever
    comes back came from the other side of the wire."""
    result = make_client(max_request_bytes=100, client_limits=False).post(
        "/echo", json_body={"v": "x" * 500}
    )
    assert result.status == 200
    assert result.answered_by == "upstream"


# -- the allowlist ----------------------------------------------------------


def test_the_allowlist_is_read_from_the_gateway(make_client) -> None:
    published = make_client().routes()
    assert [r["id"] for r in published["routes"]] == ["echo", "products", "metrics"]
    assert published["consumer"] == "agent-tool"


def test_reading_the_allowlist_fails_loudly_when_the_key_is_wrong(tmp_path, stub_gateway) -> None:
    config = Config(gateway_url=stub_gateway, api_key="wrong-key", log_path=tmp_path / "l.jsonl")
    with pytest.raises(RuntimeError, match="could not read the allowlist"):
        ProbeClient(config).routes()
