# one place for all api keys — adapters import from here instead of hitting os.environ directly
# also powers the /api/status/keys health check

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class KeyEntry:
    env_var: str
    service: str
    required: bool  # True = key-gated API; False = works without key


_REGISTRY: list[KeyEntry] = [
    KeyEntry("GEMINI_API_KEY",         "Gemini AI",         required=False),
    KeyEntry("GITHUB_TOKEN",           "GitHub API",        required=True),
    KeyEntry("STACKEXCHANGE_KEY",      "Stack Exchange",    required=True),
    KeyEntry("URLSCAN_API_KEY",        "URLScan",           required=True),
]


# checks dev menu override first, then falls back to env
# lazy import to avoid circular — adapters pull this in at import time, settings lives a level up
def get_key(env_var: str) -> Optional[str]:
    try:
        from ...application_requisites.runtime_settings import get_key_override
        override = get_key_override(env_var)
        if override:
            return override
    except Exception:
        pass
    val = os.environ.get(env_var, "").strip()
    return val if val else None


# builds the service -> status map for the health endpoint
def all_key_statuses() -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    # probe overrides once so we're not calling into settings per-entry
    override_names: set[str] = set()
    try:
        from ...application_requisites.runtime_settings import get_key_override
        for entry in _REGISTRY:
            if get_key_override(entry.env_var):
                override_names.add(entry.env_var)
    except Exception:
        pass

    for entry in _REGISTRY:
        configured = get_key(entry.env_var) is not None
        if entry.env_var in override_names:
            source = "dev_menu"
        elif os.environ.get(entry.env_var, "").strip():
            source = "env"
        else:
            source = None
        out[entry.service] = {
            "env_var": entry.env_var,
            "configured": configured,
            "required": entry.required,
            "source": source,
        }
    return out


# returns (configured, total) counting by service not by env var
def configured_count() -> tuple[int, int]:
    total = len({e.service for e in _REGISTRY})
    configured = 0
    seen = set()
    for e in _REGISTRY:
        if e.service in seen:
            continue
        seen.add(e.service)
        if get_key(e.env_var) is not None:
            configured += 1
    return configured, total
