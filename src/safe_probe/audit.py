"""The request log, and the one place that decides what may be written to it.

Redaction lives at the sink, not at the call sites. A call site that has to
remember to redact is a call site that will eventually forget, and the failure
is silent -- the log looks fine until someone greps it. So `AuditLog.write` is
the only function that opens the file, and it scrubs everything on the way
through, including fields it does not recognise.

`tests/test_redaction.py` runs a probe with a sentinel key and greps the result.
That test is the actual deliverable; this module is how it passes.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Kept for anything that still wants a generic marker (e.g. a header whose
# name we recognise as sensitive but cannot classify further). Every value or
# shape we *can* name gets its own tag below instead -- week 5 asks for that
# specificity explicitly ("nguyen.van.a@example.com" -> "[REDACTED_EMAIL]", not
# a marker that could mean anything).
REDACTED = "[REDACTED]"
REDACTED_EMAIL = "[REDACTED_EMAIL]"
REDACTED_PHONE = "[REDACTED_PHONE]"
REDACTED_TOKEN = "[REDACTED_TOKEN]"
REDACTED_API_KEY = "[REDACTED_API_KEY]"
REDACTED_PASSWORD = "[REDACTED_PASSWORD]"
REDACTED_PII = "[REDACTED_PII]"

# Matched case-insensitively against header names. Tag chosen by name, not by
# content -- a header is sensitive because of what it is, not what it says.
SENSITIVE_HEADERS = frozenset(
    {"x-api-key", "authorization", "cookie", "set-cookie", "proxy-authorization"}
)
HEADER_TAGS: dict[str, str] = {
    "x-api-key": REDACTED_API_KEY,
    "authorization": REDACTED_TOKEN,
    "cookie": REDACTED_TOKEN,
    "set-cookie": REDACTED_TOKEN,
    "proxy-authorization": REDACTED_TOKEN,
}

# Matched against query-string parameter names, same reasoning as headers.
SENSITIVE_QUERY = frozenset({"apikey", "api_key", "key", "token", "password", "secret", "email"})
QUERY_TAGS: dict[str, str] = {
    "apikey": REDACTED_API_KEY,
    "api_key": REDACTED_API_KEY,
    "key": REDACTED_API_KEY,
    "token": REDACTED_TOKEN,
    "secret": REDACTED_TOKEN,
    "password": REDACTED_PASSWORD,
    "email": REDACTED_EMAIL,
}

# -- content-shaped patterns --------------------------------------------------
#
# Everything below matches on the *shape* of a value, not on knowing it in
# advance -- the point of week 5 is that a log must be safe even when the
# secret or PII was never passed in as a known value (an upstream reflecting
# it back, a user typing it into a free-text goal, ...).

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# VN mobile/landline shape: a leading 0 or +84 followed by exactly nine more
# digits, optionally grouped with spaces/dots/dashes (e.g. "091-234-5678").
# Bounded on both sides so it does not eat into a longer digit run (an id, a
# byte count) that merely starts with the same prefix.
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+84|0)(?:[\s.-]?\d){9}(?!\d)")

# Catches a credential that ended up somewhere unexpected -- an upstream error
# message, a reflected body from /echo -- even when the exact value is unknown.
# The separator is optional because `Bearer <token>` has none -- with `[:=]`
# required, the single most common way a credential appears in a log went
# unmatched. Found by tests/test_redaction.py, not by reading.
SECRET_SHAPED = re.compile(
    r"(?i)\b(api[-_]?key|authorization|bearer|token)\b\s*[:=]?\s*[\"']?([A-Za-z0-9._\-]{16,})"
)

# A password field's *value*, not the word "password" alone -- so prose that
# merely mentions a password is left alone. The optional quote right after the
# keyword is for JSON's `"password":` -- without it the closing quote of the
# key sits between the word and the colon and the match never starts.
PASSWORD_SHAPED = re.compile(
    r'(?i)\b(password|passwd|pwd)\b["\']?\s*[:=]\s*["\']?([^\s"\',}]{3,})'
)

# Generic "shaped like a personal identifier" catch-all for the one bullet in
# the brief that names no concrete pattern: a run of digits the length of a
# card number or a VN national id (CMND: 9, CCCD: 12), not already consumed by
# the phone pattern above. Not exhaustive -- see docs/adr/0006 for why that is
# an accepted gap rather than an oversight.
PII_SHAPED = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}\d(?!\d)|(?<!\d)\d{9}(?!\d)|(?<!\d)\d{12}(?!\d)")


def _tag_secret_shaped(match: re.Match[str]) -> str:
    keyword = match.group(1).lower()
    tag = REDACTED_API_KEY if "key" in keyword else REDACTED_TOKEN
    return f"{match.group(1)}: {tag}"


def scrub(value: str, secrets: Iterable[str]) -> str:
    """Blank known credentials, then anything shaped like a secret or PII.

    Order matters: specific patterns (email, phone, a named password field,
    a named token/key) run before the generic digit-run pattern, so a phone
    number is tagged `[REDACTED_PHONE]` rather than falling through to the
    less informative `[REDACTED_PII]`.
    """
    for secret in secrets:
        if secret and secret in value:
            value = value.replace(secret, REDACTED_API_KEY)
    value = EMAIL_PATTERN.sub(REDACTED_EMAIL, value)
    # Field-labeled patterns (password=..., api_key/token/bearer ...) run
    # before the unlabeled shape patterns below -- a password value that
    # happens to be all digits must not fall through to the phone/PII guess.
    value = PASSWORD_SHAPED.sub(lambda m: f"{m.group(1)}: {REDACTED_PASSWORD}", value)
    value = SECRET_SHAPED.sub(_tag_secret_shaped, value)
    value = PHONE_PATTERN.sub(REDACTED_PHONE, value)
    value = PII_SHAPED.sub(REDACTED_PII, value)
    return value


def redact_headers(headers: Mapping[str, str], secrets: Iterable[str]) -> dict[str, str]:
    return {
        name: (HEADER_TAGS.get(name.lower(), REDACTED) if name.lower() in SENSITIVE_HEADERS
               else scrub(value, secrets))
        for name, value in headers.items()
    }


def redact_query(query: str, secrets: Iterable[str]) -> str:
    if not query:
        return query
    parts = []
    for pair in query.split("&"):
        name, sep, value = pair.partition("=")
        if name.lower() in SENSITIVE_QUERY:
            parts.append(f"{name}={QUERY_TAGS.get(name.lower(), REDACTED)}")
        else:
            parts.append(name + sep + value)
    return scrub("&".join(parts), secrets)


def _clean(value: Any, secrets: Iterable[str]) -> Any:
    """Walk anything the caller passed and scrub every string inside it.

    Recursive rather than field-by-field so that a field added later to
    ProbeResult is covered without anyone remembering to update this file.
    """
    if isinstance(value, str):
        return scrub(value, secrets)
    if isinstance(value, Mapping):
        return {
            k: (
                HEADER_TAGS.get(str(k).lower(), REDACTED)
                if str(k).lower() in SENSITIVE_HEADERS
                else _clean(v, secrets)
            )
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_clean(v, secrets) for v in value]
    return value


@dataclass
class AuditLog:
    path: Path
    secrets: tuple[str, ...] = field(default=(), repr=False)
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Scrub and append one JSONL line. Returns what was written."""
        safe = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **_clean(dict(record), self.secrets)}
        if self.enabled:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(safe, ensure_ascii=False) + "\n")
        return safe
