# AI analysis endpoint: POST /api/analyse
# accepts a completed scan result and returns Gemini commentary per finding + an overall summary

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ...gen_api import analyse_findings

router = APIRouter()


class AnalyseRequest(BaseModel):
    findings: List[Dict[str, Any]]
    query_summary: Optional[Dict[str, Any]] = None


class AnalyseResponse(BaseModel):
    per_finding: Dict[str, str]
    per_finding_mitigations: Dict[str, List[str]] = {}
    overall_summary: str
    error: Optional[str] = None


@router.post("/analyse", response_model=AnalyseResponse)
def analyse(req: AnalyseRequest) -> AnalyseResponse:
    result = analyse_findings(req.findings, req.query_summary)
    return AnalyseResponse(
        per_finding=result.get("per_finding", {}),
        per_finding_mitigations=result.get("per_finding_mitigations", {}),
        overall_summary=result.get("overall_summary", ""),
        error=result.get("error"),
    )
