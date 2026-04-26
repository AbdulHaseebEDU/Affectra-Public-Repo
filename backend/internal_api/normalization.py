# converts raw adapter findings into a canonical ExposureResult shape and
# deduplicates across services — same (url, matched-data) from two adapters
# becomes one result with source_count = 2 and a merged confirmed_by list.
#
# ID stability: when matched_data is empty (e.g. a bare URL hit), source_name
# is included in the hash so two different adapters hitting the same URL do NOT
# incorrectly collapse into one finding.
#
# Snippet merging: when the same finding is seen by multiple adapters, the
# longer/more informative snippet wins regardless of source trust rank.

from __future__ import annotations

import hashlib
from typing import Dict, List

from ..application_requisites.models import (
    ConfidenceLevel,
    ExposureCategory,
    ExposureResult,
    MatchType,
    RiskLevel,
    SourceType,
)

# Source-type trust ranking. When the same (url, fields) pair is seen from
# multiple services, the highest-trust variant's metadata is preferred.
_TRUST = {
    "api":      3,
    "scraping": 2,
    "search":   1,
}


def _stable_id(url: str, matched_data: Dict, source_name: str = "") -> str:
    """Deterministic 16-char hex ID for a (url, matched_data) pair.

    When matched_data is empty we include source_name in the hash so that two
    different adapters finding the same URL are NOT merged (they have different
    evidence bases and should remain separate findings).
    """
    if matched_data:
        payload = url + "|" + "|".join(
            f"{k}={v}"
            for k, v in sorted(matched_data.items())
            if isinstance(v, (str, int, float, bool))
        )
    else:
        payload = url + "|" + source_name

    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _coerce_enum(value, enum_cls, default):
    """Turn a string into an enum member, or return default on failure."""
    if isinstance(value, enum_cls):
        return value
    if not value:
        return default
    try:
        return enum_cls(str(value).lower())
    except ValueError:
        for member in enum_cls:
            if member.name == str(value).upper():
                return member
        return default


def _better_snippet(current: str | None, candidate: str | None) -> str | None:
    """Return whichever snippet carries more information (longer wins)."""
    if not candidate:
        return current
    if not current:
        return candidate
    return candidate if len(candidate) > len(current) else current


def normalize_findings(raw_findings: List[dict], round_index: int = 0) -> List[ExposureResult]:
    """Promote raw adapter dicts into ExposureResult objects and deduplicate.

    Same (url, matched-data) across services → one result with source_count > 1
    and a merged confirmed_by list.  The highest-trust source's metadata
    (source_name, classification) is preferred; the longer snippet always wins.
    """
    by_id: Dict[str, ExposureResult] = {}
    trust_of: Dict[str, int] = {}

    for f in raw_findings:
        url         = f.get("source_url") or ""
        source_name = str(f.get("source_name") or "unknown")

        raw_matched = f.get("matched_data")
        matched_data: Dict[str, str] = (
            {k: str(v) for k, v in raw_matched.items() if isinstance(v, (str, int, float))}
            if isinstance(raw_matched, dict)
            else {}
        )

        rid   = _stable_id(url, matched_data, source_name)
        trust = _TRUST.get(str(f.get("source_type", "api")).lower(), 0)

        source_type  = _coerce_enum(f.get("source_type"), SourceType,      SourceType.API)
        match_type   = _coerce_enum(f.get("match_type"),  MatchType,        MatchType.EXACT)
        category     = _coerce_enum(f.get("category"),    ExposureCategory, ExposureCategory.UNKNOWN)
        confirmed_by = list(f.get("confirmed_by") or [])

        existing = by_id.get(rid)
        if existing is not None:
            # Merge: same evidence found by multiple services.
            for name in confirmed_by:
                if name not in existing.confirmed_by:
                    existing.confirmed_by.append(name)
            existing.source_count = len(existing.confirmed_by)

            # Fold in new matched fields / structured data from this source.
            for k, v in matched_data.items():
                if k not in existing.matched_data:
                    existing.matched_data[k] = str(v)
                if k not in existing.matched_fields:
                    existing.matched_fields.append(k)

            # Longer snippet always wins, regardless of source trust.
            existing.snippet = _better_snippet(existing.snippet, f.get("snippet"))

            # Upgrade primary metadata only if this source has higher trust.
            if trust > trust_of.get(rid, 0):
                existing.source_type = source_type
                existing.source_name = source_name
                if category != ExposureCategory.UNKNOWN:
                    existing.classification = category
                trust_of[rid] = trust
            continue

        by_id[rid] = ExposureResult(
            id=rid,
            source_type=source_type,
            source_name=source_name,
            source_url=url,
            match_type=match_type,
            matched_fields=list(f.get("matched_fields") or []),
            matched_data=matched_data,
            snippet=f.get("snippet"),
            classification=category,
            confidence_score=0.0,
            confidence_level=ConfidenceLevel.LOW,
            risk_score=0.0,
            risk_level=RiskLevel.LOW,
            mitigation=[],
            deletion_email_template=None,
            discovered_in_round=int(f.get("discovered_in_round") or round_index),
            confirmed_by=confirmed_by or [],
            source_count=max(1, len(confirmed_by)),
        )
        trust_of[rid] = trust

    return list(by_id.values())
