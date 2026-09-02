# CineScout — Hackathon Compliance Audit

Status legend: **PASS** verified in this repo - **ACTION** requires an operator step before submission -
**VERIFY** depends on the official rules text, which must be re-read before submitting.

| # | Requirement | Status | Evidence / required action |
|---|---|---|---|
| 1 | New project created during the contest period | **ACTION** | Repository scaffolded from an empty directory on 2026-08-25 and `git init` run, but **no commit has been made yet**. Create the initial commit so the history itself evidences the creation date. |
| 2 | Eligible platform / project category | **VERIFY** | Web application solving an entertainment/media workflow. Confirm against the official category list. |
| 3 | Google Cloud AI usage at runtime | **PASS** | Gemini is invoked through ADK's `LlmAgent` in `backend/app/agents/pipeline.py` — six stages, each with a typed `output_schema`. No stage is stubbed. `scripts/verify_integrations.py` additionally issues a direct `google-genai` call. |
| 4 | Gemini usage | **PASS** | `gemini-3.7-flash` (GA) default; `GEMINI_REASONING_MODEL` may raise heavy stages to `gemini-3.1-pro-preview`. |
| 5 | Agent Builder / Agent Platform / ADK usage | **PASS** | Google ADK 2.7 `SequentialAgent` + `LlmAgent` + custom `BaseAgent` in `backend/app/agents/`. ADK is the primary and only orchestration layer. |
| 6 | Parallel runtime integration | **PASS** | `backend/app/integrations/parallel_client.py` performs live `POST https://api.parallel.ai/v1/search`. The pipeline cannot complete without it. |
| 7 | Partner calls actually execute | **ACTION** | Run `python scripts/verify_integrations.py` with real keys and keep the output. This is the proof artifact. |
| 8 | No prohibited AI providers | **PASS** | Verified by `scripts/check_dependencies.py`, which scans requirements, the frontend manifest and the installed environment. Last run: PASS. |
| 9 | Public repository | **ACTION** | Push to a public remote before the deadline. |
| 10 | OSI-approved licence at repo root | **PASS** | `LICENSE` - Apache License 2.0. |
| 11 | Hosted application | **ACTION** | `gcloud run deploy` per `README.md`, then record the public URL in the submission. The container image build has **not** been verified locally (no Docker daemon available on the build machine); the frontend build step the Dockerfile depends on was verified directly. Build the image once before relying on it. |
| 12 | English language support | **PASS** | All UI, docs and model output are English. |
| 13 | Original content | **PASS** | All code, copy and visual design authored for this project. No third-party UI kit or template. |
| 14 | No unauthorised third-party assets | **PASS** | No stock imagery, logos or fonts beyond open-licensed Inter / JetBrains Mono loaded from Google Fonts. |
| 15 | Demo under three minutes | **PASS (design)** | `docs/DEMO.md` timeline totals 3:00. **ACTION**: confirm the recorded cut is under the limit. |
| 16 | All required submission components | **VERIFY** | Typically: hosted URL, public repo, demo video, written description. Re-read the official checklist. |
| 17 | Solves a genuine entertainment/media workflow | **PASS** | Pre-production feasibility research: permits, locations, regulation, weather, crew, vendors. |

## Items deliberately flagged rather than assumed

- **#2, #16** depend on the official rules text. I have not read the rules document, so I will not certify
  these. Re-read the rules and confirm before submitting.
- **#7, #9, #11, #15** are operator actions that cannot be completed from the codebase alone. They require
  API keys, a Google Cloud project, a public git remote and a recorded video.
- The deadline stated by the project owner is **2026-09-09, 14:00 PDT**. Confirm this against the official
  source; do not rely on it second-hand.

## Verification status of this build

- **50 backend tests pass**, including an eight-stage end-to-end pipeline run against a fake
  model and fake search client. This exercises the wiring, the validators and the
  provenance guarantees offline.
- **The frontend typechecks and builds** (`tsc --noEmit`, `vite build`).
- **The API and the compiled SPA were served and exercised in a browser**: dashboard, brief
  form and the demo prefill all render and function.
- **Not yet verified, and cannot be from the codebase alone:** a live run against the real
  Parallel and Gemini APIs. No credentials were available in the build environment. Run
  `scripts/verify_integrations.py` with real keys, then run the demo brief end to end,
  before submitting. Until that is done, requirement #7 is unproven.

## Honest-claims policy

The README and UI contain **no measured business metrics**. Statements about time saved are framed as the
problem being addressed, not as measured results. Any figure shown in the product is computed from that
run's own data and is explained in `docs/SCORING.md`.
