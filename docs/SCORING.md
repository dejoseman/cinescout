# Production Readiness Scoring

The readiness score is the number a producer makes a decision on, so it is
computed in code — `backend/app/scoring.py` — and never by a language model.
Identical evidence always produces an identical score, and the product publishes
its own arithmetic in the report.

## The five components

Readiness is the sum of five components, out of 100 points.

| Component | Max | How it is computed |
|---|---:|---|
| Research coverage | 25 | `(tasks returning usable results / tasks planned) x 25`. A failed or empty search costs points directly. |
| Evidence confidence | 25 | `mean(status weight x confidence multiplier) x 25` across every claim. |
| Risk exposure | 30 | Starts at 30. Each open risk deducts by severity. Floors at 0. |
| Source depth | 10 | `min(independent domains / 10, 1) x 10`. Counts **domains**, not URLs. |
| Open questions | 10 | Starts at 10. Each unresolved research gap deducts 2.5. Floors at 0. |

### Verification status weights

| Status | Weight | Meaning |
|---|---:|---|
| `VERIFIED` | 1.00 | Two or more independent domains agree. |
| `SUPPORTED` | 0.75 | One credible source states it; nothing contradicts it. |
| `CONFLICTING` | 0.25 | Sources disagree. Deliberately low — a contradiction is close to no answer. |
| `UNCONFIRMED` | 0.35 | Only weak, indirect or commercial support. |
| `INSUFFICIENT_EVIDENCE` | 0.10 | The excerpt does not actually support the claim. |

A claim the verification stage never reached defaults to `UNCONFIRMED` (0.35),
never to verified. A claim flagged `staleness_flag` is additionally multiplied by
0.8.

### Confidence multipliers

`HIGH` 1.0 · `MEDIUM` 0.85 · `LOW` 0.65.

### Risk penalties

`CRITICAL` -10 · `HIGH` -6 · `MEDIUM` -3 · `LOW` -1.

## The absence-of-evidence rule

If **no evidence was gathered at all**, the risk-exposure and open-questions
components score **zero rather than full marks**.

This rule exists because the naive arithmetic produces a perverse result: a run
where every search failed would report "no risks found" and "no open questions"
and score 40/100 — rewarding a total research failure with a middling score. An
empty risk register is only meaningful if somebody actually looked.

Absence of evidence is not evidence of safety.

## Worked example

A run with 8 planned tasks, 7 usable, 22 claims, 14 independent domains,
2 critical / 3 high / 4 medium risks and 3 open gaps:

```
Research coverage   7/8 x 25                        = 21.9
Evidence confidence mean weight 0.71 x 25           = 17.8
Risk exposure       30 - (2x10 + 3x6 + 4x3)         =  0.0   (floored)
Source depth        min(14/10, 1) x 10              = 10.0
Open questions      10 - (3 x 2.5)                  =  2.5
                                                      -----
Production readiness                                 = 52
```

That production is not ready, and the breakdown says exactly why: the risk load
alone wipes out an entire 30-point component. This is the intended behaviour —
the score is diagnostic, not promotional.

## What the score is not

- It is **not** a prediction of whether the film gets made.
- It is **not** a substitute for legal, insurance or safety advice.
- It is **not** comparable across productions of different types; it measures how
  well *this* brief is currently evidenced, not how good the project is.

A low score most often means the research is incomplete, not that the production
is doomed. The recommendations tell you which gaps to close first.
