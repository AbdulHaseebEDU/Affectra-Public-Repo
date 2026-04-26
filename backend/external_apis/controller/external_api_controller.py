# Fans out to all registered external adapters for a given scan pass.
# One bad adapter can never crash the scan — every call is isolated.
# To add a new service: one registry entry + one adapter folder, nothing else.

from __future__ import annotations

import concurrent.futures
import importlib
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from ...application_requisites.models import NormalizedQuery
from ...application_requisites import runtime_settings


# service registry

@dataclass(frozen=True)
class ServiceSpec:
    # one entry per adapter
    name: str                  # human-readable label
    module: str                # dotted import path
    source_type: str           # "api" | "search" | "scraping"
    # EXTENDED_EXPLORATION always gets everything; other modes are selective
    modes: frozenset[str] = frozenset(
        {"API_ONLY", "HYBRID", "DEEP_SCAN", "EXTENDED_EXPLORATION"}
    )
    requires_email: bool = False
    requires_username: bool = False


_REGISTRY: List[ServiceSpec] = [
    # breach / identity intelligence APIs
    ServiceSpec(
        name="HIBP Pwned Passwords",
        module="backend.external_apis.apis.hibp_passwords.hibp_passwords",
        source_type="api",
        requires_email=True,
    ),
    ServiceSpec(
        name="Gravatar",
        module="backend.external_apis.apis.gravatar.gravatar",
        source_type="api",
        requires_email=True,
    ),
    ServiceSpec(
        name="Wayback Machine",
        module="backend.external_apis.apis.wayback_machine.wayback_machine",
        source_type="api",
    ),
    ServiceSpec(
        name="crt.sh",
        module="backend.external_apis.apis.crt_sh.crt_sh",
        source_type="api",
        requires_email=True,
    ),
    ServiceSpec(
        name="Psbdmp",
        module="backend.external_apis.apis.psbdmp.psbdmp",
        source_type="api",
    ),
    ServiceSpec(
        name="GitHub",
        module="backend.external_apis.apis.github_api.github_api",
        source_type="api",
    ),
    ServiceSpec(
        name="Stack Exchange",
        module="backend.external_apis.apis.stack_exchange.stack_exchange",
        source_type="api",
    ),
    ServiceSpec(
        name="URLScan",
        module="backend.external_apis.apis.urlscan.urlscan",
        source_type="api",
    ),
    ServiceSpec(
        name="Holehe",
        module="backend.external_apis.apis.holehe.holehe",
        source_type="api",
        requires_email=True,
    ),
    # search layer
    ServiceSpec(
        name="DuckDuckGo",
        module="backend.external_apis.apis.duckduckgo.duckduckgo",
        source_type="search",
        modes=frozenset({"HYBRID", "DEEP_SCAN", "EXTENDED_EXPLORATION"}),
    ),
    # scraping layer — gets candidate URLs from the search pass
    ServiceSpec(
        name="Ethical Scraper",
        module="backend.external_apis.apis.ethical_scraper.ethical_scraper",
        source_type="scraping",
        modes=frozenset({"HYBRID", "DEEP_SCAN", "EXTENDED_EXPLORATION"}),
    ),
]


def all_services() -> List[ServiceSpec]:
    return list(_REGISTRY)


# result envelope

@dataclass
class ExternalApiResult:
    # aggregated output of one controller pass
    findings: List[dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    api_calls_made: int = 0
    sources_checked: int = 0
    pages_scanned: int = 0
    matches_found: int = 0
    apis_attempted: int = 0
    apis_succeeded: int = 0
    apis_skipped: int = 0
    per_service: Dict[str, dict] = field(default_factory=dict)


# helpers

def _normalize_linked(linked) -> Dict[str, List[str]]:
    # adapters return linked_identifiers in different shapes — normalize to
    # {"usernames": [...], "emails": [...]} or similar dict of string lists
    if not linked:
        return {}
    if isinstance(linked, dict):
        out: Dict[str, List[str]] = {}
        for k, v in linked.items():
            if isinstance(v, list):
                out[k] = [str(x) for x in v if x]
            elif v:
                out[k] = [str(v)]
        return out
    if isinstance(linked, list):
        items = [str(x) for x in linked if x]
        return {"usernames": items} if items else {}
    return {}


def _should_run(spec: ServiceSpec, q: NormalizedQuery, mode: str) -> Optional[str]:
    # returns None if the adapter should run, or a skip-reason string
    if mode not in spec.modes:
        return f"{spec.name}: not enabled for mode {mode}"
    if spec.requires_email and not q.email:
        return f"{spec.name}: requires email — skipped"
    if spec.requires_username and not q.usernames:
        return f"{spec.name}: requires username — skipped"
    return None


def _call_adapter(
    spec: ServiceSpec,
    q: NormalizedQuery,
    limits: dict,
    extra_kwargs: Optional[dict] = None,
) -> dict:
    # lazy import so missing adapters fail gracefully at call time, not import time
    module = importlib.import_module(spec.module)
    query_fn: Callable = getattr(module, "query")
    kwargs = dict(extra_kwargs or {})
    return query_fn(
        email=q.email,
        full_name=q.full_name,
        phone=q.phone,
        usernames=list(q.usernames),
        limits=limits,
        **kwargs,
    )


# public entry point

def run_external_apis(
    query: NormalizedQuery,
    mode: str,
    limits: dict,
    deadline: Optional[float] = None,
    candidate_urls: Optional[List[str]] = None,
    source_type_filter: Optional[frozenset] = None,
) -> ExternalApiResult:
    # runs every registered adapter enabled for the given mode
    # deadline: perf_counter deadline — no new adapters start after it, in-flight ones finish
    # candidate_urls: passed only to the scraper (populated by the search pass)
    # source_type_filter: restrict to {"api","search"} or {"scraping"} to keep counters clean
    result = ExternalApiResult()
    candidate_urls = candidate_urls or []

    # merge runtime settings into limits so every adapter sees them
    # (strict flags are only consumed by Stack Exchange + GitHub, harmless elsewhere)
    effective_limits = dict(limits or {})
    effective_limits.setdefault(
        "strict_stack_exchange",
        runtime_settings.get_bool("strict_stack_exchange", True),
    )
    effective_limits.setdefault(
        "strict_github",
        runtime_settings.get_bool("strict_github", True),
    )

    per_service_cap = runtime_settings.get_int("max_findings_per_service", 0)
    # pass the cap down so adapters can short-circuit their own loops
    effective_limits.setdefault("max_findings_per_service", per_service_cap)

    # ── Phase 1: filter — decide which services are eligible to run ──────────
    to_run: List[Tuple[ServiceSpec, dict]] = []   # (spec, extra_kwargs)

    for spec in _REGISTRY:
        if source_type_filter is not None and spec.source_type not in source_type_filter:
            continue

        if not runtime_settings.is_service_enabled(spec.name):
            result.errors.append(f"{spec.name}: disabled via Dev Menu — skipped")
            result.apis_skipped += 1
            continue

        skip_reason = _should_run(spec, query, mode)
        if skip_reason is not None:
            result.errors.append(skip_reason)
            result.apis_skipped += 1
            continue

        extra: dict = {}
        if spec.source_type == "scraping":
            if not candidate_urls:
                result.errors.append(f"{spec.name}: no candidate URLs — skipped")
                result.apis_skipped += 1
                continue
            extra["candidate_urls"] = candidate_urls

        to_run.append((spec, extra))

    if not to_run:
        return result

    result.apis_attempted += len(to_run)

    # ── Phase 2: run all eligible services concurrently ───────────────────────
    # Each adapter is a stateless function — safe to call from any thread.
    # Holehe already manages its own internal thread pool; nesting is fine.

    def _run_one(item: Tuple[ServiceSpec, dict]) -> Tuple[ServiceSpec, Optional[dict], Optional[str]]:
        spec, extra = item
        if deadline is not None and time.perf_counter() >= deadline:
            return spec, None, f"scan deadline reached — skipped"
        try:
            raw = _call_adapter(spec, query, effective_limits, extra_kwargs=extra)
            return spec, raw, None
        except ModuleNotFoundError as exc:
            return spec, None, f"adapter import failed — {exc}"
        except Exception as exc:  # noqa: BLE001
            return spec, None, f"adapter crashed — {exc}"

    max_workers = min(len(to_run), 12)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_one, item): item[0] for item in to_run}
        for future in concurrent.futures.as_completed(futures):
            spec, raw, err = future.result()

            if err is not None:
                result.errors.append(f"{spec.name}: {err}")
                result.apis_skipped += 1
                result.apis_attempted -= 1
                continue

            # belt-and-suspenders cap so no single noisy adapter dominates
            if per_service_cap and raw.get("findings"):
                original = raw["findings"]
                if len(original) > per_service_cap:
                    raw["findings"] = original[:per_service_cap]
                    result.errors.append(
                        f"{spec.name}: capped at {per_service_cap} of "
                        f"{len(original)} findings"
                    )

            per_svc = {
                "service": raw.get("service_name", spec.name),
                "api_calls_made": int(raw.get("api_calls_made", 0) or 0),
                "sources_checked": int(raw.get("sources_checked", 0) or 0),
                "pages_scanned": int(raw.get("pages_scanned", 0) or 0),
                "findings": len(raw.get("findings", []) or []),
                "errors": list(raw.get("errors", []) or []),
            }
            result.per_service[spec.name] = per_svc
            result.api_calls_made  += per_svc["api_calls_made"]
            result.sources_checked += per_svc["sources_checked"]
            result.pages_scanned   += per_svc["pages_scanned"]
            result.matches_found   += per_svc["findings"]

            if per_svc["errors"]:
                for e in per_svc["errors"]:
                    result.errors.append(f"{spec.name}: {e}")
            result.apis_succeeded += 1

            for f in raw.get("findings", []) or []:
                f["confirmed_by"] = [spec.name]
                f["linked_identifiers"] = _normalize_linked(f.get("linked_identifiers"))
                f.setdefault("source_type", spec.source_type)
                f.setdefault("source_name", spec.name)
                f.setdefault("matched_fields", [])
                f.setdefault("matched_data", {})
                f.setdefault("snippet", None)
                f.setdefault("category", "unknown")
                f.setdefault("match_type", "exact")
                f.setdefault("source_url", "")
                result.findings.append(f)

    return result
