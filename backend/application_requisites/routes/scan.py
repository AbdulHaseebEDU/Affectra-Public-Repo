# scan endpoints: POST /api/scan, POST /api/scan/compare, GET /api/scan/modes

from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...app_controller import MODE_LIMITS, run_scan
from ..models import ScanMode, ScanRequest, ScanResponse
from ..utils.captcha import verify as verify_captcha
from ..utils.normalizer import normalize_request

router = APIRouter()


# POST /api/scan

@router.post("/scan", response_model=ScanResponse)
def scan(req: ScanRequest) -> ScanResponse:
    ok, reason = verify_captcha(req.hcaptcha_token or "")
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    if not req.has_any_identifier():
        raise HTTPException(
            status_code=422,
            detail=(
                "Provide at least one identifier "
                "(email, full_name, username, usernames, or phone)."
            ),
        )

    try:
        query = normalize_request(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if query.is_empty():
        raise HTTPException(
            status_code=422,
            detail="All supplied identifiers were rejected by the normalizer.",
        )

    return run_scan(query, req.scan_mode)


# POST /api/scan/compare

class CompareEntry(BaseModel):
    mode: ScanMode
    total_exposures: int
    sources_checked: int
    pages_scanned: int
    api_calls_made: int
    matches_found: int
    recursion_depth_reached: int
    runtime_delta_ms: float
    overall_risk_level: str
    overall_risk_score: float
    apis_attempted: int
    apis_succeeded: int
    apis_skipped: int


class CompareResponse(BaseModel):
    query_summary: dict
    runs: List[CompareEntry]
    coverage_uplift_pct: float
    runtime_overhead_ms: float
    full_results: Dict[str, ScanResponse]


# Run every mode for the same input and return comparable metrics.
@router.post("/scan/compare", response_model=CompareResponse)
def scan_compare(req: ScanRequest) -> CompareResponse:
    ok, reason = verify_captcha(req.hcaptcha_token or "")
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    if not req.has_any_identifier():
        raise HTTPException(status_code=422, detail="Provide at least one identifier.")

    try:
        query = normalize_request(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    runs: List[CompareEntry] = []
    full_results: Dict[str, ScanResponse] = {}
    for mode in (
        ScanMode.API_ONLY,
        ScanMode.HYBRID,
        ScanMode.DEEP_SCAN,
        ScanMode.EXTENDED_EXPLORATION,
    ):
        resp = run_scan(query, mode)
        full_results[mode.value] = resp
        runs.append(
            CompareEntry(
                mode=mode,
                total_exposures=resp.summary.total_exposures,
                sources_checked=resp.scan_metadata.sources_checked,
                pages_scanned=resp.scan_metadata.pages_scanned,
                api_calls_made=resp.scan_metadata.api_calls_made,
                matches_found=resp.scan_metadata.matches_found,
                recursion_depth_reached=resp.scan_metadata.recursion_depth_reached,
                runtime_delta_ms=resp.scan_metadata.runtime_delta_ms,
                overall_risk_level=resp.summary.overall_risk_level.value,
                overall_risk_score=resp.summary.overall_risk_score,
                apis_attempted=resp.scan_metadata.apis_attempted,
                apis_succeeded=resp.scan_metadata.apis_succeeded,
                apis_skipped=resp.scan_metadata.apis_skipped,
            )
        )

    api_baseline = runs[0].total_exposures
    extended = runs[-1].total_exposures
    if api_baseline:
        uplift = round((extended - api_baseline) / api_baseline * 100.0, 2)
    else:
        uplift = 100.0 if extended else 0.0

    overhead = round(runs[-1].runtime_delta_ms - runs[0].runtime_delta_ms, 2)

    return CompareResponse(
        query_summary=query.model_dump(),
        runs=runs,
        coverage_uplift_pct=uplift,
        runtime_overhead_ms=overhead,
        full_results=full_results,
    )


# GET /api/scan/modes

_MODE_DESCRIPTIONS = {
    "API_ONLY": (
        "Third-party intelligence APIs only (breach lookups, identity "
        "providers). Fastest, narrowest coverage. Used as the baseline "
        "in comparative evaluation."
    ),
    "HYBRID": (
        "APIs + DuckDuckGo search + ethical HTTP scraping of the returned "
        "URLs. Balanced coverage and runtime; the recommended default mode."
    ),
    "DEEP_SCAN": (
        "Same layers as HYBRID but with significantly higher per-source "
        "limits. Slower; uncovers long-tail exposures. Every fetch still "
        "obeys robots.txt and per-host rate limits."
    ),
    "EXTENDED_EXPLORATION": (
        "Recursive expansion mode. After each round, newly-discovered "
        "identifiers (linked usernames, co-occurring emails) are fed "
        "back into the pipeline — bounded by max_recursion_depth, never "
        "an unrestricted crawl."
    ),
}


@router.get("/scan/modes")
def scan_modes() -> dict:
    from ..runtime_settings import get_mode_limits
    out: Dict[str, dict] = {}
    for mode_key, limits in MODE_LIMITS.items():
        live = get_mode_limits(mode_key)
        out[mode_key] = {
            "timeout_seconds": live.get("timeout_seconds", limits.get("timeout_seconds")),
            "max_search_results": live.get("max_search_results", limits.get("max_search_results")),
            "max_sources": live.get("max_sources", limits.get("max_sources")),
            "max_recursion_depth": limits.get("max_recursion_depth"),
            "description": _MODE_DESCRIPTIONS.get(mode_key, ""),
        }
    return out
