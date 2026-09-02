"""Request-level protections.

Two concerns, both about bounding cost: a single client should not be able to
launch unlimited pipelines, and log output must never carry a credential.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import Request

WINDOW_SECONDS = 3600


class RateLimiter:
    """Fixed-window limiter keyed by client address.

    Deliberately simple and in-process. Behind a multi-instance deployment this
    limits per instance, which is sufficient for its purpose here - bounding
    accidental or casual abuse of a demo service - and is documented as such.
    """

    def __init__(self, limit: int, window: int = WINDOW_SECONDS) -> None:
        self.limit = limit
        self.window = window
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def retry_after(self, key: str) -> int:
        hits = self._hits.get(key)
        if not hits:
            return 0
        return max(1, int(self.window - (time.time() - hits[0])))


def client_key(request: Request) -> str:
    """Identify the caller for rate-limiting purposes.

    Cloud Run terminates TLS upstream, so the left-most X-Forwarded-For entry is
    the real client. Falls back to the socket address.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


#: Anything resembling a key is masked before it can reach a log sink.
_SECRET_PATTERN = re.compile(
    r"(?i)\b(?:api[_-]?key|authorization|x-api-key|bearer|token)\b\s*[:=]\s*\S+"
)


class RedactingFilter(logging.Filter):
    """Strips credential-shaped text from every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and _SECRET_PATTERN.search(record.msg):
            record.msg = _SECRET_PATTERN.sub("[redacted]", record.msg)
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    handler.addFilter(RedactingFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # ADK and httpx are chatty at INFO and can echo request payloads.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("google_adk").setLevel(logging.WARNING)
