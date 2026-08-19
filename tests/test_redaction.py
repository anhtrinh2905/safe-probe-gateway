"""The deliverable "logs do not store the API key", as a test.

The interesting cases are not the obvious ones. A header allowlist catches
`X-API-Key`. What it does not catch is a key that arrives back in a *response*
body from an application that reflects its input, or one that ends up in a query
string, or one in a field nobody thought about because it was added later.

So the end-to-end assertion here is a grep of the written log for a sentinel
value, after deliberately routing that value through each of those paths.
"""

from __future__ import annotations

import json

from safe_probe.audit import (
    REDACTED_API_KEY,
    REDACTED_EMAIL,
    REDACTED_PASSWORD,
    REDACTED_PHONE,
    REDACTED_TOKEN,
    AuditLog,
    redact_headers,
    redact_query,
    scrub,
)

from .conftest import SENTINEL_KEY

# Not a real credential and not shaped like any particular vendor's -- just long
# enough to trip the "looks like a token" pattern.
FAKE_TOKEN = "NOT-A-REAL-TOKEN-0123456789abcdef"


def test_a_known_secret_is_replaced_wherever_it_appears() -> None:
    assert SENTINEL_KEY not in scrub(f"upstream said: {SENTINEL_KEY} is invalid", (SENTINEL_KEY,))


def test_a_credential_shaped_string_is_caught_even_when_unknown() -> None:
    """The gateway's key is known; a token the application invents is not."""
    assert FAKE_TOKEN not in scrub(f"Authorization: Bearer {FAKE_TOKEN}", ())


def test_sensitive_headers_go_by_name_not_by_value() -> None:
    headers = redact_headers(
        {"X-API-Key": "anything", "Cookie": "session=1", "Accept": "application/json"}, ()
    )
    assert headers["X-API-Key"] == REDACTED_API_KEY
    assert headers["Cookie"] == REDACTED_TOKEN
    assert headers["Accept"] == "application/json"


def test_query_parameters_that_carry_credentials_are_blanked() -> None:
    assert (
        redact_query("q=hello&apikey=abc123&page=2", ())
        == f"q=hello&apikey={REDACTED_API_KEY}&page=2"
    )


# -- week 5: email, phone, password -- tagged by kind, not by a single marker


def test_an_email_address_is_replaced_with_its_own_tag() -> None:
    body = "contact: nguyen.van.a@example.com about the order"
    cleaned = scrub(body, ())
    assert "nguyen.van.a@example.com" not in cleaned
    assert REDACTED_EMAIL in cleaned


def test_a_vn_phone_number_is_replaced_with_its_own_tag() -> None:
    for candidate in ("0912345678", "+84912345678", "091-234-5678"):
        cleaned = scrub(f"gọi số {candidate} để xác nhận", ())
        assert candidate not in cleaned
        assert REDACTED_PHONE in cleaned


def test_a_password_field_value_is_replaced_with_its_own_tag() -> None:
    # Not a real credential -- see FAKE_TOKEN above for why this shape is used
    # instead of something a secret scanner would flag as a plausible finding.
    fake_value = "NOT" + "-A-REAL-PASSWORD-0123456789"
    cleaned = scrub('{"password": "' + fake_value + '"}', ())
    assert fake_value not in cleaned
    assert REDACTED_PASSWORD in cleaned


def test_the_scrubber_reaches_into_nested_structures(tmp_path) -> None:
    log = AuditLog(tmp_path / "a.jsonl", secrets=(SENTINEL_KEY,))
    written = log.write(
        {"nested": {"deep": [{"value": SENTINEL_KEY}]}, "headers": {"x-api-key": SENTINEL_KEY}}
    )
    assert SENTINEL_KEY not in json.dumps(written)


def test_a_field_added_later_is_covered_without_anyone_updating_the_scrubber(tmp_path) -> None:
    """The recursive walk is the point: field-by-field redaction rots."""
    log = AuditLog(tmp_path / "b.jsonl", secrets=(SENTINEL_KEY,))
    written = log.write({"a_field_nobody_anticipated": f"key={SENTINEL_KEY}"})
    assert SENTINEL_KEY not in json.dumps(written)


# -- end to end ------------------------------------------------------------


def test_the_key_never_reaches_the_log_file(make_client, tmp_path) -> None:
    client = make_client()
    client.get("/api/Products")
    client.post("/echo", json_body={"value": "hello"})
    client.get("/blocked")
    client.get("/forbidden")
    client.get("/api/Products", params={"apikey": SENTINEL_KEY})

    contents = (tmp_path / "requests.jsonl").read_text(encoding="utf-8")
    assert contents.strip(), "nothing was logged -- the test would pass vacuously"
    assert SENTINEL_KEY not in contents


def test_it_survives_an_application_that_reflects_the_key_back(make_client, tmp_path) -> None:
    """The stub's /reflect-key returns the credential in its body on purpose."""
    client = make_client()
    result = client.get("/reflect-key")

    assert result.status == 200
    assert SENTINEL_KEY not in result.body_excerpt
    assert SENTINEL_KEY not in (tmp_path / "requests.jsonl").read_text(encoding="utf-8")


def test_the_config_repr_cannot_leak_it_into_a_traceback(make_client) -> None:
    client = make_client()
    assert SENTINEL_KEY not in repr(client.config)
    assert "REDACTED" in repr(client.config)


def test_a_probe_result_is_safe_to_print(make_client) -> None:
    result = make_client().get("/reflect-key")
    assert SENTINEL_KEY not in repr(result)
    assert SENTINEL_KEY not in result.summary()
