# backend/data/history_store.py
# Thread-safe JSON-file store for scan history.
# File: backend/data/History.json  (auto-created if missing)

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_PATH = Path(__file__).parent / "History.json"
_MAX  = 50   # keep at most 50 scans


def _read() -> list[dict]:
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("scans", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _write(scans: list[dict]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump({"scans": scans}, f, indent=2, ensure_ascii=False)


def all_scans() -> list[dict]:
    with _LOCK:
        return _read()


def add_scan(entry: dict[str, Any]) -> None:
    with _LOCK:
        scans = _read()
        scans.insert(0, entry)          # newest first
        _write(scans[:_MAX])


def remove_scan(scan_id: str) -> bool:
    with _LOCK:
        scans = _read()
        filtered = [s for s in scans if s.get("id") != scan_id]
        if len(filtered) == len(scans):
            return False
        _write(filtered)
        return True


def clear_all() -> None:
    with _LOCK:
        _write([])
