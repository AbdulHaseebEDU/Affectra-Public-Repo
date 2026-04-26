# health and status endpoints: GET /api/health, /api/status/keys, /api/status/apis, /api/status/system
# these never raise — failures go into the payload so the splash screen can report them gracefully

from __future__ import annotations

import importlib
from typing import Any, Dict, List

from fastapi import APIRouter

from ...external_apis.api_keys.keys import all_key_statuses, configured_count
from ...external_apis.controller.external_api_controller import all_services

router = APIRouter()


# GET /api/health

@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "affectra",
        "version": "1.0.0",
    }


# GET /api/status/keys

@router.get("/status/keys")
def status_keys() -> dict:
    configured, total = configured_count()
    return {
        "configured": configured,
        "total": total,
        "services": all_key_statuses(),
    }


# GET /api/status/apis

# Offline import check — no network calls, just verifies each adapter loads
# and exposes a query() entrypoint. Live errors show up on the first real scan.
@router.get("/status/apis")
def status_apis() -> dict:
    specs = all_services()
    entries: List[Dict[str, Any]] = []
    ready = 0

    for spec in specs:
        entry: Dict[str, Any] = {
            "name": spec.name,
            "source_type": spec.source_type,
            "modes": sorted(spec.modes),
            "requires_email": spec.requires_email,
            "requires_username": spec.requires_username,
            "ready": False,
            "error": None,
        }
        try:
            module = importlib.import_module(spec.module)
            if callable(getattr(module, "query", None)):
                entry["ready"] = True
                ready += 1
            else:
                entry["error"] = "adapter missing query() entrypoint"
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"import failed: {exc}"
        entries.append(entry)

    return {
        "ready": ready,
        "total": len(specs),
        "adapters": entries,
    }


# GET /api/status/system

# Internal-API modules we expect to load: (import_path, symbol).
_INTERNAL_MODULES = [
    ("backend.internal_api.source_discovery", "build_queries"),
    ("backend.internal_api.normalization", "normalize_findings"),
    ("backend.internal_api.classifier", "classify"),
    ("backend.internal_api.confidence_scoring", "score_confidence"),
    ("backend.internal_api.risk_scoring", "score_risk"),
    ("backend.internal_api.mitigation", "apply_mitigations"),
    ("backend.internal_api.response_assembly", "assemble"),
    ("backend.internal_api.expansion", "collect_new_identifiers"),
]


# Rolled-up view consumed by the splash screen.
@router.get("/status/system")
def status_system() -> dict:
    # backend
    backend_block = {
        "ok": True,
        "detail": "affectra backend reachable",
    }

    # keys
    configured, total = configured_count()
    keys_block = {
        "ok": True,  # missing keys are non-fatal — services self-skip
        "configured": configured,
        "total": total,
        "detail": f"{configured} / {total} keyed services configured",
    }

    # external adapters
    specs = all_services()
    ready = 0
    for spec in specs:
        try:
            module = importlib.import_module(spec.module)
            if callable(getattr(module, "query", None)):
                ready += 1
        except Exception:  # noqa: BLE001
            pass
    external_block = {
        "ok": ready == len(specs),
        "ready": ready,
        "total": len(specs),
        "detail": f"{ready} / {len(specs)} external adapters loaded",
    }

    # internal modules
    internal_ready = 0
    internal_detail: List[Dict[str, Any]] = []
    for mod_path, symbol in _INTERNAL_MODULES:
        entry = {"module": mod_path.rsplit(".", 1)[-1], "ok": False, "error": None}
        try:
            m = importlib.import_module(mod_path)
            if callable(getattr(m, symbol, None)):
                entry["ok"] = True
                internal_ready += 1
            else:
                entry["error"] = f"missing symbol {symbol}"
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"{exc}"
        internal_detail.append(entry)
    internal_block = {
        "ok": internal_ready == len(_INTERNAL_MODULES),
        "ready": internal_ready,
        "total": len(_INTERNAL_MODULES),
        "detail": f"{internal_ready} / {len(_INTERNAL_MODULES)} internal modules ready",
        "modules": internal_detail,
    }

    # scanner engine
    scanner_block: Dict[str, Any] = {"ok": False, "detail": "not loaded"}
    try:
        ac = importlib.import_module("backend.app_controller")
        if callable(getattr(ac, "run_scan", None)):
            scanner_block = {"ok": True, "detail": "scanner engine initialized"}
        else:
            scanner_block = {"ok": False, "detail": "run_scan not exported"}
    except Exception as exc:  # noqa: BLE001
        scanner_block = {"ok": False, "detail": f"app_controller import failed: {exc}"}

    overall_ok = all([
        backend_block["ok"],
        external_block["ok"] or ready >= 1,  # allow partial external
        internal_block["ok"],
        scanner_block["ok"],
    ])

    return {
        "ok": overall_ok,
        "service": "affectra",
        "version": "1.0.0",
        "checks": {
            "backend": backend_block,
            "keys": keys_block,
            "external": external_block,
            "internal": internal_block,
            "scanner": scanner_block,
        },
    }
