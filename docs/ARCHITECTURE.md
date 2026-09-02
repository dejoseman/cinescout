# CineScout — Architecture Specification

> **From idea to greenlight — with evidence.**
> An autonomous production-intelligence platform for independent filmmakers and small production teams.

---

## 1. Final Architecture

CineScout is a **deterministic, multi-stage agentic pipeline**, not a conversational agent. Google Cloud's
agent guidance explicitly favours deterministic, multi-step workflows over a single free-roaming chat
agent, and the entire system is built around that principle.

The central design rule:

> **LLM where judgement is required. Code where determinism is required.**

This split is what makes the output trustworthy. Gemini decides *what to research*, *what a source means*,
and *what the risks are*. Deterministic Python decides *which searches actually execute*, *which citations
are real*, and *what the readiness score is*. A language model can never invent a source or nudge a score.

```
                         +------------------------------------------+
                         |            React SPA (Vite/TS)           |
                         |  Dashboard / Brief / Live Research /     |
                         |  Report / Evidence Explorer / Risk Center|
                         +---------------+--------------------------+
                                         | POST /api/projects
                                         | GET  /api/projects/{id}/stream  (SSE)
                         +---------------v--------------------------+
                         |        FastAPI  (Cloud Run service)      |
                         |  validation / rate limit / event bus     |
                         +---------------+--------------------------+
                                         |
                         +---------------v--------------------------+
                         |   ADK SequentialAgent: cinescout_pipeline|
                         +---------------+--------------------------+
                                         |
   +-----------+------------+------------+-----------+--------------+--------------+
   v           v            v            v           v              v              v
+-------+ +----------+ +---------+ +------------+ +-------+ +--------------+ +--------+
| Brief | | Research | |Evidence | |Verification| | Risk  | |Recommendation| | Report |
| Agent |>| Agent    |>| Agent   |>| Agent      |>| Agent |>| Agent        |>| Agent  |
| (LLM) | | (CODE)   | | (LLM)   | | (LLM)      | | (LLM) | | (LLM)        | | (LLM)  |
+-------+ +----+-----+ +---------+ +------------+ +---+---+ +--------------+ +--------+
               |                                      |
               v                              +-------v--------+
     +-------------------+                    |  Feasibility   |
     |  Parallel Search  |                    |  Scorer (CODE) |
     |  POST /v1/search  |                    |  deterministic |
     +-------------------+                    +----------------+
```

### Why the Research and Scoring stages are code, not prompts

| Stage | Implementation | Rationale |
|---|---|---|
| Research fan-out | `BaseAgent` subclass, `asyncio.gather` | Guarantees **every** planned task runs. An LLM loop may skip tasks, retry non-deterministically, or stop early. |
| Feasibility scoring | Pure function, `scoring.py` | The score must be reproducible and explainable. Identical evidence produces an identical score, every time. No invented metrics. |
| Citation binding | `agents/validators.py` | The LLM may only cite `source_id`s from a code-built catalogue. Unknown IDs are **dropped**, not rendered. Fabricated citations are structurally impossible. |

---

## 2. Agent Interaction Diagram

State flows through the ADK session store. Each stage reads typed input from state and writes typed
output back under a fixed `output_key`, so stages are independently testable and replayable.

```
ProductionBrief (user input, validated)
        |
        v
+---------------------------------------------------------------------+
| 1. BriefAgent            LlmAgent - output_schema=ResearchPlan       |
|    reads : brief                                                     |
|    writes: state["research_plan"]                                    |
|    does  : normalise requirements, name missing info, emit 6-10      |
|            ResearchTasks each with 2-3 Parallel search queries,      |
|            a category and a priority.                                |
+---------------------------------------------------------------------+
        | ResearchPlan
        v
+---------------------------------------------------------------------+
| 2. ResearchAgent         BaseAgent (deterministic Python)            |
|    reads : state["research_plan"]                                    |
|    writes: state["search_results"], state["source_catalog"]          |
|    does  : concurrent POST https://api.parallel.ai/v1/search - one   |
|            call per task, bounded by a semaphore. Dedupes sources    |
|            by normalised URL, assigns stable src_NN ids, records     |
|            per-task status (ok / empty / failed) and latency.        |
|    fails : a failed task is recorded as FAILED and surfaced to the   |
|            user. It is never silently replaced with model text.      |
+---------------------------------------------------------------------+
        | SearchResult[] + Source[]
        v
+---------------------------------------------------------------------+
| 3. EvidenceAgent         LlmAgent - output_schema=EvidenceSet        |
|    reads : search excerpts + source catalogue                        |
|    writes: state["evidence"]                                         |
|    does  : convert raw excerpts into atomic claims, each bound to    |
|            source_id + verbatim supporting excerpt.                  |
|    guard : post-validated - claims citing unknown source_ids are     |
|            discarded before they can reach the UI.                   |
+---------------------------------------------------------------------+
        | EvidenceItem[]
        v
+---------------------------------------------------------------------+
| 4. VerificationAgent     LlmAgent - output_schema=VerificationSet    |
|    writes: state["verifications"]                                    |
|    does  : cross-compare claims across independent sources.          |
|            Assigns VERIFIED / SUPPORTED / CONFLICTING /              |
|            UNCONFIRMED / INSUFFICIENT_EVIDENCE, records              |
|            corroborating and contradicting source ids, and flags     |
|            staleness where a claim rests on old material.            |
+---------------------------------------------------------------------+
        | Verification[]
        v
+---------------------------------------------------------------------+
| 5. RiskAgent             LlmAgent - output_schema=RiskSet            |
|    writes: state["risks"], state["research_gaps"]                    |
|    does  : derive production risks with severity, reasoning,         |
|            evidence ids and a recommended next action. Regulatory    |
|            items are marked requires_human_confirmation.             |
+---------------------------------------------------------------------+
        | Risk[] + ResearchGap[]
        v
+---------------------------------------------------------------------+
| 6. FeasibilityScorer     Pure function (no model)                    |
|    writes: state["assessment"]                                       |
|    does  : compute readiness %, evidence confidence %, coverage %    |
|            and a full component breakdown from counted facts.        |
+---------------------------------------------------------------------+
        | ProductionAssessment
        v
+---------------------------------------------------------------------+
| 7. RecommendationAgent   LlmAgent - output_schema=RecommendationSet  |
|    writes: state["recommendations"]                                  |
|    does  : convert risks and gaps into prioritised, concretely       |
|            actionable next steps (CRITICAL/HIGH/MEDIUM/LOW).         |
+---------------------------------------------------------------------+
        |
        v
+---------------------------------------------------------------------+
| 8. ReportAgent           LlmAgent - output_schema=ExecutiveReport    |
|    writes: state["report"]                                           |
|    does  : executive summary, opportunities, questions requiring     |
|            human confirmation, suggested next steps.                 |
+---------------------------------------------------------------------+
        |
        v
   IntelligenceReport  ->  SSE `complete` event  ->  UI
```

Every stage emits `stage_started` / `stage_completed` SSE events carrying counters, so the UI reflects
real backend progress rather than a scripted animation.

---

## 3. Data Model

All schemas are Pydantic v2 models in `backend/app/schemas.py`; the TypeScript mirror lives in
`frontend/src/lib/types.ts`.

| Model | Key fields | Notes |
|---|---|---|
| `ProductionBrief` | title, project_type, genre, country, city, budget_amount/currency, shooting_days, shooting_period, locations[], requirements[], target_audience, constraints, free_text | User input. Length-capped and validated. |
| `ResearchTask` | id, category, question, search_queries[], priority, rationale | Produced by BriefAgent, consumed by ResearchAgent. |
| `ResearchPlan` | summary, extracted_requirements[], missing_information[], tasks[] | Stage-1 output. |
| `Source` | id (`src_NN`), url, domain, title, publish_date, first_seen_task | Deduped by normalised URL. The **citation whitelist**. |
| `SearchResult` | task_id, status, queries[], source_ids[], excerpt_count, latency_ms, error | One per task, including failures. |
| `EvidenceItem` | id, task_id, category, claim, source_id, excerpt, confidence, retrieved_at | `excerpt` is verbatim from Parallel. |
| `Verification` | evidence_id, status, corroborating_source_ids[], contradicting_source_ids[], reasoning, staleness_flag | 5-value status enum. |
| `Risk` | id, title, severity, category, reasoning, evidence_ids[], recommended_action, requires_human_confirmation | |
| `ResearchGap` | id, question, why_it_matters, suggested_source | Explicit unknowns. |
| `Recommendation` | id, priority, action, rationale, related_risk_ids[], owner_hint | |
| `ProductionAssessment` | readiness_score, evidence_confidence, research_coverage, counts, `components[]`, methodology_note | Deterministic; `components[]` shows the arithmetic. |
| `ExecutiveReport` | executive_summary, opportunities[], critical_risks_summary, open_questions[], next_steps[] | |
| `AgentRun` | id, stage, status, started_at, finished_at, duration_ms, detail | Observability record per stage. |
| `Project` | id, brief, status, created_at, plan, sources, evidence, verifications, risks, gaps, recommendations, assessment, report, runs[] | Aggregate root returned by the API. |

---

## 4. API / Tool Design

### HTTP API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/projects` | Validate a brief, create a project, start the pipeline in the background. Returns `{id, status}`. |
| `GET` | `/api/projects/{id}/stream` | **SSE** stream of live pipeline events. |
| `GET` | `/api/projects/{id}` | Full project aggregate (report, evidence, risks, sources). |
| `GET` | `/api/projects` | Dashboard list with summary metrics. |
| `GET` | `/api/health` | Liveness + integration configuration status (never returns secrets). |
| `GET` | `/api/demo-brief` | The seeded demo brief, so the demo is one click. |

### SSE event contract

```jsonc
{ "type": "stage_started",   "stage": "research",  "label": "Searching external sources" }
{ "type": "search_progress", "task_id": "t3", "category": "PERMITS", "status": "ok", "sources": 5 }
{ "type": "stage_completed", "stage": "research",  "metrics": { "sources": 17, "failed_tasks": 0 } }
{ "type": "error",           "stage": "evidence",  "message": "...", "recoverable": true }
{ "type": "complete",        "project_id": "..." }
```

### Parallel tool contract (`integrations/parallel_client.py`)

```
POST https://api.parallel.ai/v1/search
headers: x-api-key: $PARALLEL_API_KEY
body: { search_queries: [str], objective: str, mode: "advanced",
        advanced_settings: { max_results, excerpt_settings: { max_chars_per_result } } }
-> { search_id, results: [{ url, title, publish_date, excerpts: [str] }], session_id, warnings, usage }
```

The client is **API-generation tolerant**: it targets the GA `/v1/search` endpoint and, on a 404,
transparently falls back to the `/v1beta/search` shape (`processor`/`max_results` flat fields).
Timeouts, 429s and 5xx are retried with exponential backoff and jitter; exhausted retries return a
typed `SearchFailure` that propagates to the UI as a visible failed task.

---

## 5. UI / UX Screen Map

| Screen | Route | Purpose |
|---|---|---|
| **Dashboard** | `/` | Active projects, readiness rings, aggregate risk counts, outstanding actions. |
| **New Production** | `/new` | Structured brief form + natural-language box. One-click demo prefill. |
| **Live Research** | `/projects/:id/live` | The centrepiece. Agent pipeline rail, per-task search cards, sources counter ticking up, evidence streaming in. |
| **Intelligence Report** | `/projects/:id` | Readiness + confidence, score breakdown, executive summary, top risks, prioritised actions. |
| **Evidence Explorer** | `/projects/:id/evidence` | Every claim with source, verbatim excerpt, verification status, confidence. Filter by status/category. |
| **Risk Center** | `/projects/:id/risks` | Risks by severity with reasoning, linked evidence, mitigation, human-confirmation flags. |

Design language: dark editorial "control room" aesthetic — near-black surfaces, restrained amber accent,
Inter for UI and a mono face for identifiers. Generous spacing, strong type hierarchy, motion used
only to signal state change.

---

## 6. Exact Google Cloud Services

| Service | Use |
|---|---|
| **Gemini** (`gemini-3.7-flash`, GA) | Reasoning for all six LLM stages. Overridable to `gemini-3.1-pro-preview` for the heavy reasoning stages via `GEMINI_REASONING_MODEL`. |
| **Agent Development Kit (ADK 2.7)** | `SequentialAgent` orchestration, `LlmAgent` typed stages, session state, event streaming, callbacks for tracing. |
| **Vertex AI / Gemini Enterprise Agent Platform** | Production auth path. `GOOGLE_GENAI_USE_VERTEXAI=TRUE` routes all Gemini traffic through the project's Google Cloud region using ADC. |
| **Cloud Run** | Hosting for the single container (API + built SPA). |
| **Secret Manager** | `PARALLEL_API_KEY` and Gemini credentials injected as secret-backed env vars. |
| **Cloud Logging** | Structured JSON logs; secrets redacted at the formatter. |

> Note: `gemini-2.5-*` is deliberately **not** used — it reaches end of life in October 2026.

---

## 7. Exact Parallel Integration Approach

Parallel is the sole source of external world knowledge. It is load-bearing: with Parallel disabled the
pipeline **cannot** produce a report, and says so explicitly rather than degrading to model recall.

1. BriefAgent generates research tasks, each with 2-3 concise keyword queries (3-6 words, per Parallel's
   guidance) plus a natural-language `objective`.
2. ResearchAgent issues one Parallel Search call per task, concurrently, bounded by `PARALLEL_MAX_CONCURRENCY`.
3. Results are normalised: URL canonicalised, tracking params stripped, sources deduped, stable `src_NN`
   ids assigned, excerpts truncated to a character budget.
4. The source catalogue is passed to Gemini as the **only** permitted citation namespace.
5. Every claim in the report carries `source_id -> url + verbatim excerpt`, rendered in the Evidence Explorer.
6. Raw Parallel metadata (`search_id`, `session_id`, latency, result counts) is retained per task and shown
   in the UI, so live external retrieval is visibly demonstrable.

**Never:** hard-coded results, cached fixtures presented as live, or model-generated URLs.

---

## 8. Security Model

- **Secrets**: env vars only, sourced from Secret Manager in production. Never logged, never returned by
  any endpoint. `/api/health` reports booleans (`parallel_configured: true`), not values.
- **Input validation**: strict Pydantic models with length caps on every string, bounded list sizes,
  numeric ranges on budget/duration. Oversized or malformed payloads are rejected with 422.
- **Prompt-injection posture**: retrieved web content is untrusted data. It is delivered to Gemini inside
  clearly fenced, labelled blocks with standing instructions that content within them is evidence to be
  analysed and never instructions to follow. Model output is re-validated against typed schemas, and
  citations are checked against the code-built whitelist.
- **Rate limiting**: token-bucket per client IP on project creation, plus a global cap on concurrent
  pipelines to bound spend.
- **Egress**: only `api.parallel.ai` and Google APIs. No user-supplied URLs are fetched.
- **Data minimisation**: no accounts, no personal data collected, no persistence of user identity.
- **Safe logging**: structured logs carry ids and counters, never brief content or API keys.

---

## 9. Deployment Architecture

Single container, multi-stage build:

```
Stage 1  node:22-alpine   -> vite build -> /frontend/dist
Stage 2  python:3.11-slim -> pip install -> copy app + dist -> uvicorn
```

FastAPI serves `/api/*` and mounts the built SPA at `/` with history-fallback routing. One Cloud Run
service, `min-instances=1` to remove cold start during judging, concurrency 8, secrets injected from
Secret Manager. Deployment is a single `gcloud run deploy --source .`.

---

## 12. MVP vs Stretch

**MVP (built, demo-critical):** the full 8-stage pipeline; real Parallel calls; citation-validated
evidence; verification with conflict detection; deterministic scoring; all six screens; SSE live
progress; graceful degradation; tests for scoring, validation and the Parallel client.

**Deliberately excluded** (would add surface without strengthening problem -> agentic solution -> live
integration -> evidence -> decision): user accounts, team collaboration, budget/schedule generation,
script analysis, storyboards, calendar and vendor integrations, PDF export, multi-language UI.

Each was tested against: does it improve the production workflow, deepen the technology, increase
impact, strengthen the demo, or sharpen differentiation? Where the answer was no, it is not in the build.
