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
from collections.abc import Callable
from typing import Any

from safe_probe.llm import LLMError
from safe_probe.plan import Proposal, Verdict, judge_proposal, send_probe, should_auto_send


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


# -- judge agent: should_auto_send is the only chokepoint the UI consults ----
#
# These are deterministic (no real LLM call) because the property under test
# is the boundary itself -- "low" skips the click, anything else doesn't --
# not what any particular model decides. `tests/test_judge_agent.py` covers
# the real-LLM, adversarial side of `judge_proposal`.


def test_should_auto_send_is_true_only_for_low_risk() -> None:
    assert should_auto_send(Verdict(risk="low", reasoning="")) is True
    assert should_auto_send(Verdict(risk="needs_review", reasoning="")) is False


class _RaisingLLM:
    """Stands in for `LLMClient`: any call to `ask_json` fails like a dead
    model gateway would (no key, network down, out of retries).
    """

    def ask_json(self, system: str, user: str, validate: Callable[[Any], str | None]) -> dict:
        raise LLMError("model gateway unreachable (simulated)")


def test_judge_proposal_fails_safe_to_needs_review_when_the_llm_is_unusable(make_client) -> None:
    client = make_client()
    published = client.routes()
    proposal = Proposal(route_id="echo", payload_id="empty-string", why="input validation probe")

    # A person never sees a stack trace here: whatever breaks in the judge
    # call, the proposal must still land on `needs_review`, never on "low".
    verdict = judge_proposal(proposal, "input validation", published, llm=_RaisingLLM())

    assert verdict.risk == "needs_review"
    assert should_auto_send(verdict) is False
