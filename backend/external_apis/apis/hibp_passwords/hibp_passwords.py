# checks HIBP Pwned Passwords using k-anonymity: only first 5 hex chars of SHA-1 are sent
# flags cases where the email string itself was used as a password and subsequently leaked

from __future__ import annotations

import hashlib
import httpx
from typing import Any

SERVICE_NAME = "HIBP Pwned Passwords"
BASE_URL = "https://api.pwnedpasswords.com/range"
USER_AGENT = "Affectra/1.0 (+academic prototype; PII self-check tool; responsible-use only)"
TIMEOUT = 10


def _empty_result(errors: list[str] | None = None) -> dict[str, Any]:
    # Return a well-formed empty result envelope.
    return {
        "findings": [],
        "api_calls_made": 0,
        "sources_checked": 0,
        "pages_scanned": 0,
        "errors": errors or [],
        "service_name": SERVICE_NAME,
    }


def query(
    email: str | None = None,
    full_name: str | None = None,
    phone: str | None = None,
    usernames: list[str] | None = None,
    limits: dict[str, Any] | None = None,
) -> dict[str, Any]:

    if not email:
        return _empty_result(
            ["HIBP Pwned Passwords requires an email address; none provided."]
        )

    # ---- SHA-1 hash the email string (k-anonymity model) -------------------
    sha1_full = hashlib.sha1(email.strip().lower().encode()).hexdigest().upper()
    prefix = sha1_full[:5]
    suffix = sha1_full[5:]

    headers = {"User-Agent": USER_AGENT, "Accept": "text/plain"}
    url = f"{BASE_URL}/{prefix}"
    findings: list[dict[str, Any]] = []
    errors: list[str] = []
    api_calls = 0

    try:
        with httpx.Client(timeout=TIMEOUT, headers=headers) as client:
            resp = client.get(url)
            api_calls += 1
            resp.raise_for_status()

        # The response is plain-text lines of the form  ``SUFFIX:COUNT``
        hit_count = 0
        for line in resp.text.splitlines():
            parts = line.strip().split(":")
            if len(parts) == 2 and parts[0].upper() == suffix:
                hit_count = int(parts[1])
                break

        if hit_count > 0:
            findings.append(
                {
                    "source_type": "api",
                    "source_name": "HIBP Pwned Passwords (k-anonymity)",
                    "source_url": "https://haveibeenpwned.com/Passwords",
                    "matched_fields": ["email"],
                    "matched_data": {
                        "email": email,
                        "sha1_prefix": prefix,
                        "times_seen": hit_count,
                    },
                    "snippet": (
                        f"The email address string was found {hit_count:,} time(s) "
                        f"in the Pwned Passwords dataset.  This means the literal "
                        f"email text was used as a password and subsequently leaked."
                    ),
                    "category": "potential_breach",
                    "match_type": "exact",
                    "linked_identifiers": [],
                    "confirmed_by_service": True,
                }
            )

    except httpx.TimeoutException:
        errors.append("HIBP Pwned Passwords request timed out.")
    except httpx.HTTPStatusError as exc:
        errors.append(
            f"HIBP Pwned Passwords returned HTTP {exc.response.status_code}: "
            f"{exc.response.text[:200]}"
        )
    except httpx.HTTPError as exc:
        errors.append(f"HIBP Pwned Passwords HTTP error: {exc}")
    except (ValueError, KeyError, TypeError) as exc:
        errors.append(f"HIBP Pwned Passwords response parsing error: {exc}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"HIBP Pwned Passwords unexpected error: {exc}")

    return {
        "findings": findings,
        "api_calls_made": api_calls,
        "sources_checked": 1,
        "pages_scanned": 0,
        "errors": errors,
        "service_name": SERVICE_NAME,
    }
