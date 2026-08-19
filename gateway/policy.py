"""Load and validate `policy.yml`.

Kept separate from `app.py` so that "what is allowed" can be unit-tested without
starting a server, and so a malformed policy fails at startup with a readable
message rather than at request time with a KeyError.

Secrets never appear in the policy file: a consumer names an environment
variable and this module resolves it. A consumer whose variable is unset is
dropped rather than treated as having an empty key -- an empty key would make
`headers.get("x-api-key")` returning None authenticate successfully.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class PolicyError(ValueError):
    """The policy file is not usable. Raised at startup, never at request time."""


@dataclass(frozen=True)
class Limits:
    rate_per_minute: int
    upstream_timeout_s: float
    max_request_bytes: int
    max_response_bytes: int


@dataclass(frozen=True)
class Consumer:
    name: str
    groups: frozenset[str]


@dataclass(frozen=True)
class Route:
    id: str
    upstream: str
    upstream_url: str
    methods: frozenset[str]
    path: str | None
    path_prefix: str | None
    groups: frozenset[str]
    note: str = ""

    def matches_path(self, path: str) -> bool:
        if self.path is not None:
            return path == self.path
        return path.startswith(self.path_prefix or "\0")

    def public(self) -> dict[str, Any]:
        """What `GET /_gateway/routes` hands back to an authenticated consumer.

        Groups are included on purpose: a tool that can see it lacks the group
        can report "403 was expected here" instead of guessing. `upstream` is
        the policy's own name for the target (e.g. "lab", "juice-shop"), not
        `upstream_url` -- a caller learns which backend a route belongs to
        without learning a hostname it has no way to reach directly anyway
        (see docs/adr/0003-topology-la-bang-chung.md).
        """
        return {
            "id": self.id,
            "upstream": self.upstream,
            "methods": sorted(self.methods),
            "path": self.path,
            "path_prefix": self.path_prefix,
            "groups": sorted(self.groups),
            "note": self.note,
        }


@dataclass
class Policy:
    limits: Limits
    routes: list[Route]
    # key -> Consumer. Never logged, never returned by any endpoint.
    _by_key: dict[str, Consumer] = field(default_factory=dict, repr=False)
    skipped_consumers: list[str] = field(default_factory=list)

    def consumer_for(self, key: str | None) -> Consumer | None:
        if not key:
            return None
        return self._by_key.get(key)

    def match(self, method: str, path: str) -> Route | None:
        """First route whose path matches, regardless of method.

        Path first, then method, because that ordering is what lets the gateway
        answer 405 for "right place, wrong verb" while still answering 404 for
        anything not in the allowlist at all.
        """
        for route in self.routes:
            if route.matches_path(path):
                return route
        return None

    def secret_values(self) -> tuple[str, ...]:
        """Every credential the gateway knows, for the audit log's scrubber."""
        return tuple(self._by_key)


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise PolicyError(f"{where}: missing required key {key!r}")
    return mapping[key]


def load_policy(path: str | Path, environ: dict[str, str] | None = None) -> Policy:
    env = os.environ if environ is None else environ
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PolicyError(f"{path}: expected a mapping at the top level")

    if raw.get("version") != 1:
        raise PolicyError(f"{path}: unsupported policy version {raw.get('version')!r}")

    lim = _require(raw, "limits", str(path))
    limits = Limits(
        rate_per_minute=int(_require(lim, "rate_per_minute", "limits")),
        upstream_timeout_s=float(_require(lim, "upstream_timeout_s", "limits")),
        max_request_bytes=int(_require(lim, "max_request_bytes", "limits")),
        max_response_bytes=int(_require(lim, "max_response_bytes", "limits")),
    )

    upstreams: dict[str, str] = dict(_require(raw, "upstreams", str(path)))

    by_key: dict[str, Consumer] = {}
    skipped: list[str] = []
    for entry in _require(raw, "consumers", str(path)):
        name = _require(entry, "name", "consumers")
        key_env = _require(entry, "key_env", f"consumers[{name}]")
        key = (env.get(key_env) or "").strip()
        if not key:
            # Not fatal: the repo ships with one key set, and admin-tool exists
            # only to give the ACL check something to contrast against.
            skipped.append(f"{name} ({key_env} unset)")
            continue
        if key in by_key:
            raise PolicyError(f"consumers: {name} and {by_key[key].name} share a key")
        by_key[key] = Consumer(name=name, groups=frozenset(entry.get("groups", ())))

    if not by_key:
        raise PolicyError("no consumer has a key -- every request would be 401")

    routes: list[Route] = []
    seen_ids: set[str] = set()
    for entry in _require(raw, "routes", str(path)):
        rid = _require(entry, "id", "routes")
        if rid in seen_ids:
            raise PolicyError(f"routes: duplicate id {rid!r}")
        seen_ids.add(rid)

        upstream = _require(entry, "upstream", f"routes[{rid}]")
        if upstream not in upstreams:
            raise PolicyError(f"routes[{rid}]: unknown upstream {upstream!r}")

        path_exact = entry.get("path")
        path_prefix = entry.get("path_prefix")
        if (path_exact is None) == (path_prefix is None):
            raise PolicyError(f"routes[{rid}]: set exactly one of path / path_prefix")
        for value in (path_exact, path_prefix):
            if value is not None and not value.startswith("/"):
                raise PolicyError(f"routes[{rid}]: path must begin with '/', got {value!r}")

        routes.append(
            Route(
                id=rid,
                upstream=upstream,
                upstream_url=upstreams[upstream].rstrip("/"),
                methods=frozenset(m.upper() for m in _require(entry, "methods", f"routes[{rid}]")),
                path=path_exact,
                path_prefix=path_prefix,
                groups=frozenset(entry.get("groups", ())),
                note=entry.get("note", ""),
            )
        )

    # Exact matches before prefix matches, longest prefix first. Without this the
    # order inside the YAML would silently decide which route wins.
    routes.sort(key=lambda r: (r.path is None, -len(r.path_prefix or "")))

    return Policy(limits=limits, routes=routes, _by_key=by_key, skipped_consumers=skipped)
