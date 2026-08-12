"""A small application whose only job is to make the gateway's limits observable.

Juice Shop is the interesting target -- it is what week 3 attacked, and the two
vulnerabilities found there are the ones now outside the allowlist. But Juice
Shop cannot be asked to answer slowly, or to return exactly 500 KB, so
"the 504 came from the timeout" and "the body was cut at the cap" would be
inferred rather than shown.

This app makes them showable. It stores nothing and reflects nothing it was not
given, so probing it cannot change any state that matters.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

app = FastAPI(title="lab-app")

MAX_SLEEP_S = 30.0
MAX_KB = 4096


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/items")
async def items() -> dict[str, Any]:
    return {"items": [{"id": i, "name": f"item-{i}"} for i in range(1, 6)]}


@app.get("/slow")
async def slow(ms: int = 100) -> dict[str, Any]:
    """Answer after `ms` milliseconds. Past the gateway's timeout, nothing here
    is ever reached by the caller -- the gateway gives up first, which is the
    point."""
    delay = min(max(ms, 0) / 1000.0, MAX_SLEEP_S)
    await asyncio.sleep(delay)
    return {"slept_ms": int(delay * 1000)}


@app.get("/big")
async def big(kb: int = 1) -> PlainTextResponse:
    """Return exactly `kb` kilobytes, so truncation is arithmetic, not a guess."""
    size = min(max(kb, 0), MAX_KB) * 1024
    return PlainTextResponse(("x" * 1023 + "\n") * (size // 1024))


@app.get("/status/{code}")
async def status(code: int) -> JSONResponse:
    """Echo back an arbitrary status so the tool's status mapping can be tested
    end to end without needing an upstream that happens to fail."""
    if not 100 <= code <= 599:
        return JSONResponse({"error": "code out of range"}, status_code=400)
    return JSONResponse({"requested": code}, status_code=code)


@app.post("/echo")
async def echo(request: Request) -> JSONResponse:
    """Reflect the request back.

    This is what turns "the payload was sent" into "the payload arrived intact":
    a 10 000-character string, an emoji, or an integer where a string was
    expected is visible in the response rather than assumed.
    """
    raw = await request.body()
    text = raw.decode("utf-8", errors="replace")
    parsed: Any = None
    parse_error: str | None = None
    try:
        parsed = json.loads(text) if text else None
    except ValueError as exc:
        parse_error = str(exc)

    return JSONResponse(
        {
            "received_bytes": len(raw),
            "content_type": request.headers.get("content-type"),
            "parsed_json": parsed,
            "parse_error": parse_error,
            "body_head": text[:500],
        }
    )
