"""Centralised configuration.

Every tunable lives here and is sourced from the environment. Secrets are read
once at import and are never logged or returned by any endpoint.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    """Load repository-root ``.env`` into the environment, if present.

    Uses ``setdefault`` so a real environment variable always wins. That matters
    in production: Cloud Run injects secrets as env vars, and a stray ``.env``
    inside an image must never override them.

    Hand-rolled rather than taking a dependency for ~15 lines, and silent when
    the file is absent, which is the normal case in a container.
    """
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    try:
        raw = env_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        # Strip surrounding quotes; keys pasted from a dashboard often carry them.
        value = value.strip().strip('"').strip("'")
        if key and value:
            os.environ.setdefault(key, value)


_load_dotenv()


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


#: Search modes the Parallel v1 API actually accepts. The schema advertises a
#: wider enum, but the service rejects anything outside this set with a 422.
PARALLEL_MODES = ("basic", "fast", "turbo", "advanced")

#: The v1beta API called this field "processor" and used "base". Anyone
#: carrying an old .env forward would otherwise get an opaque 422 at run time.
_LEGACY_MODES = {"base": "basic", "pro": "advanced"}


def _parallel_mode() -> str:
    """Resolve and validate the search mode, failing loudly on a bad value.

    A wrong mode is otherwise only discovered mid-pipeline as an HTTP 422, by
    which point several searches have already been paid for.
    """
    raw = (os.getenv("PARALLEL_MODE", "") or "basic").strip().lower()
    mode = _LEGACY_MODES.get(raw, raw)
    if mode not in PARALLEL_MODES:
        raise ValueError(
            f"PARALLEL_MODE={raw!r} is not a valid Parallel search mode. "
            f"Use one of: {', '.join(PARALLEL_MODES)}."
        )
    return mode


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
    #: gemini-3.5-flash rather than the newer 3.6/3.7: measured 2026-09-02, both
    #: newer models returned 503 "high demand" while 3.5-flash answered the same
    #: structured-output prompt in 2.7s with thinking disabled. Newest is not the
    #: same as available, and a live demo cannot ride on a constrained model.
    model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.5-flash"))
    #: Tried in order when the primary is unavailable. See agents/models.py.
    fallback_models: str = field(
        default_factory=lambda: os.getenv(
            "GEMINI_FALLBACK_MODELS", "gemini-3.6-flash,gemini-3.1-flash-lite"
        )
    )
    #: Optional heavier model for the judgement-dense stages.
    reasoning_model: str = field(default_factory=lambda: os.getenv("GEMINI_REASONING_MODEL", ""))

    # -- Parallel --------------------------------------------------------------
    parallel_api_key: str = field(default_factory=lambda: os.getenv("PARALLEL_API_KEY", ""))
    parallel_base_url: str = field(
        default_factory=lambda: os.getenv("PARALLEL_BASE_URL", "https://api.parallel.ai")
    )
    #: "basic" | "fast" | "turbo" | "advanced". Measured against the live API on
    #: 2026-09-02, "basic" was both fast (~1.7s) and returned the most excerpt
    #: text, which is what the evidence stage needs.
    parallel_mode: str = field(default_factory=_parallel_mode)
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
    #: Concurrent evidence-extraction calls. Keep at 3 on a free-tier Gemini key
    #: (5 requests/minute/model); raise to 6+ on a paid key for lower latency.
    evidence_concurrency: int = field(default_factory=lambda: _int("EVIDENCE_CONCURRENCY", 3))

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

    def fallback_list(self) -> list[str]:
        return [m.strip() for m in self.fallback_models.split(",") if m.strip()]


settings = Settings()
