"""Tests for the deterministic scorer.

The scorer is the number a producer makes a decision on, so its behaviour is
pinned: same input, same output; failures cost coverage; risks cost points; and
the published components always reconcile with the headline score.
"""

from __future__ import annotations

from app.scoring import compute_assessment
from app.schemas import (
    Confidence,
    EvidenceItem,
    ResearchCategory,
    ResearchGap,
    Risk,
    SearchResult,
    Severity,
    Source,
    TaskStatus,
    Verification,
    VerificationStatus,
)


def _source(index: int, domain: str | None = None) -> Source:
    host = domain or f"example{index}.org"
    return Source(id=f"src_{index:02d}", url=f"https://{host}/page", domain=host)


def _evidence(index: int, confidence: Confidence = Confidence.HIGH) -> EvidenceItem:
    return EvidenceItem(
        id=f"e{index}",
        task_id="t1",
        category=ResearchCategory.PERMITS,
        claim=f"Claim {index}",
        source_id=f"src_{index:02d}",
        excerpt="excerpt",
        confidence=confidence,
    )


def _verification(index: int, status: VerificationStatus, stale: bool = False) -> Verification:
    return Verification(
        evidence_id=f"e{index}", status=status, reasoning="because", staleness_flag=stale
    )


def _task(task_id: str, status: TaskStatus) -> SearchResult:
    return SearchResult(task_id=task_id, category=ResearchCategory.PERMITS, status=status)


def _risk(index: int, severity: Severity) -> Risk:
    return Risk(
        id=f"r{index}",
        title=f"Risk {index}",
        severity=severity,
        category=ResearchCategory.PERMITS,
        reasoning="because",
        recommended_action="do the thing",
    )


def test_empty_input_scores_zero_without_raising():
    assessment = compute_assessment(
        search_results=[], sources=[], evidence=[], verifications=[], risks=[], gaps=[]
    )
    assert assessment.readiness_score == 0
    assert assessment.evidence_confidence == 0
    assert assessment.research_coverage == 0


def test_components_always_total_one_hundred_available_points():
    assessment = compute_assessment(
        search_results=[_task("t1", TaskStatus.OK)],
        sources=[_source(1)],
        evidence=[_evidence(1)],
        verifications=[_verification(1, VerificationStatus.VERIFIED)],
        risks=[],
        gaps=[],
    )
    assert sum(c.max_points for c in assessment.components) == 100
    assert assessment.readiness_score == int(
        round(sum(c.points for c in assessment.components))
    )


def test_scoring_is_deterministic():
    args = dict(
        search_results=[_task("t1", TaskStatus.OK), _task("t2", TaskStatus.FAILED)],
        sources=[_source(1), _source(2)],
        evidence=[_evidence(1), _evidence(2)],
        verifications=[
            _verification(1, VerificationStatus.VERIFIED),
            _verification(2, VerificationStatus.CONFLICTING),
        ],
        risks=[_risk(1, Severity.HIGH)],
        gaps=[ResearchGap(id="g1", question="q", why_it_matters="w", suggested_source="s")],
    )
    first = compute_assessment(**args)
    second = compute_assessment(**args)
    assert first.model_dump() == second.model_dump()


def test_failed_searches_reduce_coverage():
    all_ok = compute_assessment(
        search_results=[_task("t1", TaskStatus.OK), _task("t2", TaskStatus.OK)],
        sources=[], evidence=[], verifications=[], risks=[], gaps=[],
    )
    half = compute_assessment(
        search_results=[_task("t1", TaskStatus.OK), _task("t2", TaskStatus.FAILED)],
        sources=[], evidence=[], verifications=[], risks=[], gaps=[],
    )
    assert all_ok.research_coverage == 100
    assert half.research_coverage == 50
    assert half.readiness_score < all_ok.readiness_score


def test_empty_results_do_not_count_as_coverage():
    assessment = compute_assessment(
        search_results=[_task("t1", TaskStatus.EMPTY)],
        sources=[], evidence=[], verifications=[], risks=[], gaps=[],
    )
    assert assessment.research_coverage == 0


def test_critical_risks_cost_more_than_low_risks():
    def score_with(severity: Severity) -> int:
        return compute_assessment(
            search_results=[_task("t1", TaskStatus.OK)],
            sources=[_source(1)],
            evidence=[_evidence(1)],
            verifications=[_verification(1, VerificationStatus.VERIFIED)],
            risks=[_risk(1, severity)],
            gaps=[],
        ).readiness_score

    assert score_with(Severity.CRITICAL) < score_with(Severity.HIGH)
    assert score_with(Severity.HIGH) < score_with(Severity.MEDIUM)
    assert score_with(Severity.MEDIUM) < score_with(Severity.LOW)


def test_risk_component_never_goes_negative():
    assessment = compute_assessment(
        search_results=[_task("t1", TaskStatus.OK)],
        sources=[_source(1)],
        evidence=[],
        verifications=[],
        risks=[_risk(i, Severity.CRITICAL) for i in range(10)],
        gaps=[],
    )
    risk_component = next(c for c in assessment.components if c.name == "Risk exposure")
    assert risk_component.points == 0
    assert assessment.readiness_score >= 0


def test_verified_evidence_outscores_conflicting_evidence():
    def confidence_with(status: VerificationStatus) -> int:
        return compute_assessment(
            search_results=[_task("t1", TaskStatus.OK)],
            sources=[_source(1)],
            evidence=[_evidence(1)],
            verifications=[_verification(1, status)],
            risks=[], gaps=[],
        ).evidence_confidence

    assert confidence_with(VerificationStatus.VERIFIED) == 100
    assert (
        confidence_with(VerificationStatus.VERIFIED)
        > confidence_with(VerificationStatus.SUPPORTED)
        > confidence_with(VerificationStatus.UNCONFIRMED)
        > confidence_with(VerificationStatus.CONFLICTING)
        > confidence_with(VerificationStatus.INSUFFICIENT_EVIDENCE)
    )


def test_unverified_claims_default_to_unconfirmed_weighting():
    """A claim the verifier never reached must not be treated as verified."""
    assessment = compute_assessment(
        search_results=[_task("t1", TaskStatus.OK)],
        sources=[_source(1)],
        evidence=[_evidence(1)],
        verifications=[],
        risks=[], gaps=[],
    )
    assert assessment.evidence_confidence == 35


def test_staleness_discounts_confidence():
    fresh = compute_assessment(
        search_results=[], sources=[], evidence=[_evidence(1)],
        verifications=[_verification(1, VerificationStatus.VERIFIED)],
        risks=[], gaps=[],
    ).evidence_confidence
    stale = compute_assessment(
        search_results=[], sources=[], evidence=[_evidence(1)],
        verifications=[_verification(1, VerificationStatus.VERIFIED, stale=True)],
        risks=[], gaps=[],
    ).evidence_confidence
    assert stale < fresh


def test_source_depth_counts_distinct_domains_not_urls():
    """Ten pages on one site are not ten independent sources."""
    same_domain = compute_assessment(
        search_results=[], sources=[_source(i, "same.org") for i in range(1, 11)],
        evidence=[], verifications=[], risks=[], gaps=[],
    )
    many_domains = compute_assessment(
        search_results=[], sources=[_source(i) for i in range(1, 11)],
        evidence=[], verifications=[], risks=[], gaps=[],
    )
    depth = lambda a: next(c for c in a.components if c.name == "Source depth").points
    assert depth(same_domain) == 1.0
    assert depth(many_domains) == 10.0


def test_gaps_reduce_the_score_and_are_counted():
    gaps = [
        ResearchGap(id=f"g{i}", question="q", why_it_matters="w", suggested_source="s")
        for i in range(3)
    ]
    assessment = compute_assessment(
        search_results=[_task("t1", TaskStatus.OK)],
        sources=[_source(1)],
        evidence=[_evidence(1)],
        verifications=[_verification(1, VerificationStatus.VERIFIED)],
        risks=[],
        gaps=gaps,
    )
    gap_component = next(c for c in assessment.components if c.name == "Open questions")
    assert assessment.research_gaps == 3
    assert gap_component.points == 2.5  # 10 - (3 x 2.5)


def test_a_run_with_no_evidence_cannot_score_well():
    """Absence of evidence must not be rewarded as absence of risk."""
    assessment = compute_assessment(
        search_results=[_task("t1", TaskStatus.FAILED)],
        sources=[], evidence=[], verifications=[], risks=[], gaps=[],
    )
    risk_component = next(c for c in assessment.components if c.name == "Risk exposure")
    gap_component = next(c for c in assessment.components if c.name == "Open questions")

    assert risk_component.points == 0
    assert gap_component.points == 0
    assert assessment.readiness_score == 0


def test_conflicting_findings_are_surfaced_in_the_counts():
    assessment = compute_assessment(
        search_results=[], sources=[], evidence=[_evidence(1), _evidence(2)],
        verifications=[
            _verification(1, VerificationStatus.CONFLICTING),
            _verification(2, VerificationStatus.VERIFIED),
        ],
        risks=[], gaps=[],
    )
    assert assessment.conflicting_findings == 1
    assert assessment.verified_sources == 1
