# DuckDuckGo HTML search adapter for Affectra.
# Posts to https://html.duckduckgo.com/html/ (falls back to lite.duckduckgo.com).
# No auth needed. A 1.2 s inter-query delay keeps things polite. Self-check/academic use only.

from __future__ import annotations

import time
import httpx
from typing import Any
from urllib.parse import parse_qs, urlparse, quote_plus
from bs4 import BeautifulSoup

SERVICE_NAME = "DuckDuckGo Search"
PRIMARY_URL = "https://html.duckduckgo.com/html/"
FALLBACK_URL = "https://lite.duckduckgo.com/lite/"
USER_AGENT = "Affectra/1.0 (+academic prototype; PII self-check tool; responsible-use only)"
TIMEOUT = 10
QUERY_DELAY = 1.2  # seconds between consecutive queries


# helpers

# heuristic URL-based category guess
def _classify_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if any(k in host for k in ("github", "gitlab")):
        return "code_repository"
    if any(k in host for k in ("reddit", "forum", "stackoverflow")):
        return "forum_mention"
    if any(k in host for k in ("linkedin", "twitter", "facebook", "instagram")):
        return "social_trace"
    if any(k in host for k in ("pastebin", "ghostbin")):
        return "paste_exposure"
    return "unknown"


# unwrap DDG tracking redirects to get the real URL
def _unwrap_ddg_redirect(href: str) -> str:
    if "/l/?uddg=" in href:
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        real_urls = qs.get("uddg", [])
        if real_urls:
            return real_urls[0]
    return href


def _empty_result(errors: list[str] | None = None) -> dict[str, Any]:
    return {
        "findings": [],
        "api_calls_made": 0,
        "sources_checked": 0,
        "pages_scanned": 0,
        "errors": errors or [],
        "service_name": SERVICE_NAME,
    }


# parse the DDG HTML results page into (url, snippet) pairs
def _parse_results_html(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str]] = []

    # Primary format: div.result blocks
    for block in soup.find_all("div", class_="result"):
        link_tag = block.find("a", class_="result__a")
        snippet_tag = block.find(class_="result__snippet")
        if not link_tag:
            continue
        raw_href = link_tag.get("href", "")
        url = _unwrap_ddg_redirect(raw_href)
        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
        if url and url.startswith("http"):
            results.append((url, snippet))

    # Fallback format: lite page uses simpler table rows
    if not results:
        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "")
            url = _unwrap_ddg_redirect(href)
            if url.startswith("http") and "duckduckgo.com" not in url:
                text = a_tag.get_text(strip=True)
                results.append((url, text))

    return results


# run one query against DDG (primary then fallback); returns (results, api_calls_made)
def _run_search(
    client: httpx.Client,
    query_str: str,
    errors: list[str],
) -> tuple[list[tuple[str, str]], int]:
    api_calls = 0

    # primary: POST to html.duckduckgo.com
    try:
        resp = client.post(PRIMARY_URL, data={"q": query_str})
        api_calls += 1
        if resp.status_code == 200:
            results = _parse_results_html(resp.text)
            if results:
                return results, api_calls
    except httpx.TimeoutException:
        errors.append(f"DuckDuckGo: primary endpoint timed out for '{query_str}'.")
    except httpx.HTTPError as exc:
        errors.append(f"DuckDuckGo: primary endpoint error for '{query_str}': {exc}")

    # fallback: GET lite.duckduckgo.com
    try:
        fallback = f"{FALLBACK_URL}?q={quote_plus(query_str)}"
        resp = client.get(fallback)
        api_calls += 1
        if resp.status_code == 200:
            results = _parse_results_html(resp.text)
            return results, api_calls
    except httpx.TimeoutException:
        errors.append(f"DuckDuckGo: fallback endpoint timed out for '{query_str}'.")
    except httpx.HTTPError as exc:
        errors.append(f"DuckDuckGo: fallback endpoint error for '{query_str}': {exc}")

    return [], api_calls


# public entry point

def query(
    email: str | None = None,
    full_name: str | None = None,
    phone: str | None = None,
    usernames: list[str] | None = None,
    limits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    limits = limits or {}
    max_results = limits.get("max_search_results", 30)

    # build quoted-phrase queries for each identifier
    queries: list[tuple[str, str]] = []
    if email:
        queries.append((f'"{email}"', "email"))
    if full_name:
        queries.append((f'"{full_name}"', "full_name"))
    for uname in (usernames or []):
        if uname:
            queries.append((f'"{uname}"', "username"))

    # combined query for higher-signal results
    if email and full_name:
        queries.append((f'"{email}" "{full_name}"', "email+full_name"))

    if not queries:
        return _empty_result(["DuckDuckGo: no searchable identifiers provided."])

    headers: dict[str, str] = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html",
    }

    findings: list[dict[str, Any]] = []
    errors: list[str] = []
    api_calls = 0
    seen_urls: set[str] = set()
    is_first_query = True

    try:
        with httpx.Client(timeout=TIMEOUT, headers=headers, follow_redirects=True) as client:
            for query_str, field_name in queries:

                # polite delay between queries (skip before first)
                if not is_first_query:
                    time.sleep(QUERY_DELAY)
                is_first_query = False

                results, calls = _run_search(client, query_str, errors)
                api_calls += calls

                for url, snippet in results:
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    category = _classify_url(url)

                    findings.append(
                        {
                            "source_type": "search",
                            "source_name": f"DuckDuckGo - {urlparse(url).netloc}",
                            "source_url": url,
                            "matched_fields": [field_name],
                            "matched_data": {
                                field_name: query_str.strip('"'),
                                "search_query": query_str,
                            },
                            "snippet": snippet[:300] if snippet else "",
                            "category": category,
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
        errors.append(f"DuckDuckGo: unexpected error: {exc}")

    return {
        "findings": findings,
        "api_calls_made": api_calls,
        "sources_checked": len(seen_urls),
        "pages_scanned": 0,
        "errors": errors,
        "service_name": SERVICE_NAME,
    }
