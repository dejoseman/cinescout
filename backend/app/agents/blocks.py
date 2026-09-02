"""Deterministic prompt-block builders.

Every block handed to Gemini is rendered here, in code, from typed data. No
stage builds its own context ad hoc, so what each agent sees is predictable and
reviewable.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Sequence

from ..schemas import (
    EvidenceItem,
    ProductionAssessment,
    Recommendation,
    ResearchGap,
    Risk,
    Source,
    Verification,
)


def truncate(text: str, limit: int) -> str:
    """Cut text to a hard character budget, marking where it was cut."""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def source_catalog_block(sources: Sequence[Source]) -> str:
    """The citation whitelist, exactly as the model will see it."""
    if not sources:
        return "(no sources retrieved)"
    lines = []
    for source in sources:
        dated = f" | published {source.publish_date}" if source.publish_date else ""
        lines.append(
            f"{source.id} | {source.domain}{dated} | {truncate(source.title, 120)} | {source.url}"
        )
    return "\n".join(lines)


def search_digest_block(
    grouped: Iterable[tuple[str, str, str, List[tuple[str, List[str]]]]],
    char_budget: int,
) -> str:
    """Render retrieved excerpts grouped by research task.

    ``grouped`` yields ``(task_id, category, question, [(source_id, excerpts)])``.
    The whole digest is held under ``char_budget`` by trimming the longest
    excerpts first, so no single verbose page can crowd out other tasks.
    """
    sections: List[str] = []
    for task_id, category, question, entries in grouped:
        if not entries:
            continue
        body = [f"### TASK {task_id} [{category}] {question}"]
        for source_id, excerpts in entries:
            for excerpt in excerpts:
                body.append(f"[{source_id}] {excerpt}")
        sections.append("\n".join(body))

    digest = "\n\n".join(sections)
    if len(digest) <= char_budget:
        return digest

    # Over budget: shrink per-excerpt allowance until it fits.
    for allowance in (1200, 900, 700, 500, 350, 250):
        sections = []
        for task_id, category, question, entries in grouped:
            if not entries:
                continue
            body = [f"### TASK {task_id} [{category}] {question}"]
            for source_id, excerpts in entries:
                for excerpt in excerpts:
                    body.append(f"[{source_id}] {truncate(excerpt, allowance)}")
            sections.append("\n".join(body))
        digest = "\n\n".join(sections)
        if len(digest) <= char_budget:
            return digest

    return digest[:char_budget]


def evidence_block(evidence: Sequence[EvidenceItem]) -> str:
    if not evidence:
        return "(no evidence extracted)"
    return "\n".join(
        f"{item.id} | task {item.task_id} | [{item.category}] | source {item.source_id} "
        f"| confidence {item.confidence}\n"
        f"    claim: {truncate(item.claim, 400)}\n"
        f"    excerpt: {truncate(item.excerpt, 400)}"
        for item in evidence
    )


def verification_block(verifications: Sequence[Verification]) -> str:
    if not verifications:
        return "(no verification performed)"
    lines = []
    for v in verifications:
        corroborating = ", ".join(v.corroborating_source_ids) or "none"
        contradicting = ", ".join(v.contradicting_source_ids) or "none"
        stale = " | POSSIBLY STALE" if v.staleness_flag else ""
        lines.append(
            f"{v.evidence_id} | {v.status}{stale} | corroborated by: {corroborating} "
            f"| contradicted by: {contradicting}\n    {truncate(v.reasoning, 300)}"
        )
    return "\n".join(lines)


def risk_block(risks: Sequence[Risk]) -> str:
    if not risks:
        return "(no risks identified)"
    lines = []
    for risk in risks:
        confirm = " | REQUIRES HUMAN CONFIRMATION" if risk.requires_human_confirmation else ""
        evidence = ", ".join(risk.evidence_ids) or "none"
        lines.append(
            f"{risk.id} | {risk.severity} | [{risk.category}]{confirm} | {risk.title}\n"
            f"    reasoning: {truncate(risk.reasoning, 350)}\n"
            f"    evidence: {evidence}\n"
            f"    action: {truncate(risk.recommended_action, 250)}"
        )
    return "\n".join(lines)


def gap_block(gaps: Sequence[ResearchGap]) -> str:
    if not gaps:
        return "(no open research gaps)"
    return "\n".join(
        f"{gap.id} | {gap.question}\n"
        f"    why: {truncate(gap.why_it_matters, 250)}\n"
        f"    look to: {truncate(gap.suggested_source, 150)}"
        for gap in gaps
    )


def recommendation_block(recommendations: Sequence[Recommendation]) -> str:
    if not recommendations:
        return "(none)"
    return "\n".join(
        f"{r.id} | {r.priority} | {truncate(r.action, 250)} (owner: {r.owner_hint})"
        for r in recommendations
    )


def assessment_block(assessment: ProductionAssessment) -> str:
    components = "\n".join(
        f"    {c.name}: {c.points}/{c.max_points} - {c.detail}" for c in assessment.components
    )
    return (
        f"Production readiness: {assessment.readiness_score}%\n"
        f"Evidence confidence: {assessment.evidence_confidence}%\n"
        f"Research coverage: {assessment.research_coverage}%\n"
        f"Risks: {assessment.critical_risks} critical, {assessment.high_risks} high, "
        f"{assessment.medium_risks} medium, {assessment.low_risks} low\n"
        f"Conflicting findings: {assessment.conflicting_findings}\n"
        f"Open research gaps: {assessment.research_gaps}\n"
        f"Sources: {assessment.total_sources} | Claims: {assessment.total_evidence}\n"
        f"Score breakdown:\n{components}"
    )


def coerce_list(state_value: Any, key: str) -> List[Mapping[str, Any]]:
    """Pull a list of dicts out of a state value that may be a dict or a list.

    Structured-output stages write a dict such as ``{"items": [...]}``; this
    normalises both that and a bare list without raising on malformed output.
    """
    if isinstance(state_value, Mapping):
        value = state_value.get(key, [])
    else:
        value = state_value
    if isinstance(value, list):
        return [v for v in value if isinstance(v, Mapping)]
    return []
