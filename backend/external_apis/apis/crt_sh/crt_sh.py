# crt.sh Certificate Transparency search — finds certs issued for the email domain
# exposes subdomains, SANs, issuers, and cert history; no auth, community-run, can be slow

from __future__ import annotations

import httpx
from typing import Any

SERVICE_NAME = "crt.sh (Certificate Transparency)"
BASE_URL = "https://crt.sh/"
USER_AGENT = "Affectra/1.0 (+academic prototype; PII self-check tool; responsible-use only)"
TIMEOUT = 12  # crt.sh is slow; keep below budget-monopolizing threshold


def _empty_result(errors: list[str] | None = None) -> dict[str, Any]:
    return {
        "findings": [],
        "api_calls_made": 0,
        "sources_checked": 0,
        "pages_scanned": 0,
        "errors": errors or [],
        "service_name": SERVICE_NAME,
    }


# only uses email (extracts the domain); all other args are ignored
def query(
    email: str | None = None,
    full_name: str | None = None,
    phone: str | None = None,
    usernames: list[str] | None = None,
    limits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not email or "@" not in email:
        return _empty_result(
            ["crt.sh requires a valid email address (with domain); none provided."]
        )

    domain = email.split("@")[-1].strip().lower()
    if not domain:
        return _empty_result(["Could not extract a domain from the email address."])

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    params = {"q": domain, "output": "json"}
    findings: list[dict[str, Any]] = []
    errors: list[str] = []
    api_calls = 0

    try:
        with httpx.Client(timeout=TIMEOUT, headers=headers) as client:
            resp = client.get(BASE_URL, params=params)
            api_calls += 1

            if resp.status_code == 404:
                return {
                    "findings": [],
                    "api_calls_made": api_calls,
                    "sources_checked": 1,
                    "pages_scanned": 0,
                    "errors": [],
                    "service_name": SERVICE_NAME,
                }

            resp.raise_for_status()

            # crt.sh may return an empty body for no-results.
            text = resp.text.strip()
            if not text or text == "[]":
                return {
                    "findings": [],
                    "api_calls_made": api_calls,
                    "sources_checked": 1,
                    "pages_scanned": 0,
                    "errors": [],
                    "service_name": SERVICE_NAME,
                }

            records = resp.json()

        if not isinstance(records, list):
            errors.append("crt.sh returned an unexpected response format.")
            return {
                "findings": [],
                "api_calls_made": api_calls,
                "sources_checked": 1,
                "pages_scanned": 0,
                "errors": errors,
                "service_name": SERVICE_NAME,
            }

        # De-duplicate by common_name to avoid flooding results.
        seen_names: set[str] = set()
        max_findings = 25  # Cap to keep output manageable.

        for record in records:
            if len(findings) >= max_findings:
                break

            common_name = record.get("common_name", "")
            name_value = record.get("name_value", "")
            issuer_name = record.get("issuer_name", "")
            cert_id = record.get("id", "")
            not_before = record.get("not_before", "")
            not_after = record.get("not_after", "")
            serial_number = record.get("serial_number", "")

            # Use common_name as de-dup key.
            dedup_key = f"{common_name}|{name_value}"
            if dedup_key in seen_names:
                continue
            seen_names.add(dedup_key)

            # name_value can be multi-line (one SAN per line).
            san_entries = [
                s.strip() for s in name_value.split("\n") if s.strip()
            ]

            snippet_parts = [
                f"CT log entry for domain: {domain}",
                f"Common Name: {common_name}",
            ]
            if san_entries:
                snippet_parts.append(
                    f"SANs: {', '.join(san_entries[:5])}"
                    + (f" (+{len(san_entries) - 5} more)" if len(san_entries) > 5 else "")
                )
            if issuer_name:
                snippet_parts.append(f"Issuer: {issuer_name}")
            if not_before:
                snippet_parts.append(f"Valid from: {not_before}")

            cert_url = f"https://crt.sh/?id={cert_id}" if cert_id else BASE_URL

            findings.append(
                {
                    "source_type": "api",
                    "source_name": f"crt.sh - {common_name}",
                    "source_url": cert_url,
                    "matched_fields": ["email"],
                    "matched_data": {
                        "email_domain": domain,
                        "common_name": common_name,
                        "san_entries": san_entries,
                        "issuer_name": issuer_name,
                        "not_before": not_before,
                        "not_after": not_after,
                        "serial_number": serial_number,
                        "crt_sh_id": cert_id,
                    },
                    "snippet": " | ".join(snippet_parts),
                    "category": "unknown",
                    "match_type": "partial",
                    "linked_identifiers": [],
                    "confirmed_by_service": True,
                }
            )

    except httpx.TimeoutException:
        errors.append("crt.sh request timed out (this service can be slow).")
    except httpx.HTTPStatusError as exc:
        errors.append(
            f"crt.sh returned HTTP {exc.response.status_code}: "
            f"{exc.response.text[:200]}"
        )
    except httpx.HTTPError as exc:
        errors.append(f"crt.sh HTTP error: {exc}")
    except (ValueError, KeyError, TypeError) as exc:
        errors.append(f"crt.sh response parsing error: {exc}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"crt.sh unexpected error: {exc}")

    return {
        "findings": findings,
        "api_calls_made": api_calls,
        "sources_checked": 1,
        "pages_scanned": len(findings),
        "errors": errors,
        "service_name": SERVICE_NAME,
    }
