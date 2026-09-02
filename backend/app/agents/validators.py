"""Post-stage validators.

These run in code immediately after each Gemini stage and are the reason a
citation in CineScout can be trusted. A claim may only cite a source id that the
Parallel client actually created; anything else is discarded before it can reach
the report, the UI, or the score.

The validators are intentionally forgiving about *shape* (models drift) and
strict about *provenance* (models hallucinate).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Set

from google.adk.agents.callback_context import CallbackContext

from ..schemas import (
    Confidence,
    EvidenceItem,
    Recommendation,
    ResearchCategory,
    ResearchGap,
    Risk,
    Severity,
    Verification,
    VerificationStatus,
)
from .blocks import coerce_list

logger = logging.getLogger(__name__)

#: Most serious first. Used to order risks and recommendations before they are
#: numbered, so id order and display order always agree.
SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}


def _enum(value: Any, enum_cls, default):
    """Coerce a value to an enum member, falling back to ``default``.

    Handles both raw strings and enum instances. The latter matters: ADK may
    hand back already-validated members, and ``str()`` on a ``str``-Enum yields
    ``"Class.MEMBER"`` rather than the value, so unwrap ``.value`` first.
    """
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(getattr(value, "value", value)).strip().upper())
    except (ValueError, AttributeError):
        return default


def _text(value: Any, limit: int = 2000) -> str:
    return str(value or "").strip()[:limit]


def _normalise_claim(claim: str) -> str:
    """Key used to collapse claims that say the same thing twice."""
    return re.sub(r"[^a-z0-9]+", " ", claim.lower()).strip()


def make_evidence_validator(emit: Callable[..., None]) -> Callable:
    """Drop claims that cite unknown sources, carry no excerpt, or repeat."""

    def validate(callback_context: CallbackContext) -> None:
        state = callback_context.state
        known: Set[str] = {
            str(s.get("id"))
            for s in (state.get("sources") or [])
            if isinstance(s, Mapping) and s.get("id")
        }
        items = coerce_list(state.get("evidence"), "items")

        validated: List[Dict[str, Any]] = []
        seen: Set[tuple[str, str]] = set()
        dropped_source = 0
        dropped_empty = 0
        dropped_duplicate = 0
        now = datetime.now(timezone.utc).isoformat()

        for raw in items:
            source_id = _text(raw.get("source_id"), 40)
            claim = _text(raw.get("claim"), 600)
            excerpt = _text(raw.get("excerpt"), 1200)

            if source_id not in known:
                dropped_source += 1
                continue
            if not claim or not excerpt:
                dropped_empty += 1
                continue

            key = (source_id, _normalise_claim(claim))
            if key in seen:
                dropped_duplicate += 1
                continue
            seen.add(key)

            item = EvidenceItem(
                id=f"e{len(validated) + 1}",
                task_id=_text(raw.get("task_id"), 40) or "unknown",
                category=_enum(raw.get("category"), ResearchCategory, ResearchCategory.OTHER),
                claim=claim,
                source_id=source_id,
                excerpt=excerpt,
                confidence=_enum(raw.get("confidence"), Confidence, Confidence.MEDIUM),
                retrieved_at=now,
            )
            validated.append(item.model_dump(mode="json"))
            emit(
                "evidence_found",
                evidence_id=item.id,
                claim=item.claim[:220],
                source_id=item.source_id,
                category=item.category.value,
                confidence=item.confidence.value,
            )

        state["evidence"] = validated
        dropped = dropped_source + dropped_empty + dropped_duplicate
        if dropped:
            logger.info(
                "Evidence validation dropped %d claims "
                "(unknown source: %d, empty: %d, duplicate: %d).",
                dropped, dropped_source, dropped_empty, dropped_duplicate,
            )

        emit(
            "stage_completed",
            stage="evidence",
            metrics={
                "claims": len(validated),
                "dropped": dropped,
                "dropped_unknown_source": dropped_source,
            },
        )

    return validate


def make_verification_validator(emit: Callable[..., None]) -> Callable:
    """Keep verifications aligned one-to-one with surviving evidence."""

    def validate(callback_context: CallbackContext) -> None:
        state = callback_context.state
        evidence = coerce_list(state.get("evidence"), "items")
        evidence_ids = [_text(e.get("id"), 40) for e in evidence]
        known_sources: Set[str] = {
            str(s.get("id"))
            for s in (state.get("sources") or [])
            if isinstance(s, Mapping) and s.get("id")
        }

        supplied = {
            _text(v.get("evidence_id"), 40): v
            for v in coerce_list(state.get("verifications"), "items")
        }

        validated: List[Dict[str, Any]] = []
        for evidence_id in evidence_ids:
            raw = supplied.get(evidence_id)
            if raw is None:
                # The model skipped this claim. Unconfirmed is the honest default.
                verification = Verification(
                    evidence_id=evidence_id,
                    status=VerificationStatus.UNCONFIRMED,
                    reasoning="No verification was returned for this claim.",
                )
            else:
                verification = Verification(
                    evidence_id=evidence_id,
                    status=_enum(
                        raw.get("status"), VerificationStatus, VerificationStatus.UNCONFIRMED
                    ),
                    corroborating_source_ids=[
                        s for s in (raw.get("corroborating_source_ids") or [])
                        if str(s) in known_sources
                    ][:12],
                    contradicting_source_ids=[
                        s for s in (raw.get("contradicting_source_ids") or [])
                        if str(s) in known_sources
                    ][:12],
                    reasoning=_text(raw.get("reasoning"), 600),
                    staleness_flag=bool(raw.get("staleness_flag")),
                )
                # A VERIFIED status requires corroboration to exist. Downgrade
                # an unsupported claim of verification rather than trusting it.
                if (
                    verification.status == VerificationStatus.VERIFIED
                    and not verification.corroborating_source_ids
                ):
                    verification.status = VerificationStatus.SUPPORTED
                    verification.reasoning = (
                        verification.reasoning
                        + " (Downgraded: no independent corroborating source was cited.)"
                    ).strip()

            validated.append(verification.model_dump(mode="json"))

        state["verifications"] = validated
        counts: Dict[str, int] = {}
        for v in validated:
            counts[v["status"]] = counts.get(v["status"], 0) + 1

        emit("stage_completed", stage="verification", metrics={"statuses": counts})

    return validate


def make_risk_validator(emit: Callable[..., None]) -> Callable:
    """Re-id risks and gaps, and prune references to claims that do not exist."""

    def validate(callback_context: CallbackContext) -> None:
        state = callback_context.state
        evidence_ids: Set[str] = {
            _text(e.get("id"), 40) for e in coerce_list(state.get("evidence"), "items")
        }

        parsed_risks: List[Risk] = []
        for raw in coerce_list(state.get("risks"), "risks"):
            title = _text(raw.get("title"), 200)
            if not title:
                continue
            risk = Risk(
                id="pending",
                title=title,
                severity=_enum(raw.get("severity"), Severity, Severity.MEDIUM),
                category=_enum(raw.get("category"), ResearchCategory, ResearchCategory.OTHER),
                reasoning=_text(raw.get("reasoning"), 1200),
                evidence_ids=[
                    e for e in (raw.get("evidence_ids") or []) if str(e) in evidence_ids
                ][:12],
                recommended_action=_text(raw.get("recommended_action"), 600),
                requires_human_confirmation=bool(raw.get("requires_human_confirmation")),
            )
            parsed_risks.append(risk)

        # Order by severity first, then number them, so r1 is always the most
        # serious risk and the ids match the order the producer reads them in.
        parsed_risks.sort(key=lambda r: SEVERITY_ORDER.get(r.severity, 9))
        risks: List[Dict[str, Any]] = []
        for index, risk in enumerate(parsed_risks, start=1):
            risk.id = f"r{index}"
            risks.append(risk.model_dump(mode="json"))

        gaps: List[Dict[str, Any]] = []
        for raw in coerce_list(state.get("risks"), "gaps"):
            question = _text(raw.get("question"), 300)
            if not question:
                continue
            gap = ResearchGap(
                id=f"g{len(gaps) + 1}",
                question=question,
                why_it_matters=_text(raw.get("why_it_matters"), 600),
                suggested_source=_text(raw.get("suggested_source"), 300),
            )
            gaps.append(gap.model_dump(mode="json"))

        state["risks"] = risks
        state["gaps"] = gaps

        emit(
            "stage_completed",
            stage="risk",
            metrics={
                "risks": len(risks),
                "critical": sum(1 for r in risks if r["severity"] == Severity.CRITICAL),
                "gaps": len(gaps),
            },
        )

    return validate


def make_recommendation_validator(emit: Callable[..., None]) -> Callable:
    """Re-id recommendations and prune references to risks that do not exist."""

    def validate(callback_context: CallbackContext) -> None:
        state = callback_context.state
        risk_ids: Set[str] = {
            str(r.get("id")) for r in coerce_list(state.get("risks"), "risks")
        }

        parsed: List[Recommendation] = []
        for raw in coerce_list(state.get("recommendations"), "items"):
            action = _text(raw.get("action"), 600)
            if not action:
                continue
            recommendation = Recommendation(
                id="pending",
                priority=_enum(raw.get("priority"), Severity, Severity.MEDIUM),
                action=action,
                rationale=_text(raw.get("rationale"), 800),
                related_risk_ids=[
                    r for r in (raw.get("related_risk_ids") or []) if str(r) in risk_ids
                ][:12],
                owner_hint=_text(raw.get("owner_hint"), 80) or "Producer",
            )
            parsed.append(recommendation)

        # Sort before numbering: a1 must be the most urgent action.
        parsed.sort(key=lambda r: SEVERITY_ORDER.get(r.priority, 9))
        recommendations: List[Dict[str, Any]] = []
        for index, recommendation in enumerate(parsed, start=1):
            recommendation.id = f"a{index}"
            recommendations.append(recommendation.model_dump(mode="json"))

        state["recommendations"] = recommendations
        emit(
            "stage_completed",
            stage="recommendation",
            metrics={"recommendations": len(recommendations)},
        )

    return validate
