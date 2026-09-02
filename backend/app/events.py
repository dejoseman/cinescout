"""In-process progress bus backing the SSE stream.

Each project gets a channel with a replay buffer, so a browser that connects a
moment after the pipeline starts still receives every event from the beginning.
That matters for the demo: the user submits a brief and navigates, and the first
stage has often already fired by the time the stream opens.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncGenerator, Dict, List, Set

logger = logging.getLogger(__name__)

#: Bounded so a runaway pipeline cannot grow memory without limit.
MAX_HISTORY = 500
SUBSCRIBER_QUEUE_SIZE = 500


class ProjectChannel:
    """Fan-out channel for one project's pipeline events."""

    def __init__(self) -> None:
        self.history: List[Dict[str, Any]] = []
        self.subscribers: Set[asyncio.Queue] = set()
        self.closed = False

    def publish(self, event: Dict[str, Any]) -> None:
        """Record an event and push it to every live subscriber.

        Never blocks and never raises: a slow or dead client must not be able to
        stall the pipeline.
        """
        if len(self.history) < MAX_HISTORY:
            self.history.append(event)

        for queue in list(self.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Dropping SSE event for a saturated subscriber.")

        if event.get("type") in {"complete", "failed"}:
            self.closed = True

    async def subscribe(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Replay history, then stream live events until the pipeline ends."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self.subscribers.add(queue)
        try:
            for event in list(self.history):
                yield event
            if self.closed:
                return

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    # Keep intermediaries from closing an idle connection.
                    yield {"type": "heartbeat"}
                    continue
                yield event
                if event.get("type") in {"complete", "failed"}:
                    return
        finally:
            self.subscribers.discard(queue)


class ProgressBus:
    """Registry of per-project channels."""

    def __init__(self) -> None:
        self._channels: Dict[str, ProjectChannel] = {}

    def channel(self, project_id: str) -> ProjectChannel:
        return self._channels.setdefault(project_id, ProjectChannel())

    def publish(self, project_id: str, event: Dict[str, Any]) -> None:
        self.channel(project_id).publish(event)

    def emitter(self, project_id: str):
        """Return a bound, non-async publish callable for a single project."""
        channel = self.channel(project_id)

        def emit(event_type: str, **fields: Any) -> None:
            channel.publish({"type": event_type, **fields})

        return emit

    def discard(self, project_id: str) -> None:
        self._channels.pop(project_id, None)


bus = ProgressBus()
