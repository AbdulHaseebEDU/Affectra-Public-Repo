# builds the set of targeted search queries for a scan — decides where to look,
# doesn't fetch anything itself.
#
# single-field queries use exact-quoted strings for precision.
# multi-field combinations narrow results by correlating identifiers.
# EXTENDED_EXPLORATION adds unquoted broad queries and site-specific dorks.

from __future__ import annotations

from typing import List, Tuple

from ..application_requisites.models import NormalizedQuery


def build_queries(q: NormalizedQuery, mode: str) -> List[Tuple[str, str]]:
    """Return (query_string, field_label) pairs for the search layer.

    Order matters: the most specific identifiers are added first so adapters
    can short-circuit early if they hit a per-service cap.
    """
    out: List[Tuple[str, str]] = []

    # ── single-identifier exact-quoted queries ────────────────────────────────
    if q.email:
        out.append((f'"{q.email}"', "email"))
    if q.phone:
        out.append((f'"{q.phone}"', "phone"))
    if q.full_name:
        out.append((f'"{q.full_name}"', "full_name"))
    for u in q.usernames[:3]:
        out.append((f'"{u}"', "username"))

    # ── two-field combinations (high-precision correlations) ─────────────────
    if q.full_name and q.email:
        out.append((f'"{q.full_name}" "{q.email}"', "full_name+email"))
    if q.full_name and q.phone:
        out.append((f'"{q.full_name}" "{q.phone}"', "full_name+phone"))
    for u in q.usernames[:2]:
        if q.email:
            out.append((f'"{u}" "{q.email}"', "username+email"))
        if q.full_name:
            out.append((f'"{q.full_name}" "{u}"', "full_name+username"))

    # ── extended exploration: broader queries + platform-specific dorks ───────
    if mode == "EXTENDED_EXPLORATION":
        if q.full_name:
            out.append((f"{q.full_name} contact email", "full_name"))
            out.append((f"{q.full_name} phone number", "full_name"))
            out.append((f'site:linkedin.com "{q.full_name}"', "full_name"))
            out.append((f'site:github.com "{q.full_name}"', "full_name"))
            out.append((f'site:reddit.com "{q.full_name}"', "full_name"))

        if q.email:
            domain = q.email.split("@", 1)[1] if "@" in q.email else ""
            if domain:
                out.append((f"site:{domain} contact", "email_domain"))
            out.append((f'site:github.com "{q.email}"', "email"))
            out.append((f'site:linkedin.com "{q.email}"', "email"))

        for u in q.usernames[:5]:
            out.append((f"{u} profile bio", "username"))
            out.append((f'site:github.com "{u}"', "username"))
            out.append((f'site:reddit.com "u/{u}"', "username"))
            out.append((f'site:twitter.com "{u}"', "username"))
            out.append((f'site:stackoverflow.com/users "{u}"', "username"))

    return out
