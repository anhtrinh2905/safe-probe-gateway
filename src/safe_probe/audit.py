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

REDACTED = "***REDACTED***"

# Matched case-insensitively against header names.
SENSITIVE_HEADERS = frozenset(
    {"x-api-key", "authorization", "cookie", "set-cookie", "proxy-authorization"}
)

# Matched against query-string parameter names.
SENSITIVE_QUERY = frozenset({"apikey", "api_key", "key", "token", "password", "secret"})

# Catches a credential that ended up somewhere unexpected -- an upstream error
# message, a reflected body from /echo -- even when the exact value is unknown.
# The separator is optional because `Bearer <token>` has none -- with `[:=]`
# required, the single most common way a credential appears in a log went
# unmatched. Found by tests/test_redaction.py, not by reading.
SECRET_SHAPED = re.compile(
    r"(?i)\b(api[-_]?key|authorization|bearer|token)\b\s*[:=]?\s*[\"']?([A-Za-z0-9._\-]{16,})"
)


def scrub(value: str, secrets: Iterable[str]) -> str:
    """Blank known credentials, then anything shaped like one."""
    for secret in secrets:
        if secret and secret in value:
            value = value.replace(secret, REDACTED)
    return SECRET_SHAPED.sub(lambda m: f"{m.group(1)}: {REDACTED}", value)


def redact_headers(headers: Mapping[str, str], secrets: Iterable[str]) -> dict[str, str]:
    return {
        name: (REDACTED if name.lower() in SENSITIVE_HEADERS else scrub(value, secrets))
        for name, value in headers.items()
    }


def redact_query(query: str, secrets: Iterable[str]) -> str:
    if not query:
        return query
    parts = []
    for pair in query.split("&"):
        name, sep, value = pair.partition("=")
        if name.lower() in SENSITIVE_QUERY:
            parts.append(f"{name}={REDACTED}")
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
            k: (REDACTED if str(k).lower() in SENSITIVE_HEADERS else _clean(v, secrets))
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
