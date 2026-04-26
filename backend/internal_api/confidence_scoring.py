# estimates how likely each exposure actually belongs to the queried person
#
# scoring components (max 100 before clamping):
#   source trust       — API > scraping > search
#   match exactness    — exact > partial > contextual
#   field coverage     — what fraction of the query's identifiers were matched
#   field specificity  — email/phone are stronger identifiers than name/username
#   data richness      — more matched_data fields = more structured evidence
#   multi-source boost — same finding confirmed by ≥2 independent services
#   snippet bonus      — adapter found enough context to write a quote
#
# final score is clamped to [0, 100] and bucketed into a ConfidenceLevel

from __future__ import annotations

from typing import List, Set

from ..application_requisites.models import (
    ConfidenceLevel,
    ExposureResult,
    MatchType,
    NormalizedQuery,
    SourceType,
)

# how uniquely identifying is each field type?
# email and phone are globally unique; usernames are platform-unique;
# full names are very common and weak alone.
_FIELD_SPECIFICITY: dict[str, float] = {
    "email":     14.0,
    "phone":     12.0,
    "username":   7.0,
    "full_name":  3.0,
}


def _query_field_set(q: NormalizedQuery) -> Set[str]:
    s: Set[str] = set()
    if q.email:
        s.add("email")
    if q.full_name:
        s.add("full_name")
    if q.phone:
        s.add("phone")
    if q.usernames:
        s.add("username")
    return s


def _bucket(score: float) -> ConfidenceLevel:
    if score >= 70:
        return ConfidenceLevel.HIGH
    if score >= 40:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def score_confidence(
    exposures: List[ExposureResult],
    query: NormalizedQuery,
) -> List[ExposureResult]:
    qf = _query_field_set(query)

    for e in exposures:
        score = 0.0

        # ── source-type trust ────────────────────────────────────────────────
        # API adapters query live databases directly; scrapers and search engines
        # add noise through page-content ambiguity.
        if e.source_type == SourceType.API:
            score += 30
        elif e.source_type == SourceType.SCRAPING:
            score += 20
        else:   # SEARCH
            score += 10

        # ── match exactness ──────────────────────────────────────────────────
        if e.match_type == MatchType.EXACT:
            score += 22
        elif e.match_type == MatchType.PARTIAL:
            score += 12
        else:   # CONTEXTUAL — loosest evidence
            score += 4

        # ── field coverage ───────────────────────────────────────────────────
        # What fraction of the query's provided identifiers appear in this finding?
        if qf:
            matched_qf = set(e.matched_fields) & qf
            coverage = len(matched_qf) / len(qf)
            if coverage >= 1.0:
                score += 18
                # Solo-input boost: user submitted one identifier and it matched —
                # that's strong signal, not just high coverage by accident.
                if len(qf) == 1:
                    score += 6
            elif coverage >= 0.5:
                score += 10
            elif coverage > 0:
                score += 4

        # ── field specificity ────────────────────────────────────────────────
        # Weight each matched field by how uniquely identifying it is globally.
        # Capped at 16 so all-four-fields doesn't unfairly dominate.
        specificity_bonus = sum(
            _FIELD_SPECIFICITY.get(f, 2.0) for f in set(e.matched_fields)
        )
        score += min(specificity_bonus, 16.0)

        # ── data richness ────────────────────────────────────────────────────
        # Structured matched_data (multiple keyed values) means the adapter
        # returned real database evidence, not just a page mention.
        data_depth = len(e.matched_data)
        if data_depth >= 4:
            score += 6
        elif data_depth >= 2:
            score += 3
        elif data_depth == 1:
            score += 1

        # ── snippet bonus ────────────────────────────────────────────────────
        # A snippet means the adapter extracted quoted context, which is stronger
        # evidence than a bare URL match with no supporting text.
        if e.snippet:
            score += 4

        # ── multi-source confirmation ────────────────────────────────────────
        # The same finding independently confirmed by multiple services is the
        # single strongest confidence signal available.
        if e.source_count >= 3:
            score += 18
        elif e.source_count == 2:
            score += 9

        e.confidence_score = round(max(0.0, min(100.0, score)), 2)
        e.confidence_level = _bucket(e.confidence_score)

    return exposures
