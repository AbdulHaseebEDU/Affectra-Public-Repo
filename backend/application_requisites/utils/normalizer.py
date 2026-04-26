# normalize and validate incoming scan request fields

from __future__ import annotations

import re
from typing import List, Optional

from ..models import NormalizedQuery, ScanRequest

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_PHONE_DIGITS_RE = re.compile(r"\D+")
_NAME_WS_RE = re.compile(r"\s+")


def normalize_email(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip().lower()
    if not _EMAIL_RE.match(cleaned):
        raise ValueError(f"Invalid email format: {raw!r}")
    return cleaned


def normalize_phone(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip()
    has_plus = raw.startswith("+")
    digits = _PHONE_DIGITS_RE.sub("", raw)
    if len(digits) < 7:
        raise ValueError(f"Phone number too short: {raw!r}")
    return f"+{digits}" if has_plus else digits


def normalize_name(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    cleaned = _NAME_WS_RE.sub(" ", raw.strip())
    return cleaned.title() if cleaned else None


def normalize_usernames(raw: Optional[List[str]]) -> List[str]:
    if not raw:
        return []
    seen: set[str] = set()
    cleaned: List[str] = []
    for u in raw:
        if not u:
            continue
        c = u.strip().lower()
        if c and c not in seen:
            seen.add(c)
            cleaned.append(c)
    return cleaned


def normalize_request(req: ScanRequest) -> NormalizedQuery:
    raw_users: List[str] = []
    if req.username:
        raw_users.append(req.username)
    if req.usernames:
        raw_users.extend(req.usernames)
    return NormalizedQuery(
        email=normalize_email(req.email),
        full_name=normalize_name(req.full_name),
        phone=normalize_phone(req.phone),
        usernames=normalize_usernames(raw_users),
    )
