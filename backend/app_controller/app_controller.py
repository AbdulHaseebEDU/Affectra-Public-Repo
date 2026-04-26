# top-level scan orchestrator: fans out to the external API controller,
# then pipes findings through the internal pipeline (normalize → classify → score → mitigate)

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from ..application_requisites.models import (
    NormalizedQuery,
    ScanMode,
    ScanResponse,
)
from ..external_apis.controller.external_api_controller import (
    ExternalApiResult,
    run_external_apis,
)
from ..internal_api.classifier import classify
from ..internal_api.confidence_scoring import score_confidence
from ..internal_api.expansion import SeenIdentifiers, collect_new_identifiers
from ..internal_api.mitigation import apply_mitigations
from ..internal_api.normalization import normalize_findings
from ..internal_api.response_assembly import assemble
from ..internal_api.risk_scoring import score_risk
from ..internal_api.source_discovery import build_queries


# per-mode limits

# Runtime/search/scrape budgets passed down to each adapter via limits=.
MODE_LIMITS: Dict[str, dict] = {
    "API_ONLY": {
        "timeout_seconds": 15,
        "max_search_results": 0,
        "max_sources": 0,
        "max_recursion_depth": 0,
    },
    "HYBRID": {
        "timeout_seconds": 75,
        "max_search_results": 25,
        "max_sources": 10,
        "max_recursion_depth": 0,
    },
    "DEEP_SCAN": {
        "timeout_seconds": 180,
        "max_search_results": 60,
        "max_sources": 25,
        "max_recursion_depth": 0,
    },
    "EXTENDED_EXPLORATION": {
        "timeout_seconds": 360,
        "max_search_results": 80,
        "max_sources": 40,
        "max_recursion_depth": 2,
    },
}


def _limits_for(mode: ScanMode) -> dict:
    """Return effective limits for this mode — user overrides win over hardcoded defaults."""
    try:
        from ..application_requisites.runtime_settings import get_mode_limits
        live = get_mode_limits(mode.value)
        # merge: start with hardcoded defaults (includes max_recursion_depth),
        # then overlay the (potentially user-edited) live limits
        base = dict(MODE_LIMITS.get(mode.value, MODE_LIMITS["HYBRID"]))
        base.update(live)
        return base
    except Exception:
        return dict(MODE_LIMITS.get(mode.value, MODE_LIMITS["HYBRID"]))


# helpers

# Pull search-result URLs from findings so the scraper knows what to hit.
def _extract_candidate_urls(findings: List[dict], cap: int) -> List[str]:
    urls: List[str] = []
    seen: set[str] = set()
    for f in findings:
        if str(f.get("source_type", "")).lower() != "search":
            continue
        u = f.get("source_url") or ""
        if u and u.startswith("http") and u not in seen:
            seen.add(u)
            urls.append(u)
            if len(urls) >= cap:
                break
    return urls


# Fold a second pass of external results into the aggregated bag.
def _merge_external_results(
    dest: ExternalApiResult,
    src: ExternalApiResult,
) -> None:
    dest.findings.extend(src.findings)
    dest.errors.extend(src.errors)
    dest.api_calls_made += src.api_calls_made
    dest.sources_checked += src.sources_checked
    dest.pages_scanned += src.pages_scanned
    dest.matches_found += src.matches_found
    dest.apis_attempted += src.apis_attempted
    dest.apis_succeeded += src.apis_succeeded
    dest.apis_skipped += src.apis_skipped
    for k, v in src.per_service.items():
        dest.per_service[k] = v


def _tag_round(findings: List[dict], round_index: int) -> None:
    for f in findings:
        f.setdefault("discovered_in_round", round_index)


# one scan round

def _run_round(
    query: NormalizedQuery,
    mode: ScanMode,
    limits: dict,
    deadline: float,
    round_index: int,
) -> ExternalApiResult:
    agg = ExternalApiResult()

    # Pass A: APIs + search layer (everything except the scraper)
    pass_a = run_external_apis(
        query=query,
        mode=mode.value,
        limits=limits,
        deadline=deadline,
        source_type_filter=frozenset({"api", "search"}),
    )
    _tag_round(pass_a.findings, round_index)
    _merge_external_results(agg, pass_a)

    # Pass B: scraper fed by URLs from Pass A's search results
    if mode in {ScanMode.HYBRID, ScanMode.DEEP_SCAN, ScanMode.EXTENDED_EXPLORATION}:
        cap = int(limits.get("max_sources", 10) or 10)
        urls = _extract_candidate_urls(pass_a.findings, cap)
        if urls and (deadline is None or time.perf_counter() < deadline):
            pass_b = run_external_apis(
                query=query,
                mode=mode.value,
                limits=limits,
                deadline=deadline,
                candidate_urls=urls,
                source_type_filter=frozenset({"scraping"}),
            )
            _tag_round(pass_b.findings, round_index)
            _merge_external_results(agg, pass_b)

    return agg


# public entry point

# Full pipeline: external APIs → internal API → assembled response.
def run_scan(query: NormalizedQuery, mode: ScanMode) -> ScanResponse:
    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    limits = _limits_for(mode)
    total_timeout = float(limits.get("timeout_seconds", 30))
    deadline = t0 + total_timeout

    # Aggregated external-API bag across all rounds.
    agg = ExternalApiResult()

    # Round 0 — baseline scan.
    round_index = 0
    round_result = _run_round(query, mode, limits, deadline, round_index)
    _merge_external_results(agg, round_result)

    # EXTENDED_EXPLORATION recursion
    seen = SeenIdentifiers()
    seen.absorb(query)
    effective_query = query

    if mode == ScanMode.EXTENDED_EXPLORATION:
        max_depth = int(limits.get("max_recursion_depth", 0) or 0)
        while round_index < max_depth:
            if time.perf_counter() >= deadline:
                agg.errors.append(
                    f"EXTENDED_EXPLORATION: deadline hit before round {round_index + 1}"
                )
                break

            # Which new identifiers did the latest round surface?
            new_q = collect_new_identifiers(round_result.findings, seen)
            if new_q.is_empty():
                # Nothing new to chase — recursion converges.
                break

            # Merge freshly discovered identifiers into the working query.
            effective_query = effective_query.merge(new_q)
            seen.absorb(effective_query)

            round_index += 1
            round_result = _run_round(
                effective_query, mode, limits, deadline, round_index
            )
            _merge_external_results(agg, round_result)

    # Internal API pipeline — each stage wrapped so one bug doesn't drop the run.
    try:
        exposures = normalize_findings(agg.findings)
    except Exception as exc:  # noqa: BLE001
        agg.errors.append(f"normalization: {exc}")
        exposures = []

    try:
        exposures = classify(exposures)
    except Exception as exc:  # noqa: BLE001
        agg.errors.append(f"classifier: {exc}")

    try:
        exposures = score_confidence(exposures, effective_query)
    except Exception as exc:  # noqa: BLE001
        agg.errors.append(f"confidence_scoring: {exc}")

    try:
        exposures = score_risk(exposures)
    except Exception as exc:  # noqa: BLE001
        agg.errors.append(f"risk_scoring: {exc}")

    # Sort: CRITICAL first, then by risk_score desc, then confidence desc.
    _rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    exposures.sort(
        key=lambda e: (
            _rank.get(e.risk_level.value, 4),
            -e.risk_score,
            -e.confidence_score,
        )
    )

    try:
        exposures = apply_mitigations(exposures, effective_query)
    except Exception as exc:  # noqa: BLE001
        agg.errors.append(f"mitigation: {exc}")

    # assemble response
    completed_at = datetime.now(timezone.utc)
    runtime_ms = (time.perf_counter() - t0) * 1000.0

    return assemble(
        query=effective_query,
        mode=mode,
        exposures=exposures,
        started_at=started_at,
        completed_at=completed_at,
        runtime_ms=round(runtime_ms, 2),
        sources_checked=agg.sources_checked,
        pages_scanned=agg.pages_scanned,
        api_calls_made=agg.api_calls_made,
        matches_found=len(exposures),
        recursion_depth_reached=round_index,
        apis_attempted=agg.apis_attempted,
        apis_succeeded=agg.apis_succeeded,
        apis_skipped=agg.apis_skipped,
        errors=list(agg.errors),
    )


# Convenience for unit tests / callers that want the intermediate shape.
def discover_queries(q: NormalizedQuery, mode: ScanMode) -> List[Tuple[str, str]]:
    return build_queries(q, mode.value)
