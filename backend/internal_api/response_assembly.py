# packages scored exposures plus counters and errors into the final ScanResponse

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime
from typing import List

from ..application_requisites.models import (
    ExposureResult,
    NormalizedQuery,
    ScanMetadata,
    ScanMode,
    ScanResponse,
    ScanSummary,
)
from .risk_scoring import overall_risk


def assemble(
    query: NormalizedQuery,
    mode: ScanMode,
    exposures: List[ExposureResult],
    started_at: datetime,
    completed_at: datetime,
    runtime_ms: float,
    sources_checked: int,
    pages_scanned: int,
    api_calls_made: int,
    matches_found: int,
    recursion_depth_reached: int,
    apis_attempted: int,
    apis_succeeded: int,
    apis_skipped: int,
    errors: List[str],
) -> ScanResponse:
    by_category = dict(Counter(e.classification.value for e in exposures))
    by_risk = dict(Counter(e.risk_level.value for e in exposures))
    score, level = overall_risk(exposures)

    metadata = ScanMetadata(
        scan_id=str(uuid.uuid4()),
        scan_mode=mode,
        started_at=started_at,
        completed_at=completed_at,
        runtime_delta_ms=runtime_ms,
        sources_checked=sources_checked,
        pages_scanned=pages_scanned,
        api_calls_made=api_calls_made,
        matches_found=matches_found,
        recursion_depth_reached=recursion_depth_reached,
        apis_attempted=apis_attempted,
        apis_succeeded=apis_succeeded,
        apis_skipped=apis_skipped,
        errors=errors,
    )

    summary = ScanSummary(
        total_exposures=len(exposures),
        by_category=by_category,
        by_risk_level=by_risk,
        overall_risk_level=level,
        overall_risk_score=score,
        hygiene_score=round(max(0.0, 100.0 - score), 1),
    )

    return ScanResponse(
        query=query,
        scan_metadata=metadata,
        results=exposures,
        summary=summary,
    )
