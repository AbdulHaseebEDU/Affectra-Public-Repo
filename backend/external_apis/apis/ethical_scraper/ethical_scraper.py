# ethical scraper — fetches candidate URLs from DuckDuckGo and checks whether PII identifiers appear in page content
# robots.txt is checked and obeyed per host before any fetch
# per-host delay of 1.2 s and a 1.5 MB body cap keep it well-behaved
# self-check / academic-prototype use only

from __future__ import annotations

import re
import time
import httpx
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup

SERVICE_NAME = "Ethical Scraper"
USER_AGENT = "Affectra/1.0 (+academic prototype; PII self-check tool; responsible-use only)"
TIMEOUT = 10
HOST_DELAY = 1.2        # seconds between requests to the same host
MAX_BODY_SIZE = 1_500_000  # 1.5 MB
SNIPPET_RADIUS = 140    # chars on each side of match (~280 total)

# helpers

def _classify_url(url: str) -> str:
    # Heuristic URL-based category classification.
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


def _empty_result(errors: list[str] | None = None) -> dict[str, Any]:
    return {
        "findings": [],
        "api_calls_made": 0,
        "sources_checked": 0,
        "pages_scanned": 0,
        "errors": errors or [],
        "service_name": SERVICE_NAME,
    }


def _extract_visible_text(html: str) -> str:
    # Strip script/style tags and return visible text.
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "meta", "link"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def _build_snippet(text: str, match_start: int) -> str:
    # Return ~280 chars of context around the match position.
    start = max(0, match_start - SNIPPET_RADIUS)
    end = min(len(text), match_start + SNIPPET_RADIUS)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


# returns True if robots.txt allows fetching url; results cached per host
def _check_robots(host: str, url: str, cache: dict[str, RobotFileParser]) -> bool:
    if host in cache:
        rp = cache[host]
    else:
        rp = RobotFileParser()
        robots_url = f"https://{host}/robots.txt"
        try:
            rp.set_url(robots_url)
            rp.read()
        except Exception:  # noqa: BLE001
            # If we can't fetch robots.txt, assume allowed.
            rp = RobotFileParser()
            rp.allow_all = True
        cache[host] = rp

    return rp.can_fetch(USER_AGENT, url)


def _find_linked_identifiers(text: str) -> list[str]:
    linked: list[str] = []

    emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}", text)
    if emails:
        linked.append(emails[0])

    handles = re.findall(r"(?<!\w)@([a-zA-Z0-9_]{2,30})(?!\w)", text)
    if handles:
        linked.append(f"@{handles[0]}")

    return linked[:2]


def _match_identifiers(
    text: str,
    email: str | None,
    full_name: str | None,
    phone: str | None,
    usernames: list[str] | None,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    text_lower = text.lower()

    # Exact email match
    if email:
        idx = text_lower.find(email.lower())
        if idx != -1:
            matches.append(
                {"field": "email", "value": email, "start": idx, "match_type": "exact"}
            )

    # Phone: digits-only comparison
    if phone:
        phone_digits = re.sub(r"\D", "", phone)
        if len(phone_digits) >= 7:
            text_digits = re.sub(r"\D", "", text)
            idx = text_digits.find(phone_digits)
            if idx != -1:
                # Approximate char position in original text.
                real_idx = text_lower.find(phone_digits[:4])
                matches.append(
                    {
                        "field": "phone",
                        "value": phone,
                        "start": max(real_idx, 0),
                        "match_type": "partial",
                    }
                )

    # Full name: token-overlap (all tokens must appear)
    if full_name:
        tokens = [t.lower() for t in full_name.split() if len(t) >= 2]
        if tokens and all(t in text_lower for t in tokens):
            idx = text_lower.find(tokens[0])
            matches.append(
                {
                    "field": "full_name",
                    "value": full_name,
                    "start": max(idx, 0),
                    "match_type": "partial",
                }
            )

    # Usernames: word-boundary match
    for uname in (usernames or []):
        if not uname:
            continue
        pattern = re.compile(r"\b" + re.escape(uname) + r"\b", re.IGNORECASE)
        m = pattern.search(text)
        if m:
            matches.append(
                {
                    "field": "username",
                    "value": uname,
                    "start": m.start(),
                    "match_type": "exact",
                }
            )

    return matches

# entry point

def query(
    email: str | None = None,
    full_name: str | None = None,
    phone: str | None = None,
    usernames: list[str] | None = None,
    limits: dict[str, Any] | None = None,
    candidate_urls: list[str] | None = None,
) -> dict[str, Any]:

    if not candidate_urls:
        return _empty_result(["Ethical scraper: no candidate URLs provided."])

    has_identifiers = any([email, full_name, phone, (usernames or [])])
    if not has_identifiers:
        return _empty_result(["Ethical scraper: no identifiers to search for."])

    limits = limits or {}
    max_per_host = limits.get("max_sources", 5)

    findings: list[dict[str, Any]] = []
    errors: list[str] = []
    api_calls = 0
    pages_scanned = 0
    host_page_counts: dict[str, int] = {}
    host_last_request: dict[str, float] = {}
    robots_cache: dict[str, RobotFileParser] = {}

    headers: dict[str, str] = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html",
    }

    try:
        with httpx.Client(
            timeout=TIMEOUT,
            headers=headers,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            for url in candidate_urls:
                try:
                    parsed = urlparse(url)
                    host = parsed.netloc.lower()
                    if not host:
                        continue

                    # --- Per-host page cap ---
                    if host_page_counts.get(host, 0) >= max_per_host:
                        continue

                    # --- robots.txt check ---
                    if not _check_robots(host, url, robots_cache):
                        errors.append(f"Ethical scraper: robots.txt disallows '{url}' -- skipped.")
                        continue

                    # --- Per-host delay ---
                    last_time = host_last_request.get(host, 0.0)
                    elapsed = time.time() - last_time
                    if elapsed < HOST_DELAY:
                        time.sleep(HOST_DELAY - elapsed)

                    # --- Fetch page ---
                    resp = client.get(url)
                    api_calls += 1
                    host_last_request[host] = time.time()
                    host_page_counts[host] = host_page_counts.get(host, 0) + 1

                    if resp.status_code != 200:
                        continue

                    # --- Body size guard ---
                    body = resp.text
                    if len(body) > MAX_BODY_SIZE:
                        errors.append(
                            f"Ethical scraper: '{url}' body exceeds 1.5 MB -- skipped."
                        )
                        continue

                    pages_scanned += 1

                    # --- Extract visible text and check identifiers ---
                    visible_text = _extract_visible_text(body)
                    matches = _match_identifiers(
                        visible_text, email, full_name, phone, usernames
                    )

                    if not matches:
                        continue

                    # Use the first match for the primary snippet.
                    first = matches[0]
                    snippet = _build_snippet(visible_text, first["start"])

                    matched_fields = list({m["field"] for m in matches})
                    matched_data = {m["field"]: m["value"] for m in matches}
                    match_type = first["match_type"]

                    # Collect linked identifiers from page content.
                    linked = _find_linked_identifiers(visible_text)

                    category = _classify_url(url)

                    findings.append(
                        {
                            "source_type": "scraping",
                            "source_name": f"Ethical Scraper - {host}",
                            "source_url": url,
                            "matched_fields": matched_fields,
                            "matched_data": matched_data,
                            "snippet": snippet,
                            "category": category,
                            "match_type": match_type,
                            "linked_identifiers": linked,
                            "confirmed_by_service": False,
                        }
                    )

                except httpx.TimeoutException:
                    errors.append(f"Ethical scraper: timed out fetching '{url}'.")
                except httpx.HTTPError as exc:
                    errors.append(f"Ethical scraper: HTTP error for '{url}': {exc}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"Ethical scraper: error processing '{url}': {exc}")

    except Exception as exc:  # noqa: BLE001
        errors.append(f"Ethical scraper: unexpected error: {exc}")

    return {
        "findings": findings,
        "api_calls_made": api_calls,
        "sources_checked": sum(host_page_counts.values()),
        "pages_scanned": pages_scanned,
        "errors": errors,
        "service_name": SERVICE_NAME,
    }
