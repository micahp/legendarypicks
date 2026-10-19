# Model checkpoints — the five-stage standard

Micah, 2026-10-18:

> "Each model brief should include the same five explicit checkpoints: baseline established,
> candidate validated chronologically, distribution calibrated, prospective confirmation completed,
> and production integration approved. A model shouldn't be considered finished just because its
> research ladder is exhausted. Conversely, a model that fails a gate should still be documented as
> a completed experiment."

Every league brief carries this block, with each checkpoint marked for the current incumbent.

## The five checkpoints

| # | Checkpoint | What must be true to mark it passed |
|---|---|---|
| **CP1** | **Baseline established** | A no-information and at least one simple reference are scored on the same population, with sample size and a stated population definition. Not a leaderboard — a floor. |
| **CP2** | **Candidate validated chronologically** | The candidate is fit only on information available before each forecast, scored walk-forward, compared to the CP1 baselines with a paired, *clustered* interval, and the population is identical across every model compared. |
| **CP3** | **Distribution calibrated** | The predictive distribution is scored on proper scores (CRPS, log score) **and** calibration (PIT, reliability, zero-event reliability where relevant) on identical observations, with the per-observation PMFs preserved. Point-forecast accuracy is not calibration. |
| **CP4** | **Prospective confirmation** | Frozen, immutable, pre-event forecasts scored against outcomes that were unknown when the forecast was written. Retrospective work cannot pass this checkpoint, no matter how good it looks. |
| **CP5** | **Production integration approved** | An explicit decision by Micah, with the surface named (table, route, page), the presentation constraints stated, and the model version pinned. Research completion is not approval. |

## The rules that follow from it

- **A tick is not a pass.** `✓` in a baseline ladder means an implementation exists, not that it
  cleared CP2.
- **A failed gate is still a completed experiment.** Document it with its numbers, its verdict and
  its learnings entry. Do not delete it, do not quietly re-run it with different settings.
- **CP4 cannot be shortcut.** The 2023–2026 tennis window has been inspected and is development
  data. 2026 FBS weeks already played are development data. Only genuinely future, frozen forecasts
  count.
- **CP5 is Micah's, never an agent's.** No agent promotes a model, merges it to `dev`, or presents a
  probability as a forecast on the strength of a research result.
- **Research stays on branches** until CP5. Merge when there is a table, a route or a page — not
  when an agent finishes.

## Presentation constraints that ride along

Where a checkpoint passes but a sub-market fails, the failure is stated on the surface, not just in
the doc. Current examples:

- **NFL game distribution** — winner passes, spread and total invert. They are not forecasts.
- **NFL rushing carries** — no candidate is validated; nothing ships.
- **NHL tiered policy** — NO-GO; the puck-line base rate is not skill.

## Where each league stands

| league | CP1 | CP2 | CP3 | CP4 | CP5 |
|---|---|---|---|---|---|
| **FBS** G2h | ✓ | ✓ walk-forward 2023–25, 0.1946 | ✗ winner-only, no score distribution | partial — 2026 played games | ✗ |
| **NFL** v2-platt props | ✓ | ✓ vs Marcel and market | ✗ coverage over-covers 82.7–97.4% | ✗ | live, but CP3 unmet |
| **NFL** game winner | ✓ | ✓ 0.2243 vs 0.2474 | ✗ spread/total invert | ✗ | ✗ |
| **NHL** xG model | ✓ B0–B4 | ◐ B5 not graded | ✗ | ✗ | ✗ |
| **Tennis** M1 Elo | ✓ | ◐ 2023–26 only, no rolling-origin | ✗ no incumbent | ✗ | ✗ |

The honest summary: **every league has CP1, none has passed CP3, and CP4 is essentially untouched
everywhere.** Better Brier scores are the foundation, not the destination.
