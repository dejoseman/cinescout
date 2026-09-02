"""Parallel Search API client.

This is the only path through which external world knowledge enters CineScout.
It is deliberately strict:

* A failed search returns a typed :class:`SearchFailure`. It never returns
  invented results, and the caller never substitutes model recall for it.
* URLs are canonicalised and deduplicated so a source cited twice is one source.
* The client tolerates both Parallel API generations: it targets the GA
  ``/v1/search`` shape and falls back to the older ``/v1beta/search`` shape
  (flat ``processor``/``max_results``) if the GA route is not available.

Contract (GA)::

    POST https://api.parallel.ai/v1/search
    x-api-key: <key>
    { "search_queries": [...], "objective": "...", "mode": "base",
      "advanced_settings": { "max_results": 6,
                             "excerpt_settings": {"max_chars_per_result": 1500} } }

    -> { "search_id", "session_id", "results": [
           {"url", "title", "publish_date", "excerpts": [...]} ], "warnings", "usage" }
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

#: Query parameters that identify a campaign rather than a document.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "ref_src", "source",
}

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def canonicalise_url(url: str) -> str:
    """Normalise a URL so the same document dedupes to one entry.

    Lowercases the host, drops ``www.``, strips tracking parameters and any
    fragment, and removes a trailing slash on non-root paths.
    """
    try:
        parts = urlparse(url.strip())
    except ValueError:
        return url.strip()
    if not parts.scheme or not parts.netloc:
        return url.strip()

    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
         if k.lower() not in _TRACKING_PARAMS]
    )
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]

    return urlunparse((parts.scheme.lower(), host, path, "", query, ""))


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------


@dataclass
class SearchHit:
    """One retrieved document."""

    url: str
    title: str
    publish_date: Optional[str]
    excerpts: List[str] = field(default_factory=list)


@dataclass
class SearchSuccess:
    task_id: str
    queries: List[str]
    hits: List[SearchHit]
    search_id: Optional[str]
    latency_ms: int
    ok: bool = True


@dataclass
class SearchFailure:
    """A search that genuinely failed. Surfaced to the user as FAILED."""

    task_id: str
    queries: List[str]
    error: str
    latency_ms: int
    ok: bool = False


SearchOutcome = SearchSuccess | SearchFailure


class ParallelNotConfigured(RuntimeError):
    """Raised when no API key is present. The pipeline refuses to run."""


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------


class ParallelSearchClient:
    """Async client with bounded concurrency, retries and generation fallback."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        *,
        concurrency: Optional[int] = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.parallel_api_key
        self.base_url = (base_url or settings.parallel_base_url).rstrip("/")
        self._semaphore = asyncio.Semaphore(concurrency or settings.parallel_concurrency)
        self._client: Optional[httpx.AsyncClient] = None
        # Set to "/v1beta/search" once we learn the GA route is unavailable.
        self._path = "/v1/search"

    def _headers(self) -> dict[str, str]:
        """Auth and content headers. Kept separate so tests exercise the real ones."""
        return {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "CineScout/1.0",
        }

    async def __aenter__(self) -> "ParallelSearchClient":
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.parallel_timeout_s),
            headers=self._headers(),
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # -- request construction -------------------------------------------------

    def _payload(self, queries: List[str], objective: str) -> dict:
        """Build the request body for whichever API generation is in play."""
        if self._path == "/v1/search":
            return {
                "search_queries": queries,
                "objective": objective[:1500],
                "mode": settings.parallel_mode,
                "advanced_settings": {
                    "max_results": settings.parallel_max_results,
                    "excerpt_settings": {
                        "max_chars_per_result": settings.parallel_max_chars,
                    },
                },
            }
        # Older generation: flat fields, "processor" instead of "mode".
        return {
            "search_queries": queries,
            "objective": objective[:1500],
            "processor": settings.parallel_mode,
            "max_results": settings.parallel_max_results,
            "max_chars_per_result": settings.parallel_max_chars,
        }

    @staticmethod
    def _parse(data: dict) -> tuple[List[SearchHit], Optional[str]]:
        """Normalise a Parallel response into hits, tolerating field drift."""
        hits: List[SearchHit] = []
        seen: set[str] = set()

        for raw in data.get("results") or []:
            if not isinstance(raw, dict):
                continue
            url = (raw.get("url") or "").strip()
            if not url:
                continue
            canonical = canonicalise_url(url)
            if canonical in seen:
                continue
            seen.add(canonical)

            excerpts_raw = raw.get("excerpts") or raw.get("excerpt") or []
            if isinstance(excerpts_raw, str):
                excerpts_raw = [excerpts_raw]
            excerpts = [
                e.strip() for e in excerpts_raw if isinstance(e, str) and e.strip()
            ]

            hits.append(
                SearchHit(
                    url=canonical,
                    title=(raw.get("title") or "").strip()[:300],
                    publish_date=raw.get("publish_date") or raw.get("published_date"),
                    excerpts=excerpts,
                )
            )
        return hits, data.get("search_id")

    # -- public API -----------------------------------------------------------

    async def search(
        self, task_id: str, queries: List[str], objective: str
    ) -> SearchOutcome:
        """Run one search. Never raises for expected failure modes."""
        if not self.api_key:
            raise ParallelNotConfigured(
                "PARALLEL_API_KEY is not set. CineScout cannot perform live research."
            )
        if self._client is None:
            raise RuntimeError("Use ParallelSearchClient as an async context manager.")

        clean = [q.strip() for q in queries if q and q.strip()][:5]
        if not clean:
            return SearchFailure(task_id, queries, "No valid search queries generated.", 0)

        started = time.perf_counter()
        last_error = "unknown error"

        async with self._semaphore:
            for attempt in range(settings.parallel_max_retries):
                try:
                    response = await self._client.post(
                        f"{self.base_url}{self._path}",
                        json=self._payload(clean, objective),
                    )

                    # GA route absent -> switch generation once and retry now.
                    if response.status_code == 404 and self._path == "/v1/search":
                        logger.info("Parallel /v1/search unavailable; falling back to /v1beta.")
                        self._path = "/v1beta/search"
                        continue

                    if response.status_code in _RETRYABLE_STATUS:
                        last_error = f"HTTP {response.status_code}"
                        await self._backoff(attempt, response)
                        continue

                    if response.status_code == 401:
                        return SearchFailure(
                            task_id, clean,
                            "Parallel rejected the API key (401).",
                            self._ms(started),
                        )
                    if response.status_code >= 400:
                        return SearchFailure(
                            task_id, clean,
                            f"Parallel returned HTTP {response.status_code}.",
                            self._ms(started),
                        )

                    try:
                        data = response.json()
                    except ValueError:
                        last_error = "Malformed JSON from Parallel."
                        await self._backoff(attempt)
                        continue

                    if not isinstance(data, dict):
                        return SearchFailure(
                            task_id, clean, "Unexpected response shape.", self._ms(started)
                        )

                    hits, search_id = self._parse(data)
                    for warning in data.get("warnings") or []:
                        logger.warning("Parallel warning on %s: %s", task_id, warning)

                    return SearchSuccess(
                        task_id=task_id,
                        queries=clean,
                        hits=hits,
                        search_id=search_id,
                        latency_ms=self._ms(started),
                    )

                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    await self._backoff(attempt)

        return SearchFailure(task_id, clean, last_error, self._ms(started))

    async def search_many(self, tasks: list[tuple[str, List[str], str]]) -> List[SearchOutcome]:
        """Run many searches concurrently. One failure never cancels the rest."""
        results = await asyncio.gather(
            *(self.search(tid, q, obj) for tid, q, obj in tasks),
            return_exceptions=True,
        )
        outcomes: List[SearchOutcome] = []
        for (tid, queries, _), result in zip(tasks, results):
            if isinstance(result, BaseException):
                logger.exception("Search task %s raised", tid, exc_info=result)
                outcomes.append(SearchFailure(tid, queries, str(result) or "internal error", 0))
            else:
                outcomes.append(result)
        return outcomes

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    @staticmethod
    async def _backoff(attempt: int, response: Optional[httpx.Response] = None) -> None:
        """Exponential backoff with jitter, honouring Retry-After when present."""
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    await asyncio.sleep(min(float(retry_after), 10.0))
                    return
                except ValueError:
                    pass
        await asyncio.sleep(min(2**attempt * 0.5, 8.0) + random.uniform(0, 0.4))
