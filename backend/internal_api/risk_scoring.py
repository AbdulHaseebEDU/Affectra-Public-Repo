# scores how serious each exposure is, independent of identity confidence
#
# per-finding score:
#   base weight   — determined by ExposureCategory (breach > paste > broker …)
#   field bonus   — sensitive fields (phone, email) raise the stakes; capped
#   confidence    — a low-confidence finding is discounted so users aren't
#                   alarmed by probable false positives
#   final clamped to [0, 100] and bucketed into a RiskLevel
#
# overall_risk:
#   65 % top score + 25 % cohort average + volume escalator (up to +10)
#   the escalator reflects that 20 critical findings are worse than 1.

from __future__ import annotations

from typing import List, Tuple

from ..application_requisites.models import (
    ExposureCategory,
    ExposureResult,
    RiskLevel,
)

# base danger score per category
_CATEGORY_WEIGHT: dict[ExposureCategory, int] = {
    ExposureCategory.POTENTIAL_BREACH:  92,   # credentials confirmed compromised
    ExposureCategory.PASTE_EXPOSURE:    80,   # raw dump — often includes passwords
    ExposureCategory.DATA_BROKER:       70,   # aggregated PII sold/indexed publicly
    ExposureCategory.CODE_REPOSITORY:   60,   # secrets / private data in source code
    ExposureCategory.DOCUMENT:          55,   # file containing personal information
    ExposureCategory.PUBLIC_DIRECTORY:  45,   # structured listing (e.g. people-finder)
    ExposureCategory.HISTORICAL_CACHE:  38,   # archived copy — less urgent, stale data
    ExposureCategory.FORUM_MENTION:     32,   # public post mentioning the target
    ExposureCategory.SOCIAL_TRACE:      22,   # public profile — expected, low urgency
    ExposureCategory.UNKNOWN:           18,
}

# per-field sensitivity bonus
_FIELD_SENSITIVITY: dict[str, int] = {
    "phone":     18,   # enables direct contact / SIM-swap attacks
    "email":     12,   # core identity anchor for most online services
    "full_name":  8,   # personal but widely published voluntarily
    "username":   4,   # pseudonym, lower inherent sensitivity
}

# cap so all-four-fields can't inflate a low-category base past CRITICAL alone
_FIELD_BONUS_CAP = 28


def _bucket(score: float) -> RiskLevel:
    if score >= 75:
        return RiskLevel.CRITICAL
    if score >= 52:
        return RiskLevel.HIGH
    if score >= 28:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def score_risk(exposures: List[ExposureResult]) -> List[ExposureResult]:
    for e in exposures:
        base = _CATEGORY_WEIGHT.get(e.classification, 18)

        # Unique fields only — the same field name twice adds nothing.
        field_bonus = min(
            sum(_FIELD_SENSITIVITY.get(f, 0) for f in set(e.matched_fields)),
            _FIELD_BONUS_CAP,
        )

        # Confidence factor: score 100 → 1.0; score 0 → 0.4.
        # A speculative find should never reach CRITICAL risk.
        confidence_factor = 0.4 + 0.6 * (e.confidence_score / 100.0)

        raw = (base + field_bonus) * confidence_factor
        e.risk_score = round(max(0.0, min(100.0, raw)), 2)
        e.risk_level = _bucket(e.risk_score)

    return exposures


def overall_risk(exposures: List[ExposureResult]) -> Tuple[float, RiskLevel]:
    """Compute an aggregate risk score and level for the whole scan result.

    Components:
      65 % — worst individual finding (anchors the overall level)
      25 % — cohort average (raises the floor when many findings exist)
      10 % — volume escalator (more high/critical findings → higher overall)
    """
    if not exposures:
        return 0.0, RiskLevel.LOW

    top = max(e.risk_score for e in exposures)
    avg = sum(e.risk_score for e in exposures) / len(exposures)

    critical_n = sum(1 for e in exposures if e.risk_level == RiskLevel.CRITICAL)
    high_n     = sum(1 for e in exposures if e.risk_level == RiskLevel.HIGH)
    volume_bonus = min(10.0, critical_n * 2.0 + high_n * 1.0)

    score = round(min(100.0, 0.65 * top + 0.25 * avg + volume_bonus), 2)
    return score, _bucket(score)
