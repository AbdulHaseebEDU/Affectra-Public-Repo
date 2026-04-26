# GitHub user search via the REST API.
# Endpoints:
#   GET https://api.github.com/search/users?q={email_or_username}
#   GET https://api.github.com/users/{username}
# Set GITHUB_TOKEN to get 5 000 req/hr instead of the default 60.

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import httpx

from ...api_keys.keys import get_key

_BASE = "https://api.github.com"
_UA = "Affectra/1.0 (+academic prototype; PII self-check tool; responsible-use only)"
_TIMEOUT = 10.0


# builds headers and also tells the caller whether we have a token
def _build_headers() -> tuple[Dict[str, str], bool]:
    headers: Dict[str, str] = {
        "User-Agent": _UA,
        "Accept": "application/vnd.github+json",
    }
    token = get_key("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
        return headers, True
    return headers, False


# packs a GitHub profile dict into our standard finding shape
def _profile_finding(
    user: Dict[str, Any],
    query_term: str,
    match_type: str,
) -> Dict[str, Any]:
    linked: List[str] = []
    if user.get("login"):
        linked.append(user["login"])
    if user.get("email"):
        linked.append(user["email"])
    if user.get("twitter_username"):
        linked.append(user["twitter_username"])

    parts: List[str] = []
    if user.get("name"):
        parts.append(f"Name: {user['name']}")
    if user.get("bio"):
        parts.append(f"Bio: {user['bio']}")
    if user.get("company"):
        parts.append(f"Company: {user['company']}")
    if user.get("location"):
        parts.append(f"Location: {user['location']}")
    if user.get("public_repos") is not None:
        parts.append(f"Public repos: {user['public_repos']}")
    if user.get("email"):
        parts.append(f"Email: {user['email']}")
    snippet = "; ".join(parts) if parts else f"GitHub user {user.get('login', '?')}"

    matched_fields: List[str] = []
    if match_type == "email":
        matched_fields.append("email")
    else:
        matched_fields.append("username")

    matched_data_dict: Dict[str, str] = (
        {"email": query_term} if match_type == "email" else {"username": query_term}
    )

    return {
        "source_type": "api",
        "source_name": "github",
        "source_url": user.get("html_url", f"https://github.com/{user.get('login', '')}"),
        "matched_fields": matched_fields,
        "matched_data": matched_data_dict,
        "snippet": snippet[:500],
        "category": "code_repository",
        "match_type": "exact",
        "linked_identifiers": linked,
        "confirmed_by_service": True,
    }


# lowercase + strip non-alphanumeric, used for fuzzy comparisons
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


# confirms the profile actually belongs to our target, not just a name collision
def _is_strong_match(
    profile: Dict[str, Any],
    *,
    email: Optional[str],
    full_name: Optional[str],
    usernames: List[str],
) -> bool:
    # passes if login, email, or name matches exactly, or if target identifiers
    # show up in the bio/blog/company fields (usernames must be >=3 chars to avoid noise)
    login = _norm(profile.get("login"))
    name = _norm(profile.get("name"))
    p_email = (profile.get("email") or "").lower()
    blog = (profile.get("blog") or "").lower()
    bio = (profile.get("bio") or "").lower()
    company = (profile.get("company") or "").lower()

    target_usernames = [_norm(u) for u in (usernames or []) if u]
    target_usernames = [u for u in target_usernames if u]
    target_name = _norm(full_name) if full_name else ""
    target_email = (email or "").lower()
    target_local = target_email.split("@", 1)[0] if "@" in target_email else ""

    # 1. Exact login match to a target username.
    if login and login in target_usernames:
        return True

    # 2. Exact email match on public profile email.
    if target_email and p_email == target_email:
        return True

    # 3. Full-name exact match (normalized).
    if target_name and name == target_name:
        return True

    # 4. Target email / username appears in blog / bio / public email /
    #    company field. Usernames must be >=3 chars to avoid "al" hits.
    needles: List[str] = []
    if target_email:
        needles.append(target_email)
    if target_local and len(target_local) >= 3:
        needles.append(target_local)
    for u in usernames or []:
        if u and len(u) >= 3:
            needles.append(u.lower())

    haystack = " ".join([blog, bio, p_email, company])
    for n in needles:
        if n and n in haystack:
            return True

    return False


# runs the user search and fetches a full profile for each candidate
def _search_users(
    client: httpx.Client,
    term: str,
    match_type: str,
    findings: List[Dict[str, Any]],
    errors: List[str],
    limits: Dict[str, int],
    *,
    strict: bool,
    email: Optional[str],
    full_name: Optional[str],
    usernames: List[str],
) -> int:
    api_calls = 0
    max_results = limits.get("max_results", 10)

    try:
        resp = client.get(f"{_BASE}/search/users", params={"q": term})
        api_calls += 1
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
    except httpx.HTTPStatusError as exc:
        errors.append(f"github: HTTP {exc.response.status_code} searching '{term}'")
        return api_calls
    except httpx.RequestError as exc:
        errors.append(f"github: request failed searching '{term}' -- {exc}")
        return api_calls
    except Exception as exc:  # noqa: BLE001
        errors.append(f"github: unexpected error searching '{term}' -- {exc}")
        return api_calls

    # in strict mode, skip the profile fetch entirely for obvious non-matches
    # — saves rate limit and wall time
    kept = 0
    dropped_cheap = 0
    for item in items[:max_results]:
        login = item.get("login")
        if not login:
            continue

        # cheap pre-check before spending a profile API call on a bad candidate
        if strict:
            login_norm = _norm(login)
            target_usernames = [_norm(u) for u in (usernames or []) if u]
            exact = login_norm in target_usernames
            if not exact and _norm(term) and _norm(term) not in login_norm:
                # Not an obvious match — skip the profile fetch entirely.
                dropped_cheap += 1
                continue

        try:
            profile_resp = client.get(f"{_BASE}/users/{login}")
            api_calls += 1
            profile_resp.raise_for_status()
            profile = profile_resp.json()
        except httpx.HTTPStatusError as exc:
            errors.append(
                f"github: HTTP {exc.response.status_code} fetching profile '{login}'"
            )
            # Fall back to search-result data
            profile = item
        except httpx.RequestError as exc:
            errors.append(f"github: request failed fetching profile '{login}' -- {exc}")
            profile = item
        except Exception as exc:  # noqa: BLE001
            errors.append(f"github: unexpected error fetching profile '{login}' -- {exc}")
            profile = item

        if strict and not _is_strong_match(
            profile,
            email=email,
            full_name=full_name,
            usernames=usernames,
        ):
            continue

        findings.append(_profile_finding(profile, term, match_type))
        kept += 1

    if strict and items and kept == 0:
        errors.append(
            f"github: strict filter rejected {len(items)} loose match(es) for '{term}'"
            + (f" ({dropped_cheap} pre-skipped)" if dropped_cheap else "")
        )

    return api_calls


# main entry point — phone is accepted but ignored, GitHub has no phone lookup
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

    strict = bool(limits.get("strict_github", True))
    usernames_list = list(usernames or [])

    headers, has_token = _build_headers()
    if not has_token:
        errors.append(
            "github: GITHUB_TOKEN not set -- proceeding with 60 req/hr public rate limit"
        )

    try:
        with httpx.Client(headers=headers, timeout=_TIMEOUT) as client:
            # search by email
            if email:
                sources_checked += 1
                total_api_calls += _search_users(
                    client, email, "email",
                    findings, errors, limits,
                    strict=strict,
                    email=email,
                    full_name=full_name,
                    usernames=usernames_list,
                )

            # search by each username
            for uname in usernames_list:
                if uname and uname.strip():
                    sources_checked += 1
                    total_api_calls += _search_users(
                        client, uname.strip(), "username",
                        findings, errors, limits,
                        strict=strict,
                        email=email,
                        full_name=full_name,
                        usernames=usernames_list,
                    )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"github: client setup failed -- {exc}")

    return {
        "findings": findings,
        "api_calls_made": total_api_calls,
        "sources_checked": sources_checked,
        "pages_scanned": 0,
        "errors": errors,
        "service_name": "github",
    }
