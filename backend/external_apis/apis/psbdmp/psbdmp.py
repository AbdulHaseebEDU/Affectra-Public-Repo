# searches psbdmp.ws paste archive for the target email or usernames
# GET https://psbdmp.ws/api/v3/search/{query} — no auth needed
# each hit becomes a finding with the paste URL, snippet, and match metadata

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

_BASE = "https://psbdmp.ws/api/v3/search"
_UA = "Affectra/1.0 (+academic prototype; PII self-check tool; responsible-use only)"
_TIMEOUT = 10.0


def _make_finding(
    paste_id: str,
    query: str,
    snippet: str,
    match_type: str,
) -> Dict[str, Any]:
    # Build a single finding dict from a paste hit.
    return {
        "source_type": "api",
        "source_name": "psbdmp",
        "source_url": f"https://psbdmp.ws/api/b/{paste_id}",
        "matched_fields": ["email"] if match_type == "email" else ["username"],
        "matched_data": {"email": query} if match_type == "email" else {"username": query},
        "snippet": snippet,
        "category": "paste_exposure",
        "match_type": "exact",
        "linked_identifiers": [],
        "confirmed_by_service": True,
    }


def _search_term(
    client: httpx.Client,
    term: str,
    match_type: str,
    findings: List[Dict[str, Any]],
    errors: List[str],
    limits: Dict[str, int],
) -> int:
    # Search a single term and append results. Returns API calls made.
    api_calls = 0
    try:
        url = f"{_BASE}/{term}"
        resp = client.get(url)
        api_calls += 1
        resp.raise_for_status()
        data = resp.json()

        # psbdmp returns a list of paste objects or a dict with a "data" key
        pastes: list = []
        if isinstance(data, list):
            pastes = data
        elif isinstance(data, dict):
            pastes = data.get("data", data.get("results", []))
            if isinstance(pastes, dict):
                pastes = []

        max_results = limits.get("max_results", 25)
        for paste in pastes[:max_results]:
            paste_id = paste.get("id", paste.get("dump_id", ""))
            snippet_text = paste.get("text", paste.get("content", ""))
            if isinstance(snippet_text, str) and len(snippet_text) > 300:
                snippet_text = snippet_text[:300] + "..."
            if not snippet_text:
                snippet_text = f"Paste {paste_id} matched query '{term}'"
            findings.append(
                _make_finding(
                    paste_id=str(paste_id),
                    query=term,
                    snippet=snippet_text,
                    match_type=match_type,
                )
            )
    except httpx.HTTPStatusError as exc:
        errors.append(f"psbdmp: HTTP {exc.response.status_code} for query '{term}'")
    except httpx.RequestError as exc:
        errors.append(f"psbdmp: request failed for query '{term}' -- {exc}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"psbdmp: unexpected error for query '{term}' -- {exc}")
    return api_calls


def query(
    email: Optional[str] = None,
    full_name: Optional[str] = None,
    phone: Optional[str] = None,
    usernames: Optional[List[str]] = None,
    limits: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    limits = limits or {}
    findings: List[Dict[str, Any]] = []
    errors: List[str] = []
    total_api_calls = 0
    sources_checked = 0

    headers = {"User-Agent": _UA}

    try:
        with httpx.Client(headers=headers, timeout=_TIMEOUT) as client:
            # Search by email
            if email:
                sources_checked += 1
                total_api_calls += _search_term(
                    client, email, "email", findings, errors, limits
                )

            # Search by each username
            for uname in (usernames or []):
                if uname and uname.strip():
                    sources_checked += 1
                    total_api_calls += _search_term(
                        client, uname.strip(), "username", findings, errors, limits
                    )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"psbdmp: client setup failed -- {exc}")

    return {
        "findings": findings,
        "api_calls_made": total_api_calls,
        "sources_checked": sources_checked,
        "pages_scanned": 0,
        "errors": errors,
        "service_name": "psbdmp",
    }
