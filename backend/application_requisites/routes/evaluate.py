# evaluation endpoints: FPR measurement and risk-scoring sensitivity analysis

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ...app_controller import run_scan
from ...internal_api.risk_scoring import (
    _CATEGORY_WEIGHT,
    _FIELD_BONUS_CAP,
    _FIELD_SENSITIVITY,
    _bucket,
    overall_risk,
)
from ..models import ScanMode
from ..models.requests import NormalizedQuery
from ..models.responses import ExposureCategory
from ..utils.normalizer import normalize_request

router = APIRouter()


# ── Coverage Comparison (no CAPTCHA — evaluation use only) ────────────────────

class EvalCompareRequest(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    usernames: Optional[List[str]] = None
    phone: Optional[str] = None


@router.post("/evaluate/compare")
def evaluate_compare(req: EvalCompareRequest) -> dict:
    """Run all four scan modes against the same input. No CAPTCHA required
    because this endpoint is intended for the in-app evaluation page only."""
    from ..models.requests import ScanRequest
    from ...app_controller import run_scan as _run

    # Build a normalised query directly (bypass CAPTCHA + EmailStr validation)
    query = NormalizedQuery(
        email=req.email or None,
        full_name=req.full_name or None,
        usernames=req.usernames or [],
    )
    if query.is_empty():
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Provide at least one identifier.")

    runs = []
    full_results = {}
    for mode in (ScanMode.API_ONLY, ScanMode.HYBRID, ScanMode.DEEP_SCAN, ScanMode.EXTENDED_EXPLORATION):
        resp = _run(query, mode)
        full_results[mode.value] = resp.model_dump(mode="json")
        md = resp.scan_metadata
        sm = resp.summary
        runs.append({
            "mode": mode.value,
            "total_exposures": sm.total_exposures,
            "sources_checked": md.sources_checked,
            "pages_scanned": md.pages_scanned,
            "api_calls_made": md.api_calls_made,
            "matches_found": md.matches_found,
            "runtime_delta_ms": md.runtime_delta_ms,
            "overall_risk_level": sm.overall_risk_level.value,
            "overall_risk_score": sm.overall_risk_score,
            "apis_attempted": md.apis_attempted,
            "apis_succeeded": md.apis_succeeded,
            "apis_skipped": md.apis_skipped,
        })

    api_base = runs[0]["total_exposures"]
    extended = runs[-1]["total_exposures"]
    uplift = round((extended - api_base) / api_base * 100, 2) if api_base else (100.0 if extended else 0.0)
    overhead = round(runs[-1]["runtime_delta_ms"] - runs[0]["runtime_delta_ms"], 2)

    return {
        "query_summary": query.model_dump(),
        "runs": runs,
        "coverage_uplift_pct": uplift,
        "runtime_overhead_ms": overhead,
        "full_results": full_results,
    }


# ── False Positive Rate ────────────────────────────────────────────────────────
#
# Runs API_ONLY scans against a small set of identifiers that are guaranteed
# not to belong to any real person (RFC-reserved .invalid TLD, nonsense names).
# Every finding returned counts as a false positive by construction.

_FPR_QUERIES: List[NormalizedQuery] = [
    NormalizedQuery(email="clean.test.affectra.9x@nonexistent.invalid"),
    NormalizedQuery(full_name="Zxqvbn Qrstuvwx Noreality"),
    NormalizedQuery(usernames=["affectratestclean9xyzqw"]),
]

_FPR_LABELS = [
    "Fabricated email (RFC .invalid TLD)",
    "Nonsense full name",
    "Random username string",
]


@router.post("/evaluate/fpr")
def evaluate_fpr() -> Dict[str, Any]:
    """Estimate false positive rate using known-clean fabricated identifiers."""
    per_query = []
    total_fps = 0

    for query, label in zip(_FPR_QUERIES, _FPR_LABELS):
        t0 = time.perf_counter()
        resp = run_scan(query, ScanMode.API_ONLY)
        runtime_ms = round((time.perf_counter() - t0) * 1000, 1)
        fps = resp.summary.total_exposures
        total_fps += fps
        per_query.append({
            "label": label,
            "query": {k: v for k, v in query.model_dump().items() if v},
            "false_positives": fps,
            "runtime_ms": runtime_ms,
            "apis_attempted": resp.scan_metadata.apis_attempted,
            "apis_succeeded": resp.scan_metadata.apis_succeeded,
        })

    total_queries = len(_FPR_QUERIES)
    # FP rate = FPs / (FPs + true negatives per query treated as 1 each)
    fpr_pct = round(total_fps / max(1, total_queries + total_fps) * 100, 2)

    return {
        "total_queries": total_queries,
        "total_false_positives": total_fps,
        "false_positive_rate_pct": fpr_pct,
        "per_query": per_query,
        "methodology": (
            "API_ONLY mode against RFC-reserved .invalid domain email, a "
            "nonsense name, and a random username string. Any result returned "
            "is a false positive by construction."
        ),
    }


# ── Risk Scoring Sensitivity ───────────────────────────────────────────────────
#
# Re-scores a caller-supplied set of findings with three weight profiles:
#   conservative  — category base × 0.80, field bonus × 0.80
#   balanced      — category base × 1.00, field bonus × 1.00  (current default)
#   aggressive    — category base × 1.20, field bonus × 1.20
#
# Shows how much the overall risk conclusion depends on the chosen weights.


class SensitivityFinding(BaseModel):
    source_name: str
    classification: str
    matched_fields: List[str]
    confidence_score: float
    current_risk_score: float


class SensitivityRequest(BaseModel):
    findings: List[SensitivityFinding]


@router.post("/evaluate/sensitivity")
def evaluate_sensitivity(req: SensitivityRequest) -> Dict[str, Any]:
    """Re-score findings with conservative / balanced / aggressive weight sets."""
    if not req.findings:
        return {"per_finding": [], "overall": {}, "methodology": ""}

    _PROFILES = [
        ("conservative", 0.80),
        ("balanced",     1.00),
        ("aggressive",   1.20),
    ]

    per_finding = []
    profile_scores: Dict[str, List[float]] = {p: [] for p, _ in _PROFILES}

    for f in req.findings:
        try:
            cat = ExposureCategory(f.classification)
        except ValueError:
            cat = ExposureCategory.UNKNOWN

        base = _CATEGORY_WEIGHT.get(cat, 18)
        raw_field = sum(_FIELD_SENSITIVITY.get(fld, 0) for fld in set(f.matched_fields))
        cf = 0.4 + 0.6 * (f.confidence_score / 100.0)

        row: Dict[str, Any] = {
            "source_name": f.source_name,
            "classification": f.classification,
            "baseline": f.current_risk_score,
        }
        for label, mult in _PROFILES:
            b = base * mult
            fb = min(raw_field * mult, _FIELD_BONUS_CAP)
            score = round(max(0.0, min(100.0, (b + fb) * cf)), 2)
            row[label] = score
            profile_scores[label].append(score)
        per_finding.append(row)

    # compute overall risk per profile using the same formula as the scanner
    overall: Dict[str, Any] = {}
    for label, _ in _PROFILES:
        scores = profile_scores[label]
        top = max(scores)
        avg = sum(scores) / len(scores)
        critical_n = sum(1 for s in scores if s >= 75)
        high_n = sum(1 for s in scores if 52 <= s < 75)
        volume = min(10.0, critical_n * 2.0 + high_n * 1.0)
        risk = round(min(100.0, 0.65 * top + 0.25 * avg + volume), 2)
        overall[label] = {
            "risk_score": risk,
            "hygiene_score": round(max(0.0, 100.0 - risk), 2),
            "risk_level": _bucket(risk).value,
        }

    return {
        "per_finding": per_finding,
        "overall": overall,
        "methodology": (
            "Category base weights and field sensitivity bonuses scaled by "
            "±20 % relative to the default (balanced) values. The overall "
            "score formula is unchanged: 65 % top + 25 % average + volume escalator."
        ),
    }
