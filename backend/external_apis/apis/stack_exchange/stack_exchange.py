# Stack Exchange user search using the public API.
# Endpoint: GET https://api.stackexchange.com/2.3/users?inname={name}&site=stackoverflow
# Set STACKEXCHANGE_KEY to bump the quota from 300 to 10 000 req/day.
# Works fine without the key, just hits the lower limit faster.

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import httpx

from ...api_keys.keys import get_key

_BASE = "https://api.stackexchange.com/2.3"
_UA = "Affectra/1.0 (+academic prototype; PII self-check tool; responsible-use only)"
_TIMEOUT = 10.0


# turns a raw API user object into our standard finding shape
def _user_finding(
    user: Dict[str, Any],
    query_term: str,
    match_type: str,
) -> Dict[str, Any]:
    linked: List[str] = []
    display_name = user.get("display_name", "")
    if display_name:
        linked.append(display_name)
    if user.get("link"):
        linked.append(user["link"])
    if user.get("website_url"):
        linked.append(user["website_url"])

    parts: List[str] = []
    if display_name:
        parts.append(f"Name: {display_name}")
    if user.get("reputation") is not None:
        parts.append(f"Reputation: {user['reputation']}")
    if user.get("location"):
        parts.append(f"Location: {user['location']}")
    if user.get("website_url"):
        parts.append(f"Website: {user['website_url']}")
    if user.get("answer_count") is not None:
        parts.append(f"Answers: {user['answer_count']}")
    if user.get("question_count") is not None:
        parts.append(f"Questions: {user['question_count']}")
    snippet = "; ".join(parts) if parts else f"Stack Exchange user #{user.get('user_id', '?')}"

    matched_fields: List[str] = []
    if match_type == "email":
        matched_fields.append("email")
    elif match_type == "full_name":
        matched_fields.append("full_name")
    else:
        matched_fields.append("username")

    profile_url = user.get("link", "")

    if match_type == "email":
        matched_data_dict: Dict[str, str] = {"email": query_term}
    elif match_type == "full_name":
        matched_data_dict = {"full_name": query_term}
    else:
        matched_data_dict = {"username": query_term}

    return {
        "source_type": "api",
        "source_name": "stack_exchange",
        "source_url": profile_url,
        "matched_fields": matched_fields,
        "matched_data": matched_data_dict,
        "snippet": snippet[:500],
        "category": "forum_mention",
        "match_type": "partial",
        "linked_identifiers": linked,
        "confirmed_by_service": True,
    }


# strips everything except alphanumerics for fuzzy equality checks
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


# inname= is a loose substring match, so we need this to avoid false positives
def _is_strong_match(
    user: Dict[str, Any],
    *,
    term: str,
    match_type: str,
    email: Optional[str],
    full_name: Optional[str],
    usernames: List[str],
) -> bool:
    # We don't check `link` here — it's the SO profile URL which always contains
    # the slugified display_name, so it would match anything we searched for.
    display = _norm(user.get("display_name", ""))
    website = (user.get("website_url") or "").lower()

    targets: List[str] = []
    if full_name:
        targets.append(_norm(full_name))
    for u in usernames or []:
        if u:
            targets.append(_norm(u))
    targets = [t for t in targets if t]

    # 1. Exact display name match against any target identifier.
    if display and display in targets:
        return True

    # 2. Email or username appears in the user's own website_url.
    #    Usernames must be ≥4 chars to avoid "tim" matching every Tim's blog.
    needles: List[str] = []
    if email:
        needles.append(email.lower())
        local = email.split("@", 1)[0].lower()
        if local and len(local) >= 4:
            needles.append(local)
    for u in usernames or []:
        if u and len(u) >= 4:
            needles.append(u.lower())

    if website:
        for needle in needles:
            if needle and needle in website:
                return True

    return False


# hits /users?inname= and filters results; returns number of API calls made
def _search_users(
    client: httpx.Client,
    term: str,
    match_type: str,
    api_key: Optional[str],
    findings: List[Dict[str, Any]],
    errors: List[str],
    limits: Dict[str, int],
    *,
    strict: bool,
    email: Optional[str],
    full_name: Optional[str],
    usernames: List[str],
) -> int:
    # strict=False is legacy/permissive mode, toggled from the Dev Menu
    api_calls = 0
    max_results = limits.get("max_results", 10)
    page_size = min(max_results, 30)

    params: Dict[str, Any] = {
        "inname": term,
        "site": "stackoverflow",
        "pagesize": page_size,
        "order": "desc",
        "sort": "reputation",
    }
    if api_key:
        params["key"] = api_key

    try:
        resp = client.get(f"{_BASE}/users", params=params)
        api_calls += 1
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        errors.append(
            f"stack_exchange: HTTP {exc.response.status_code} searching '{term}'"
        )
        return api_calls
    except httpx.RequestError as exc:
        errors.append(f"stack_exchange: request failed searching '{term}' -- {exc}")
        return api_calls
    except Exception as exc:  # noqa: BLE001
        errors.append(f"stack_exchange: unexpected error searching '{term}' -- {exc}")
        return api_calls

    items = data.get("items", [])
    kept = 0
    for user in items[:max_results]:
        if strict and not _is_strong_match(
            user,
            term=term,
            match_type=match_type,
            email=email,
            full_name=full_name,
            usernames=usernames,
        ):
            continue
        findings.append(_user_finding(user, term, match_type))
        kept += 1

    if strict and items and kept == 0:
        # Not an error — just telemetry so the user can see precision in action.
        errors.append(
            f"stack_exchange: strict filter rejected {len(items)} loose match(es) "
            f"for '{term}'"
        )

    return api_calls


# SE doesn't support email lookup, so we search by the local part as a heuristic
def _search_by_email(
    client: httpx.Client,
    email: str,
    api_key: Optional[str],
    findings: List[Dict[str, Any]],
    errors: List[str],
    limits: Dict[str, int],
    *,
    strict: bool,
    full_name: Optional[str],
    usernames: List[str],
) -> int:
    local_part = email.split("@")[0] if "@" in email else email
    if not local_part:
        return 0
    return _search_users(
        client,
        local_part,
        "email",
        api_key,
        findings,
        errors,
        limits,
        strict=strict,
        email=email,
        full_name=full_name,
        usernames=usernames,
    )


# main entry point — searches by email, full name, and each username
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

    # strict flag comes in via limits from the API controller; default True is the safe choice
    strict = bool(limits.get("strict_stack_exchange", True))
    usernames_list = list(usernames or [])

    api_key = get_key("STACKEXCHANGE_KEY")
    if not api_key:
        errors.append(
            "stack_exchange: STACKEXCHANGE_KEY not set -- "
            "proceeding with lower 300 req/day quota"
        )

    headers: Dict[str, str] = {"User-Agent": _UA}

    try:
        with httpx.Client(headers=headers, timeout=_TIMEOUT) as client:
            # email search uses the local part as a display name heuristic
            if email:
                sources_checked += 1
                total_api_calls += _search_by_email(
                    client,
                    email,
                    api_key,
                    findings,
                    errors,
                    limits,
                    strict=strict,
                    full_name=full_name,
                    usernames=usernames_list,
                )

            # full name
            if full_name and full_name.strip():
                sources_checked += 1
                total_api_calls += _search_users(
                    client,
                    full_name.strip(),
                    "full_name",
                    api_key,
                    findings,
                    errors,
                    limits,
                    strict=strict,
                    email=email,
                    full_name=full_name,
                    usernames=usernames_list,
                )

            # each username separately
            for uname in usernames_list:
                if uname and uname.strip():
                    sources_checked += 1
                    total_api_calls += _search_users(
                        client,
                        uname.strip(),
                        "username",
                        api_key,
                        findings,
                        errors,
                        limits,
                        strict=strict,
                        email=email,
                        full_name=full_name,
                        usernames=usernames_list,
                    )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"stack_exchange: client setup failed -- {exc}")

    return {
        "findings": findings,
        "api_calls_made": total_api_calls,
        "sources_checked": sources_checked,
        "pages_scanned": 0,
        "errors": errors,
        "service_name": "stack_exchange",
    }
