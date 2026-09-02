"""Stage 2 - the deterministic research agent.

This stage is Python, not a prompt, and that is the point. An LLM driving a
search tool in a loop may skip a task, retry unpredictably or decide it has
"enough" early. Here, every task in the plan is executed exactly once, failures
are recorded rather than hidden, and the source catalogue that downstream stages
are allowed to cite is built from what the API actually returned.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Callable, Dict, List, Mapping

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from ..config import settings
from ..integrations.parallel_client import (
    ParallelNotConfigured,
    ParallelSearchClient,
    SearchSuccess,
    domain_of,
)
from ..schemas import ResearchCategory, SearchResult, Source, TaskStatus
from .blocks import search_digest_block, source_catalog_block

logger = logging.getLogger(__name__)


def _category(raw: Any) -> ResearchCategory:
    """Coerce a model-supplied category, defaulting rather than failing.

    Unwraps ``.value`` first: ADK may return an enum member, and ``str()`` on a
    ``str``-Enum gives ``"ResearchCategory.PERMITS"`` rather than ``"PERMITS"``.
    """
    if isinstance(raw, ResearchCategory):
        return raw
    try:
        return ResearchCategory(str(getattr(raw, "value", raw)).strip().upper())
    except (ValueError, AttributeError):
        return ResearchCategory.OTHER


class ResearchAgent(BaseAgent):
    """Fans the research plan out across the Parallel Search API."""

    # ADK agents are pydantic models, so collaborators are declared as fields.
    emit: Callable[..., None]
    client_factory: Callable[[], ParallelSearchClient] = ParallelSearchClient

    model_config = {"arbitrary_types_allowed": True}

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        plan = state.get("research_plan") or {}
        raw_tasks = plan.get("tasks") if isinstance(plan, Mapping) else None
        tasks: List[Mapping[str, Any]] = [
            t for t in (raw_tasks or []) if isinstance(t, Mapping)
        ][: settings.max_research_tasks]

        if not tasks:
            # No plan means nothing to research. Say so; do not improvise one.
            self.emit(
                "error",
                stage="research",
                message="The planning stage produced no research tasks.",
                recoverable=False,
            )
            yield self._state_event(
                ctx,
                {
                    "search_results": [],
                    "sources": [],
                    "search_digest": "",
                    "source_catalog_block": "(no sources retrieved)",
                    "task_digests": [],
                },
            )
            return

        self.emit(
            "research_plan_ready",
            task_count=len(tasks),
            tasks=[
                {
                    "id": str(t.get("id") or f"t{i + 1}"),
                    "category": _category(t.get("category")).value,
                    "question": str(t.get("question") or "")[:300],
                    "priority": str(t.get("priority") or "MEDIUM"),
                    "queries": [str(q) for q in (t.get("search_queries") or [])][:5],
                }
                for i, t in enumerate(tasks)
            ],
            summary=str(plan.get("summary") or "")[:500],
            missing_information=[
                str(m)[:200] for m in (plan.get("missing_information") or [])
            ][:10],
        )

        payloads = [
            (
                str(task.get("id") or f"t{index + 1}"),
                [str(q) for q in (task.get("search_queries") or [])],
                str(task.get("objective") or task.get("question") or ""),
            )
            for index, task in enumerate(tasks)
        ]

        try:
            async with self.client_factory() as client:
                for task_id, _, _ in payloads:
                    self.emit("search_progress", task_id=task_id, status="RUNNING")
                outcomes = await client.search_many(payloads)
        except ParallelNotConfigured as exc:
            # Live research is not optional. Fail loudly rather than degrade to
            # model recall dressed up as research.
            self.emit("error", stage="research", message=str(exc), recoverable=False)
            raise

        state_delta = self._collect(tasks, payloads, outcomes)
        yield self._state_event(ctx, state_delta)

    # -- normalisation --------------------------------------------------------

    def _collect(
        self,
        tasks: List[Mapping[str, Any]],
        payloads: List[tuple[str, List[str], str]],
        outcomes: List[Any],
    ) -> Dict[str, Any]:
        """Turn raw search outcomes into a deduplicated, citable corpus."""
        by_id = {str(t.get("id") or f"t{i + 1}"): t for i, t in enumerate(tasks)}

        sources: List[Source] = []
        source_by_url: Dict[str, Source] = {}
        results: List[SearchResult] = []
        grouped: List[tuple[str, str, str, List[tuple[str, List[str]]]]] = []
        failures = 0

        for (task_id, queries, _), outcome in zip(payloads, outcomes):
            task = by_id.get(task_id, {})
            category = _category(task.get("category"))
            question = str(task.get("question") or "")[:300]

            if not isinstance(outcome, SearchSuccess):
                failures += 1
                results.append(
                    SearchResult(
                        task_id=task_id,
                        category=category,
                        question=question,
                        status=TaskStatus.FAILED,
                        queries=queries,
                        error=getattr(outcome, "error", "search failed"),
                        latency_ms=getattr(outcome, "latency_ms", 0),
                    )
                )
                self.emit(
                    "search_progress",
                    task_id=task_id,
                    category=category.value,
                    status="FAILED",
                    error=getattr(outcome, "error", "search failed")[:200],
                )
                continue

            task_source_ids: List[str] = []
            entries: List[tuple[str, List[str]]] = []
            excerpt_count = 0

            for hit in outcome.hits:
                if not hit.excerpts:
                    continue  # A result with no text cannot support a claim.
                source = source_by_url.get(hit.url)
                if source is None:
                    source = Source(
                        id=f"src_{len(sources) + 1:02d}",
                        url=hit.url,
                        domain=domain_of(hit.url),
                        title=hit.title,
                        publish_date=hit.publish_date,
                        first_seen_task=task_id,
                    )
                    sources.append(source)
                    source_by_url[hit.url] = source
                    self.emit(
                        "source_found",
                        source_id=source.id,
                        domain=source.domain,
                        title=source.title[:160],
                        url=source.url,
                        task_id=task_id,
                    )
                if source.id not in task_source_ids:
                    task_source_ids.append(source.id)
                entries.append((source.id, hit.excerpts))
                excerpt_count += len(hit.excerpts)

            status = TaskStatus.OK if task_source_ids else TaskStatus.EMPTY
            results.append(
                SearchResult(
                    task_id=task_id,
                    category=category,
                    question=question,
                    status=status,
                    queries=outcome.queries,
                    source_ids=task_source_ids,
                    excerpt_count=excerpt_count,
                    latency_ms=outcome.latency_ms,
                    search_id=outcome.search_id,
                )
            )
            grouped.append((task_id, category.value, question, entries))
            self.emit(
                "search_progress",
                task_id=task_id,
                category=category.value,
                status=status.value,
                sources=len(task_source_ids),
                excerpts=excerpt_count,
                latency_ms=outcome.latency_ms,
                search_id=outcome.search_id,
            )

        digest = search_digest_block(grouped, settings.max_evidence_chars)
        catalog = source_catalog_block(sources)

        # Per-task bundles for the evidence stage, which extracts each task
        # concurrently and may only cite that task's own sources.
        by_source_id = {s.id: s for s in sources}
        per_task_budget = max(4000, settings.max_evidence_chars // max(1, len(grouped)))
        task_digests = []
        for task_id, category, question, entries in grouped:
            task_source_ids = []
            for source_id, _ in entries:
                if source_id not in task_source_ids:
                    task_source_ids.append(source_id)
            task_digests.append({
                "task_id": task_id,
                "category": category,
                "question": question,
                "source_ids": task_source_ids,
                "catalog_block": source_catalog_block(
                    [by_source_id[i] for i in task_source_ids if i in by_source_id]
                ),
                "digest": search_digest_block(
                    [(task_id, category, question, entries)], per_task_budget
                ),
            })

        self.emit(
            "stage_completed",
            stage="research",
            metrics={
                "sources": len(sources),
                "domains": len({s.domain for s in sources}),
                "tasks": len(results),
                "failed_tasks": failures,
                "excerpts": sum(r.excerpt_count for r in results),
            },
        )

        return {
            "search_results": [r.model_dump(mode="json") for r in results],
            "sources": [s.model_dump(mode="json") for s in sources],
            "search_digest": digest,
            "source_catalog_block": catalog,
            "task_digests": task_digests,
        }

    @staticmethod
    def _state_event(ctx: InvocationContext, state_delta: Dict[str, Any]) -> Event:
        return Event(
            author="research_agent",
            invocation_id=ctx.invocation_id,
            actions=EventActions(state_delta=state_delta),
        )
