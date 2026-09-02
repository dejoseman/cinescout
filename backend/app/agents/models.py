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

import asyncio
import logging
import time
from collections import deque
from typing import Any, AsyncGenerator, Deque, List

from google.adk.models.base_llm import BaseLlm
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from ..config import settings

logger = logging.getLogger(__name__)

#: Transport retry is disabled on purpose.
#:
#: The client's own retries do not pass through :class:`RequestPacer`, so one
#: paced request could become several real HTTP requests and blow through the
#: per-minute quota the pacer exists to respect. Measured live: pacing with
#: transport retry still produced 22 quota rejections and pushed a 131s run to
#: 283s. With retries disabled, one paced slot means exactly one request, and
#: recovery is handled where it can be accounted for - the failover chain.
RETRY_OPTIONS = types.HttpRetryOptions(attempts=1)

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


class RequestPacer:
    """Caps model requests to a rolling requests-per-minute budget.

    Rate limiting is self-amplifying without this: a burst trips a 429, each
    retry spends another quota unit, and the retries trip further 429s. Observed
    live on 2026-09-02 - 36 quota rejections in a single run that only needed
    about eleven successful calls.

    Waiting for a slot is strictly cheaper than being rejected and retrying, so
    pacing makes a constrained run faster, not slower.
    """

    def __init__(self, requests_per_minute: int) -> None:
        self.limit = max(1, requests_per_minute)
        self._recent: Deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._recent and now - self._recent[0] >= 60.0:
                    self._recent.popleft()
                if len(self._recent) < self.limit:
                    self._recent.append(now)
                    return
                wait = 60.0 - (now - self._recent[0])
            logger.debug("Pacing model requests: waiting %.1fs for a slot.", wait)
            # Re-check rather than trusting one long sleep; other coroutines
            # release slots as their entries age out of the window.
            await asyncio.sleep(min(max(wait, 0.05), 5.0))


#: Shared across every stage, since the quota is per project, not per agent.
pacer = RequestPacer(settings.gemini_max_rpm)


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
            await pacer.acquire()
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
                # Collapse whitespace before truncating: provider errors often
                # begin with a newline, which otherwise hides the actual cause
                # behind a mitigation link.
                summary = " ".join(str(exc).split())[:220] or type(exc).__name__
                logger.warning(
                    "Model %s unavailable (%s: %s). Falling back.",
                    self.model_names[index], type(exc).__name__, summary,
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
