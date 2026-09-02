"""Model selection with automatic failover.

Gemini capacity is not uniform across model versions, and a model that answers
in two seconds one hour can return sustained ``503 UNAVAILABLE`` the next. That
was observed twice during development on 2026-09-02: first ``gemini-3.7-flash``,
then intermittently ``gemini-3.6-flash``.

Transport-level retry (``HttpRetryOptions``) handles a brief blip, but it cannot
help when a specific model is capacity-constrained for minutes at a time - it
just spends the demo's time budget waiting. :class:`FallbackGemini` moves to the
next model instead.

This matters more than it looks: a stage failure aborts the whole pipeline, so a
single 503 during a live demo destroys the run.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, List

from google.adk.models.base_llm import BaseLlm
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_response import LlmResponse
from google.genai import types

logger = logging.getLogger(__name__)

#: Retry policy for brief, transient failures on a single model.
RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=3,
    initial_delay=1.0,
    max_delay=8.0,
    exp_base=2.0,
    jitter=0.3,
    http_status_codes=[408, 429, 500, 502, 503, 504],
)

#: Substrings marking an error worth trying another model for. Capacity and
#: rate limits are model-specific; a malformed request is not, so it is not
#: listed here and will surface immediately.
_FAILOVER_MARKERS = (
    "503",
    "unavailable",
    "high demand",
    "overloaded",
    "resource_exhausted",
    "429",
    "quota",
    "500",
    "internal error",
    "deadline",
    "timeout",
)


def _is_failover_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _FAILOVER_MARKERS)


class FallbackGemini(BaseLlm):
    """Tries each model in turn, moving on when one is unavailable.

    Behaves exactly like a single Gemini model when the primary is healthy,
    which is the common case; the cost is paid only on failure.
    """

    #: Ordered candidates. The first is the primary.
    model_names: List[str] = []

    _clients: List[Gemini] = []

    model_config = {"arbitrary_types_allowed": True, "extra": "allow"}

    def __init__(self, model_names: List[str], **kwargs: Any) -> None:
        if not model_names:
            raise ValueError("FallbackGemini requires at least one model name.")
        # BaseLlm.model is the primary; it is what ADK reports in traces.
        super().__init__(model=model_names[0], **kwargs)
        self.model_names = list(model_names)
        self._clients = [
            Gemini(model=name, retry_options=RETRY_OPTIONS) for name in model_names
        ]

    async def generate_content_async(
        self, llm_request: Any, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        last_error: BaseException | None = None

        for index, client in enumerate(self._clients):
            # The request carries the model name; point it at this candidate.
            llm_request.model = self.model_names[index]
            try:
                produced = False
                async for response in client.generate_content_async(llm_request, stream):
                    produced = True
                    yield response
                if produced:
                    if index:
                        logger.warning(
                            "Model %s answered after %d model(s) were unavailable.",
                            self.model_names[index], index,
                        )
                    return
                last_error = RuntimeError(f"{self.model_names[index]} produced no response")
            except Exception as exc:  # noqa: BLE001 - decide by error, below
                last_error = exc
                if not _is_failover_error(exc):
                    # A bad request fails the same way everywhere. Surface it now
                    # rather than repeating it against every model.
                    raise
                logger.warning(
                    "Model %s unavailable (%s). Falling back.",
                    self.model_names[index], str(exc)[:120],
                )

        raise RuntimeError(
            "Every configured Gemini model was unavailable "
            f"({', '.join(self.model_names)}). Last error: {last_error}"
        )


def build_model(primary: str, fallbacks: List[str]) -> FallbackGemini:
    """Build the model chain, de-duplicated and preserving order."""
    ordered: List[str] = []
    for name in [primary, *fallbacks]:
        name = name.strip()
        if name and name not in ordered:
            ordered.append(name)
    return FallbackGemini(ordered)
