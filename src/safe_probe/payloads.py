"""The payload catalogue, and the definition of what makes a payload safe.

The brief allows long strings, special characters, empty values and wrong types,
and forbids anything destructive, anything that reaches the system, and anything
that changes real data. Saying so in a README would be a promise. Putting the
forbidden shapes in `FORBIDDEN_PATTERNS` and having `tests/test_payloads.py`
check every entry against them makes it an invariant: adding an SQL injection
string to this file turns the test suite red.

What these payloads look for is *input handling*, not exploitation. A 10 000
character string, an emoji, a `null` where a string was expected, and an integer
where an e-mail was expected all ask the same question -- does the application
validate, or does it assume? None of them carries a way to make it do something
on the answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Every one of these is a class of payload this repo will not send. The pattern
# is what the test checks; the name is what the failure message says.
FORBIDDEN_PATTERNS: dict[str, re.Pattern[str]] = {
    "sql-injection": re.compile(r"(?i)('\s*(or|and)\s|--\s|\bunion\s+select\b|;\s*drop\b)"),
    "xss": re.compile(r"(?i)(<\s*script|javascript:|onerror\s*=|<\s*iframe)"),
    "path-traversal": re.compile(r"(\.\./|\.\.\\|%2e%2e)"),
    "command-injection": re.compile(
        r"(?i)(;\s*(rm|cat|curl|wget|nc|sh|bash)\b|\$\(|`[^`]+`|\|\s*sh\b)"
    ),
    "template-injection": re.compile(r"(\{\{.+\}\}|\$\{.+\})"),
    "jndi": re.compile(r"(?i)\$\{jndi:"),
    "xxe": re.compile(r"(?i)(<!ENTITY|SYSTEM\s+[\"']file:)"),
    "nosql-operator": re.compile(r"\$(where|ne|gt|lt|regex|in|exists)\b"),
    "header-injection": re.compile(r"[\r\n]\s*(set-cookie|location|host|authorization)\s*:", re.I),
    "null-byte": re.compile(r"(%00|\\x00|\x00)"),
    "ssrf-url": re.compile(r"(?i)\b(file|gopher|dict)://|169\.254\.169\.254"),
}

# Which limit or behaviour a payload is aimed at. Used to group the report.
KINDS = ("long-string", "special-chars", "empty", "wrong-type", "boundary")


@dataclass(frozen=True)
class Payload:
    id: str
    kind: str
    value: Any
    asks: str  # the question this payload puts to the application

    @property
    def as_text(self) -> str:
        """Everything about the payload as one string, for the safety check.

        Both the raw value and its `repr` are included, and both are needed.
        `repr` escapes control characters, so a CRLF header-injection string
        checked only through `repr` reads as the two characters `\\r` and slips
        past a `[\\r\\n]` pattern. The raw value alone would in turn miss a
        payload that spells an escape out literally. Found by
        tests/test_payloads.py, not by reading.
        """
        raw = self.value if isinstance(self.value, str) else ""
        return f"{self.id} {raw} {self.value!r}"


SAFE_PAYLOADS: tuple[Payload, ...] = (
    # -- long strings: does the application bound what it accepts? ----------
    Payload("long-1k", "long-string", "A" * 1024, "1 KB in a field that expects a word"),
    Payload("long-10k", "long-string", "A" * 10_000, "10 KB, still under the gateway's 64 KB cap"),
    Payload(
        "long-unicode-2k",
        "long-string",
        "é" * 2_000,
        "2 000 characters but 4 000 bytes -- length in chars is not length in bytes",
    ),
    # -- special characters: does it escape, or does it concatenate? --------
    Payload(
        "special-ascii",
        "special-chars",
        "!@#$%^&*()_+-=[]{}|:,.<>/?~",
        "punctuation that HTML, JSON and URLs each treat differently",
    ),
    Payload(
        "special-quotes", "special-chars", "\"'", "quote characters on their own, carrying nothing"
    ),
    Payload(
        "special-whitespace",
        "special-chars",
        " \t\n\r ",
        "whitespace only -- is it trimmed or stored?",
    ),
    Payload(
        "unicode-emoji", "special-chars", "日本語 🎉 ñ Ω", "multi-byte and astral-plane characters"
    ),
    Payload("unicode-rtl", "special-chars", "مرحبا שלום", "right-to-left text"),
    Payload(
        "unicode-zero-width",
        "special-chars",
        "a​b﻿c",
        "invisible characters that survive a length check",
    ),
    Payload(
        "unicode-combining",
        "special-chars",
        "é" * 100,
        "combining marks -- normalisation, not just encoding",
    ),
    # -- empty: is the field actually required? -----------------------------
    Payload("empty-string", "empty", "", "an empty string where a value is expected"),
    Payload("null", "empty", None, "JSON null rather than a missing key"),
    Payload("whitespace-only", "empty", "   ", "present but meaningless"),
    # -- wrong type: is the input validated or coerced? ---------------------
    Payload("wrong-type-int", "wrong-type", 12345, "an integer where a string is expected"),
    Payload("wrong-type-float", "wrong-type", 1.5, "a float where a string is expected"),
    Payload("wrong-type-bool", "wrong-type", True, "a boolean where a string is expected"),
    Payload("wrong-type-list", "wrong-type", ["a", "b"], "an array where a scalar is expected"),
    Payload(
        "wrong-type-object",
        "wrong-type",
        {"nested": "value"},
        "an object where a scalar is expected",
    ),
    # -- boundaries: arithmetic, not exploitation ---------------------------
    Payload("boundary-zero", "boundary", 0, "zero, which is falsy in most languages"),
    Payload("boundary-negative", "boundary", -1, "a negative where a count is expected"),
    Payload("boundary-int64", "boundary", 2**63, "one past a signed 64-bit integer"),
    Payload("boundary-float-max", "boundary", 1e308, "near the top of a double"),
)

BY_ID: dict[str, Payload] = {p.id: p for p in SAFE_PAYLOADS}


class UnsafePayload(ValueError):
    """A payload matched a forbidden pattern. Never reaches the network."""


def check_safe(payload: Payload) -> None:
    """Raise if a payload looks like an attack rather than a malformed input.

    Called by the suite and by the LLM planning layer, so that a payload id is
    re-validated at use time and not only when the catalogue is written.
    """
    text = payload.as_text
    for name, pattern in FORBIDDEN_PATTERNS.items():
        if pattern.search(text):
            raise UnsafePayload(f"payload {payload.id!r} matches forbidden pattern {name!r}")


def get(payload_id: str) -> Payload:
    try:
        payload = BY_ID[payload_id]
    except KeyError:
        raise KeyError(
            f"unknown payload {payload_id!r}; known ids: {', '.join(sorted(BY_ID))}"
        ) from None
    check_safe(payload)
    return payload
