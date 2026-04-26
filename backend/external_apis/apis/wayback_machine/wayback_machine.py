# searches Wayback Machine CDX API for archived snapshots mentioning email domain, name, or usernames
# no auth needed; space out requests — aggressive use can get the IP temporarily blocked

from __future__ import annotations

import httpx
from urllib.parse import quote
from typing import Any

SERVICE_NAME = "Wayback Machine (CDX)"
CDX_BASE = "https://web.archive.org/cdx/search/cdx"
WAYBACK_PREFIX = "https://web.archive.org/web"
USER_AGENT = "Affectra/1.0 (+academic prototype; PII self-check tool; responsible-use only)"
TIMEOUT = 8   # CDX is slow but this adapter fires up to 4 queries per scan;
              # anything longer monopolizes the HYBRID 75s budget.
DEFAULT_LIMIT = 10


def _empty_result(errors: list[str] | None = None) -> dict[str, Any]:
    return {
        "findings": [],
        "api_calls_made": 0,
        "sources_checked": 0,
        "pages_scanned": 0,
        "errors": errors or [],
        "service_name": SERVICE_NAME,
    }


# builds the list of cdx search terms from whatever identifiers we have
def _build_queries(
    email: str | None,
    full_name: str | None,
    usernames: list[str] | None,
) -> list[dict[str, str]]:
    queries: list[dict[str, str]] = []

    if email:
        domain = email.split("@")[-1] if "@" in email else None
        if domain:
            queries.append(
                {"query": domain, "label": f"email domain ({domain})"}
            )
        # Also search for the literal email as a URL substring.
        queries.append(
            {"query": quote(email, safe=""), "label": f"email literal ({email})"}
        )

    if full_name:
        # Turn "John Doe" into "john+doe" and "john-doe" URL patterns.
        slug_plus = "+".join(full_name.lower().split())
        slug_dash = "-".join(full_name.lower().split())
        queries.append(
            {"query": slug_plus, "label": f"full name slug ({slug_plus})"}
        )
        if slug_dash != slug_plus:
            queries.append(
                {"query": slug_dash, "label": f"full name slug ({slug_dash})"}
            )

    for uname in (usernames or []):
        if uname:
            queries.append(
                {"query": uname, "label": f"username ({uname})"}
            )

    return queries


# main entry point -- phone is accepted but ignored, just here for interface consistency
def query(
    email: str | None = None,
    full_name: str | None = None,
    phone: str | None = None,
    usernames: list[str] | None = None,
    limits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    search_queries = _build_queries(email, full_name, usernames)

    if not search_queries:
        return _empty_result(
            [
                "Wayback Machine adapter requires at least one of: email, "
                "full_name, or usernames; none provided."
            ]
        )

    per_query_limit = DEFAULT_LIMIT
    if limits and isinstance(limits.get("wayback_limit"), int):
        per_query_limit = min(limits["wayback_limit"], 50)

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    findings: list[dict[str, Any]] = []
    errors: list[str] = []
    api_calls = 0
    sources_checked = 0
    pages_scanned = 0

    # Respect the controller's per-service cap so we don't fire every CDX
    # query just to have the controller throw the results away.
    cap_hint = 0
    if limits and isinstance(limits.get("max_findings_per_service"), int):
        cap_hint = int(limits["max_findings_per_service"])

    try:
        with httpx.Client(timeout=TIMEOUT, headers=headers) as client:
            for search in search_queries:
                # Early-exit: we already have more than the controller will keep.
                if cap_hint and len(findings) >= cap_hint:
                    break
                sources_checked += 1
                params = {
                    "url": search["query"],
                    "output": "json",
                    "limit": str(per_query_limit),
                }

                try:
                    resp = client.get(CDX_BASE, params=params)
                    api_calls += 1

                    if resp.status_code == 404:
                        continue

                    resp.raise_for_status()
                    rows = resp.json()

                except httpx.TimeoutException:
                    errors.append(
                        f"Wayback CDX timed out for query: {search['label']}"
                    )
                    continue
                except httpx.HTTPStatusError as exc:
                    errors.append(
                        f"Wayback CDX HTTP {exc.response.status_code} for "
                        f"query: {search['label']}"
                    )
                    continue
                except httpx.HTTPError as exc:
                    errors.append(
                        f"Wayback CDX error for query {search['label']}: {exc}"
                    )
                    continue
                except (ValueError, TypeError):
                    # Non-JSON response -- skip.
                    errors.append(
                        f"Wayback CDX returned non-JSON for query: {search['label']}"
                    )
                    continue

                if not rows or len(rows) < 2:
                    # First row is the header; if only one row, no results.
                    continue

                header = rows[0]
                data_rows = rows[1:]
                pages_scanned += len(data_rows)

                for row in data_rows:
                    record = dict(zip(header, row)) if len(row) == len(header) else {}
                    if not record:
                        continue

                    original_url = record.get("original", "")
                    timestamp = record.get("timestamp", "")
                    mimetype = record.get("mimetype", "")
                    status_code = record.get("statuscode", "")

                    wayback_url = (
                        f"{WAYBACK_PREFIX}/{timestamp}/{original_url}"
                        if timestamp and original_url
                        else ""
                    )

                    snippet_parts = [
                        f"Archived snapshot found for query: {search['label']}",
                        f"URL: {original_url}",
                    ]
                    if timestamp:
                        # Format YYYYMMDDHHMMSS into something readable.
                        ts_display = (
                            f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}"
                            if len(timestamp) >= 8
                            else timestamp
                        )
                        snippet_parts.append(f"Captured: {ts_display}")
                    if mimetype:
                        snippet_parts.append(f"Type: {mimetype}")

                    matched_fields = []
                    if email:
                        matched_fields.append("email")
                    if full_name:
                        matched_fields.append("full_name")
                    if usernames:
                        matched_fields.append("usernames")

                    findings.append(
                        {
                            "source_type": "api",
                            "source_name": f"Wayback Machine - {search['label']}",
                            "source_url": wayback_url,
                            "matched_fields": matched_fields,
                            "matched_data": {
                                "query": search["query"],
                                "original_url": original_url,
                                "timestamp": timestamp,
                                "mimetype": mimetype,
                                "status_code": status_code,
                            },
                            "snippet": " | ".join(snippet_parts),
                            "category": "historical_cache",
                            "match_type": "contextual",
                            "linked_identifiers": [],
                            "confirmed_by_service": True,
                        }
                    )

    except Exception as exc:  # noqa: BLE001
        errors.append(f"Wayback Machine adapter unexpected error: {exc}")

    return {
        "findings": findings,
        "api_calls_made": api_calls,
        "sources_checked": sources_checked,
        "pages_scanned": pages_scanned,
        "errors": errors,
        "service_name": SERVICE_NAME,
    }
