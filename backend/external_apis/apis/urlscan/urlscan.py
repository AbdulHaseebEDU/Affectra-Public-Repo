# URLScan.io search — finds pages mentioning the queried identifiers
# URLSCAN_API_KEY is optional but raises the rate limit beyond the default ~60 req/min

from __future__ import annotations

import httpx
from typing import Any

from ...api_keys.keys import get_key

SERVICE_NAME = "URLScan.io"
BASE_URL = "https://urlscan.io/api/v1/search/"
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

    limits = limits or {}
    max_results = limits.get("max_search_results", 25)

    # Build search queries from whatever identifiers we have.
    search_terms: list[tuple[str, str]] = []
    if email:
        search_terms.append((email, "email"))
    if full_name:
        search_terms.append((full_name, "full_name"))
    for uname in (usernames or []):
        if uname:
            search_terms.append((uname, "username"))

    if not search_terms:
        return _empty_result(["URLScan: no searchable identifiers provided."])

    # Build headers -- attach API key if available.
    api_key = get_key("URLSCAN_API_KEY")
    headers: dict[str, str] = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if api_key:
        headers["API-Key"] = api_key

    findings: list[dict[str, Any]] = []
    errors: list[str] = []
    api_calls = 0
    sources_checked = 0
    seen_urls: set[str] = set()

    try:
        with httpx.Client(timeout=TIMEOUT, headers=headers) as client:
            for term, field_name in search_terms:
                params = {"q": f'"{term}"', "size": min(max_results, 100)}
                try:
                    resp = client.get(BASE_URL, params=params)
                    api_calls += 1

                    if resp.status_code == 429:
                        errors.append("URLScan: rate-limited (HTTP 429). Try again later.")
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.TimeoutException:
                    errors.append(f"URLScan: request timed out for query '{term}'.")
                    continue
                except httpx.HTTPStatusError as exc:
                    errors.append(
                        f"URLScan: HTTP {exc.response.status_code} for query "
                        f"'{term}': {exc.response.text[:200]}"
                    )
                    continue
                except httpx.HTTPError as exc:
                    errors.append(f"URLScan: HTTP error for query '{term}': {exc}")
                    continue

                results = data.get("results", [])
                sources_checked += len(results)

                for entry in results:
                    page = entry.get("page", {})
                    task = entry.get("task", {})

                    page_url = page.get("url", "") or task.get("url", "")
                    page_domain = page.get("domain", "")
                    result_id = entry.get("_id", "")
                    scan_url = f"https://urlscan.io/result/{result_id}/" if result_id else page_url

                    if page_url in seen_urls:
                        continue
                    seen_urls.add(page_url)

                    snippet_parts = []
                    if page_domain:
                        snippet_parts.append(f"Domain: {page_domain}")
                    if page.get("title"):
                        snippet_parts.append(f"Title: {page['title']}")
                    if page.get("server"):
                        snippet_parts.append(f"Server: {page['server']}")
                    snippet_parts.append(f"Scanned URL: {page_url}")

                    findings.append(
                        {
                            "source_type": "api",
                            "source_name": f"URLScan.io - {page_domain or 'unknown'}",
                            "source_url": scan_url,
                            "matched_fields": [field_name],
                            "matched_data": {
                                field_name: term,
                                "page_url": page_url,
                                "domain": page_domain,
                                "title": page.get("title", ""),
                            },
                            "snippet": " | ".join(snippet_parts),
                            "category": "unknown",
                            "match_type": "contextual",
                            "linked_identifiers": [],
                            "confirmed_by_service": False,
                        }
                    )

                    if len(findings) >= max_results:
                        break

                if len(findings) >= max_results:
                    break

    except Exception as exc:  # noqa: BLE001
        errors.append(f"URLScan: unexpected error: {exc}")

    return {
        "findings": findings,
        "api_calls_made": api_calls,
        "sources_checked": sources_checked,
        "pages_scanned": 0,
        "errors": errors,
        "service_name": SERVICE_NAME,
    }
