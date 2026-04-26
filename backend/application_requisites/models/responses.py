# pydantic response models

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from .enums import (
    ConfidenceLevel,
    ExposureCategory,
    MatchType,
    RiskLevel,
    ScanMode,
    SourceType,
)
from .requests import NormalizedQuery


class ExposureResult(BaseModel):
    id: str
    source_type: SourceType
    source_name: str
    source_url: str
    match_type: MatchType
    matched_fields: List[str]
    matched_data: Dict[str, str]
    snippet: Optional[str] = None
    classification: ExposureCategory = ExposureCategory.UNKNOWN
    confidence_score: float = 0.0
    confidence_level: ConfidenceLevel = ConfidenceLevel.LOW
    risk_score: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW
    mitigation: List[str] = Field(default_factory=list)
    deletion_email_template: Optional[str] = None
    discovered_in_round: int = 0
    confirmed_by: List[str] = Field(default_factory=list)
    source_count: int = 1


class ScanMetadata(BaseModel):
    scan_id: str
    scan_mode: ScanMode
    started_at: datetime
    completed_at: datetime
    runtime_delta_ms: float
    sources_checked: int = 0
    pages_scanned: int = 0
    api_calls_made: int = 0
    matches_found: int = 0
    recursion_depth_reached: int = 0
    apis_attempted: int = 0
    apis_succeeded: int = 0
    apis_skipped: int = 0
    errors: List[str] = Field(default_factory=list)


class ScanSummary(BaseModel):
    total_exposures: int = 0
    by_category: Dict[str, int] = Field(default_factory=dict)
    by_risk_level: Dict[str, int] = Field(default_factory=dict)
    overall_risk_level: RiskLevel = RiskLevel.LOW
    overall_risk_score: float = 0.0
    hygiene_score: float = 100.0  # 100 − overall_risk_score; higher = cleaner


class ScanResponse(BaseModel):
    query: NormalizedQuery
    scan_metadata: ScanMetadata
    results: List[ExposureResult] = Field(default_factory=list)
    summary: ScanSummary = Field(default_factory=ScanSummary)
