# looks up a Gravatar profile via MD5(email).json — no auth needed
# exposes display name, linked accounts, and photo URLs the owner may have forgotten are public

from __future__ import annotations

import hashlib
import httpx
from typing import Any

SERVICE_NAME = "Gravatar"
BASE_URL = "https://en.gravatar.com"
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
        return _empty_result(["Gravatar requires an email address; none provided."])

    md5_hash = hashlib.md5(email.strip().lower().encode()).hexdigest()
    url = f"{BASE_URL}/{md5_hash}.json"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    findings: list[dict[str, Any]] = []
    errors: list[str] = []
    api_calls = 0

    try:
        with httpx.Client(timeout=TIMEOUT, headers=headers) as client:
            resp = client.get(url)
            api_calls += 1

            if resp.status_code == 404:
                # No Gravatar profile for this email.
                return {
                    "findings": [],
                    "api_calls_made": api_calls,
                    "sources_checked": 1,
                    "pages_scanned": 0,
                    "errors": [],
                    "service_name": SERVICE_NAME,
                }

            resp.raise_for_status()
            data = resp.json()

        # ----- Parse profile entries -----------------------------------------
        entries = data.get("entry", [])

        for entry in entries:
            display_name = entry.get("displayName", "")
            preferred_username = entry.get("preferredUsername", "")
            about_me = entry.get("aboutMe", "")
            current_location = entry.get("currentLocation", "")
            profile_url = entry.get("profileUrl", "")
            thumbnail_url = entry.get("thumbnailUrl", "")

            # Collect linked accounts / URLs as linked_identifiers.
            linked_identifiers: list[dict[str, str]] = []

            for acct in entry.get("accounts", []):
                linked_identifiers.append(
                    {
                        "platform": acct.get("shortname", acct.get("domain", "unknown")),
                        "username": acct.get("username", ""),
                        "url": acct.get("url", ""),
                        "display": acct.get("display", ""),
                    }
                )

            for url_obj in entry.get("urls", []):
                linked_identifiers.append(
                    {
                        "platform": url_obj.get("title", "website"),
                        "url": url_obj.get("value", ""),
                    }
                )

            # Build matched_data dict with all extracted fields.
            matched_data: dict[str, Any] = {"email": email}
            matched_fields = ["email"]

            if display_name:
                matched_data["display_name"] = display_name
                matched_fields.append("display_name")
            if preferred_username:
                matched_data["preferred_username"] = preferred_username
                matched_fields.append("preferred_username")
            if about_me:
                matched_data["about_me"] = about_me
            if current_location:
                matched_data["current_location"] = current_location
                matched_fields.append("current_location")
            if thumbnail_url:
                matched_data["thumbnail_url"] = thumbnail_url
            if profile_url:
                matched_data["profile_url"] = profile_url

            # Snippet -- concise, human-readable summary.
            snippet_parts = ["Gravatar profile found"]
            if display_name:
                snippet_parts.append(f"Display name: {display_name}")
            if preferred_username:
                snippet_parts.append(f"Username: {preferred_username}")
            if current_location:
                snippet_parts.append(f"Location: {current_location}")
            if linked_identifiers:
                snippet_parts.append(
                    f"Linked accounts: {len(linked_identifiers)}"
                )

            findings.append(
                {
                    "source_type": "api",
                    "source_name": "Gravatar Profile",
                    "source_url": profile_url or f"https://en.gravatar.com/{md5_hash}",
                    "matched_fields": matched_fields,
                    "matched_data": matched_data,
                    "snippet": " | ".join(snippet_parts),
                    "category": "social_trace",
                    "match_type": "exact",
                    "linked_identifiers": linked_identifiers,
                    "confirmed_by_service": True,
                }
            )

    except httpx.TimeoutException:
        errors.append("Gravatar request timed out.")
    except httpx.HTTPStatusError as exc:
        errors.append(
            f"Gravatar returned HTTP {exc.response.status_code}: "
            f"{exc.response.text[:200]}"
        )
    except httpx.HTTPError as exc:
        errors.append(f"Gravatar HTTP error: {exc}")
    except (ValueError, KeyError, TypeError) as exc:
        errors.append(f"Gravatar response parsing error: {exc}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Gravatar unexpected error: {exc}")

    return {
        "findings": findings,
        "api_calls_made": api_calls,
        "sources_checked": 1,
        "pages_scanned": 0,
        "errors": errors,
        "service_name": SERVICE_NAME,
    }
