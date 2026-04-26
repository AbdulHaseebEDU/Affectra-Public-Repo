# shared enums

from __future__ import annotations

from enum import Enum


class ScanMode(str, Enum):
    API_ONLY = "API_ONLY"
    HYBRID = "HYBRID"
    DEEP_SCAN = "DEEP_SCAN"
    EXTENDED_EXPLORATION = "EXTENDED_EXPLORATION"


class SourceType(str, Enum):
    API = "api"
    SEARCH = "search"
    SCRAPING = "scraping"


class MatchType(str, Enum):
    EXACT = "exact"
    PARTIAL = "partial"
    CONTEXTUAL = "contextual"


class ExposureCategory(str, Enum):
    DATA_BROKER = "data_broker"
    FORUM_MENTION = "forum_mention"
    PUBLIC_DIRECTORY = "public_directory"
    DOCUMENT = "document"
    SOCIAL_TRACE = "social_trace"
    POTENTIAL_BREACH = "potential_breach"
    CODE_REPOSITORY = "code_repository"
    PASTE_EXPOSURE = "paste_exposure"
    HISTORICAL_CACHE = "historical_cache"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
