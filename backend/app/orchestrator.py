"""Runs the ADK pipeline for one project and assembles the result.

Responsibilities:

* build the per-run agent tree and ADK ``Runner``
* record an :class:`AgentRun` for every stage, derived from the same events the
  UI sees, so observability and the interface never disagree
* translate the final session state into a typed :class:`Project`
* fail loudly and specifically - a broken run reports what broke, at which
  stage, and never emits a half-real report as if it were complete
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .agents.blocks import coerce_list
from .agents.pipeline import build_pipeline
from .config import settings
from .events import bus
from .integrations.parallel_client import ParallelNotConfigured
from .schemas import (
    AgentRun,
    EvidenceItem,
    ExecutiveReport,
    ProductionAssessment,
    Project,
    ProjectStatus,
    Recommendation,
    ResearchGap,
    ResearchPlan,
    Risk,
    SearchResult,
    Source,
    Stage,
    STAGE_LABELS,
    Verification,
)

logger = logging.getLogger(__name__)

APP_NAME = "cinescout"

#: Hard ceiling on a single run, so a hung upstream cannot pin a worker forever.
#: Raised for free-tier pacing (GEMINI_MAX_RPM=4): ~11 calls at 15s spacing
#: plus model processing time needs more headroom than the billing-tier 420s.
PIPELINE_TIMEOUT_S = 600

#: Bounds concurrent pipelines to keep latency and spend predictable.
_pipeline_slots = asyncio.Semaphore(settings.max_concurrent_pipelines)


def _parse_many(model_cls, raw: Any, key: str) -> List[Any]:
    """Validate a list of rows, skipping any that fail rather than aborting."""
    parsed = []
    for entry in coerce_list(raw, key):
        try:
            parsed.append(model_cls.model_validate(entry))
        except Exception:  # noqa: BLE001
            logger.debug("Dropping unparseable %s row.", model_cls.__name__)
    return parsed


def _parse_one(model_cls, raw: Any):
    if not isinstance(raw, dict):
        return None
    try:
        return model_cls.model_validate(raw)
    except Exception:  # noqa: BLE001
        logger.warning("Could not parse %s from state.", model_cls.__name__)
        return None


class RunRecorder:
    """Wraps the progress emitter to also build the AgentRun timeline."""

    def __init__(self, project_id: str) -> None:
        self._emit = bus.emitter(project_id)
        self.runs: Dict[str, AgentRun] = {}
        self.order: List[str] = []

    def __call__(self, event_type: str, **fields: Any) -> None:
        stage = fields.get("stage")
        if event_type == "stage_started" and stage:
            # Stages run strictly in sequence, so a new one starting means the
            # previous has finished. Without this, a stage that emits no
            # completion event (the plain LLM stages do not) would stay open and
            # later be stamped with the entire run's duration.
            self.close_open_runs()
            run = AgentRun(
                stage=Stage(stage),
                label=str(fields.get("label") or STAGE_LABELS.get(stage, stage)),
                status="RUNNING",
            )
            self.runs[stage] = run
            if stage not in self.order:
                self.order.append(stage)
        elif event_type == "stage_completed" and stage:
            run = self.runs.get(stage)
            if run:
                run.finished_at = datetime.now(timezone.utc)
                run.status = "OK"
                run.duration_ms = int(
                    (run.finished_at - run.started_at).total_seconds() * 1000
                )
                metrics = fields.get("metrics")
                if metrics:
                    run.detail = ", ".join(f"{k}: {v}" for k, v in metrics.items())
        elif event_type == "error" and stage:
            run = self.runs.get(stage)
            if run:
                run.status = "ERROR"
                run.detail = str(fields.get("message") or "")[:300]

        self._emit(event_type, **fields)

    def timeline(self) -> List[AgentRun]:
        return [self.runs[stage] for stage in self.order if stage in self.runs]

    def close_open_runs(self, status: str = "OK") -> None:
        """Stages that never emitted a completion (the LLM stages) get closed here."""
        for run in self.runs.values():
            if run.finished_at is None:
                run.finished_at = datetime.now(timezone.utc)
                run.status = status
                run.duration_ms = int(
                    (run.finished_at - run.started_at).total_seconds() * 1000
                )


async def run_pipeline(project: Project) -> Project:
    """Execute the full pipeline, mutating and returning the project."""
    emit = RunRecorder(project.id)

    async with _pipeline_slots:
        project.status = ProjectStatus.RUNNING
        emit("pipeline_started", project_id=project.id, title=project.brief.title)

        #: Retry the whole pipeline once on transient "model output" errors
        #: (ADK raises these when Gemini returns an empty response).
        max_attempts = 2
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            session_service = InMemorySessionService()
            pipeline = build_pipeline(emit, project.brief.to_prompt_block())
            runner = Runner(
                app_name=APP_NAME,
                agent=pipeline,
                session_service=session_service,
            )

            session = await session_service.create_session(
                app_name=APP_NAME,
                user_id="producer",
                session_id=f"{project.id}_attempt{attempt}",
                state={"brief": project.brief.model_dump(mode="json")},
            )

            # ADK anchors each stage's context on this message; the substance of
            # every prompt is built deterministically from session state.
            kickoff = types.Content(
                role="user",
                parts=[types.Part(text=f"Assess production feasibility for: {project.brief.title}")],
            )

            try:
                async def drive() -> None:
                    async for event in runner.run_async(
                        user_id="producer",
                        session_id=session.id,
                        new_message=kickoff,
                    ):
                        if event.error_message:
                            logger.warning(
                                "ADK event error from %s: %s", event.author, event.error_message
                            )

                await asyncio.wait_for(drive(), timeout=PIPELINE_TIMEOUT_S)

                # Success — break out of retry loop
                final = await session_service.get_session(
                    app_name=APP_NAME, user_id="producer", session_id=session.id
                )
                state: Dict[str, Any] = dict(final.state) if final else {}

                _populate(project, state)
                emit.close_open_runs()
                project.runs = emit.timeline()
                project.status = ProjectStatus.COMPLETE
                project.completed_at = datetime.now(timezone.utc)

                emit(
                    "complete",
                    project_id=project.id,
                    readiness=project.assessment.readiness_score if project.assessment else None,
                    sources=len(project.sources),
                    evidence=len(project.evidence),
                    risks=len(project.risks),
                )
                return project

            except ParallelNotConfigured as exc:
                return _fail(project, emit, str(exc))
            except asyncio.TimeoutError:
                return _fail(
                    project, emit,
                    f"The research pipeline exceeded its {PIPELINE_TIMEOUT_S}s time limit. "
                    "The most common cause is Gemini rate limiting: a free-tier key allows "
                    "only 5 requests per minute per model. Try setting GEMINI_MODEL to a "
                    "model with available quota (e.g. gemini-3.1-flash-lite), lowering "
                    "GEMINI_MAX_RPM to 4, EVIDENCE_CONCURRENCY to 1, and "
                    "MAX_RESEARCH_TASKS to 5.",
                )
            except Exception as exc:  # noqa: BLE001 - surface, never swallow
                last_exc = exc
                detail = str(exc)

                # Transient empty model response — retry if we have attempts left
                if ("model output" in detail.lower() or "cannot both be empty" in detail.lower()):
                    if attempt < max_attempts:
                        logger.warning(
                            "Pipeline attempt %d/%d failed with empty model response, "
                            "retrying in 5s: %s", attempt, max_attempts, detail[:200],
                        )
                        await asyncio.sleep(5.0)
                        continue
                    # Exhausted retries
                    return _fail(
                        project, emit,
                        "The model returned empty responses on multiple attempts. "
                        "This usually resolves by waiting a minute and retrying. "
                        "If it persists, try changing GEMINI_MODEL to a different model.",
                    )

                logger.exception("Pipeline failed for project %s", project.id)
                if "RESOURCE_EXHAUSTED" in detail or "429" in detail or "quota" in detail.lower():
                    return _fail(
                        project, emit,
                        "Gemini rejected requests for exceeding the API quota. Free-tier "
                        "limit is 5 requests per minute per model. Ensure GEMINI_MODEL "
                        "is set to a model with available quota (e.g. gemini-3.1-flash-lite), "
                        "GEMINI_MAX_RPM is 4 or lower, EVIDENCE_CONCURRENCY to 1, and "
                        "MAX_RESEARCH_TASKS is 5 or lower. Wait 60 seconds before retrying.",
                    )
                return _fail(project, emit, f"{type(exc).__name__}: {exc}")

        # Should not reach here, but just in case:
        return _fail(project, emit, f"Pipeline exhausted all {max_attempts} attempts. Last error: {last_exc}")


def _populate(project: Project, state: Dict[str, Any]) -> None:
    """Translate final session state into the typed aggregate."""
    project.plan = _parse_one(ResearchPlan, state.get("research_plan"))
    project.search_results = _parse_many(SearchResult, state.get("search_results"), "items")
    project.sources = _parse_many(Source, state.get("sources"), "items")
    project.evidence = _parse_many(EvidenceItem, state.get("evidence"), "items")
    project.verifications = _parse_many(Verification, state.get("verifications"), "items")
    project.risks = _parse_many(Risk, state.get("risks"), "risks")
    project.gaps = _parse_many(ResearchGap, state.get("gaps"), "gaps")
    project.recommendations = _parse_many(
        Recommendation, state.get("recommendations"), "items"
    )
    project.assessment = _parse_one(ProductionAssessment, state.get("assessment"))
    project.report = _parse_one(ExecutiveReport, state.get("report"))

    # Be explicit with the user about anything that reduced the quality of the run.
    failed = [r for r in project.search_results if r.status.value == "FAILED"]
    if failed:
        project.warnings.append(
            f"{len(failed)} of {len(project.search_results)} research tasks failed to "
            "return results. Coverage and readiness are reduced accordingly."
        )
    empty = [r for r in project.search_results if r.status.value == "EMPTY"]
    if empty:
        project.warnings.append(
            f"{len(empty)} research tasks returned no usable content."
        )
    if not project.evidence:
        project.warnings.append(
            "No verifiable claims could be extracted. Treat this report as unproven."
        )
    if project.report is None:
        project.warnings.append(
            "The executive report could not be generated; the underlying findings are "
            "still shown below."
        )


def _fail(project: Project, emit: RunRecorder, message: str) -> Project:
    """Mark a run failed and tell the user exactly what happened."""
    emit.close_open_runs(status="ERROR")
    project.runs = emit.timeline()
    project.status = ProjectStatus.FAILED
    project.error = message
    project.completed_at = datetime.now(timezone.utc)
    emit("failed", project_id=project.id, message=message)
    return project
