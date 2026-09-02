"""Typed data model for CineScout.

Two families of models live here:

* **LLM-facing schemas** (``ResearchPlan``, ``EvidenceSet``, ``VerificationSet``,
  ``RiskSet``, ``RecommendationSet``, ``ExecutiveReport``) are used directly as
  Gemini structured-output schemas. They are kept deliberately flat and free of
  unions so they translate cleanly to the response-schema format.
* **Internal / API schemas** (``Source``, ``SearchResult``, ``Project`` ...) are
  richer and are produced by deterministic Python code, never by a model.

The separation matters: anything a model emits is re-validated against a code
built whitelist before it reaches the UI.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class ResearchCategory(str, Enum):
    """Buckets a production research question can fall into."""

    PERMITS = "PERMITS"
    LOCATIONS = "LOCATIONS"
    REGULATION = "REGULATION"
    WEATHER = "WEATHER"
    CREW_TALENT = "CREW_TALENT"
    EQUIPMENT_VENDORS = "EQUIPMENT_VENDORS"
    SAFETY_SECURITY = "SAFETY_SECURITY"
    LOGISTICS_ACCESS = "LOGISTICS_ACCESS"
    COSTS_INCENTIVES = "COSTS_INCENTIVES"
    MARKET_AUDIENCE = "MARKET_AUDIENCE"
    RIGHTS_LICENSING = "RIGHTS_LICENSING"
    OTHER = "OTHER"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class VerificationStatus(str, Enum):
    """How well a claim is supported once sources are cross-compared."""

    VERIFIED = "VERIFIED"
    SUPPORTED = "SUPPORTED"
    CONFLICTING = "CONFLICTING"
    UNCONFIRMED = "UNCONFIRMED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    OK = "OK"
    EMPTY = "EMPTY"
    FAILED = "FAILED"


class Stage(str, Enum):
    """The eight pipeline stages, in execution order."""

    BRIEF = "brief"
    RESEARCH = "research"
    EVIDENCE = "evidence"
    VERIFICATION = "verification"
    RISK = "risk"
    SCORING = "scoring"
    RECOMMENDATION = "recommendation"
    REPORT = "report"


STAGE_LABELS: dict[str, str] = {
    Stage.BRIEF: "Understanding production brief",
    Stage.RESEARCH: "Searching external sources",
    Stage.EVIDENCE: "Analysing evidence",
    Stage.VERIFICATION: "Cross-checking information",
    Stage.RISK: "Assessing risks",
    Stage.SCORING: "Computing readiness",
    Stage.RECOMMENDATION: "Preparing recommendations",
    Stage.REPORT: "Preparing production report",
}


class ProjectStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# User input
# --------------------------------------------------------------------------


class ProductionBrief(BaseModel):
    """A production brief as submitted by the user.

    Every string is length-capped and every list is size-capped: this model is
    the outer trust boundary of the application.
    """

    title: str = Field(min_length=2, max_length=120)
    project_type: str = Field(max_length=60, default="Independent feature film")
    genre: str = Field(max_length=60, default="")
    country: str = Field(min_length=2, max_length=60)
    city: str = Field(max_length=80, default="")
    budget_amount: Optional[float] = Field(default=None, ge=0, le=1_000_000_000)
    budget_currency: str = Field(max_length=8, default="USD")
    shooting_days: Optional[int] = Field(default=None, ge=1, le=500)
    shooting_period: str = Field(max_length=80, default="")
    locations: List[str] = Field(default_factory=list, max_length=20)
    requirements: List[str] = Field(default_factory=list, max_length=20)
    target_audience: str = Field(max_length=200, default="")
    constraints: str = Field(max_length=1000, default="")
    free_text: str = Field(max_length=4000, default="")

    @field_validator("locations", "requirements", mode="after")
    @classmethod
    def _trim_items(cls, values: List[str]) -> List[str]:
        """Drop blanks and cap individual entry length."""
        return [v.strip()[:160] for v in values if v and v.strip()]

    def to_prompt_block(self) -> str:
        """Render the brief as a stable, readable block for model prompts."""
        budget = (
            f"{self.budget_amount:,.0f} {self.budget_currency}"
            if self.budget_amount
            else "not specified"
        )
        days = str(self.shooting_days) if self.shooting_days else "not specified"
        lines = [
            f"Title: {self.title}",
            f"Type: {self.project_type}",
            f"Genre: {self.genre or 'not specified'}",
            f"Country: {self.country}",
            f"City/region: {self.city or 'not specified'}",
            f"Budget: {budget}",
            f"Shooting days: {days}",
            f"Shooting period: {self.shooting_period or 'not specified'}",
            f"Required locations: {', '.join(self.locations) or 'not specified'}",
            f"Production requirements: {', '.join(self.requirements) or 'not specified'}",
            f"Target audience: {self.target_audience or 'not specified'}",
            f"Additional constraints: {self.constraints or 'none stated'}",
        ]
        if self.free_text:
            lines.append(f"Producer's own description: {self.free_text}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Stage 1 - research planning (LLM-facing)
# --------------------------------------------------------------------------


class ResearchTask(BaseModel):
    """One externally-answerable research question plus its search queries."""

    id: str = Field(description="Short stable id such as t1, t2, t3.")
    category: ResearchCategory
    question: str = Field(description="The specific question to answer.")
    objective: str = Field(
        description="One sentence describing what a good answer looks like. "
        "Passed to Parallel as the search objective."
    )
    search_queries: List[str] = Field(
        description="Two or three concise keyword queries, 3-6 words each."
    )
    priority: Severity
    rationale: str = Field(description="Why this matters for this production.")


class ResearchPlan(BaseModel):
    """Stage-1 output: the agent's own plan for what to investigate."""

    summary: str = Field(description="Two sentences on the production and research posture.")
    extracted_requirements: List[str] = Field(
        description="Concrete production requirements read out of the brief."
    )
    missing_information: List[str] = Field(
        description="Information the producer did not supply that materially affects feasibility."
    )
    tasks: List[ResearchTask]


# --------------------------------------------------------------------------
# Stage 2 - retrieval (deterministic, code-produced)
# --------------------------------------------------------------------------


class Source(BaseModel):
    """A deduplicated web source returned by Parallel.

    The set of ``Source.id`` values is the *only* citation namespace the model
    is permitted to use.
    """

    id: str
    url: str
    domain: str
    title: str = ""
    publish_date: Optional[str] = None
    first_seen_task: str = ""


class SearchResult(BaseModel):
    """The outcome of one Parallel search call, success or failure."""

    task_id: str
    category: ResearchCategory
    question: str = ""
    status: TaskStatus = TaskStatus.PENDING
    queries: List[str] = Field(default_factory=list)
    source_ids: List[str] = Field(default_factory=list)
    excerpt_count: int = 0
    latency_ms: int = 0
    search_id: Optional[str] = None
    error: Optional[str] = None


# --------------------------------------------------------------------------
# Stage 3 - evidence (LLM-facing, then code-validated)
# --------------------------------------------------------------------------


class EvidenceItem(BaseModel):
    """A single atomic claim bound to exactly one retrieved source."""

    id: str = Field(description="Short stable id such as e1, e2.")
    task_id: str = Field(description="The research task this answers.")
    category: ResearchCategory
    claim: str = Field(description="One factual claim, stated plainly.")
    source_id: str = Field(
        description="MUST be a source id from the supplied catalogue, e.g. src_03."
    )
    excerpt: str = Field(
        description="Verbatim supporting text copied from that source's excerpts."
    )
    confidence: Confidence
    retrieved_at: Optional[str] = None


class EvidenceSet(BaseModel):
    items: List[EvidenceItem]


# --------------------------------------------------------------------------
# Stage 4 - verification
# --------------------------------------------------------------------------


class Verification(BaseModel):
    evidence_id: str
    status: VerificationStatus
    corroborating_source_ids: List[str] = Field(default_factory=list)
    contradicting_source_ids: List[str] = Field(default_factory=list)
    reasoning: str = Field(description="Why this status was assigned.")
    staleness_flag: bool = Field(
        default=False,
        description="True when the claim rests on material that may be out of date.",
    )


class VerificationSet(BaseModel):
    items: List[Verification]


# --------------------------------------------------------------------------
# Stage 5 - risks and gaps
# --------------------------------------------------------------------------


class Risk(BaseModel):
    id: str
    title: str
    severity: Severity
    category: ResearchCategory
    reasoning: str
    evidence_ids: List[str] = Field(default_factory=list)
    recommended_action: str
    requires_human_confirmation: bool = Field(
        default=False,
        description="True for legal, regulatory, permit or safety matters that a "
        "professional or authority must confirm.",
    )


class ResearchGap(BaseModel):
    id: str
    question: str
    why_it_matters: str
    suggested_source: str = Field(description="Where a human should go to close this gap.")


class RiskSet(BaseModel):
    risks: List[Risk]
    gaps: List[ResearchGap]


# --------------------------------------------------------------------------
# Stage 7 - recommendations
# --------------------------------------------------------------------------


class Recommendation(BaseModel):
    id: str
    priority: Severity
    action: str = Field(description="A concrete action a producer can take this week.")
    rationale: str
    related_risk_ids: List[str] = Field(default_factory=list)
    owner_hint: str = Field(description="Who typically does this, e.g. Line producer.")


class RecommendationSet(BaseModel):
    items: List[Recommendation]


# --------------------------------------------------------------------------
# Stage 8 - executive report
# --------------------------------------------------------------------------


class ExecutiveReport(BaseModel):
    executive_summary: str = Field(
        description="Three to five sentences a producer could read aloud in a greenlight meeting."
    )
    opportunities: List[str] = Field(description="Concrete advantages found in the research.")
    critical_risks_summary: str
    open_questions: List[str] = Field(
        description="Questions that genuinely require human confirmation."
    )
    next_steps: List[str] = Field(description="Ordered, practical next steps.")


# --------------------------------------------------------------------------
# Stage 6 - deterministic assessment (code-produced)
# --------------------------------------------------------------------------


class ScoreComponent(BaseModel):
    """One line of the readiness arithmetic, shown to the user."""

    name: str
    detail: str
    points: float
    max_points: float


class ProductionAssessment(BaseModel):
    readiness_score: int
    evidence_confidence: int
    research_coverage: int
    critical_risks: int
    high_risks: int
    medium_risks: int
    low_risks: int
    research_gaps: int
    verified_sources: int
    total_sources: int
    total_evidence: int
    conflicting_findings: int
    components: List[ScoreComponent] = Field(default_factory=list)
    methodology_note: str = ""


# --------------------------------------------------------------------------
# Observability + aggregate
# --------------------------------------------------------------------------


class AgentRun(BaseModel):
    """One stage execution record."""

    stage: Stage
    label: str = ""
    status: str = "RUNNING"
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    detail: str = ""


class Project(BaseModel):
    """Aggregate root. This is what the API returns and the UI renders."""

    id: str
    brief: ProductionBrief
    status: ProjectStatus = ProjectStatus.QUEUED
    created_at: datetime = Field(default_factory=_utcnow)
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    plan: Optional[ResearchPlan] = None
    search_results: List[SearchResult] = Field(default_factory=list)
    sources: List[Source] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    verifications: List[Verification] = Field(default_factory=list)
    risks: List[Risk] = Field(default_factory=list)
    gaps: List[ResearchGap] = Field(default_factory=list)
    recommendations: List[Recommendation] = Field(default_factory=list)
    assessment: Optional[ProductionAssessment] = None
    report: Optional[ExecutiveReport] = None
    runs: List[AgentRun] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ProjectSummary(BaseModel):
    """Compact dashboard row."""

    id: str
    title: str
    city: str
    country: str
    status: ProjectStatus
    created_at: datetime
    readiness_score: Optional[int] = None
    evidence_confidence: Optional[int] = None
    critical_risks: int = 0
    open_actions: int = 0
    total_sources: int = 0
