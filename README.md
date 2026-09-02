<div align="center">

# CineScout

**From idea to greenlight — with evidence.**

An autonomous production-intelligence platform that turns a filmmaker's production
brief into an evidence-backed feasibility decision.

Google Gemini reasons · Google ADK orchestrates · Parallel Search retrieves the live web

</div>

---

## The problem

Before a single frame is shot, someone has to answer a genuinely hard question:
**can we actually make this?**

Answering it means researching permits, local regulation, locations, weather in the
shooting window, crew and equipment depth, security, access and cost — across dozens of
scattered, frequently out-of-date sources.

A studio has a department for this. An independent filmmaker has a browser with forty
tabs open at midnight, and often discovers the blocker after the money is committed.

## The solution

CineScout is a virtual production-research department. Give it a brief and it will:

1. **Plan** its own research, and tell you what your brief left out.
2. **Execute** every research task against the live web through the Parallel Search API.
3. **Extract** atomic claims, each bound to the exact source and excerpt it came from.
4. **Cross-check** those claims against each other, flagging conflicts instead of resolving
   them by guesswork.
5. **Reason** about production risk in the context of *your* budget, crew size and season.
6. **Score** readiness deterministically, and show its arithmetic.
7. **Recommend** prioritised actions a producer can start on Monday morning.

It answers one question: *can we realistically make this production, and what could stop us?*

### What makes it different

- **Live web intelligence**, not model recall. Every claim is retrieved at run time.
- **Fabricated citations are structurally impossible.** The model may only cite source ids
  the retrieval layer actually created; anything else is discarded in code before it can
  reach the report.
- **Conflicts are surfaced, not smoothed over.** A disagreement between two sources is more
  useful to a producer than a false consensus.
- **The score is deterministic and explainable.** No model touches it, and the report shows
  every component of the calculation.
- **Failure is visible.** If a search fails, the UI says so and the score drops. CineScout
  refuses to run at all without live retrieval, because a report without evidence would be
  worse than no report.

---

## Architecture

> **LLM where judgement is required. Code where determinism is required.**

```
Production brief
      |
      v
[1] Brief Agent          LLM    -> research plan + gaps in the brief
[2] Research Agent       CODE   -> concurrent Parallel Search, one call per task
[3] Evidence Agent       LLM    -> atomic claims bound to real sources
      |-- validator      CODE   -> drops unknown citations, empties, duplicates
[4] Verification Agent   LLM    -> VERIFIED / SUPPORTED / CONFLICTING / UNCONFIRMED
      |-- validator      CODE   -> downgrades uncorroborated "verified" claims
[5] Risk Agent           LLM    -> risks with severity, evidence and mitigations
[6] Feasibility Scorer   CODE   -> deterministic readiness score
[7] Recommendation Agent LLM    -> prioritised producer actions
[8] Report Agent         LLM    -> executive production intelligence report
```

Stages 2 and 6 are deliberately **not** prompts. An LLM driving a search tool may skip a
task or stop early; deterministic Python guarantees every planned task runs exactly once.
And a readiness score a model could nudge is a score no producer should trust.

Full detail: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** ·
scoring methodology: **[docs/SCORING.md](docs/SCORING.md)**

### Google Cloud usage

| Service | Role |
|---|---|
| **Gemini** `gemini-3.7-flash` | Reasoning for all six LLM stages. `GEMINI_REASONING_MODEL` can raise the judgement-dense stages to `gemini-3.1-pro-preview`. |
| **Agent Development Kit (ADK 2.7)** | `SequentialAgent` orchestration, `LlmAgent` typed structured output, custom `BaseAgent` stages, session state, event streaming. ADK is the only orchestration layer — no third-party agent framework is used. |
| **Vertex AI / Gemini Enterprise Agent Platform** | Production auth path via ADC (`GOOGLE_GENAI_USE_VERTEXAI=TRUE`). |
| **Cloud Run** | Hosts the single container. |
| **Secret Manager** | Supplies API keys as secret-backed environment variables. |

`gemini-2.5-*` is deliberately avoided: it reaches end of life in October 2026.

### Parallel usage

Parallel is the sole path through which external world knowledge enters the system, and it
is load-bearing — without it the pipeline refuses to produce a report.

```http
POST https://api.parallel.ai/v1/search
x-api-key: $PARALLEL_API_KEY

{ "search_queries": ["Lagos film permit requirements", "Lagos State filming fees"],
  "objective": "Identify the permitting authority, fees and lead times.",
  "mode": "base",
  "advanced_settings": { "max_results": 6,
                         "excerpt_settings": { "max_chars_per_result": 1500 } } }
```

Results are canonicalised (tracking parameters stripped, `www.` removed), deduplicated by
URL, and assigned stable `src_NN` ids. That id set becomes the **only** citation namespace
Gemini is permitted to use. Per-task `search_id`, latency and result counts are retained and
shown in the interface, so live retrieval is visibly demonstrable.

The client tolerates both API generations: it targets GA `/v1/search` and transparently
falls back to `/v1beta/search` on a 404. Timeouts, 429s and 5xx are retried with exponential
backoff; an exhausted retry becomes a typed failure the user sees, never invented content.

Implementation: [`backend/app/integrations/parallel_client.py`](backend/app/integrations/parallel_client.py)

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- A **Parallel API key** — <https://parallel.ai>
- **Gemini credentials** — a key from <https://aistudio.google.com>, or a Google Cloud
  project with Vertex AI enabled

### Local development

```bash
git clone <your-repo-url> && cd CineScout
cp .env.example .env      # then fill in PARALLEL_API_KEY and GOOGLE_API_KEY
```

Backend:

```bash
python -m venv .venv && source .venv/Scripts/activate   # macOS/Linux: .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend && python -m uvicorn app.main:app --reload --port 8080
```

Frontend, in a second terminal:

```bash
cd frontend && npm install && npm run dev
```

Open <http://localhost:5173>. The dev server proxies `/api` to the backend.

### Verify the integrations actually execute

```bash
python scripts/verify_integrations.py
```

This issues one real Parallel search and one real Gemini generation, printing the URLs
returned and the model that answered. It exits non-zero if either fails.

```bash
python scripts/check_dependencies.py
```

Asserts that no prohibited AI provider SDK is present in the requirements, the frontend
manifest, or the installed environment.

### Tests

```bash
cd backend && python -m pytest -q      # 50 tests
```

The suite includes a full eight-stage pipeline run against a fake model and a fake search
client, so the wiring, the validators and the provenance guarantees are all exercised
offline without API keys or network access.

---

## Deployment

Single container, multi-stage build: Node compiles the SPA, Python serves it alongside the
API.

```bash
gcloud run deploy cinescout \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --min-instances 1 \
  --max-instances 1 \
  --concurrency 8 \
  --timeout 900 \
  --memory 1Gi \
  --set-secrets PARALLEL_API_KEY=parallel-api-key:latest,GOOGLE_API_KEY=gemini-api-key:latest
```

Every flag here is load-bearing — do not drop them:

- `--min-instances 1` removes cold start, which matters when a judge opens the link.
- `--max-instances 1` is **required** while the project store is in memory. A pipeline runs
  on the instance that accepted the brief; if Cloud Run scaled out, the browser's
  `/stream` request could land on a second instance that has never heard of that project
  and return 404. Raise this only after moving `store.py` to Firestore.
- `--timeout 900` must exceed `PIPELINE_TIMEOUT_S` (420s) in
  [`backend/app/orchestrator.py`](backend/app/orchestrator.py). Cloud Run's default request
  timeout is 300s, which would sever the SSE stream mid-analysis.

To use Vertex AI instead of an API key, set `GOOGLE_GENAI_USE_VERTEXAI=TRUE` and
`GOOGLE_CLOUD_PROJECT`, and grant the service account the Vertex AI User role.

---

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `PARALLEL_API_KEY` | **yes** | — | Parallel Search API key. |
| `GOOGLE_API_KEY` | yes* | — | Gemini Developer API key. |
| `GOOGLE_GENAI_USE_VERTEXAI` | no | `FALSE` | Route Gemini through Vertex AI using ADC. |
| `GOOGLE_CLOUD_PROJECT` | yes* | — | Required when using Vertex AI. |
| `GOOGLE_CLOUD_LOCATION` | no | `us-central1` | Vertex AI region. |
| `GEMINI_MODEL` | no | `gemini-3.7-flash` | Workhorse model for all stages. |
| `GEMINI_REASONING_MODEL` | no | = `GEMINI_MODEL` | Heavier model for judgement-dense stages. |
| `PARALLEL_MODE` | no | `base` | `turbo` \| `fast` \| `base` \| `advanced`. |
| `PARALLEL_MAX_RESULTS` | no | `6` | Results per search. |
| `PARALLEL_MAX_CHARS` | no | `1500` | Excerpt characters per result. |
| `PARALLEL_MAX_CONCURRENCY` | no | `5` | Concurrent searches. |
| `MAX_RESEARCH_TASKS` | no | `8` | Cap on planned tasks; bounds latency and spend. |
| `MAX_CONCURRENT_PIPELINES` | no | `3` | Concurrent analyses per instance. |
| `RATE_LIMIT_PER_HOUR` | no | `20` | Analyses per client IP per hour. |
| `LOG_LEVEL` | no | `INFO` | Logging verbosity. |

\* Supply **either** `GOOGLE_API_KEY` **or** Vertex AI configuration.

---

## Demo flow

Full script and timing: **[docs/DEMO.md](docs/DEMO.md)**

1. **Dashboard** — the problem, framed.
2. **New production** — *Load demo brief* fills in *Shadow District*: a 12-day independent
   crime thriller in Lagos with night exteriors, drone shots and an 85,000 USD budget.
3. **Live research** — the pipeline rail advances stage by stage, search tasks fire
   concurrently, the source counter climbs, and claims stream in as they are extracted.
4. **Evidence explorer** — every claim with its verification status, source URL and the
   verbatim excerpt it came from.
5. **Risk center** — risks by severity with linked evidence, plus the questions that need a
   human, and the research tasks that failed.
6. **Intelligence report** — readiness and confidence, the full score breakdown, the
   executive summary and the prioritised actions.

The demo brief is chosen because it is genuinely hard: Lagos permitting, Nigerian drone
regulation, February harmattan conditions and local crew depth are not answerable from model
memory. That is the point.

---

## Security

- Secrets live in environment variables, sourced from Secret Manager in production. They are
  never logged and never returned by any endpoint — `/api/health` reports booleans only.
- All input is validated by strict Pydantic models with length and range caps.
- Retrieved web content is treated as **untrusted data**: it is delivered to Gemini inside
  labelled `<retrieved_content>` fences under a standing instruction that text within them is
  evidence to analyse, never instructions to follow. Model output is then re-validated
  against typed schemas and a code-built citation whitelist.
- A log filter redacts credential-shaped strings before they can reach a sink.
- Rate limiting per client IP, plus a global cap on concurrent pipelines.
- No accounts, no personal data collected, no user identity persisted.

---

## Limitations and assumptions

Stated plainly, because a production-intelligence tool that overstates its own certainty is
the failure mode this project exists to prevent.

- **This is research, not legal advice.** Permit, regulatory, insurance and safety findings
  are signals gathered from public sources. They must be confirmed with the relevant
  authority or a qualified professional before budget or crew is committed. The UI says so
  on every relevant surface.
- **Quality is bounded by what the open web publishes.** In regions where filming rules are
  not published online, coverage will be thin — and CineScout will report low coverage
  rather than filling the gap with plausible text.
- **Sources can be out of date.** Claims resting on undated or old material are flagged
  `staleness_flag` and discounted in scoring, but freshness cannot be guaranteed.
- **The readiness score is diagnostic, not predictive.** It measures how well *this brief is
  currently evidenced*, not the film's odds of being made, and is not comparable across
  productions of different types.
- **Storage is in-memory.** Projects live as long as the service instance. This is
  deliberate for the scope — no accounts, no user data at rest — and `store.py` is a
  single-class swap for Firestore.
- **Rate limiting is per instance.** Behind a multi-instance deployment the effective limit
  is per instance, which is sufficient for bounding casual abuse of a demo service.
- **No measured business metrics are claimed anywhere.** Statements about research effort
  describe the problem being addressed, not measured outcomes.

---

## Project structure

```
backend/
  app/
    agents/          pipeline, per-stage prompts, validators, research agent
    integrations/    Parallel Search client
    schemas.py       typed data model, shared with the frontend contract
    scoring.py       deterministic readiness scoring
    orchestrator.py  runs the ADK pipeline, assembles the project
    main.py          FastAPI app, SSE streaming
  tests/             50 tests, including an offline end-to-end pipeline run
frontend/
  src/pages/         dashboard, brief, live research, report, evidence, risks
  src/styles/        hand-authored design system
docs/                architecture, scoring, demo script, compliance audit
scripts/             integration verification, dependency compliance check
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
