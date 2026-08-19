"""Human-in-the-loop: two cases, per week 5.

`plan.py::send_probe` is the single place a `Proposal` turns into a request
(see its docstring and docs/adr/0002-guardrail-hai-lop.md) -- which is exactly
what makes the human-in-the-loop gate possible without weakening anything
else: `ui/streamlit_app.py` (Streamlit needs its own dependency set, not
exercised by this stdlib-only suite -- see AGENTS.md) calls `propose_round` to
get a proposal, shows it to a person, and calls `send_probe` only if they
click Approve. This module tests that chokepoint directly: a proposal that
never reaches `send_probe` produces no request and no log entry (Reject), and
one that does reach it is actually sent and logged (Approve). If either of
those stopped being true, the UI's Approve/Reject buttons would stop meaning
anything, no matter how they render.
"""

from __future__ import annotations

import json

from safe_probe.plan import Proposal, send_probe


def _logged_paths(tmp_path) -> list[str]:
    log_path = tmp_path / "requests.jsonl"
    if not log_path.exists():
        return []
    return [json.loads(line).get("path") for line in log_path.read_text("utf-8").splitlines()]


def test_a_rejected_proposal_is_never_sent_and_never_logged(make_client, tmp_path) -> None:
    client = make_client()
    client.routes()  # the allowlist read itself logs, so the log isn't vacuously empty

    # A person clicking Reject in the UI: the proposal exists, but nothing
    # downstream of it ever runs. This line is the whole test -- everything
    # after it just confirms that not calling send_probe left no trace of an
    # actual request to /echo.
    Proposal(route_id="echo", payload_id="empty-string", why="rejected by operator")

    paths = _logged_paths(tmp_path)
    assert paths, "the routes read should have logged something -- test would pass vacuously"
    assert "/echo" not in paths


def test_an_approved_proposal_is_actually_sent_and_logged(make_client, tmp_path) -> None:
    client = make_client()
    published = client.routes()
    proposal = Proposal(route_id="echo", payload_id="empty-string", why="approved by operator")

    # A person clicking Approve: the UI calls exactly this.
    result = send_probe(client, published, proposal)

    assert result.ok
    assert result.path == "/echo"
    assert "/echo" in _logged_paths(tmp_path), "the approved send must be audited"
