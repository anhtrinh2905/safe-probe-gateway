"""Minimal OpenAI-compatible chat client. Stdlib only, one POST.

Carried over from week 3 (`juiceshop_scan/llm/client.py`) and cut down to what
this week needs. Two facts about the opencode.ai Zen gateway shape it, both
inherited from week 3's notes:

1. `response_format: {"type": "json_schema"}` is rejected, so JSON is asked for
   in `json_object` mode and validated here, re-prompting with the validation
   error on a miss.
2. The default model is a reasoning model whose reasoning tokens are billed
   against `max_tokens` and returned separately, so a budget sized for the
   answer alone comes back with an empty `content`.

Every call is appended to `data/llm/calls.jsonl`. A non-deterministic component
is only acceptable next to this work if what it was asked can be re-read later.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from safe_probe.config import REPO_ROOT, load_env

CALL_LOG = REPO_ROOT / "data" / "llm" / "calls.jsonl"
DEFAULT_MAX_TOKENS = 8000
TIMEOUT_S = 120


class LLMError(RuntimeError):
    """The model could not be reached, or would not answer in the shape asked."""


@dataclass
class LLMClient:
    base_url: str
    api_key: str
    model: str
    max_tokens: int = DEFAULT_MAX_TOKENS
    log_path: Path = CALL_LOG

    def __repr__(self) -> str:
        return (
            f"LLMClient(base_url={self.base_url!r}, model={self.model!r}, api_key=***REDACTED***)"
        )

    @classmethod
    def from_env(cls, model_env_key: str = "CUSTOM_SCAN_MODEL") -> LLMClient:
        """Build a client from the environment.

        `model_env_key` lets a second caller (the judge agent in `plan.py`)
        pick a different model than the proposer via `CUSTOM_JUDGE_MODEL`,
        without a second client class -- falls back to `CUSTOM_SCAN_MODEL`
        when that variable is unset, so model diversity is opt-in.
        """
        env = load_env()
        key = (env.get("OPENCODE_API_KEY") or "").strip()
        if not key:
            raise LLMError(
                "OPENCODE_API_KEY is empty. The LLM layer is optional -- "
                "`probe suite` and `probe get/post` work without it."
            )
        return cls(
            base_url=(env.get("OPENCODE_BASE_URL") or "https://opencode.ai/zen/go/v1").rstrip("/"),
            api_key=key,
            model=env.get(model_env_key) or env.get("CUSTOM_SCAN_MODEL") or "deepseek-v4-pro",
        )

    def _post(self, messages: list[dict[str, str]], json_mode: bool) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": 0,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                # The gateway sits behind Cloudflare, which answers the default
                # `Python-urllib/*` with HTTP 403 (error 1010) while accepting
                # any ordinary token. Carried over from week 3; without it every
                # call fails.
                "User-Agent": "safe-probe/0.1",
            },
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise LLMError(f"HTTP {exc.code} from the model gateway: {detail}") from None
        except OSError as exc:
            raise LLMError(f"could not reach the model gateway: {exc}") from None

        choice = (payload.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        self._log(messages, payload, content, time.monotonic() - started)
        if not content.strip():
            raise LLMError(
                f"empty content (finish_reason={choice.get('finish_reason')!r}); "
                "the reasoning budget was probably spent -- raise max_tokens"
            )
        return content

    def _log(
        self, messages: list[dict[str, str]], payload: dict, content: str, secs: float
    ) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        prompt = json.dumps(messages, ensure_ascii=False)
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "model": self.model,
            # The prompt itself is long and contains probe output; the hash is
            # what makes a run re-derivable without storing all of it again.
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "prompt_chars": len(prompt),
            "usage": payload.get("usage", {}),
            "elapsed_s": round(secs, 2),
            "content": content[:4000],
        }
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def ask_json(
        self,
        system: str,
        user: str,
        validate: Callable[[Any], str | None],
        attempts: int = 3,
    ) -> Any:
        """Ask for JSON and keep asking until `validate` is satisfied.

        `validate` returns an error string or None. Re-prompting with the
        validation error rather than raising is what makes this usable against a
        gateway that will not enforce a schema server-side.
        """
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_error = "no attempt was made"
        for _ in range(attempts):
            content = self._post(messages, json_mode=True)
            try:
                parsed = json.loads(content)
            except ValueError as exc:
                last_error = f"not valid JSON: {exc}"
            else:
                error = validate(parsed)
                if error is None:
                    return parsed
                last_error = error
            messages += [
                {"role": "assistant", "content": content[:2000]},
                {"role": "user", "content": f"That was rejected: {last_error}. Answer again."},
            ]
        raise LLMError(f"model never produced a usable answer: {last_error}")
