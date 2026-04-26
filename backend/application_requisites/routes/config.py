# dev menu endpoints — GET/PATCH settings, PUT/DELETE key overrides
# nothing here triggers a scan, all responses mask raw key values

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import runtime_settings

router = APIRouter(prefix="/config", tags=["config"])


# models

# all fields optional — only send what you want to change
class ConfigPatch(BaseModel):
    enabled_services: Optional[list[str]] = Field(
        default=None,
        description="Allow-list of service names. ``null`` means run every service.",
    )
    strict_stack_exchange: Optional[bool] = None
    strict_github: Optional[bool] = None
    max_findings_per_service: Optional[int] = Field(default=None, ge=0, le=100)
    theme: Optional[str] = None
    mode_limits: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Per-mode limit overrides, e.g. {'HYBRID': {'timeout_seconds': 90}}",
    )


class KeyValue(BaseModel):
    value: str = Field(..., description="Raw key value (stored in memory, masked on read)")


# routes

@router.get("", summary="Current runtime settings (keys masked)")
def get_config() -> Dict[str, Any]:
    return runtime_settings.snapshot()


@router.patch("", summary="Update runtime settings")
def patch_config(patch: ConfigPatch) -> Dict[str, Any]:
    return runtime_settings.update(patch.model_dump(exclude_none=True))


@router.put("/keys/{name}", summary="Set a runtime API-key override")
def put_key(name: str, body: KeyValue) -> Dict[str, Any]:
    try:
        return runtime_settings.set_api_key(name, body.value)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/keys/{name}", summary="Clear the runtime override for a key")
def delete_key(name: str) -> Dict[str, Any]:
    try:
        return runtime_settings.clear_api_key(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
