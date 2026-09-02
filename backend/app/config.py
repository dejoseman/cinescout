"""Centralised configuration.

Every tunable lives here and is sourced from the environment. Secrets are read
once at import and are never logged or returned by any endpoint.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # -- Google Cloud / Gemini -------------------------------------------------
    google_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_API_KEY", ""))
    use_vertex: bool = field(default_factory=lambda: _bool("GOOGLE_GENAI_USE_VERTEXAI"))
    gcp_project: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    gcp_location: str = field(
        default_factory=lambda: os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    )
    #: Fast, GA workhorse used for every stage by default.
    model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.7-flash"))
    #: Optional heavier model for the judgement-dense stages.
    reasoning_model: str = field(default_factory=lambda: os.getenv("GEMINI_REASONING_MODEL", ""))

    # -- Parallel --------------------------------------------------------------
    parallel_api_key: str = field(default_factory=lambda: os.getenv("PARALLEL_API_KEY", ""))
    parallel_base_url: str = field(
        default_factory=lambda: os.getenv("PARALLEL_BASE_URL", "https://api.parallel.ai")
    )
    #: "turbo" | "fast" | "base" | "advanced". Lower tiers are faster, which
    #: matters for a live three-minute demo.
    parallel_mode: str = field(default_factory=lambda: os.getenv("PARALLEL_MODE", "base"))
    parallel_max_results: int = field(default_factory=lambda: _int("PARALLEL_MAX_RESULTS", 6))
    parallel_max_chars: int = field(default_factory=lambda: _int("PARALLEL_MAX_CHARS", 1500))
    parallel_timeout_s: int = field(default_factory=lambda: _int("PARALLEL_TIMEOUT_S", 45))
    parallel_max_retries: int = field(default_factory=lambda: _int("PARALLEL_MAX_RETRIES", 3))
    parallel_concurrency: int = field(default_factory=lambda: _int("PARALLEL_MAX_CONCURRENCY", 5))

    # -- Pipeline limits (bound latency and spend) -----------------------------
    max_research_tasks: int = field(default_factory=lambda: _int("MAX_RESEARCH_TASKS", 8))
    max_concurrent_pipelines: int = field(
        default_factory=lambda: _int("MAX_CONCURRENT_PIPELINES", 3)
    )
    max_evidence_chars: int = field(default_factory=lambda: _int("MAX_EVIDENCE_CHARS", 60000))

    # -- API -------------------------------------------------------------------
    rate_limit_per_hour: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_HOUR", 20))
    cors_origins: str = field(default_factory=lambda: os.getenv("CORS_ORIGINS", ""))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    @property
    def parallel_configured(self) -> bool:
        return bool(self.parallel_api_key)

    @property
    def gemini_configured(self) -> bool:
        """Vertex uses ADC, so a project id is sufficient there."""
        return bool(self.google_api_key) or (self.use_vertex and bool(self.gcp_project))

    def reasoning_model_or_default(self) -> str:
        return self.reasoning_model or self.model


settings = Settings()
