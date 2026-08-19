"""The gateway's policy file, checked without starting the gateway.

This is the one place a test reaches across the boundary AGENTS.md draws: the
*tool* must never import `gateway/`, but a test is not the tool, and the
allowlist is exactly the kind of thing that should fail in CI rather than in
production.

Skipped when PyYAML is absent, since it lives in the gateway's container and not
in the tool's stdlib-only dependency set.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML lives in the gateway container")

REPO_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_DIR = REPO_ROOT / "gateway"
sys.path.insert(0, str(GATEWAY_DIR))

from policy import PolicyError, load_policy  # noqa: E402

POLICY_FILE = GATEWAY_DIR / "policy.yml"
RAILWAY_POLICY_FILE = GATEWAY_DIR / "policy.railway.yml"
ENV = {"PROBE_API_KEY": "test-key-for-policy-loading"}


@pytest.fixture
def policy():
    return load_policy(POLICY_FILE, environ=ENV)


# -- what the shipped policy actually says ---------------------------------


def test_the_endpoints_week_three_exploited_are_not_reachable(policy) -> None:
    """The claim this whole repo makes, as an assertion."""
    for path in ("/ftp", "/ftp/coupons_2013.md.bak", "/rest/basket/1", "/api/Users"):
        assert policy.match("GET", path) is None, f"{path} is reachable"


def test_no_route_can_write_real_data(policy) -> None:
    """Every non-GET route has to be one where a wrong request changes nothing."""
    writable = {"/rest/user/login", "/echo"}  # 401 on bad credentials; reflects only
    for route in policy.routes:
        if route.methods - {"GET", "HEAD"}:
            assert route.path in writable, f"{route.id} accepts a write method"


def test_the_shipped_policy_has_a_working_consumer(policy) -> None:
    assert policy.consumer_for(ENV["PROBE_API_KEY"]) is not None
    assert policy.consumer_for("anything-else") is None
    assert policy.consumer_for(None) is None
    assert policy.consumer_for("") is None


def test_limits_are_present_and_sane(policy) -> None:
    limits = policy.limits
    assert limits.rate_per_minute > 0
    assert 0 < limits.upstream_timeout_s <= 30
    assert limits.max_request_bytes < limits.max_response_bytes


def test_a_route_reserved_for_another_group_is_matched_but_not_granted(policy) -> None:
    route = policy.match("GET", "/metrics")
    consumer = policy.consumer_for(ENV["PROBE_API_KEY"])
    assert route is not None and route.id == "metrics"
    assert not (route.groups & consumer.groups), "the 403 case would not be a 403"


def test_public_route_shape_names_its_upstream(policy) -> None:
    """`GET /_gateway/routes` names which backend a route belongs to (docs/adr/0010)

    -- the Allowlist page's lab-app/juice-shop column reads this field.
    """
    published = policy.match("POST", "/echo").public()
    assert published["upstream"] == "lab"
    published = policy.match("GET", "/api/Products").public()
    assert published["upstream"] == "juice-shop"


# -- Railway's policy is the same allowlist, different upstream hostnames --


def test_railway_policy_declares_the_same_routes_as_local(policy) -> None:
    """docs/adr/0010: Railway is meant to have exact allowlist parity with

    local now, not a reduced one -- this is what keeps that a fact instead of
    an assertion made once in a commit message and left to drift.
    """
    railway = load_policy(RAILWAY_POLICY_FILE, environ={**ENV, "PROBE_ADMIN_KEY": "irrelevant"})
    local_ids = {(r.id, r.upstream, frozenset(r.methods)) for r in policy.routes}
    railway_ids = {(r.id, r.upstream, frozenset(r.methods)) for r in railway.routes}
    assert local_ids == railway_ids


def test_railway_policy_uses_railway_internal_hostnames(policy) -> None:
    railway = load_policy(RAILWAY_POLICY_FILE, environ=ENV)
    for route in railway.routes:
        assert route.upstream_url.endswith(".railway.internal:3000") or route.upstream_url.endswith(
            ".railway.internal:8080"
        ), f"{route.id} does not point at a *.railway.internal host: {route.upstream_url!r}"


# -- the loader ------------------------------------------------------------


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "policy.yml"
    path.write_text(body, encoding="utf-8")
    return path


BASE = """
version: 1
limits: {rate_per_minute: 10, upstream_timeout_s: 1, max_request_bytes: 10, max_response_bytes: 20}
consumers: [{name: a, key_env: K, groups: [probe]}]
upstreams: {u: http://u:1}
routes: [{id: r, upstream: u, methods: [GET], path: /r, groups: [probe]}]
"""


def test_a_consumer_with_no_key_is_dropped_not_given_an_empty_one(tmp_path) -> None:
    """An empty key would authenticate a request that sent no header at all."""
    body = BASE.replace(
        "consumers: [{name: a, key_env: K, groups: [probe]}]",
        "consumers: [{name: a, key_env: K, groups: [probe]}, "
        "{name: b, key_env: MISSING, groups: [admin]}]",
    )
    loaded = load_policy(_write(tmp_path, body), environ={"K": "k"})
    assert loaded.consumer_for("") is None
    assert "b (MISSING unset)" in loaded.skipped_consumers


def test_a_policy_where_nobody_has_a_key_is_refused_at_startup(tmp_path) -> None:
    with pytest.raises(PolicyError, match="every request would be 401"):
        load_policy(_write(tmp_path, BASE), environ={})


def test_two_consumers_sharing_a_key_is_refused(tmp_path) -> None:
    body = BASE.replace(
        "consumers: [{name: a, key_env: K, groups: [probe]}]",
        "consumers: [{name: a, key_env: K, groups: [probe]}, "
        "{name: b, key_env: K2, groups: [admin]}]",
    )
    with pytest.raises(PolicyError, match="share a key"):
        load_policy(_write(tmp_path, body), environ={"K": "same", "K2": "same"})


def test_an_unknown_upstream_is_refused(tmp_path) -> None:
    body = BASE.replace("upstream: u", "upstream: nope")
    with pytest.raises(PolicyError, match="unknown upstream"):
        load_policy(_write(tmp_path, body), environ={"K": "k"})


def test_a_route_with_both_path_and_prefix_is_refused(tmp_path) -> None:
    body = BASE.replace("path: /r,", "path: /r, path_prefix: /r/,")
    with pytest.raises(PolicyError, match="exactly one of"):
        load_policy(_write(tmp_path, body), environ={"K": "k"})


def test_a_duplicate_route_id_is_refused(tmp_path) -> None:
    body = BASE.replace(
        "routes: [{id: r, upstream: u, methods: [GET], path: /r, groups: [probe]}]",
        "routes: [{id: r, upstream: u, methods: [GET], path: /r, groups: [probe]}, "
        "{id: r, upstream: u, methods: [GET], path: /r2, groups: [probe]}]",
    )
    with pytest.raises(PolicyError, match="duplicate id"):
        load_policy(_write(tmp_path, body), environ={"K": "k"})


def test_exact_paths_win_over_prefixes_regardless_of_file_order(tmp_path) -> None:
    """Otherwise which route applies depends on how the YAML happens to be sorted."""
    body = BASE.replace(
        "routes: [{id: r, upstream: u, methods: [GET], path: /r, groups: [probe]}]",
        "routes: [{id: wide, upstream: u, methods: [GET], path_prefix: /a/, groups: [probe]}, "
        "{id: exact, upstream: u, methods: [GET], path: /a/b, groups: [probe]}]",
    )
    loaded = load_policy(_write(tmp_path, body), environ={"K": "k"})
    assert loaded.match("GET", "/a/b").id == "exact"
    assert loaded.match("GET", "/a/c").id == "wide"


def test_an_unsupported_version_is_refused(tmp_path) -> None:
    with pytest.raises(PolicyError, match="unsupported policy version"):
        load_policy(_write(tmp_path, BASE.replace("version: 1", "version: 2")), environ={"K": "k"})
