"""The CineScout agent pipeline.

An ADK ``SequentialAgent`` composed of eight stages. Six are Gemini-backed
``LlmAgent``s with typed structured output; two - research and scoring - are
deterministic Python ``BaseAgent``s.

The tree is constructed per run so that each stage can be bound to that run's
progress emitter, and so no agent instance is ever shared between two parents.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Callable, Dict, List

from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event, EventActions
from google.genai import types

from ..config import settings
from ..integrations.parallel_client import ParallelSearchClient
from ..schemas import (
    EvidenceSet,
    ExecutiveReport,
    ProductionAssessment,
    RecommendationSet,
    ResearchGap,
    ResearchPlan,
    Risk,
    RiskSet,
    SearchResult,
    Source,
    Stage,
    STAGE_LABELS,
    VerificationSet,
    EvidenceItem,
    Verification,
)
from ..scoring import compute_assessment
from . import blocks, prompts
from .research_agent import ResearchAgent
from .validators import (
    make_evidence_validator,
    make_recommendation_validator,
    make_risk_validator,
    make_verification_validator,
)

logger = logging.getLogger(__name__)

#: Low temperature: this is an analysis system, not a creative one.
GENERATION_CONFIG = types.GenerateContentConfig(temperature=0.2, top_p=0.9)


def _stage_start(emit: Callable[..., None], stage: Stage) -> Callable:
    """Emit a stage_started event as an agent begins."""

    def callback(callback_context: CallbackContext) -> None:
        emit("stage_started", stage=stage.value, label=STAGE_LABELS[stage])

    return callback


class ScoringAgent(BaseAgent):
    """Stage 6 - deterministic readiness scoring. No model involved."""

    emit: Callable[..., None]

    model_config = {"arbitrary_types_allowed": True}

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        self.emit("stage_started", stage=Stage.SCORING.value, label=STAGE_LABELS[Stage.SCORING])

        def parse(model_cls, raw: Any, key: str) -> List[Any]:
            parsed = []
            for entry in blocks.coerce_list(raw, key):
                try:
                    parsed.append(model_cls.model_validate(entry))
                except Exception:  # noqa: BLE001 - a bad row must not stop scoring
                    logger.debug("Skipping unparseable %s row", model_cls.__name__)
            return parsed

        assessment = compute_assessment(
            search_results=parse(SearchResult, state.get("search_results"), "items"),
            sources=parse(Source, state.get("sources"), "items"),
            evidence=parse(EvidenceItem, state.get("evidence"), "items"),
            verifications=parse(Verification, state.get("verifications"), "items"),
            risks=parse(Risk, state.get("risks"), "risks"),
            gaps=parse(ResearchGap, state.get("gaps"), "gaps"),
        )

        self.emit(
            "stage_completed",
            stage=Stage.SCORING.value,
            metrics={
                "readiness": assessment.readiness_score,
                "confidence": assessment.evidence_confidence,
                "coverage": assessment.research_coverage,
            },
        )

        yield Event(
            author="scoring_agent",
            invocation_id=ctx.invocation_id,
            actions=EventActions(
                state_delta={"assessment": assessment.model_dump(mode="json")}
            ),
        )


def _assessment_of(state) -> ProductionAssessment:
    raw = state.get("assessment")
    if isinstance(raw, dict):
        try:
            return ProductionAssessment.model_validate(raw)
        except Exception:  # noqa: BLE001
            logger.warning("Assessment in state was unparseable; using an empty one.")
    return ProductionAssessment(
        readiness_score=0, evidence_confidence=0, research_coverage=0,
        critical_risks=0, high_risks=0, medium_risks=0, low_risks=0,
        research_gaps=0, verified_sources=0, total_sources=0,
        total_evidence=0, conflicting_findings=0,
    )


def _parsed(model_cls, raw: Any, key: str) -> List[Any]:
    out = []
    for entry in blocks.coerce_list(raw, key):
        try:
            out.append(model_cls.model_validate(entry))
        except Exception:  # noqa: BLE001
            continue
    return out


def build_pipeline(
    emit: Callable[..., None],
    brief_block: str,
    client_factory: Callable[[], Any] = ParallelSearchClient,
) -> SequentialAgent:
    """Construct the full eight-stage pipeline for one production brief.

    ``client_factory`` is injectable so the pipeline can be exercised
    end-to-end in tests without reaching the network.
    """

    fast = settings.model
    deep = settings.reasoning_model_or_default()

    # -- Stage 1: plan the research ------------------------------------------
    brief_agent = LlmAgent(
        name="brief_agent",
        model=fast,
        description="Extracts requirements and produces a research plan.",
        instruction=lambda _ctx: prompts.brief_instruction(
            brief_block, settings.max_research_tasks
        ),
        output_schema=ResearchPlan,
        output_key="research_plan",
        include_contents="none",
        generate_content_config=GENERATION_CONFIG,
        before_agent_callback=_stage_start(emit, Stage.BRIEF),
    )

    # -- Stage 2: execute it against the live web (deterministic) -------------
    research_agent = ResearchAgent(
        name="research_agent",
        description="Executes every research task against the Parallel Search API.",
        emit=emit,
        client_factory=client_factory,
        before_agent_callback=_stage_start(emit, Stage.RESEARCH),
    )

    # -- Stage 3: raw excerpts -> citable claims ------------------------------
    def evidence_instruction(ctx: ReadonlyContext) -> str:
        state = ctx.state
        return prompts.evidence_instruction(
            brief_block,
            str(state.get("source_catalog_block") or "(no sources retrieved)"),
            str(state.get("search_digest") or "(no content retrieved)"),
        )

    evidence_agent = LlmAgent(
        name="evidence_agent",
        model=fast,
        description="Extracts atomic, source-bound claims from retrieved content.",
        instruction=evidence_instruction,
        output_schema=EvidenceSet,
        output_key="evidence",
        include_contents="none",
        generate_content_config=GENERATION_CONFIG,
        before_agent_callback=_stage_start(emit, Stage.EVIDENCE),
        after_agent_callback=make_evidence_validator(emit),
    )

    # -- Stage 4: cross-check claims against each other -----------------------
    def verification_instruction(ctx: ReadonlyContext) -> str:
        state = ctx.state
        evidence = _parsed(EvidenceItem, state.get("evidence"), "items")
        return prompts.verification_instruction(
            str(state.get("source_catalog_block") or "(no sources retrieved)"),
            blocks.evidence_block(evidence),
        )

    verification_agent = LlmAgent(
        name="verification_agent",
        model=deep,
        description="Corroborates, contradicts and dates the evidence.",
        instruction=verification_instruction,
        output_schema=VerificationSet,
        output_key="verifications",
        include_contents="none",
        generate_content_config=GENERATION_CONFIG,
        before_agent_callback=_stage_start(emit, Stage.VERIFICATION),
        after_agent_callback=make_verification_validator(emit),
    )

    # -- Stage 5: risks and gaps ----------------------------------------------
    def risk_instruction(ctx: ReadonlyContext) -> str:
        state = ctx.state
        evidence = _parsed(EvidenceItem, state.get("evidence"), "items")
        verifications = _parsed(Verification, state.get("verifications"), "items")
        return prompts.risk_instruction(
            brief_block,
            blocks.evidence_block(evidence),
            blocks.verification_block(verifications),
        )

    risk_agent = LlmAgent(
        name="risk_agent",
        model=deep,
        description="Derives production risks and open research gaps.",
        instruction=risk_instruction,
        output_schema=RiskSet,
        output_key="risks",
        include_contents="none",
        generate_content_config=GENERATION_CONFIG,
        before_agent_callback=_stage_start(emit, Stage.RISK),
        after_agent_callback=make_risk_validator(emit),
    )

    # -- Stage 6: deterministic scoring ---------------------------------------
    scoring_agent = ScoringAgent(
        name="scoring_agent",
        description="Computes production readiness deterministically.",
        emit=emit,
    )

    # -- Stage 7: recommendations ---------------------------------------------
    def recommendation_instruction(ctx: ReadonlyContext) -> str:
        state = ctx.state
        return prompts.recommendation_instruction(
            brief_block,
            blocks.risk_block(_parsed(Risk, state.get("risks"), "risks")),
            blocks.gap_block(_parsed(ResearchGap, state.get("gaps"), "gaps")),
            blocks.assessment_block(_assessment_of(state)),
        )

    recommendation_agent = LlmAgent(
        name="recommendation_agent",
        model=deep,
        description="Turns findings into prioritised producer actions.",
        instruction=recommendation_instruction,
        output_schema=RecommendationSet,
        output_key="recommendations",
        include_contents="none",
        generate_content_config=GENERATION_CONFIG,
        before_agent_callback=_stage_start(emit, Stage.RECOMMENDATION),
        after_agent_callback=make_recommendation_validator(emit),
    )

    # -- Stage 8: executive report --------------------------------------------
    def report_instruction(ctx: ReadonlyContext) -> str:
        state = ctx.state
        from ..schemas import Recommendation

        return prompts.report_instruction(
            brief_block,
            blocks.assessment_block(_assessment_of(state)),
            blocks.risk_block(_parsed(Risk, state.get("risks"), "risks")),
            blocks.recommendation_block(
                _parsed(Recommendation, state.get("recommendations"), "items")
            ),
            blocks.gap_block(_parsed(ResearchGap, state.get("gaps"), "gaps")),
        )

    report_agent = LlmAgent(
        name="report_agent",
        model=deep,
        description="Writes the executive production intelligence report.",
        instruction=report_instruction,
        output_schema=ExecutiveReport,
        output_key="report",
        include_contents="none",
        generate_content_config=GENERATION_CONFIG,
        before_agent_callback=_stage_start(emit, Stage.REPORT),
    )

    return SequentialAgent(
        name="cinescout_pipeline",
        description=(
            "Turns a production brief into an evidence-backed production "
            "intelligence report."
        ),
        sub_agents=[
            brief_agent,
            research_agent,
            evidence_agent,
            verification_agent,
            risk_agent,
            scoring_agent,
            recommendation_agent,
            report_agent,
        ],
    )
