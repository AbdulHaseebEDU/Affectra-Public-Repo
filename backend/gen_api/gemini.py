# thin httpx wrapper for the Gemini REST API
#
# model waterfall:
#   1. gemini-2.5-flash      — best quality; tried first
#   2. gemini-2.5-flash-lite — lighter model; used when the primary is
#                              quota-limited (429) or overloaded (5xx)
#
# within each model: up to _MAX_RETRIES attempts with exponential back-off
# on transient server errors (5xx).  a 429 or 400 skips straight to the next
# model — quota errors and malformed-request errors don't resolve with retries.
#
# NOTE: responseMimeType is intentionally omitted.  It is a paid/preview
# feature that not all model tiers support, and its absence causes 400 errors
# on lighter models.  The caller's JSON parser already handles both plain JSON
# and markdown-fenced JSON (```json … ```) so we don't need it.

from __future__ import annotations

import time
import httpx
from typing import Any

_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]
_BASE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

TIMEOUT = 45
_RETRYABLE_5XX = {500, 502, 503, 504}   # transient — worth retrying
_SKIP_TO_NEXT   = {429, 400}            # quota/rate-limit or bad-request — try next model
_MAX_RETRIES = 3                         # attempts per model on 5xx
_BASE_DELAY  = 5                         # seconds; doubles each attempt: 5, 10, 20


def generate(prompt: str, api_key: str) -> str:
    """Send a single-turn prompt and return the text response.

    Tries each model in _MODELS.  Within a model, retries on transient 5xx
    errors with exponential back-off.  On 429 or 400 the model is skipped
    immediately (quota/bad-request errors don't resolve with retries).
    Raises on the last failure.
    """
    last_exc: Exception | None = None

    for model in _MODELS:
        url = _BASE.format(model=model) + f"?key={api_key}"
        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 8192,
            },
        }

        for attempt in range(_MAX_RETRIES):
            delay = _BASE_DELAY * (2 ** attempt)   # 5 s, 10 s, 20 s
            try:
                resp = httpx.post(url, json=payload, timeout=TIMEOUT)

                if resp.status_code in _SKIP_TO_NEXT:
                    # quota exceeded or bad-request — this model won't help, move on.
                    # try to surface the actual Google error message (e.g. "API key expired")
                    try:
                        _msg = resp.json().get("error", {}).get("message", "")
                    except Exception:
                        _msg = ""
                    _detail = f": {_msg}" if _msg else ""
                    last_exc = httpx.HTTPStatusError(
                        f"{model} returned {resp.status_code}{_detail}",
                        request=resp.request,
                        response=resp,
                    )
                    break   # next model

                if resp.status_code in _RETRYABLE_5XX:
                    if attempt < _MAX_RETRIES - 1:
                        time.sleep(delay)
                        continue
                    # all retries spent — fall through to next model
                    last_exc = httpx.HTTPStatusError(
                        f"{model} still returning {resp.status_code} after "
                        f"{_MAX_RETRIES} attempts",
                        request=resp.request,
                        response=resp,
                    )
                    break   # next model

                resp.raise_for_status()
                data = resp.json()
                try:
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError) as exc:
                    raise ValueError(
                        f"Unexpected Gemini response shape: {data}"
                    ) from exc

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                code = exc.response.status_code
                if code in _SKIP_TO_NEXT:
                    break   # quota/bad-request — next model immediately
                if code in _RETRYABLE_5XX and attempt < _MAX_RETRIES - 1:
                    time.sleep(delay)
                    continue
                break   # non-retryable or exhausted

            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(delay)
                    continue
                break   # timed out on all attempts — try next model

    raise last_exc or RuntimeError("Gemini: all models exhausted")
