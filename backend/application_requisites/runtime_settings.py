# runtime settings the dev menu can flip without restarting the server
# single process-global dict behind a lock, optionally written to disk
# best-effort persistence — if the file is unwritable we just stay in memory

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


# defaults

# every ServiceSpec.name from the external API controller — kept as a literal
# so this module has no dependency on the controller at import time
ALL_SERVICES: List[str] = [
    "HIBP Pwned Passwords",
    "Gravatar",
    "Wayback Machine",
    "crt.sh",
    "Psbdmp",
    "GitHub",
    "Stack Exchange",
    "URLScan",
    "Holehe",
    "DuckDuckGo",
    "Ethical Scraper",
]


# keys the dev menu "API Keys" tab can override at runtime
OVERRIDABLE_KEYS: List[str] = [
    "GEMINI_API_KEY",
    "GITHUB_TOKEN",
    "STACKEXCHANGE_KEY",
    "URLSCAN_API_KEY",
    "HCAPTCHA_SECRET",
]


AVAILABLE_THEMES: List[str] = ["navy-gold", "midnight", "graphite", "ivory"]


# default per-mode scan limits — mirrors app_controller.MODE_LIMITS
# stored separately so runtime_settings has no import-time dep on app_controller
_MODE_LIMIT_DEFAULTS: Dict[str, Dict[str, int]] = {
    "API_ONLY":             {"timeout_seconds": 15,  "max_search_results": 0,  "max_sources": 0},
    "HYBRID":               {"timeout_seconds": 75,  "max_search_results": 25, "max_sources": 10},
    "DEEP_SCAN":            {"timeout_seconds": 180, "max_search_results": 60, "max_sources": 25},
    "EXTENDED_EXPLORATION": {"timeout_seconds": 360, "max_search_results": 80, "max_sources": 40},
}


_DEFAULTS: Dict[str, Any] = {
    "enabled_services": None,       # None = all enabled; list[str] = allow-list
    "strict_stack_exchange": True,  # precision flags toggled in dev menu
    "strict_github": True,
    "max_findings_per_service": 8,  # 0 or None = unbounded
    "theme": "navy-gold",
    "api_keys": {},                 # runtime overrides win over os.environ
    "mode_limits": None,            # None = use _MODE_LIMIT_DEFAULTS; dict = user overrides
}


_LOCK = threading.RLock()
_SETTINGS: Dict[str, Any] = {}

# sits next to the backend package root so docker/venv setups survive restarts
# never checked into git
_PERSIST_PATH = (
    Path(__file__).resolve().parent.parent.parent / ".affectra_runtime.json"
)


# disk stuff

def _load_from_disk() -> None:
    global _SETTINGS
    data: Dict[str, Any] = {}
    if _PERSIST_PATH.exists():
        try:
            data = json.loads(_PERSIST_PATH.read_text("utf-8")) or {}
        except Exception:
            data = {}

    merged = dict(_DEFAULTS)
    for k, v in data.items():
        if k in _DEFAULTS:
            merged[k] = v

    # If a saved allow-list exists, add any services that were registered AFTER
    # the list was last saved so they are on by default rather than silently off.
    saved_list = merged.get("enabled_services")
    if isinstance(saved_list, list):
        new_services = [s for s in ALL_SERVICES if s not in saved_list]
        if new_services:
            merged["enabled_services"] = saved_list + new_services

    _SETTINGS = merged


def _persist() -> None:
    try:
        _PERSIST_PATH.write_text(
            json.dumps(_SETTINGS, indent=2, sort_keys=True), "utf-8"
        )
    except Exception:
        # non-fatal — settings still work in memory
        pass


_load_from_disk()


# public api

# returns a safe snapshot — keys are always masked before sending to the ui
def snapshot() -> Dict[str, Any]:
    with _LOCK:
        masked_keys = {
            name: ("•" * 8) if (val and val.strip()) else ""
            for name, val in _SETTINGS.get("api_keys", {}).items()
        }
        # also tell the ui which keys are set via env so it can show the right badge
        env_status: Dict[str, bool] = {}
        for name in OVERRIDABLE_KEYS:
            env_status[name] = bool(os.environ.get(name, "").strip())

        enabled = _SETTINGS.get("enabled_services")
        # build resolved mode_limits: defaults merged with any saved overrides
        saved_limits = _SETTINGS.get("mode_limits") or {}
        resolved_limits: Dict[str, Dict[str, int]] = {}
        for mode_key, defaults in _MODE_LIMIT_DEFAULTS.items():
            override = saved_limits.get(mode_key, {}) if isinstance(saved_limits, dict) else {}
            resolved_limits[mode_key] = {**defaults, **override}

        return {
            "enabled_services": list(enabled) if enabled is not None else None,
            "strict_stack_exchange": bool(_SETTINGS.get("strict_stack_exchange")),
            "strict_github": bool(_SETTINGS.get("strict_github")),
            "max_findings_per_service": int(
                _SETTINGS.get("max_findings_per_service") or 0
            ),
            "theme": str(_SETTINGS.get("theme") or "navy-gold"),
            "api_keys_masked": masked_keys,
            "api_keys_from_env": env_status,
            "all_services": list(ALL_SERVICES),
            "overridable_keys": list(OVERRIDABLE_KEYS),
            "available_themes": list(AVAILABLE_THEMES),
            "mode_limits": resolved_limits,
            "mode_limit_defaults": {k: dict(v) for k, v in _MODE_LIMIT_DEFAULTS.items()},
        }


# partial update — unknown keys are silently ignored, api_keys goes through set_api_key
def update(patch: Dict[str, Any]) -> Dict[str, Any]:
    with _LOCK:
        for k, v in patch.items():
            if k == "api_keys":
                continue  # routed through set_api_key
            if k not in _DEFAULTS:
                continue
            if k == "enabled_services":
                if v is None:
                    _SETTINGS[k] = None
                elif isinstance(v, list):
                    _SETTINGS[k] = [str(x) for x in v if str(x) in ALL_SERVICES]
            elif k == "max_findings_per_service":
                try:
                    n = int(v)
                except (TypeError, ValueError):
                    continue
                _SETTINGS[k] = max(0, n)
            elif k == "theme":
                s = str(v)
                if s in AVAILABLE_THEMES:
                    _SETTINGS[k] = s
            elif k in {"strict_stack_exchange", "strict_github"}:
                _SETTINGS[k] = bool(v)
            elif k == "mode_limits":
                if not isinstance(v, dict):
                    continue
                current = dict(_SETTINGS.get("mode_limits") or {})
                for mode_key, mode_vals in v.items():
                    if mode_key not in _MODE_LIMIT_DEFAULTS:
                        continue
                    if not isinstance(mode_vals, dict):
                        continue
                    mode = dict(current.get(mode_key) or {})
                    for limit_key in ("timeout_seconds", "max_search_results", "max_sources"):
                        if limit_key in mode_vals:
                            try:
                                mode[limit_key] = max(0, int(mode_vals[limit_key]))
                            except (TypeError, ValueError):
                                pass
                    current[mode_key] = mode
                _SETTINGS["mode_limits"] = current
        _persist()
    return snapshot()


# set or clear a single api key override
def set_api_key(name: str, value: str) -> Dict[str, Any]:
    if name not in OVERRIDABLE_KEYS:
        raise KeyError(f"unknown key: {name}")
    with _LOCK:
        keys = dict(_SETTINGS.get("api_keys") or {})
        if value and value.strip():
            keys[name] = value.strip()
        else:
            keys.pop(name, None)
        _SETTINGS["api_keys"] = keys
        _persist()
    return snapshot()


def clear_api_key(name: str) -> Dict[str, Any]:
    return set_api_key(name, "")


# internal accessors used by the controller and adapters

def get_key_override(name: str) -> Optional[str]:
    with _LOCK:
        return (_SETTINGS.get("api_keys") or {}).get(name) or None


def is_service_enabled(name: str) -> bool:
    with _LOCK:
        enabled = _SETTINGS.get("enabled_services")
        if enabled is None:
            return True
        return name in enabled


def get_bool(name: str, default: bool = False) -> bool:
    with _LOCK:
        return bool(_SETTINGS.get(name, default))


def get_int(name: str, default: int = 0) -> int:
    with _LOCK:
        try:
            return int(_SETTINGS.get(name, default) or 0)
        except (TypeError, ValueError):
            return default


def get_theme() -> str:
    with _LOCK:
        return str(_SETTINGS.get("theme") or "navy-gold")


def get_mode_limits(mode_key: str) -> Dict[str, int]:
    """Return the effective limits for a scan mode, merging defaults with any saved overrides."""
    with _LOCK:
        defaults = dict(_MODE_LIMIT_DEFAULTS.get(mode_key, {}))
        overrides = (_SETTINGS.get("mode_limits") or {})
        if isinstance(overrides, dict):
            defaults.update(overrides.get(mode_key, {}))
        return defaults
