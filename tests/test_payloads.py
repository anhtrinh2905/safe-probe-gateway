"""The safety contract of the payload catalogue.

The brief says "only safe payloads". This file is what makes that a fact rather
than a claim: if anyone adds an injection string to `SAFE_PAYLOADS`, the suite
goes red before it goes near a network.
"""

from __future__ import annotations

import pytest

from safe_probe.payloads import (
    BY_ID,
    FORBIDDEN_PATTERNS,
    KINDS,
    SAFE_PAYLOADS,
    Payload,
    UnsafePayload,
    check_safe,
    get,
)

# Real attack strings, kept here and nowhere else. Their only job is to prove the
# patterns match something -- a regex that matches nothing would pass the
# catalogue check while protecting nothing.
KNOWN_BAD = [
    ("sql-injection", "' OR 1=1 --"),
    ("sql-injection", "1 UNION SELECT password FROM users"),
    ("xss", "<script>alert(1)</script>"),
    ("xss", "<img src=x onerror=alert(1)>"),
    ("path-traversal", "../../etc/passwd"),
    ("path-traversal", "%2e%2e%2f%2e%2e%2fetc"),
    ("command-injection", "; rm -rf /"),
    ("command-injection", "$(whoami)"),
    ("template-injection", "{{7*7}}"),
    ("jndi", "${jndi:ldap://x/a}"),
    ("xxe", '<!ENTITY xxe SYSTEM "file:///etc/passwd">'),
    ("nosql-operator", '{"$ne": null}'),
    ("header-injection", "value\r\nSet-Cookie: admin=1"),
    ("null-byte", "file.txt%00.png"),
    ("ssrf-url", "http://169.254.169.254/latest/meta-data/"),
]


@pytest.mark.parametrize("payload", SAFE_PAYLOADS, ids=lambda p: p.id)
def test_every_catalogue_payload_is_safe(payload: Payload) -> None:
    check_safe(payload)


@pytest.mark.parametrize("name,text", KNOWN_BAD, ids=[f"{n}:{t[:18]}" for n, t in KNOWN_BAD])
def test_forbidden_patterns_actually_catch_attacks(name: str, text: str) -> None:
    """A pattern that never fires is decoration. Each one has to catch its own."""
    assert FORBIDDEN_PATTERNS[name].search(text), f"{name} failed to match {text!r}"


@pytest.mark.parametrize("name,text", KNOWN_BAD, ids=[f"{n}:{t[:18]}" for n, t in KNOWN_BAD])
def test_check_safe_rejects_a_smuggled_payload(name: str, text: str) -> None:
    with pytest.raises(UnsafePayload):
        check_safe(Payload("smuggled", "special-chars", text, "should never be sent"))


def test_get_revalidates_rather_than_trusting_the_catalogue(monkeypatch) -> None:
    """`get` is the last gate before a payload is used, so it re-checks."""
    monkeypatch.setitem(BY_ID, "poisoned", Payload("poisoned", "special-chars", "' OR 1=1 --", ""))
    with pytest.raises(UnsafePayload):
        get("poisoned")


def test_unknown_payload_id_lists_what_is_available() -> None:
    with pytest.raises(KeyError) as excinfo:
        get("no-such-payload")
    assert "long-1k" in str(excinfo.value)


def test_catalogue_covers_every_kind_the_brief_asks_for() -> None:
    present = {p.kind for p in SAFE_PAYLOADS}
    assert present == set(KINDS), f"missing kinds: {set(KINDS) - present}"


def test_payload_ids_are_unique() -> None:
    assert len(BY_ID) == len(SAFE_PAYLOADS)


def test_nothing_in_the_catalogue_is_big_enough_to_be_a_dos() -> None:
    """ "Long string" means long, not "as much as the process can allocate"."""
    for payload in SAFE_PAYLOADS:
        if isinstance(payload.value, str):
            assert len(payload.value) <= 10_000, payload.id
