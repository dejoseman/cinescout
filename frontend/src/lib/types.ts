/**
 * TypeScript mirror of the backend Pydantic models in `backend/app/schemas.py`.
 * Keep the two files in step: the API is the contract between them.
 */

export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
export type Confidence = "HIGH" | "MEDIUM" | "LOW";
export type TaskStatus = "PENDING" | "RUNNING" | "OK" | "EMPTY" | "FAILED";
export type ProjectStatus = "QUEUED" | "RUNNING" | "COMPLETE" | "FAILED";

export type VerificationStatus =
  | "VERIFIED"
  | "SUPPORTED"
  | "CONFLICTING"
  | "UNCONFIRMED"
  | "INSUFFICIENT_EVIDENCE";

export type StageName =
  | "brief"
  | "research"
  | "evidence"
  | "verification"
  | "risk"
  | "scoring"
  | "recommendation"
  | "report";

export interface ProductionBrief {
  title: string;
  project_type: string;
  genre: string;
  country: string;
  city: string;
  budget_amount: number | null;
  budget_currency: string;
  shooting_days: number | null;
  shooting_period: string;
  locations: string[];
  requirements: string[];
  target_audience: string;
  constraints: string;
  free_text: string;
}

export interface ResearchTask {
  id: string;
  category: string;
  question: string;
  objective: string;
  search_queries: string[];
  priority: Severity;
  rationale: string;
}

export interface ResearchPlan {
  summary: string;
  extracted_requirements: string[];
  missing_information: string[];
  tasks: ResearchTask[];
}

export interface Source {
  id: string;
  url: string;
  domain: string;
  title: string;
  publish_date: string | null;
  first_seen_task: string;
}

export interface SearchResult {
  task_id: string;
  category: string;
  question: string;
  status: TaskStatus;
  queries: string[];
  source_ids: string[];
  excerpt_count: number;
  latency_ms: number;
  search_id: string | null;
  error: string | null;
}

export interface EvidenceItem {
  id: string;
  task_id: string;
  category: string;
  claim: string;
  source_id: string;
  excerpt: string;
  confidence: Confidence;
  retrieved_at: string | null;
}

export interface Verification {
  evidence_id: string;
  status: VerificationStatus;
  corroborating_source_ids: string[];
  contradicting_source_ids: string[];
  reasoning: string;
  staleness_flag: boolean;
}

export interface Risk {
  id: string;
  title: string;
  severity: Severity;
  category: string;
  reasoning: string;
  evidence_ids: string[];
  recommended_action: string;
  requires_human_confirmation: boolean;
}

export interface ResearchGap {
  id: string;
  question: string;
  why_it_matters: string;
  suggested_source: string;
}

export interface Recommendation {
  id: string;
  priority: Severity;
  action: string;
  rationale: string;
  related_risk_ids: string[];
  owner_hint: string;
}

export interface ScoreComponent {
  name: string;
  detail: string;
  points: number;
  max_points: number;
}

export interface ProductionAssessment {
  readiness_score: number;
  evidence_confidence: number;
  research_coverage: number;
  critical_risks: number;
  high_risks: number;
  medium_risks: number;
  low_risks: number;
  research_gaps: number;
  verified_sources: number;
  total_sources: number;
  total_evidence: number;
  conflicting_findings: number;
  components: ScoreComponent[];
  methodology_note: string;
}

export interface ExecutiveReport {
  executive_summary: string;
  opportunities: string[];
  critical_risks_summary: string;
  open_questions: string[];
  next_steps: string[];
}

export interface AgentRun {
  stage: StageName;
  label: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  detail: string;
}

export interface Project {
  id: string;
  brief: ProductionBrief;
  status: ProjectStatus;
  created_at: string;
  completed_at: string | null;
  error: string | null;
  plan: ResearchPlan | null;
  search_results: SearchResult[];
  sources: Source[];
  evidence: EvidenceItem[];
  verifications: Verification[];
  risks: Risk[];
  gaps: ResearchGap[];
  recommendations: Recommendation[];
  assessment: ProductionAssessment | null;
  report: ExecutiveReport | null;
  runs: AgentRun[];
  warnings: string[];
}

export interface ProjectSummary {
  id: string;
  title: string;
  city: string;
  country: string;
  status: ProjectStatus;
  created_at: string;
  readiness_score: number | null;
  evidence_confidence: number | null;
  critical_risks: number;
  open_actions: number;
  total_sources: number;
}

export interface HealthStatus {
  status: string;
  parallel_configured: boolean;
  gemini_configured: boolean;
  vertex_mode: boolean;
  model: string;
  reasoning_model: string;
  active_projects: number;
}

/** Live pipeline events delivered over SSE. */
export interface StreamEvent {
  type:
    | "pipeline_started"
    | "stage_started"
    | "stage_completed"
    | "research_plan_ready"
    | "search_progress"
    | "source_found"
    | "evidence_found"
    | "error"
    | "failed"
    | "complete"
    | "heartbeat";
  stage?: StageName;
  label?: string;
  message?: string;
  metrics?: Record<string, unknown>;
  task_id?: string;
  category?: string;
  status?: string;
  sources?: number;
  excerpts?: number;
  latency_ms?: number;
  search_id?: string;
  error?: string;
  source_id?: string;
  domain?: string;
  title?: string;
  url?: string;
  evidence_id?: string;
  claim?: string;
  confidence?: string;
  task_count?: number;
  tasks?: Array<{
    id: string;
    category: string;
    question: string;
    priority: string;
    queries: string[];
  }>;
  summary?: string;
  missing_information?: string[];
  project_id?: string;
  readiness?: number;
  recoverable?: boolean;
}
