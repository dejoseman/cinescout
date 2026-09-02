"""Stage 3 - concurrent, per-task evidence extraction.

Originally a single ``LlmAgent`` handling every research task in one call. That
worked but was the pipeline's bottleneck by an order of magnitude: measured live
on 2026-09-02 it took 371s of a 406s run, while producing only ~8KB of output.
Every other stage finished in under nine seconds.

Splitting the work per research task turns a serial call into ``asyncio.gather``
over small ones, so total latency is roughly the slowest task rather than the sum
of all of them.

It also tightens the provenance guarantee. Each call sees only the sources
retrieved for its own task, so a claim cannot cite a source that belongs to a
different question - a stronger constraint than the global catalogue allowed.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Dict, List, Mapping, Set

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from ..config import settings
from ..schemas import Confidence, EvidenceItem, EvidenceSet, ResearchCategory
from . import prompts

logger = logging.getLogger(__name__)

#: Concurrency cap. Enough to collapse the latency, low enough to stay clear of
#: per-minute request limits. The Gemini free tier allows only 5 requests per
#: minute per model, so a wide burst here exhausts the quota for the whole
#: pipeline. Configurable for paid keys, where a higher value is faster.
MAX_CONCURRENT_EXTRACTIONS = max(1, settings.evidence_concurrency)


def _normalise_claim(claim: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", claim.lower()).strip()


def _enum(value: Any, enum_cls, default):
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(getattr(value, "value", value)).strip().upper())
    except (ValueError, AttributeError):
        return default


class EvidenceAgent(BaseAgent):
    """Extracts source-bound claims, one concurrent model call per task."""

    emit: Callable[..., None]
    model: BaseLlm
    brief_block: str
    generate_config: types.GenerateContentConfig

    model_config = {"arbitrary_types_allowed": True}

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        digests = state.get("task_digests") or []
        digests = [d for d in digests if isinstance(d, Mapping) and d.get("digest")]

        if not digests:
            self.emit(
                "stage_completed",
                stage="evidence",
                metrics={"claims": 0, "dropped": 0, "note": "no retrieved content"},
            )
            yield self._event(ctx, {"evidence": []})
            return

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)

        async def extract(entry: Mapping[str, Any]) -> List[Dict[str, Any]]:
            async with semaphore:
                return await self._extract_one(entry)

        results = await asyncio.gather(
            *(extract(entry) for entry in digests), return_exceptions=True
        )

        validated: List[Dict[str, Any]] = []
        seen: Set[tuple] = set()
        dropped = 0
        failed_tasks = 0
        now = datetime.now(timezone.utc).isoformat()

        for entry, result in zip(digests, results):
            if isinstance(result, BaseException):
                failed_tasks += 1
                logger.warning(
                    "Evidence extraction failed for task %s: %s",
                    entry.get("task_id"), result,
                )
                continue

            for raw in result:
                claim = str(raw.get("claim") or "").strip()[:600]
                key = (raw["source_id"], _normalise_claim(claim))
                if key in seen:
                    dropped += 1
                    continue
                seen.add(key)

                item = EvidenceItem(
                    id=f"e{len(validated) + 1}",
                    task_id=str(entry.get("task_id") or "unknown"),
                    category=_enum(
                        raw.get("category"), ResearchCategory,
                        _enum(entry.get("category"), ResearchCategory, ResearchCategory.OTHER),
                    ),
                    claim=claim,
                    source_id=raw["source_id"],
                    excerpt=str(raw.get("excerpt") or "").strip()[:1200],
                    confidence=_enum(raw.get("confidence"), Confidence, Confidence.MEDIUM),
                    retrieved_at=now,
                )
                validated.append(item.model_dump(mode="json"))
                self.emit(
                    "evidence_found",
                    evidence_id=item.id,
                    claim=item.claim[:220],
                    source_id=item.source_id,
                    category=item.category.value,
                    confidence=item.confidence.value,
                )

        self.emit(
            "stage_completed",
            stage="evidence",
            metrics={
                "claims": len(validated),
                "dropped": dropped,
                "failed_tasks": failed_tasks,
            },
        )
        yield self._event(ctx, {"evidence": validated})

    async def _extract_one(self, entry: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """Run one extraction and keep only claims citing this task's sources."""
        allowed: Set[str] = {str(s) for s in (entry.get("source_ids") or [])}

        request = LlmRequest(
            model=self.model.model,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text="Extract the evidence as instructed.")],
                )
            ],
            config=self.generate_config.model_copy(
                update={
                    "system_instruction": prompts.evidence_instruction(
                        self.brief_block,
                        str(entry.get("catalog_block") or ""),
                        str(entry.get("digest") or ""),
                    ),
                    "response_mime_type": "application/json",
                    "response_schema": EvidenceSet,
                }
            ),
        )

        text = ""
        async for response in self.model.generate_content_async(request, False):
            if response.content and response.content.parts:
                for part in response.content.parts:
                    if part.text:
                        text += part.text

        items = self._parse(text)
        kept: List[Dict[str, Any]] = []
        for raw in items:
            source_id = str(raw.get("source_id") or "").strip()
            excerpt = str(raw.get("excerpt") or "").strip()
            claim = str(raw.get("claim") or "").strip()
            # The provenance guarantee, enforced in code: the source must be one
            # this task actually retrieved.
            if source_id not in allowed or not claim or not excerpt:
                continue
            raw = dict(raw)
            raw["source_id"] = source_id
            kept.append(raw)
        return kept

    @staticmethod
    def _parse(text: str) -> List[Mapping[str, Any]]:
        import json

        text = text.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Evidence extraction returned unparseable JSON.")
            return []
        if isinstance(data, Mapping):
            data = data.get("items", [])
        return [d for d in data if isinstance(d, Mapping)] if isinstance(data, list) else []

    @staticmethod
    def _event(ctx: InvocationContext, delta: Dict[str, Any]) -> Event:
        return Event(
            author="evidence_agent",
            invocation_id=ctx.invocation_id,
            actions=EventActions(state_delta=delta),
        )
