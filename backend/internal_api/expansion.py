# pulls new identifiers out of each round's findings and feeds them back into
# the pipeline for EXTENDED_EXPLORATION — bounded by max_recursion_depth.
# only follows identifiers that adapters explicitly surface (no arbitrary crawling).
#
# all newly discovered emails, names, phones, and usernames are accumulated —
# not just the first one — so a round that surfaces three new usernames
# passes all three to the next round's query.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Set

from ..application_requisites.models import NormalizedQuery
from ..application_requisites.utils.normalizer import (
    normalize_email,
    normalize_name,
    normalize_phone,
    normalize_usernames,
)

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


@dataclass
class SeenIdentifiers:
    emails:     Set[str] = field(default_factory=set)
    usernames:  Set[str] = field(default_factory=set)
    full_names: Set[str] = field(default_factory=set)
    phones:     Set[str] = field(default_factory=set)

    def absorb(self, q: NormalizedQuery) -> None:
        if q.email:
            self.emails.add(q.email)
        if q.full_name:
            self.full_names.add(q.full_name)
        if q.phone:
            self.phones.add(q.phone)
        for u in q.usernames:
            self.usernames.add(u)


def collect_new_identifiers(
    findings: List[dict],
    seen: SeenIdentifiers,
) -> NormalizedQuery:
    """Extract identifiers surfaced by this round that haven't been queried yet.

    Returns a NormalizedQuery whose non-empty fields contain new identifiers.
    The caller merges this into the working query and checks is_empty() to
    decide whether to continue recursing.

    All discovered usernames are accumulated (not just the first); additional
    discovered emails beyond the first are appended to the username list so
    the next round probes each of them as well.
    """
    new_emails: List[str] = []
    new_users:  List[str] = []
    new_names:  List[str] = []
    new_phones: List[str] = []

    for f in findings:
        linked = f.get("linked_identifiers") if isinstance(f, dict) else None
        if not linked:
            continue
        if not isinstance(linked, dict):
            linked = {"usernames": list(linked) if isinstance(linked, list) else []}

        # ── usernames (may include misrouted emails) ──────────────────────────
        for u in linked.get("usernames", []) or []:
            if not isinstance(u, str):
                continue
            stripped = u.strip().lower()
            if _EMAIL_RE.match(stripped):
                try:
                    ne = normalize_email(u)
                    if ne and ne not in seen.emails and ne not in new_emails:
                        new_emails.append(ne)
                except ValueError:
                    pass
                continue
            try:
                cleaned = normalize_usernames([u])
                if cleaned and cleaned[0] not in seen.usernames and cleaned[0] not in new_users:
                    new_users.append(cleaned[0])
            except ValueError:
                continue

        # ── emails ───────────────────────────────────────────────────────────
        for e in linked.get("emails", []) or []:
            try:
                ne = normalize_email(e)
                if ne and ne not in seen.emails and ne not in new_emails:
                    new_emails.append(ne)
            except ValueError:
                continue

        # ── full names ────────────────────────────────────────────────────────
        for n in linked.get("full_names", []) or []:
            try:
                nn = normalize_name(n)
                if nn and nn not in seen.full_names and nn not in new_names:
                    new_names.append(nn)
            except ValueError:
                continue

        # ── phones ───────────────────────────────────────────────────────────
        for p in linked.get("phones", []) or []:
            try:
                np_ = normalize_phone(p)
                if np_ and np_ not in seen.phones and np_ not in new_phones:
                    new_phones.append(np_)
            except ValueError:
                continue

    # Carry ALL discovered usernames; additional emails (beyond the first) are
    # appended so the next round probes each of them as a username identifier.
    combined_users = list(dict.fromkeys(new_users + new_emails[1:]))

    return NormalizedQuery(
        email=new_emails[0] if new_emails else None,
        full_name=new_names[0] if new_names else None,
        phone=new_phones[0] if new_phones else None,
        usernames=combined_users,
    )
