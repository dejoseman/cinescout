"""Deterministic production-readiness scoring.

No model participates in this module. The same evidence always yields the same
score, and every component of the arithmetic is returned to the UI so a producer
can see exactly why the number is what it is.

Readiness is built from five components totalling 100 points:

===========================  ====  ====================================================
Component                     Max  Meaning
===========================  ====  ====================================================
Research coverage              25  Share of planned research tasks that returned usable
                                   results. Failed or empty searches cost points.
Evidence confidence            25  Verification-weighted quality of the claims gathered.
Risk exposure                  30  Starts full; each open risk deducts by severity.
Source depth                   10  Breadth of independent domains behind the findings.
Open gaps                      10  Starts full; each unresolved question deducts.
===========================  ====  ====================================================

A low score is a *finding*, not a failure: it means the production is not yet
evidenced well enough to greenlight.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

from .integrations.parallel_client import domain_of
from .schemas import (
    Confidence,
    EvidenceItem,
    ProductionAssessment,
    ResearchGap,
    Risk,
    ScoreComponent,
    SearchResult,
    Severity,
    Source,
    TaskStatus,
    Verification,
    VerificationStatus,
)

#: How much each verification status contributes to evidence confidence.
STATUS_WEIGHT: Dict[VerificationStatus, float] = {
    VerificationStatus.VERIFIED: 1.00,
    VerificationStatus.SUPPORTED: 0.75,
    VerificationStatus.UNCONFIRMED: 0.35,
    VerificationStatus.CONFLICTING: 0.25,
    VerificationStatus.INSUFFICIENT_EVIDENCE: 0.10,
}

#: A claim the verification stage never reached is treated as unconfirmed.
DEFAULT_STATUS_WEIGHT = STATUS_WEIGHT[VerificationStatus.UNCONFIRMED]

#: Readiness points deducted per open risk.
RISK_PENALTY: Dict[Severity, float] = {
    Severity.CRITICAL: 10.0,
    Severity.HIGH: 6.0,
    Severity.MEDIUM: 3.0,
    Severity.LOW: 1.0,
}

#: Confidence multiplier applied to each claim's status weight.
CONFIDENCE_MULTIPLIER: Dict[Confidence, float] = {
    Confidence.HIGH: 1.0,
    Confidence.MEDIUM: 0.85,
    Confidence.LOW: 0.65,
}

GAP_PENALTY = 2.5
TARGET_DOMAINS = 10

MAX_COVERAGE = 25.0
MAX_CONFIDENCE = 25.0
MAX_RISK = 30.0
MAX_DEPTH = 10.0
MAX_GAPS = 10.0

METHODOLOGY = (
    "Readiness = research coverage (25) + evidence confidence (25) + risk exposure (30) "
    "+ source depth (10) + open gaps (10). Risk exposure starts at 30 and deducts 10 per "
    "critical, 6 per high, 3 per medium and 1 per low risk. Open gaps start at 10 and "
    "deduct 2.5 each. Evidence confidence weights every claim by its verification status "
    "(verified 1.0, supported 0.75, unconfirmed 0.35, conflicting 0.25, insufficient 0.1) "
    "and by its stated confidence. If no evidence was gathered at all, the risk "
    "and open-question components score zero rather than full marks: absence of "
    "evidence is not evidence of safety. Computed in code, not by a model."
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compute_evidence_confidence(
    evidence: Sequence[EvidenceItem], verifications: Sequence[Verification]
) -> float:
    """Return verification-weighted confidence across all claims, 0.0-1.0."""
    if not evidence:
        return 0.0

    by_evidence = {v.evidence_id: v for v in verifications}
    total = 0.0
    for item in evidence:
        verification = by_evidence.get(item.id)
        weight = (
            STATUS_WEIGHT.get(verification.status, DEFAULT_STATUS_WEIGHT)
            if verification
            else DEFAULT_STATUS_WEIGHT
        )
        # A claim resting on possibly-stale material is discounted.
        if verification and verification.staleness_flag:
            weight *= 0.8
        total += weight * CONFIDENCE_MULTIPLIER.get(item.confidence, 0.85)

    return _clamp(total / len(evidence), 0.0, 1.0)


def compute_assessment(
    *,
    search_results: Sequence[SearchResult],
    sources: Sequence[Source],
    evidence: Sequence[EvidenceItem],
    verifications: Sequence[Verification],
    risks: Sequence[Risk],
    gaps: Sequence[ResearchGap],
) -> ProductionAssessment:
    """Compute the full production assessment. Pure and deterministic."""

    components: List[ScoreComponent] = []

    # 1. Research coverage ----------------------------------------------------
    total_tasks = len(search_results)
    usable_tasks = sum(1 for r in search_results if r.status == TaskStatus.OK)
    coverage_ratio = (usable_tasks / total_tasks) if total_tasks else 0.0
    coverage_points = coverage_ratio * MAX_COVERAGE
    components.append(
        ScoreComponent(
            name="Research coverage",
            detail=f"{usable_tasks} of {total_tasks} research tasks returned usable results.",
            points=round(coverage_points, 1),
            max_points=MAX_COVERAGE,
        )
    )

    # 2. Evidence confidence --------------------------------------------------
    confidence_ratio = compute_evidence_confidence(evidence, verifications)
    confidence_points = confidence_ratio * MAX_CONFIDENCE
    verified_count = sum(
        1 for v in verifications if v.status == VerificationStatus.VERIFIED
    )
    components.append(
        ScoreComponent(
            name="Evidence confidence",
            detail=(
                f"{len(evidence)} claims gathered, {verified_count} independently verified."
                if evidence
                else "No claims were extracted."
            ),
            points=round(confidence_points, 1),
            max_points=MAX_CONFIDENCE,
        )
    )

    # 3. Risk exposure --------------------------------------------------------
    # Absence of evidence is not evidence of safety. If nothing was gathered, a
    # clean risk register means nobody looked, so this component scores zero
    # rather than rewarding a failed run with full marks.
    counts = {severity: 0 for severity in Severity}
    for risk in risks:
        counts[risk.severity] = counts.get(risk.severity, 0) + 1

    researched = bool(evidence)
    deduction = sum(RISK_PENALTY[severity] * count for severity, count in counts.items())
    risk_points = _clamp(MAX_RISK - deduction, 0.0, MAX_RISK) if researched else 0.0
    components.append(
        ScoreComponent(
            name="Risk exposure",
            detail=(
                (
                    f"{counts[Severity.CRITICAL]} critical, {counts[Severity.HIGH]} high, "
                    f"{counts[Severity.MEDIUM]} medium, {counts[Severity.LOW]} low "
                    f"(-{round(deduction, 1)} points)."
                )
                if researched
                else "No evidence was gathered, so risk exposure cannot be assessed."
            ),
            points=round(risk_points, 1),
            max_points=MAX_RISK,
        )
    )

    # 4. Source depth ---------------------------------------------------------
    domains = {domain_of(s.url) for s in sources if s.url}
    domains.discard("")
    depth_points = _clamp(len(domains) / TARGET_DOMAINS, 0.0, 1.0) * MAX_DEPTH
    components.append(
        ScoreComponent(
            name="Source depth",
            detail=(
                f"{len(sources)} sources across {len(domains)} independent domains "
                f"(target {TARGET_DOMAINS})."
            ),
            points=round(depth_points, 1),
            max_points=MAX_DEPTH,
        )
    )

    # 5. Open gaps ------------------------------------------------------------
    # Same principle: with nothing researched, "no open questions" is meaningless.
    gap_points = (
        _clamp(MAX_GAPS - GAP_PENALTY * len(gaps), 0.0, MAX_GAPS) if researched else 0.0
    )
    if not researched:
        gap_detail = "No evidence was gathered, so open questions cannot be assessed."
    elif gaps:
        gap_detail = (
            f"{len(gaps)} unresolved research gaps "
            f"(-{round(GAP_PENALTY * len(gaps), 1)} points)."
        )
    else:
        gap_detail = "No unresolved research gaps."
    components.append(
        ScoreComponent(
            name="Open questions",
            detail=gap_detail,
            points=round(gap_points, 1),
            max_points=MAX_GAPS,
        )
    )

    readiness = sum(component.points for component in components)
    conflicting = sum(
        1 for v in verifications if v.status == VerificationStatus.CONFLICTING
    )

    return ProductionAssessment(
        readiness_score=int(round(_clamp(readiness, 0.0, 100.0))),
        evidence_confidence=int(round(confidence_ratio * 100)),
        research_coverage=int(round(coverage_ratio * 100)),
        critical_risks=counts[Severity.CRITICAL],
        high_risks=counts[Severity.HIGH],
        medium_risks=counts[Severity.MEDIUM],
        low_risks=counts[Severity.LOW],
        research_gaps=len(gaps),
        verified_sources=verified_count,
        total_sources=len(sources),
        total_evidence=len(evidence),
        conflicting_findings=conflicting,
        components=components,
        methodology_note=METHODOLOGY,
    )
