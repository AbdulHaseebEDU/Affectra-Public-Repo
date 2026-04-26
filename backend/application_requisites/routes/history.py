# backend/application_requisites/routes/history.py
# REST endpoints for scan history stored in backend/data/History.json
#
#   GET    /api/history          — return all saved scans (newest first)
#   POST   /api/history          — save a new scan entry
#   DELETE /api/history          — wipe all scans
#   DELETE /api/history/{id}     — remove one scan by id

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...data.history_store import add_scan, all_scans, clear_all, remove_scan

router = APIRouter()


class ScanEntry(BaseModel):
    id:        str
    timestamp: str
    query:     dict[str, Any]
    summary:   dict[str, Any]
    metadata:  dict[str, Any]
    results:   list[dict[str, Any]]


@router.get("/history")
def get_history() -> dict:
    return {"scans": all_scans()}


@router.post("/history", status_code=201)
def save_scan(entry: ScanEntry) -> dict:
    add_scan(entry.model_dump())
    return {"ok": True}


@router.delete("/history/{scan_id}")
def delete_scan(scan_id: str) -> dict:
    removed = remove_scan(scan_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Scan not found")
    return {"ok": True}


@router.delete("/history")
def delete_all() -> dict:
    clear_all()
    return {"ok": True}
