# assigns an ExposureCategory to each exposure using three-tier fallback:
#   1. trust the adapter's own category if it set one (not UNKNOWN)
#   2. infer from source_name — adapters are named services with known categories
#   3. classify from source_url using domain heuristics
#   4. scan the snippet for category keywords as a last resort

from __future__ import annotations

from typing import List

from ..application_requisites.models import ExposureCategory, ExposureResult
from ..application_requisites.utils.helpers import classify_url


# known adapter names → their authoritative category
# these win over URL heuristics because the adapter knows what it found
_SOURCE_NAME_CATEGORY: dict[str, ExposureCategory] = {
    # breach / credential databases
    "XposedOrNot":                          ExposureCategory.POTENTIAL_BREACH,
    "HIBP Pwned Passwords":                 ExposureCategory.POTENTIAL_BREACH,
    "HIBP Pwned Passwords (k-anonymity)":   ExposureCategory.POTENTIAL_BREACH,
    # profile / identity probing
    "Gravatar":                             ExposureCategory.SOCIAL_TRACE,
    "Holehe":                               ExposureCategory.SOCIAL_TRACE,
    # paste / dump search
    "Psbdmp":                               ExposureCategory.PASTE_EXPOSURE,
    # code hosting
    "GitHub":                               ExposureCategory.CODE_REPOSITORY,
    # forum / community
    "Stack Exchange":                       ExposureCategory.FORUM_MENTION,
    # archive / scan history
    "URLScan":                              ExposureCategory.HISTORICAL_CACHE,
    "Wayback Machine":                      ExposureCategory.HISTORICAL_CACHE,
    # certificate transparency — surfacing domains, treated as public directory
    "crt.sh":                               ExposureCategory.PUBLIC_DIRECTORY,
}

# keyword groups matched against snippet text when both adapter and URL give no signal
_SNIPPET_SIGNALS: list[tuple[tuple[str, ...], ExposureCategory]] = [
    (
        ("breach", "pwned", "leaked", "compromised", "hacked", "credential", "data dump"),
        ExposureCategory.POTENTIAL_BREACH,
    ),
    (
        ("paste", "pastebin", "dump", "hastebin"),
        ExposureCategory.PASTE_EXPOSURE,
    ),
    (
        ("opt-out", "people search", "background check", "data broker", "public records"),
        ExposureCategory.DATA_BROKER,
    ),
    (
        ("repository", "commit", "gist", "source code", "pull request"),
        ExposureCategory.CODE_REPOSITORY,
    ),
    (
        ("forum", "thread", "post", "reply", "discussion"),
        ExposureCategory.FORUM_MENTION,
    ),
    (
        ("profile", "account", "social media", "bio", "avatar", "gravatar"),
        ExposureCategory.SOCIAL_TRACE,
    ),
    (
        ("directory", "listing", "yellow pages", "business listing"),
        ExposureCategory.PUBLIC_DIRECTORY,
    ),
    (
        ("archive", "cached", "wayback", "historical snapshot"),
        ExposureCategory.HISTORICAL_CACHE,
    ),
]


def _from_snippet(snippet: str | None) -> ExposureCategory:
    if not snippet:
        return ExposureCategory.UNKNOWN
    lower = snippet.lower()
    for keywords, category in _SNIPPET_SIGNALS:
        if any(kw in lower for kw in keywords):
            return category
    return ExposureCategory.UNKNOWN


def classify(exposures: List[ExposureResult]) -> List[ExposureResult]:
    """Assign a category to every exposure that is still UNKNOWN.

    Tier 1 — adapter-supplied category (already set by normalization, trusted).
    Tier 2 — source_name lookup against the known-adapter table.
    Tier 3 — URL domain heuristics.
    Tier 4 — snippet keyword scan as a last resort.
    """
    for e in exposures:
        if e.classification != ExposureCategory.UNKNOWN:
            continue  # adapter already classified this — trust it

        # tier 2: known adapter name
        by_name = _SOURCE_NAME_CATEGORY.get(e.source_name)
        if by_name is not None:
            e.classification = by_name
            continue

        # tier 3: URL domain heuristics
        by_url = classify_url(e.source_url)
        if by_url != ExposureCategory.UNKNOWN:
            e.classification = by_url
            continue

        # tier 4: snippet keyword scan
        e.classification = _from_snippet(e.snippet)

    return exposures
