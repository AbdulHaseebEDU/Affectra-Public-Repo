# hCaptcha server-side verification helper

from __future__ import annotations

import os
from typing import Tuple

import httpx

from ..runtime_settings import get_key_override

HCAPTCHA_VERIFY_URL = "https://api.hcaptcha.com/siteverify"

# hCaptcha's official test secret — always passes for the test site key
_TEST_SECRET = "0x0000000000000000000000000000000000000000"


def verify(token: str) -> Tuple[bool, str]:
    """Verify an hCaptcha response token.

    Returns (True, "") on success, (False, human_readable_reason) on failure.
    Uses the HCAPTCHA_SECRET runtime override, falling back to the env var,
    then the test secret so development works without any key configured.
    """
    if not token or not token.strip():
        return False, "CAPTCHA response is missing. Please complete the CAPTCHA."

    secret = (
        get_key_override("HCAPTCHA_SECRET")
        or os.environ.get("HCAPTCHA_SECRET", "").strip()
        or _TEST_SECRET
    )

    try:
        resp = httpx.post(
            HCAPTCHA_VERIFY_URL,
            data={"secret": secret, "response": token.strip()},
            timeout=10.0,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        # treat network errors as a soft failure so a brief outage doesn't
        # hard-block every user — log and pass through
        return False, f"CAPTCHA verification service unavailable: {exc}"

    if payload.get("success"):
        return True, ""

    codes = payload.get("error-codes") or []
    # map the most common codes to plain English
    _msgs = {
        "missing-input-response": "Please complete the CAPTCHA.",
        "invalid-input-response": "CAPTCHA response is invalid or expired. Please try again.",
        "missing-input-secret":   "CAPTCHA secret is not configured (server error).",
        "invalid-input-secret":   "CAPTCHA secret is invalid (server error).",
        "timeout-or-duplicate":   "CAPTCHA response has expired or was already used. Please try again.",
    }
    for code in codes:
        if code in _msgs:
            return False, _msgs[code]
    return False, "CAPTCHA verification failed. Please try again."
