# CineScout — 3-Minute Demonstration Plan

▶️ **[Watch the recorded demo](https://youtu.be/sXap5aZjbl4)**

The demo is a single uninterrupted end-to-end run. Nothing is pre-rendered, scripted, or mocked.

## Demo brief (seeded, one-click prefill)

| Field | Value |
|---|---|
| Title | **Shadow District** |
| Type | Independent feature film |
| Genre | Crime thriller |
| Country / City | Nigeria / Lagos |
| Budget | 85,000 USD |
| Shooting days | 12 |
| Period | February 2027 |
| Locations | Rooftop (Lagos Island), police-station exterior, nightclub interior, urban street |
| Requirements | Night filming, small crew (12-15), drone establishing shots, practical locations |
| Audience | 18-34, domestic Nigerian + international festival circuit |
| Constraints | No studio build, single equipment vendor, limited contingency |

This brief is chosen because it forces genuinely hard, genuinely external research: Lagos State filming
permits, drone rules under the Nigerian Civil Aviation Authority, night-shoot security, February
harmattan/weather conditions, local equipment rental depth, and police-location protocol. None of it is
answerable from model memory alone, which is exactly the point.

## Timeline

| Time | On screen | Narration |
|---|---|---|
| **0:00-0:20** | Dashboard, then the problem framing | "Studios have whole departments for production research. Independent filmmakers do it themselves, across dozens of tabs, and often get it wrong at the worst moment." |
| **0:20-0:40** | New Production, demo prefill, submit | "One production brief. Twelve shooting days in Lagos, night exteriors, drone work, 85 thousand dollars." |
| **0:40-1:20** | Live Research: pipeline rail advances; research plan appears; search cards fire concurrently; source counter climbs | "CineScout plans its own research: permits, drone regulation, weather, crew, security. Then it executes every task, in parallel, against the live web." |
| **1:20-1:45** | Evidence panel filling; hover a claim to show source URL + verbatim excerpt | "Every claim is bound to a real source retrieved through Parallel, with the exact excerpt it came from. The model is not allowed to cite anything the retrieval layer did not actually return." |
| **1:45-2:15** | Verification badges; a CONFLICTING item expanded; Risk Center | "It cross-checks sources against each other. Here two sources disagree on drone permit lead time, so it is flagged as conflicting rather than resolved by guesswork - and routed to a human." |
| **2:15-2:40** | Intelligence Report: readiness, confidence, score breakdown, prioritised actions | "Production readiness 74 percent, computed deterministically - and it shows the arithmetic. Then the part a producer actually uses: what to do on Monday morning." |
| **2:40-3:00** | Architecture panel | "Gemini plans and reasons. Google Cloud's Agent Development Kit orchestrates a deterministic eight-stage pipeline. Parallel provides live, traceable web intelligence. CineScout turns production research from a manual bottleneck into an autonomous intelligence workflow." |

## Reliability rules for the live run

1. **Warm the service** before recording (`min-instances=1`) so there is no cold start.
2. **Bound the runtime**: `PARALLEL_MODE=base` and a capped task count keep a full run in the 45-75s range.
3. **Failure is a feature, not a retake**: if a search task fails, the UI shows it as FAILED and the score
   reflects reduced coverage. This is a correct demonstration of the system, not a broken one - narrate it.
4. **Never re-record to hide uncertainty.** Conflicting and unconfirmed findings are the differentiator.

## What the judges should take away

- The agent **plans**, then **acts**, then **checks its own evidence**, then **decides**.
- The external world enters the system through **one auditable path**: Parallel.
- The number at the top of the report is **explainable**, not decorative.
